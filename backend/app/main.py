from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import activity
from app.core.actor import module_access, require_feature
from app.modules.accounting.posting import register_subscribers
from app.modules.admin.router import router as admin_router
from app.modules.accounting.router import router as accounting_router
from app.modules.assets.router import router as assets_router
from app.modules.crm.router import router as crm_router
from app.modules.hr.router import router as hr_router
from app.modules.inventory.router import router as inventory_router
from app.modules.manufacturing.router import router as manufacturing_router
from app.modules.platform.router import router as platform_router
from app.modules.purchasing.router import router as purchasing_router
from app.modules.sales.router import router as sales_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    register_subscribers()
    yield


app = FastAPI(title="ERP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Platform (auth, workspaces) is always available — everything else is gated by
# the workspace's Package via require_feature, applied once per module here
# rather than per-endpoint.
app.include_router(platform_router)
app.include_router(admin_router)
app.include_router(crm_router, dependencies=[Depends(module_access("crm"))])
app.include_router(inventory_router, dependencies=[Depends(module_access("inventory"))])
app.include_router(sales_router, dependencies=[Depends(module_access("sales"))])
app.include_router(purchasing_router, dependencies=[Depends(module_access("purchasing"))])
app.include_router(accounting_router, dependencies=[Depends(module_access("accounting"))])
app.include_router(hr_router, dependencies=[Depends(require_feature("hr"))])
app.include_router(assets_router, dependencies=[Depends(require_feature("assets"))])
app.include_router(manufacturing_router, dependencies=[Depends(require_feature("manufacturing"))])


@app.get("/health")
async def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    """Readiness for load balancers and uptime monitors: can we actually
    reach the database (required) and Redis (optional — only rate limiting
    depends on it)?"""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.core.db import SessionLocal

    checks = {"database": "ok", "redis": "ok"}
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        from app.core.ratelimit import _redis

        await _redis().ping()
    except Exception as exc:
        checks["redis"] = f"unavailable: {type(exc).__name__}"
    healthy = checks["database"] == "ok"
    return JSONResponse({"status": "ok" if healthy else "degraded", **checks}, status_code=200 if healthy else 503)


@app.middleware("http")
async def log_unhandled_errors(request, call_next):
    """Anything that escapes a handler is logged with enough to find it —
    method, path and a short id the user can quote — and answered with a
    plain 500 instead of a stack trace."""
    import logging
    import uuid

    from fastapi.responses import JSONResponse

    try:
        response = await call_next(request)
        await activity.record(request, response)
        return response
    except Exception:
        error_id = uuid.uuid4().hex[:8]
        logging.getLogger("erp").exception("unhandled error %s on %s %s", error_id, request.method, request.url.path)
        return JSONResponse({"detail": f"Something went wrong on our side (reference {error_id})."}, status_code=500)
