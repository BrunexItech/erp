from decimal import Decimal

from app.modules.accounting.service import AccountingService
from app.modules.crm.models import PartyKind
from app.modules.crm.schemas import PartyCreate
from app.modules.crm.service import CrmService
from app.modules.inventory import valuation
from app.modules.inventory.models import ValuationMethod
from app.modules.inventory.schemas import ProductCreate, WarehouseCreate
from app.modules.inventory.service import InventoryService
from app.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptLineInput,
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    VendorBillCreate,
)
from app.modules.purchasing.service import PurchasingService
from app.modules.sales.schemas import (
    DeliveryCreate,
    DeliveryLineInput,
    InvoiceCreate,
    SalesOrderCreate,
    SalesOrderLineCreate,
)
from app.modules.sales.service import SalesService


async def test_buy_sell_pay_reconciles_to_zero_and_inventory_matches_stock(session, workspace_id):
    """End-to-end: buy stock at actual cost, sell part of it, collect payment, pay
    the vendor — then assert (1) the trial balance nets to zero and (2) the
    Inventory GL account balance equals the physical stock value left. This is
    the test that proves valuation and accounting are actually wired together,
    not just individually correct.
    """
    crm = CrmService(session, workspace_id)
    inventory = InventoryService(session, workspace_id)
    purchasing = PurchasingService(session, workspace_id)
    sales = SalesService(session, workspace_id)
    accounting = AccountingService(session, workspace_id)

    await accounting.seed_default_accounts()

    vendor = await crm.create_party(PartyCreate(name="Supplier", kind=PartyKind.vendor))
    customer = await crm.create_party(PartyCreate(name="Customer", kind=PartyKind.customer))
    warehouse = await inventory.create_warehouse(WarehouseCreate(name="Main", code="MAIN"))
    product = await inventory.create_product(
        ProductCreate(sku="RECON-1", name="Widget", valuation_method=ValuationMethod.fifo)
    )

    # Buy 10 @ 220 actual cost (PO said 200 — the receipt cost is what counts).
    po = await purchasing.create_purchase_order(
        PurchaseOrderCreate(
            party_id=vendor.id,
            lines=[PurchaseOrderLineCreate(product_id=product.id, qty_ordered=Decimal("10"), unit_cost=Decimal("200"))],
        )
    )
    po_lines = await purchasing.order_lines.list()
    po_line = next(l for l in po_lines if l.po_id == po.id)
    await purchasing.confirm_purchase_order(po.id)
    await purchasing.receive_goods(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=warehouse.id,
            lines=[
                GoodsReceiptLineInput(
                    po_line_id=po_line.id, product_id=product.id,
                    qty_received=Decimal("10"), actual_unit_cost=Decimal("220"),
                )
            ],
        )
    )
    bill = await purchasing.create_vendor_bill(
        VendorBillCreate(party_id=vendor.id, po_id=po.id, subtotal=Decimal("2200"))
    )
    await purchasing.record_payment(bill.id, Decimal("2200"), "bank")

    # Sell 6 @ 500 + 16% tax.
    so = await sales.create_sales_order(
        SalesOrderCreate(
            party_id=customer.id,
            lines=[SalesOrderLineCreate(product_id=product.id, qty=Decimal("6"), unit_price=Decimal("500"), tax_rate=Decimal("0.16"))],
        )
    )
    so_lines = await sales.order_lines.list()
    so_line = next(l for l in so_lines if l.order_id == so.id)
    await sales.confirm_sales_order(so.id)
    delivery = await sales.create_delivery(
        DeliveryCreate(
            order_id=so.id, warehouse_id=warehouse.id,
            lines=[DeliveryLineInput(order_line_id=so_line.id, product_id=product.id, qty_delivered=Decimal("6"))],
        )
    )
    assert delivery.total_cogs == Decimal("1320")  # 6 * 220

    invoice = await sales.create_invoice(
        InvoiceCreate(party_id=customer.id, order_id=so.id, subtotal=Decimal("3000"), tax_total=Decimal("480"))
    )
    await sales.record_payment(invoice.id, Decimal("3480"), "mpesa")

    # --- Assertions ---
    await session.refresh(product)
    assert product.stock_qty == Decimal("4")

    trial_balance = await accounting.trial_balance()
    total_debit = sum(row["debit"] for row in trial_balance)
    total_credit = sum(row["credit"] for row in trial_balance)
    assert total_debit == total_credit, f"trial balance does not net to zero: {trial_balance}"

    inventory_row = next(r for r in trial_balance if r["code"] == "1200")
    physical_value = await valuation.current_value(session, workspace_id, product, warehouse.id)
    assert inventory_row["debit"] == physical_value == Decimal("880")  # 4 * 220

    ar_balance = await sales.customer_balance(customer.id)
    ap_balance = await purchasing.vendor_balance(vendor.id)
    assert ar_balance == Decimal("0")
    assert ap_balance == Decimal("0")
