from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return {"status": "ok"}
