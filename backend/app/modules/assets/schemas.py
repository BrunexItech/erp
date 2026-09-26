from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.assets.models import AssetStatus, DepreciationMethod


class AssetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    method: DepreciationMethod = DepreciationMethod.straight_line
    useful_life_months: int = Field(default=60, ge=1, le=1200)
    annual_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class AssetCategoryOut(BaseModel):
    id: str
    name: str
    method: DepreciationMethod
    useful_life_months: int
    annual_rate: Decimal

    class Config:
        from_attributes = True


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category_id: str | None = None
    description: str = ""
    serial_number: str = ""
    location: str = ""
    custodian: str = ""
    acquisition_date: date
    depreciation_start: date | None = None  # defaults to the acquisition month
    cost: Decimal = Field(gt=0)
    salvage_value: Decimal = Field(default=Decimal("0"), ge=0)
    method: DepreciationMethod | None = None  # defaults from the category
    useful_life_months: int | None = Field(default=None, ge=1, le=1200)
    annual_rate: Decimal | None = Field(default=None, ge=0, le=1)
    # How it was paid for: "cash" (Cr Cash), "payable" (Cr AP) or "opening"
    # (an asset the business already owned at go-live; Cr Opening Balance Equity).
    funding: str = Field(default="cash", pattern="^(cash|payable|opening)$")
    opening_accumulated_depreciation: Decimal = Field(default=Decimal("0"), ge=0)


class AssetOut(BaseModel):
    id: str
    asset_no: str
    name: str
    category_id: str | None
    description: str
    serial_number: str
    location: str
    custodian: str
    acquisition_date: date
    depreciation_start: date
    cost: Decimal
    salvage_value: Decimal
    method: DepreciationMethod
    useful_life_months: int
    annual_rate: Decimal
    accumulated_depreciation: Decimal
    depreciated_through: date | None
    status: AssetStatus
    disposal_date: date | None
    disposal_proceeds: Decimal
    net_book_value: Decimal

    class Config:
        from_attributes = True


class DepreciationRunRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class DisposalRequest(BaseModel):
    disposal_date: date
    proceeds: Decimal = Field(default=Decimal("0"), ge=0)
