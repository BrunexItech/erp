from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class DepreciationMethod(str, enum.Enum):
    straight_line = "straight_line"  # (cost - salvage) spread evenly over the useful life
    declining_balance = "declining_balance"  # annual_rate x net book value, month by month


class AssetStatus(str, enum.Enum):
    active = "active"
    fully_depreciated = "fully_depreciated"
    disposed = "disposed"


class AssetCategory(TenantModel):
    """Defaults for new assets — e.g. Motor Vehicles 25% reducing balance,
    Computers 3 years straight line."""

    __tablename__ = "asset_categories"

    name: Mapped[str] = mapped_column(String(120))
    method: Mapped[DepreciationMethod] = mapped_column(default=DepreciationMethod.straight_line)
    useful_life_months: Mapped[int] = mapped_column(default=60)
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)  # declining balance only

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_asset_category_name"),)


class FixedAsset(TenantModel):
    __tablename__ = "fixed_assets"

    asset_no: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("asset_categories.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(1000), default="")
    serial_number: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    custodian: Mapped[str] = mapped_column(String(200), default="")

    acquisition_date: Mapped[date]
    depreciation_start: Mapped[date]  # first month charged (full-month convention)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    salvage_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    method: Mapped[DepreciationMethod] = mapped_column(default=DepreciationMethod.straight_line)
    useful_life_months: Mapped[int] = mapped_column(default=60)
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)

    accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    depreciated_through: Mapped[date | None] = mapped_column(nullable=True)  # last month-end charged
    status: Mapped[AssetStatus] = mapped_column(default=AssetStatus.active)
    disposal_date: Mapped[date | None] = mapped_column(nullable=True)
    disposal_proceeds: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    @property
    def net_book_value(self) -> Decimal:
        return self.cost - self.accumulated_depreciation


class DepreciationEntry(TenantModel):
    __tablename__ = "depreciation_entries"

    asset_id: Mapped[str] = mapped_column(ForeignKey("fixed_assets.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    period: Mapped[str] = mapped_column(String(7))  # "YYYY-MM"
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    __table_args__ = (UniqueConstraint("asset_id", "period", name="uq_depreciation_asset_period"),)
