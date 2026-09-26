from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.accounting.service import AccountingService
from app.modules.assets.models import AssetStatus, DepreciationMethod
from app.modules.assets.schemas import AssetCreate
from app.modules.assets.service import AssetService


async def _service(session, workspace_id) -> tuple[AssetService, AccountingService]:
    accounting = AccountingService(session, workspace_id)
    await accounting.seed_default_accounts()
    return AssetService(session, workspace_id), accounting


async def test_straight_line_depreciation_catches_up_and_is_idempotent(session, workspace_id):
    assets, accounting = await _service(session, workspace_id)
    laptop = await assets.create_asset(
        AssetCreate(name="Dell Latitude", acquisition_date=date(2025, 1, 10), cost=Decimal("120000"),
                    salvage_value=Decimal("12000"), useful_life_months=36)
    )
    assert laptop.asset_no.startswith("FA-")
    assert await accounting.balance_for_key("FIXED_ASSETS") == Decimal("120000")
    assert await accounting.balance_for_key("CASH") == Decimal("-120000")

    # Jan..Mar in one run (catch-up): 3 x (108,000 / 36) = 9,000
    result = await assets.run_depreciation(2025, 3)
    assert result["total"] == Decimal("9000.00")
    assert (await assets.run_depreciation(2025, 3))["total"] == 0  # re-run is a no-op

    await session.refresh(laptop)
    assert laptop.accumulated_depreciation == Decimal("9000.00")
    assert await accounting.balance_for_key("ACCUM_DEPRECIATION") == Decimal("-9000.00")
    assert await accounting.balance_for_key("DEPRECIATION_EXPENSE") == Decimal("9000.00")


async def test_asset_depreciates_exactly_down_to_salvage(session, workspace_id):
    assets, _ = await _service(session, workspace_id)
    asset = await assets.create_asset(
        AssetCreate(name="Printer", acquisition_date=date(2024, 1, 1), cost=Decimal("10000"),
                    salvage_value=Decimal("1"), useful_life_months=7)  # 9,999/7 doesn't divide evenly
    )
    await assets.run_depreciation(2024, 12)
    await session.refresh(asset)
    assert asset.accumulated_depreciation == Decimal("9999.00")
    assert asset.net_book_value == Decimal("1.00")
    assert asset.status == AssetStatus.fully_depreciated
    schedule = await assets.schedule(asset.id)
    assert len(schedule["rows"]) == 7


async def test_declining_balance(session, workspace_id):
    assets, _ = await _service(session, workspace_id)
    truck = await assets.create_asset(
        AssetCreate(name="Isuzu FRR", acquisition_date=date(2025, 1, 5), cost=Decimal("4800000"),
                    method=DepreciationMethod.declining_balance, annual_rate=Decimal("0.25"))
    )
    await assets.run_depreciation(2025, 2)
    await session.refresh(truck)
    # Jan: 4,800,000 x 25%/12 = 100,000 ; Feb: 4,700,000 x 25%/12 = 97,916.67
    assert truck.accumulated_depreciation == Decimal("197916.67")


async def test_disposal_posts_gain_and_clears_the_asset(session, workspace_id):
    """A van bought Jan 2023 is migrated onto the system at go-live (Jan 2024)
    with one year's depreciation already behind it, then sold in March 2024."""
    assets, accounting = await _service(session, workspace_id)
    van = await assets.create_asset(
        AssetCreate(name="Delivery van", acquisition_date=date(2023, 1, 1), depreciation_start=date(2024, 1, 1),
                    cost=Decimal("1200000"), useful_life_months=60, funding="opening",
                    opening_accumulated_depreciation=Decimal("240000"))
    )
    assert await accounting.balance_for_key("ACCUM_DEPRECIATION") == Decimal("-240000")

    # Disposal first charges Jan + Feb 2024 (2 x 1,200,000/60 = 40,000).
    sold = await assets.dispose(van.id, date(2024, 3, 15), Decimal("1000000"))
    assert sold.status == AssetStatus.disposed
    assert sold.accumulated_depreciation == Decimal("280000.00")
    # NBV 920,000 sold for 1,000,000 -> 80,000 gain
    assert await accounting.balance_for_key("GAIN_ON_DISPOSAL") == Decimal("80000.00")
    assert await accounting.balance_for_key("FIXED_ASSETS") == Decimal("0")
    assert await accounting.balance_for_key("ACCUM_DEPRECIATION") == Decimal("0")

    with pytest.raises(HTTPException):
        await assets.dispose(van.id, date(2024, 4, 1), Decimal("0"))

    sheet = await accounting.balance_sheet(date(2024, 12, 31))
    assert sheet["balanced"]
