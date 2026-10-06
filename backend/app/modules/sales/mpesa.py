"""M-Pesa STK push (Lipa na M-Pesa Online) via Safaricom's Daraja API.

Flow: we ask Safaricom to prompt the customer's phone -> they enter their
PIN -> Safaricom calls our callback URL with the result -> on success the
payment is recorded against the invoice automatically, with the M-Pesa
receipt code as its reference.

Each business uses its own Daraja app credentials (Settings -> Payments), so
money lands directly in their paybill or till.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.config import settings
from app.core.db import TenantRepository
from app.modules.sales.models import MpesaConfig, MpesaRequest

BASE_URLS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}
NAIROBI = ZoneInfo("Africa/Nairobi")


def normalise_phone(phone: str) -> str:
    """0712 345 678, +254712345678, 712345678 -> 254712345678."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        digits = "254" + digits
    if not re.fullmatch(r"254[71]\d{8}", digits):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "enter a Safaricom number like 0712 345 678")
    return digits


class DarajaClient:
    def __init__(self, config: MpesaConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.base = BASE_URLS.get(config.environment, BASE_URLS["sandbox"])
        self.transport = transport  # tests inject a fake Safaricom here

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=25, transport=self.transport)

    async def stk_push(self, *, phone: str, amount: int, reference: str, description: str, callback_url: str) -> dict:
        key, secret = crypto.decrypt(self.config.consumer_key_enc), crypto.decrypt(self.config.consumer_secret_enc)
        passkey = crypto.decrypt(self.config.passkey_enc)
        if not (key and secret and passkey and self.config.shortcode):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "M-Pesa isn't fully set up — add your Daraja credentials in Settings")
        timestamp = datetime.now(NAIROBI).strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{self.config.shortcode}{passkey}{timestamp}".encode()).decode()
        till = self.config.till_number
        try:
            async with self._client() as client:
                auth = await client.get("/oauth/v1/generate", params={"grant_type": "client_credentials"}, auth=(key, secret))
                if auth.status_code != 200:
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Safaricom rejected the M-Pesa API keys — check them in Settings")
                response = await client.post(
                    "/mpesa/stkpush/v1/processrequest",
                    headers={"Authorization": f"Bearer {auth.json()['access_token']}"},
                    json={
                        "BusinessShortCode": self.config.shortcode,
                        "Password": password,
                        "Timestamp": timestamp,
                        "TransactionType": "CustomerBuyGoodsOnline" if till else "CustomerPayBillOnline",
                        "Amount": amount,
                        "PartyA": phone,
                        "PartyB": till or self.config.shortcode,
                        "PhoneNumber": phone,
                        "CallBackURL": callback_url,
                        "AccountReference": reference[:12] or "Payment",
                        "TransactionDesc": description[:13] or "Payment",
                    },
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"couldn't reach Safaricom: {type(exc).__name__}") from exc
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code != 200 or str(body.get("ResponseCode")) != "0":
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                body.get("errorMessage") or body.get("ResponseDescription") or "Safaricom did not accept the request",
            )
        return body


class MpesaService:
    def __init__(self, session: AsyncSession, workspace_id: str, transport: httpx.AsyncBaseTransport | None = None):
        self.session = session
        self.workspace_id = workspace_id
        self.configs = TenantRepository(session, workspace_id, MpesaConfig)
        self.requests = TenantRepository(session, workspace_id, MpesaRequest)
        self.transport = transport

    async def _config(self) -> MpesaConfig | None:
        rows = await self.configs.list()
        return rows[0] if rows else None

    async def config_view(self) -> dict:
        """Never returns the secrets — only whether each is set."""
        config = await self._config()
        if config is None:
            return {"configured": False, "is_active": False, "environment": "sandbox", "shortcode": "", "till_number": "",
                    "consumer_key": "", "consumer_secret": "", "passkey": "", "callback_base": settings.api_public_url}
        return {
            "configured": bool(config.consumer_key_enc and config.consumer_secret_enc and config.passkey_enc and config.shortcode),
            "is_active": config.is_active,
            "environment": config.environment,
            "shortcode": config.shortcode,
            "till_number": config.till_number,
            "consumer_key": crypto.mask(crypto.decrypt(config.consumer_key_enc)),
            "consumer_secret": crypto.mask(crypto.decrypt(config.consumer_secret_enc)),
            "passkey": crypto.mask(crypto.decrypt(config.passkey_enc)),
            "callback_base": settings.api_public_url,
        }

    async def save_config(self, data: dict) -> dict:
        config = await self._config()
        if config is None:
            config = MpesaConfig()
            await self.configs.add(config)
        for field in ("environment", "shortcode", "till_number", "is_active"):
            if data.get(field) is not None:
                setattr(config, field, data[field])
        # A blank secret means "keep what's stored" (the form shows only a mask).
        for field in ("consumer_key", "consumer_secret", "passkey"):
            if data.get(field):
                setattr(config, f"{field}_enc", crypto.encrypt(data[field].strip()))
        await self.session.commit()
        return await self.config_view()

    async def initiate(self, *, phone: str, amount: Decimal, invoice_id: str | None, reference: str, user_id: str) -> MpesaRequest:
        config = await self._config()
        if config is None or not config.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "M-Pesa prompts aren't switched on — set them up in Settings")
        phone = normalise_phone(phone)
        whole = int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # M-Pesa has no cents
        if whole < 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount must be at least KES 1")
        if whole > 250000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "M-Pesa allows at most KES 250,000 per transaction")

        token = secrets.token_urlsafe(24)
        request = MpesaRequest(
            invoice_id=invoice_id, phone=phone, amount=Decimal(whole), account_reference=reference[:32],
            callback_token_hash=hashlib.sha256(token.encode()).hexdigest(), requested_by=user_id,
        )
        await self.requests.add(request)
        callback = f"{settings.api_public_url.rstrip('/')}/api/v1/mpesa/callback/{self.workspace_id}/{token}"
        try:
            body = await DarajaClient(config, self.transport).stk_push(
                phone=phone, amount=whole, reference=reference, description="Payment", callback_url=callback
            )
        except HTTPException as exc:
            request.status = "failed"
            request.result_desc = str(exc.detail)[:300]
            await self.session.commit()
            raise
        request.checkout_request_id = body.get("CheckoutRequestID", "")
        request.merchant_request_id = body.get("MerchantRequestID", "")
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def handle_callback(self, token: str, payload: dict) -> None:
        """Safaricom's result. Authenticated by the unguessable per-request
        token in the URL; a replayed callback is ignored."""
        matches = await self.requests.list(MpesaRequest.callback_token_hash == hashlib.sha256(token.encode()).hexdigest())
        if not matches:
            return
        request = await self.requests.get_for_update(matches[0].id)
        if request.status != "pending":
            return
        callback = (payload.get("Body") or {}).get("stkCallback") or {}
        request.result_desc = str(callback.get("ResultDesc", ""))[:300]
        if str(callback.get("ResultCode")) != "0":
            request.status = "failed"
            await self.session.commit()
            return

        items = {i.get("Name"): i.get("Value") for i in (callback.get("CallbackMetadata") or {}).get("Item", [])}
        paid = Decimal(str(items.get("Amount", request.amount)))
        request.mpesa_receipt = str(items.get("MpesaReceiptNumber", ""))[:32]
        request.status = "success"
        await self.session.flush()

        if request.invoice_id:
            from app.modules.sales.service import SalesService

            sales = SalesService(self.session, self.workspace_id)
            invoice = await sales.invoices.get(request.invoice_id)
            if invoice is not None:
                due = sales.balance_due(invoice)
                if due > 0:
                    # record_payment commits (and posts to the M-Pesa ledger).
                    await sales.record_payment(invoice.id, min(paid, due), "mpesa", reference=request.mpesa_receipt)
                    return
        await self.session.commit()

    async def status_of(self, request_id: str) -> MpesaRequest:
        request = await self.requests.get(request_id)
        if request is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "M-Pesa request not found")
        return request
