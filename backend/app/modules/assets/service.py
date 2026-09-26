from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import TenantRepository
from app.core.numbering import next_number
from app.modules.assets.models import (
    AssetCategory,
    AssetStatus,
    DepreciationEntry,
    DepreciationMethod,
    FixedAsset,
)
from app.modules.assets.schemas import AssetCategoryCreate, AssetCreate

ZERO = Decimal("0")


def q2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def next_month(d: date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def months_between(start: date, end: date) -> int:
    """Whole months from start's month through end's month, inclusive."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def monthly_charge(asset: FixedAsset, accumulated: Decimal, months_charged: int) -> Decimal:
    remaining = asset.cost - asset.salvage_value - accumulated
    if remaining <= 0:
        return ZERO
    if asset.method == DepreciationMethod.straight_line:
        if months_charged + 1 >= asset.useful_life_months:
            return remaining  # last month absorbs rounding so NBV lands exactly on salvage
        charge = q2((asset.cost - asset.salvage_value) / asset.useful_life_months)
    else:
        charge = q2((asset.cost - accumulated) * asset.annual_rate / 12)
    return min(charge, remaining)


class AssetService:
    def __init__(self, session: AsyncSession, workspace_id: str):
        self.session = session
        self.workspace_id = workspace_id
        self.categories = TenantRepository(session, workspace_id, AssetCategory)
        self.assets = TenantRepository(session, workspace_id, FixedAsset)
        self.entries = TenantRepository(session, workspace_id, DepreciationEntry)

    async def create_category(self, payload: AssetCategoryCreate) -> AssetCategory:
        if await self.categories.list(AssetCategory.name == payload.name):
            raise HTTPException(status.HTTP_409_CONFLICT, "category exists")
        category = AssetCategory(**payload.model_dump())
        await self.categories.add(category)
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def get_asset(self, asset_id: str, *, for_update: bool = False) -> FixedAsset:
        asset = await (self.assets.get_for_update(asset_id) if for_update else self.assets.get(asset_id))
        if asset is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found")
        return asset

    async def create_asset(self, payload: AssetCreate) -> FixedAsset:
        category = None
        if payload.category_id:
            category = await self.categories.get(payload.category_id)
            if category is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "asset category not found")
        method = payload.method or (category.method if category else DepreciationMethod.straight_line)
        life = payload.useful_life_months or (category.useful_life_months if category else 60)
        rate = payload.annual_rate if payload.annual_rate is not None else (category.annual_rate if category else ZERO)
        if method == DepreciationMethod.declining_balance and rate <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "declining balance needs an annual_rate (e.g. 0.25)")
        if payload.salvage_value >= payload.cost:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "salvage value must be below cost")
        if payload.opening_accumulated_depreciation and payload.funding != "opening":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "prior accumulated depreciation only applies to opening-balance assets"
            )
        if payload.opening_accumulated_depreciation > payload.cost - payload.salvage_value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "accumulated depreciation exceeds the depreciable amount")

        start = payload.depreciation_start or payload.acquisition_date
        asset = FixedAsset(
            asset_no=await next_number(self.session, self.workspace_id, "asset"),
            name=payload.name,
            category_id=payload.category_id,
            description=payload.description,
            serial_number=payload.serial_number,
            location=payload.location,
            custodian=payload.custodian,
            acquisition_date=payload.acquisition_date,
            depreciation_start=start.replace(day=1),
            cost=payload.cost,
            salvage_value=payload.salvage_value,
            method=method,
            useful_life_months=life,
            annual_rate=rate,
            accumulated_depreciation=payload.opening_accumulated_depreciation,
        )
        await self.assets.add(asset)
        await events.publish(
            events.AssetAcquired(
                workspace_id=self.workspace_id,
                asset_id=asset.id,
                cost=float(payload.cost),
                funding=payload.funding,
                entry_date=payload.acquisition_date,
                opening_accumulated_depreciation=float(payload.opening_accumulated_depreciation),
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def _months_charged(self, asset: FixedAsset) -> int:
        return len(await self.entries.list(DepreciationEntry.asset_id == asset.id))

    async def _depreciate_through(self, asset: FixedAsset, through: date, run_id: str) -> Decimal:
        """Charges every uncharged month from the asset's start (or last run)
        through `through`'s month — so a skipped month is caught up rather
        than silently lost."""
        if asset.status != AssetStatus.active:
            return ZERO
        if asset.depreciated_through:
            year, month = next_month(asset.depreciated_through)
        else:
            year, month = asset.depreciation_start.year, asset.depreciation_start.month
        months_charged = await self._months_charged(asset)
        total = ZERO
        while month_end(year, month) <= month_end(through.year, through.month):
            charge = monthly_charge(asset, asset.accumulated_depreciation, months_charged)
            if charge <= 0:
                asset.status = AssetStatus.fully_depreciated
                break
            await self.entries.add(
                DepreciationEntry(asset_id=asset.id, run_id=run_id, period=f"{year}-{month:02d}", amount=charge)
            )
            asset.accumulated_depreciation += charge
            asset.depreciated_through = month_end(year, month)
            total += charge
            months_charged += 1
            if asset.accumulated_depreciation >= asset.cost - asset.salvage_value:
                asset.status = AssetStatus.fully_depreciated
                break
            year, month = next_month(date(year, month, 1))
        return total

    async def run_depreciation(self, year: int, month: int) -> dict:
        """Month-end depreciation for every active asset, as a single journal
        entry. Safe to re-run: months already charged are skipped."""
        run_id = str(uuid4())
        through = month_end(year, month)
        assets = await self.assets.list(FixedAsset.status == AssetStatus.active)
        total = ZERO
        charged = 0
        for asset in sorted(assets, key=lambda a: a.id):
            locked = await self.get_asset(asset.id, for_update=True)
            amount = await self._depreciate_through(locked, through, run_id)
            if amount:
                total += amount
                charged += 1
        if total:
            await events.publish(
                events.DepreciationPosted(
                    workspace_id=self.workspace_id,
                    reference=run_id,
                    amount=float(total),
                    period=f"{year}-{month:02d}",
                    entry_date=through,
                ),
                self.session,
            )
        await self.session.commit()
        return {"period": f"{year}-{month:02d}", "assets_charged": charged, "total": total}

    async def dispose(self, asset_id: str, disposal_date: date, proceeds: Decimal) -> FixedAsset:
        asset = await self.get_asset(asset_id, for_update=True)
        if asset.status == AssetStatus.disposed:
            raise HTTPException(status.HTTP_409_CONFLICT, "asset already disposed")
        if disposal_date < asset.acquisition_date:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "disposal date is before acquisition")

        # Full-month convention: depreciate through the month before disposal.
        prior = disposal_date.replace(day=1)
        prior_year, prior_month = (prior.year - 1, 12) if prior.month == 1 else (prior.year, prior.month - 1)
        run_id = str(uuid4())
        catch_up = await self._depreciate_through(asset, month_end(prior_year, prior_month), run_id)
        if catch_up:
            await events.publish(
                events.DepreciationPosted(
                    workspace_id=self.workspace_id,
                    reference=run_id,
                    amount=float(catch_up),
                    period=f"{prior_year}-{prior_month:02d}",
                    entry_date=disposal_date,
                ),
                self.session,
            )

        asset.status = AssetStatus.disposed
        asset.disposal_date = disposal_date
        asset.disposal_proceeds = proceeds
        await events.publish(
            events.AssetDisposed(
                workspace_id=self.workspace_id,
                asset_id=asset.id,
                cost=float(asset.cost),
                accumulated_depreciation=float(asset.accumulated_depreciation),
                proceeds=float(proceeds),
                entry_date=disposal_date,
            ),
            self.session,
        )
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def schedule(self, asset_id: str) -> dict:
        """Charged history plus the projected charge for every remaining month."""
        asset = await self.get_asset(asset_id)
        history = sorted(await self.entries.list(DepreciationEntry.asset_id == asset.id), key=lambda e: e.period)
        rows = []
        running = asset.accumulated_depreciation - sum((e.amount for e in history), ZERO)
        for e in history:
            running += e.amount
            rows.append({"period": e.period, "charge": e.amount, "accumulated": running,
                         "net_book_value": asset.cost - running, "posted": True})

        if asset.status == AssetStatus.active:
            accumulated = asset.accumulated_depreciation
            months_charged = len(history)
            if asset.depreciated_through:
                year, month = next_month(asset.depreciated_through)
            else:
                year, month = asset.depreciation_start.year, asset.depreciation_start.month
            for _ in range(1200):
                charge = monthly_charge(asset, accumulated, months_charged)
                if charge <= 0:
                    break
                accumulated += charge
                months_charged += 1
                rows.append({"period": f"{year}-{month:02d}", "charge": charge, "accumulated": accumulated,
                             "net_book_value": asset.cost - accumulated, "posted": False})
                year, month = next_month(date(year, month, 1))
        return {"asset_id": asset.id, "asset_no": asset.asset_no, "name": asset.name, "rows": rows}

    async def register(self) -> dict:
        assets = sorted(await self.assets.list(), key=lambda a: a.asset_no)
        live = [a for a in assets if a.status != AssetStatus.disposed]
        return {
            "assets": assets,
            "totals": {
                "cost": sum((a.cost for a in live), ZERO),
                "accumulated_depreciation": sum((a.accumulated_depreciation for a in live), ZERO),
                "net_book_value": sum((a.net_book_value for a in live), ZERO),
            },
        }
