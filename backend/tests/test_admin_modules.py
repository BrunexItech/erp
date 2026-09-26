"""Platform super-admin module switches and POS till features."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core import features
from app.modules.accounting.service import AccountingService
from app.modules.admin.service import AdminService
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.sales.schemas import PosCheckoutLine, PosCheckoutRequest
from app.modules.sales.service import SalesService


def test_disabling_a_module_also_disables_its_dependents():
    modules = features.effective_workspace_modules(["*"], {"inventory": False})
    assert "inventory" not in modules
    # sales, purchasing, pos and manufacturing all need inventory
    assert not modules & {"sales", "purchasing", "pos", "manufacturing"}
    assert {"crm", "accounting", "hr", "assets"} <= modules


def test_workspace_switch_beats_user_grant():
    modules = features.effective_workspace_modules(["crm", "hr"], {"hr": False}, {"hr": True})
    assert "hr" not in modules


def test_workspace_can_enable_module_outside_its_package():
    modules = features.effective_workspace_modules(["crm", "inventory", "accounting"], {"manufacturing": True})
    assert "manufacturing" in modules


async def test_admin_updates_workspace_modules(session, workspace_id):
    admin = AdminService(session)
    result = await admin.update_workspace(workspace_id, package_id=None, module_overrides={"hr": False}, is_active=None)
    assert "hr" not in result["effective_modules"]
    assert result["module_overrides"] == {"hr": False}

    result = await admin.update_workspace(workspace_id, package_id=None, module_overrides={"hr": None}, is_active=None)
    assert "hr" in result["effective_modules"]  # test package is "*"
    assert result["module_overrides"] == {}

    with pytest.raises(HTTPException):
        await admin.update_workspace(workspace_id, package_id=None, module_overrides={"payroll2": True}, is_active=None)


async def test_pos_change_and_till_summary(session, workspace_id):
    await AccountingService(session, workspace_id).seed_default_accounts()
    inventory = InventoryService(session, workspace_id)
    till = await inventory.create_warehouse(WarehouseCreate(name="Till 1", code="T1"))
    soda = await inventory.create_product(ProductCreate(sku="SODA", name="Soda 500ml", barcode="6161100000013"))
    await inventory.record_adjustment(
        product_id=soda.id, warehouse_id=till.id, qty_delta=Decimal("24"), unit_cost=Decimal("40"),
        reason="opening", is_opening=True,
    )
    till_id = till.id  # plain str survives the rollback below (ORM attributes expire)
    sales = SalesService(session, workspace_id)
    line = PosCheckoutLine(product_id=soda.id, qty=Decimal("2"), unit_price=Decimal("60"))

    invoice, _, payment = await sales.pos_checkout(
        PosCheckoutRequest(warehouse_id=till.id, lines=[line], payment_method="cash", amount_tendered=Decimal("200"))
    )
    assert invoice.channel == "pos" and invoice.warehouse_id == till.id
    assert payment.document_no.startswith("RCT-")

    await sales.pos_checkout(
        PosCheckoutRequest(warehouse_id=till.id, lines=[line], payment_method="mpesa", payment_reference="SJK8H2L1QP")
    )
    with pytest.raises(HTTPException):  # 100 tendered for a 120 sale
        await sales.pos_checkout(
            PosCheckoutRequest(warehouse_id=till.id, lines=[line], payment_method="cash", amount_tendered=Decimal("100"))
        )
    await session.rollback()

    summary = await sales.pos_summary(date.today(), till_id)
    assert summary["sales_count"] == 2
    assert summary["gross_sales"] == Decimal("240.00")
    methods = {m["method"]: m["amount"] for m in summary["by_method"]}
    assert methods == {"cash": Decimal("120.00"), "mpesa": Decimal("120.00")}
