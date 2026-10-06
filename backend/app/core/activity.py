"""Activity log: who changed what, and when.

Recorded centrally by a middleware rather than by hand in each service, so a
new endpoint is logged the moment it exists and none can be forgotten. Every
successful change (anything that isn't a read) made inside a workspace becomes
one row: the person, a readable description, and the address called.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import SessionLocal, TenantModel, set_tenant_context

log = logging.getLogger(__name__)

# Calls that change nothing worth recording.
SKIP_ROUTES = {"pay_calculator", "login", "refresh", "upload_logo"}
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class ActivityLog(TenantModel):
    __tablename__ = "activity_log"

    user_id: Mapped[str] = mapped_column(String(36), index=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(120))  # "Create invoice"
    area: Mapped[str] = mapped_column(String(32), index=True)  # sales, inventory, hr…
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    via_support: Mapped[bool] = mapped_column(default=False)  # done by a platform admin signed in as the user


def describe(route_name: str) -> str:
    return route_name.replace("_", " ").strip().capitalize()


async def record(request, response) -> None:
    """Called after every response. Never raises: failing to log must not
    turn a successful request into an error."""
    try:
        if request.method in ("GET", "HEAD", "OPTIONS") or response.status_code >= 400:
            return
        actor = getattr(request.state, "actor", None)
        route = request.scope.get("route")
        if actor is None or route is None or route.name in SKIP_ROUTES:
            return
        parts = request.url.path.split("/")  # /api/v1/<area>/...
        area = parts[3] if len(parts) > 3 else ""
        async with SessionLocal() as session:
            await set_tenant_context(session, actor.workspace_id)
            session.add(
                ActivityLog(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    user_email=getattr(request.state, "user_email", ""),
                    action=describe(route.name)[:120],
                    area=area[:32],
                    method=request.method,
                    path=_ID.sub("…", request.url.path)[:300],
                    via_support=bool(getattr(request.state, "impersonator", None)),
                )
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("activity log write failed: %s", exc)
