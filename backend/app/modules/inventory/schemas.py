from decimal import Decimal

from pydantic import BaseModel

from app.modules.inventory.models import StockMovementType, StockTransferStatus, ValuationMethod


class ProductCreate(BaseModel):
    sku: str
    name: str
    barcode: str | None = None
    valuation_method: ValuationMethod = ValuationMethod.weighted_average
    sale_price: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    low_stock_threshold: Decimal = Decimal("0")


class ProductOut(BaseModel):
    id: str
    sku: str
    name: str
    barcode: str | None
    valuation_method: ValuationMethod
    sale_price: Decimal
    tax_rate: Decimal
    stock_qty: Decimal
    avg_cost: Decimal
    low_stock_threshold: Decimal
    is_active: bool

    class Config:
        from_attributes = True


class WarehouseCreate(BaseModel):
    name: str
    code: str


class WarehouseOut(BaseModel):
    id: str
    name: str
    code: str

    class Config:
        from_attributes = True


class StockAdjustmentRequest(BaseModel):
    product_id: str
    warehouse_id: str
    qty_delta: Decimal
    unit_cost: Decimal | None = None
    reason: str = ""
    is_opening: bool = False  # opening stock balance rather than a count correction


class StockMovementOut(BaseModel):
    id: str
    product_id: str
    warehouse_id: str
    type: StockMovementType
    qty_delta: Decimal
    unit_cost: Decimal
    balance_after: Decimal
    value_after: Decimal
    ref_type: str
    ref_id: str

    class Config:
        from_attributes = True


class WarehouseStockOut(BaseModel):
    product_id: str
    warehouse_id: str
    qty: Decimal

    class Config:
        from_attributes = True


class TransferLineInput(BaseModel):
    product_id: str
    qty: Decimal


class TransferCreate(BaseModel):
    from_warehouse_id: str
    to_warehouse_id: str
    note: str = ""
    lines: list[TransferLineInput]


class StockTransferOut(BaseModel):
    id: str
    from_warehouse_id: str
    to_warehouse_id: str
    status: StockTransferStatus
    note: str

    class Config:
        from_attributes = True
