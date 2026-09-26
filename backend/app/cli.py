"""Operator commands.

    python -m app.cli make-admin you@company.com     # grant platform super admin
    python -m app.cli revoke-admin you@company.com
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


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("make-admin", "revoke-admin"):
        sys.exit(__doc__)
    asyncio.run(_set_admin(sys.argv[2], sys.argv[1] == "make-admin"))


if __name__ == "__main__":
    main()
