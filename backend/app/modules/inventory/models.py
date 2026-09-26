from __future__ import annotations

import enum
from decimal import Decimal

from sqlalchemy import ForeignKey, Identity, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class ValuationMethod(str, enum.Enum):
    fifo = "fifo"
    weighted_average = "weighted_average"


class Product(TenantModel):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valuation_method: Mapped[ValuationMethod] = mapped_column(
        default=ValuationMethod.weighted_average
    )
    sale_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    low_stock_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Running fields — ALWAYS derived from stock_movements / stock_layers, never
    # hand-edited by any code path other than inventory.service.apply_movement().
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)

    __table_args__ = (
        UniqueConstraint("workspace_id", "sku", name="uq_product_sku_per_workspace"),
    )


class Warehouse(TenantModel):
    __tablename__ = "warehouses"

    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_warehouse_code_per_workspace"),
    )


class StockMovementType(str, enum.Enum):
    opening = "opening"
    receipt = "receipt"
    sale = "sale"
    return_ = "return"
    adjustment = "adjustment"
    transfer = "transfer"
    production_issue = "production_issue"  # component consumed by a work order
    production_receipt = "production_receipt"  # finished good produced by a work order


class StockMovement(TenantModel):
    """Append-only ledger. Rows are never updated or deleted — corrections are new
    rows (type=adjustment). The only writer is inventory.service.apply_movement()."""

    __tablename__ = "stock_movements"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    type: Mapped[StockMovementType]
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4))  # + in, - out
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # cost for THIS movement
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 4))  # running qty AT THIS WAREHOUSE
    value_after: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # running inventory value snapshot
    ref_type: Mapped[str] = mapped_column(String(64))  # "sale_delivery" | "goods_receipt" | ...
    ref_id: Mapped[str] = mapped_column(String(36))

    __table_args__ = (
        Index("ix_stock_movements_product_time", "product_id", "created_at"),
    )


class WarehouseStock(TenantModel):
    """Per-location quantity — the source of truth for 'how much of this product
    is physically at this warehouse/shop right now'. Product.stock_qty stays as
    the fast global total (sum across all locations); this table is what makes
    multi-shop operations (transfers, location-aware selling) correct instead of
    just checking the company-wide total. Updated only by
    inventory.service.apply_movement(), same discipline as everything else here.
    """

    __tablename__ = "warehouse_stock"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "product_id", "warehouse_id", name="uq_warehouse_stock_product"
        ),
    )


class StockTransferStatus(str, enum.Enum):
    completed = "completed"  # MVP: transfers are instantaneous, no in-transit state


class StockTransfer(TenantModel):
    """A tracked movement of stock from one shop/warehouse to another — the
    record a multi-shop workspace needs to know what moved, when, and between
    which locations. Each line generates a paired 'transfer out' / 'transfer in'
    StockMovement (see InventoryService.transfer_stock), both tagged with this
    transfer's id as ref_id."""

    __tablename__ = "stock_transfers"

    from_warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    to_warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    status: Mapped[StockTransferStatus] = mapped_column(default=StockTransferStatus.completed)
    note: Mapped[str] = mapped_column(String(500), default="")


class StockTransferLine(TenantModel):
    __tablename__ = "stock_transfer_lines"

    transfer_id: Mapped[str] = mapped_column(ForeignKey("stock_transfers.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))  # cost snapshot carried over, not repriced


class StockLayer(TenantModel):
    """FIFO cost layers — one row per receipt, for products using
    ValuationMethod.fifo. Consumed oldest-first on every outflow.

    Ordered by `seq`, not `created_at`: Postgres's now() returns the
    transaction's START time, not per-statement time, so two layers created in
    the same transaction (or even two separate transactions that happen to
    start within the same tick) can get identical created_at values, making
    "oldest first" ambiguous right when it matters most. `seq` is a DB identity
    column backed by a sequence — allocation is atomic and strictly increasing
    regardless of transaction timing, so it's the only reliable ordering key.
    """

    __tablename__ = "stock_layers"

    seq: Mapped[int] = mapped_column(Identity(always=True), unique=True, nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), index=True)
    qty_received: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    qty_remaining: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source_movement_id: Mapped[str] = mapped_column(ForeignKey("stock_movements.id"))

    __table_args__ = (
        Index("ix_stock_layers_fifo_order", "product_id", "warehouse_id", "seq"),
    )
