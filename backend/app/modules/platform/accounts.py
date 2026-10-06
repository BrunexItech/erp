"""Team membership, invitations and password recovery.

Kept apart from PlatformService (sign-up/login/branding) so the security-
sensitive flows — anything that hands out or consumes a secret link — live in
one small, reviewable place.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import settings
from app.core import totp
from app.core.security import hash_password, verify_password
from app.modules.platform.models import (
    AuthToken,
    AuthTokenPurpose,
    EmailLog,
    Package,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.modules.platform.schemas import TokenResponse

RESET_TTL = timedelta(hours=2)
INVITE_TTL = timedelta(days=7)
MIN_PASSWORD_LENGTH = 8


def utcnow() -> datetime:
    """Naive UTC — the schema's timestamp columns carry no timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.isdigit() or password.isalpha():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password must mix letters with numbers or symbols")


async def workspace_limit(session: AsyncSession, workspace_id: str, key: str) -> int | None:
    """A package limit (e.g. "max_users", "max_sku"), or None for unlimited."""
    row = (
        await session.execute(
            select(Package.limits).join(Workspace, Workspace.package_id == Package.id).where(Workspace.id == workspace_id)
        )
    ).scalar_one_or_none()
    value = (row or {}).get(key)
    return int(value) if value is not None else None


class AccountService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------ mail

    async def _send(self, mail: mailer.Mail, *, kind: str, reference: str = "", workspace_id: str | None = None, sent_by: str | None = None) -> mailer.MailResult:
        try:
            result = await mailer.send(mail)
            error = ""
        except Exception as exc:  # SMTP down must not turn into a 500 for the caller
            result = mailer.MailResult(delivered=False, backend="smtp", detail=str(exc))
            error = str(exc)[:500]
        self.session.add(
            EmailLog(
                workspace_id=workspace_id, to=", ".join(mail.to)[:500], subject=mail.subject[:300], kind=kind,
                reference=reference[:64], delivered=result.delivered, backend=result.backend, error=error, sent_by=sent_by,
            )
        )
        await self.session.flush()
        return result

    async def send_logged(self, mail: mailer.Mail, **kwargs) -> mailer.MailResult:
        """For other modules (e.g. sales emailing an invoice): send + audit."""
        return await self._send(mail, **kwargs)

    # ---------------------------------------------------------------- tokens

    async def _issue(self, purpose: AuthTokenPurpose, email: str, ttl: timedelta, **fields) -> str:
        raw = secrets.token_urlsafe(32)
        self.session.add(
            AuthToken(purpose=purpose, token_hash=_hash(raw), email=email.lower(), expires_at=utcnow() + ttl, **fields)
        )
        await self.session.flush()
        return raw

    async def _consume(self, raw: str, purpose: AuthTokenPurpose, *, mark_used: bool = True) -> AuthToken:
        token = (
            await self.session.execute(
                select(AuthToken).where(AuthToken.token_hash == _hash(raw), AuthToken.purpose == purpose).with_for_update()
            )
        ).scalar_one_or_none()
        if token is None or token.used_at is not None or token.expires_at < utcnow():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "this link is invalid or has expired — request a new one")
        if mark_used:
            token.used_at = utcnow()
        return token

    # --------------------------------------------------------------- members

    async def list_members(self, workspace_id: str) -> list[dict]:
        rows = (
            await self.session.execute(
                select(WorkspaceMember, User)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(WorkspaceMember.workspace_id == workspace_id)
                .order_by(WorkspaceMember.created_at)
            )
        ).all()
        return [
            {
                "id": member.id, "user_id": user.id, "email": user.email, "full_name": user.full_name,
                "role": member.role, "is_active": user.is_active, "joined_at": member.created_at,
            }
            for member, user in rows
        ]

    async def list_invitations(self, workspace_id: str) -> list[AuthToken]:
        return list(
            (
                await self.session.execute(
                    select(AuthToken).where(
                        AuthToken.workspace_id == workspace_id,
                        AuthToken.purpose == AuthTokenPurpose.invitation,
                        AuthToken.used_at.is_(None),
                        AuthToken.expires_at > utcnow(),
                    ).order_by(AuthToken.created_at.desc())
                )
            ).scalars()
        )

    async def _seats_used(self, workspace_id: str) -> int:
        members = (
            await self.session.execute(
                select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == workspace_id)
            )
        ).scalar_one()
        return members + len(await self.list_invitations(workspace_id))

    async def invite(self, workspace_id: str, email: str, role: WorkspaceRole, inviter: User, inviter_role: str) -> dict:
        email = email.lower().strip()
        if role == WorkspaceRole.owner and inviter_role != WorkspaceRole.owner.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can add another owner")

        limit = await workspace_limit(self.session, workspace_id, "max_users")
        if limit is not None and await self._seats_used(workspace_id) >= limit:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"your package allows {limit} users — remove someone or upgrade to add more",
            )

        workspace = (await self.session.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
        user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is not None:
            existing = (
                await self.session.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, "that person is already on the team")

        for stale in await self.list_invitations(workspace_id):
            if stale.email == email:
                stale.used_at = utcnow()  # re-inviting replaces the old link

        raw = await self._issue(
            AuthTokenPurpose.invitation, email, INVITE_TTL,
            workspace_id=workspace_id, role=role.value, invited_by=inviter.id, user_id=user.id if user else None,
        )
        link = f"{settings.app_url.rstrip('/')}/accept-invite?token={raw}"
        result = await self._send(
            mailer.Mail(
                to=[email],
                subject=f"You're invited to {workspace.name}",
                html=mailer.layout(
                    heading=f"Join {workspace.name}",
                    body_html=(
                        f"<p>{escape(inviter.full_name or inviter.email)} has invited you to work in "
                        f"<b>{escape(workspace.name)}</b> as <b>{role.value}</b>.</p>"
                        f"<p>The invitation is valid for 7 days.</p>"
                    ),
                    button=("Accept invitation", link),
                    brand=workspace.brand_color or "#1a7a8c",
                    sender=workspace.name,
                ),
                text=f"You've been invited to {workspace.name}. Accept: {link}",
                from_name=workspace.name,
            ),
            kind="invitation", reference=email, workspace_id=workspace_id, sent_by=inviter.id,
        )
        await self.session.commit()
        return {"email": email, "role": role, "invite_link": link, "email_delivered": result.delivered}

    async def revoke_invitation(self, workspace_id: str, invitation_id: str) -> None:
        token = (
            await self.session.execute(
                select(AuthToken).where(AuthToken.id == invitation_id, AuthToken.workspace_id == workspace_id)
            )
        ).scalar_one_or_none()
        if token is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation not found")
        token.used_at = utcnow()
        await self.session.commit()

    async def invitation_info(self, raw: str) -> dict:
        token = await self._consume(raw, AuthTokenPurpose.invitation, mark_used=False)
        workspace = (await self.session.execute(select(Workspace).where(Workspace.id == token.workspace_id))).scalar_one()
        existing = (await self.session.execute(select(User).where(User.email == token.email))).scalar_one_or_none()
        return {"email": token.email, "workspace_name": workspace.name, "role": token.role, "has_account": existing is not None}

    async def accept_invitation(self, raw: str, full_name: str, password: str) -> TokenResponse:
        """New people set their name and password here; someone who already
        has an account proves it's them with their existing password."""
        token = await self._consume(raw, AuthTokenPurpose.invitation)
        user = (await self.session.execute(select(User).where(User.email == token.email))).scalar_one_or_none()
        if user is None:
            validate_password(password)
            user = User(email=token.email, hashed_password=hash_password(password), full_name=full_name.strip())
            self.session.add(user)
            await self.session.flush()
        elif not verify_password(password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "that email already has an account — enter its password to join")

        already = (
            await self.session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == token.workspace_id, WorkspaceMember.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if already is None:
            self.session.add(
                WorkspaceMember(workspace_id=token.workspace_id, user_id=user.id, role=WorkspaceRole(token.role))
            )
        await self.session.commit()
        from app.modules.platform.service import issue_tokens

        return issue_tokens(user)

    async def _member(self, workspace_id: str, member_id: str) -> WorkspaceMember:
        member = (
            await self.session.execute(
                select(WorkspaceMember).where(WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id)
            )
        ).scalar_one_or_none()
        if member is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "team member not found")
        return member

    async def _owner_count(self, workspace_id: str) -> int:
        return (
            await self.session.execute(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == WorkspaceRole.owner
                )
            )
        ).scalar_one()

    async def change_role(self, workspace_id: str, member_id: str, role: WorkspaceRole, actor_role: str) -> WorkspaceMember:
        member = await self._member(workspace_id, member_id)
        touching_owner = member.role == WorkspaceRole.owner or role == WorkspaceRole.owner
        if touching_owner and actor_role != WorkspaceRole.owner.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can change who the owners are")
        if member.role == WorkspaceRole.owner and role != WorkspaceRole.owner and await self._owner_count(workspace_id) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "a workspace must keep at least one owner")
        member.role = role
        await self.session.commit()
        await self.session.refresh(member)
        return member

    async def remove_member(self, workspace_id: str, member_id: str, actor_role: str) -> None:
        member = await self._member(workspace_id, member_id)
        if member.role == WorkspaceRole.owner:
            if actor_role != WorkspaceRole.owner.value:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "only an owner can remove an owner")
            if await self._owner_count(workspace_id) <= 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "a workspace must keep at least one owner")
        await self.session.delete(member)
        await self.session.commit()

    # -------------------------------------------------------------- password

    async def forgot_password(self, email: str) -> None:
        """Always succeeds from the caller's point of view — never reveals
        whether an address has an account."""
        user = (await self.session.execute(select(User).where(User.email == email.lower().strip()))).scalar_one_or_none()
        if user is None or not user.is_active:
            return
        raw = await self._issue(AuthTokenPurpose.password_reset, user.email, RESET_TTL, user_id=user.id)
        link = f"{settings.app_url.rstrip('/')}/reset-password?token={raw}"
        await self._send(
            mailer.Mail(
                to=[user.email],
                subject="Reset your password",
                html=mailer.layout(
                    heading="Reset your password",
                    body_html="<p>We received a request to reset your password. This link works once and expires in 2 hours.</p>"
                              "<p>If you didn't ask for this, you can ignore this email — your password stays the same.</p>",
                    button=("Choose a new password", link),
                ),
                text=f"Reset your password: {link}",
            ),
            kind="password_reset", reference=user.email,
        )
        await self.session.commit()

    async def admin_reset_link(self, user_id: str) -> str:
        """Support tool: a reset link the platform admin can hand to a locked-out
        customer directly."""
        user = (await self.session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        raw = await self._issue(AuthTokenPurpose.password_reset, user.email, RESET_TTL, user_id=user.id)
        await self.session.commit()
        return f"{settings.app_url.rstrip('/')}/reset-password?token={raw}"

    async def reset_password(self, raw: str, new_password: str) -> None:
        validate_password(new_password)
        token = await self._consume(raw, AuthTokenPurpose.password_reset)
        user = (await self.session.execute(select(User).where(User.id == token.user_id))).scalar_one()
        user.hashed_password = hash_password(new_password)
        user.token_version += 1  # signs out every existing session
        await self.session.commit()

    async def change_password(self, user: User, current: str, new_password: str) -> TokenResponse:
        """Other devices are signed out; the caller gets fresh tokens so the
        session that made the change carries on."""
        from app.modules.platform.service import issue_tokens

        if not verify_password(current, user.hashed_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
        validate_password(new_password)
        user.hashed_password = hash_password(new_password)
        user.token_version += 1
        await self.session.commit()
        return issue_tokens(user)

    # ------------------------------------------------------------ two-factor

    async def totp_begin(self, user: User, issuer: str) -> dict:
        if user.totp_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "two-factor sign-in is already on")
        user.totp_secret = totp.new_secret()
        await self.session.commit()
        uri = totp.provisioning_uri(user.totp_secret, user.email, issuer)
        return {"secret": user.totp_secret, "uri": uri, "qr_svg": totp.qr_svg(uri)}

    async def totp_enable(self, user: User, code: str) -> list[str]:
        """Turns it on only after a correct code — proof the app is really set
        up — and returns one-time recovery codes, shown exactly once."""
        if user.totp_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "two-factor sign-in is already on")
        if not user.totp_secret or not totp.verify(user.totp_secret, code):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "that code isn't right — check the time on your phone and try again")
        codes = totp.new_recovery_codes()
        user.totp_enabled = True
        user.recovery_codes = [totp.hash_recovery(c) for c in codes]
        await self.session.commit()
        return codes

    async def totp_disable(self, user: User, password: str) -> None:
        if not verify_password(password, user.hashed_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "password is incorrect")
        user.totp_enabled = False
        user.totp_secret = None
        user.recovery_codes = []
        await self.session.commit()
