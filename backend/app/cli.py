"""Operator commands.

    python -m app.cli make-admin you@company.com     # grant platform super admin
    python -m app.cli revoke-admin you@company.com
    python -m app.cli billing-cycle                   # raise renewal invoices that are due (run daily from cron)
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.platform.models import User


async def _set_admin(email: str, value: bool) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            sys.exit(f"no user with email {email} — sign up first")
        user.is_platform_admin = value
        await session.commit()
        print(f"{email}: platform admin = {value}")


async def _billing_cycle() -> None:
    """Invoices are also raised whenever a customer or admin opens a billing
    screen; running this daily just means they exist (and can be emailed)
    without anyone having to look."""
    from app.modules.billing.service import BillingService
    from app.modules.platform.models import Workspace

    async with SessionLocal() as session:
        billing = BillingService(session)
        workspaces = (await session.execute(select(Workspace).where(Workspace.is_active.is_(True)))).scalars().all()
        raised = 0
        for workspace in workspaces:
            before = len(await billing.invoices(workspace.id, "open"))
            await billing.ensure_renewal_invoice(workspace.id)
            raised += len(await billing.invoices(workspace.id, "open")) - before
        await session.commit()
        print(f"checked {len(workspaces)} workspaces; raised {raised} invoice(s)")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "billing-cycle":
        asyncio.run(_billing_cycle())
        return
    if len(sys.argv) != 3 or sys.argv[1] not in ("make-admin", "revoke-admin"):
        sys.exit(__doc__)
    asyncio.run(_set_admin(sys.argv[2], sys.argv[1] == "make-admin"))


if __name__ == "__main__":
    main()
