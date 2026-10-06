"""Bulk product import/export (CSV) — how a shop with 800 lines gets onto the
system in an afternoon instead of typing each one."""

from __future__ import annotations

from decimal import Decimal

from fastapi import UploadFile

from app.core import csvio
from app.modules.inventory.models import Product, StockMovementType
from app.modules.inventory.service import InventoryService

COLUMNS = [
    "sku", "name", "category", "barcode", "unit", "sale_price", "tax_rate",
    "low_stock_threshold", "opening_qty", "opening_cost", "warehouse_code",
]
TEMPLATE_ROWS = [
    ["CEM-50", "Cement 50kg", "Building", "6161100000013", "bag", "850", "16", "20", "100", "620", "MAIN"],
    ["NAIL-4", "Nails 4 inch", "Hardware", "", "kg", "280", "16", "10", "", "", ""],
]


async def import_products(service: InventoryService, file: UploadFile) -> dict:
    rows = await csvio.read_rows(file, required=["sku", "name"])
    report = csvio.ImportReport()
    existing = {p.sku.lower(): p for p in await service.products.list()}
    warehouses = {w.code.lower(): w for w in await service.warehouses.list()}
    new_count = sum(1 for _, r in rows if r.get("sku", "").lower() not in existing)
    await service._check_sku_limit(adding=new_count)

    seen: set[str] = set()
    for number, row in rows:
        sku = row.get("sku", "")
        try:
            if not sku or not row.get("name"):
                raise ValueError("sku and name are required")
            if sku.lower() in seen:
                raise ValueError(f"SKU {sku} appears more than once in this file")
            seen.add(sku.lower())

            fields = {
                "name": row["name"][:200],
                "category": row.get("category", "")[:80],
                "barcode": row.get("barcode") or None,
                "unit": (row.get("unit") or "pcs")[:16],
                "sale_price": csvio.decimal_of(row.get("sale_price", ""), default=Decimal("0"), label="sale price"),
                "tax_rate": csvio.rate_of(row.get("tax_rate", "")),
                "low_stock_threshold": csvio.decimal_of(row.get("low_stock_threshold", ""), default=Decimal("0"), label="low stock threshold"),
            }
            opening_qty = csvio.decimal_of(row.get("opening_qty", ""), default=Decimal("0"), label="opening qty")
            product = existing.get(sku.lower())

            # A savepoint per row: a failure rolls back just this row.
            async with service.session.begin_nested():
                if product is not None:
                    for key, value in fields.items():
                        setattr(product, key, value)
                    await service.session.flush()
                    report.updated += 1
                    continue

                warehouse = None
                if opening_qty > 0:
                    code = row.get("warehouse_code", "").lower()
                    warehouse = warehouses.get(code) if code else (next(iter(warehouses.values())) if len(warehouses) == 1 else None)
                    if warehouse is None:
                        raise ValueError(
                            f"warehouse_code '{row.get('warehouse_code', '')}' not found — needed to place the opening stock"
                        )
                product = Product(sku=sku[:64], **fields)
                await service.products.add(product)
                if warehouse is not None:
                    await service.apply_movement(
                        product_id=product.id,
                        warehouse_id=warehouse.id,
                        type=StockMovementType.opening,
                        qty_delta=opening_qty,
                        unit_cost=csvio.decimal_of(row.get("opening_cost", ""), default=Decimal("0"), label="opening cost"),
                        ref_type="import",
                        ref_id="opening",
                    )
                existing[sku.lower()] = product
                report.created += 1
        except ValueError as exc:
            report.fail(number, str(exc))
        except Exception as exc:  # e.g. an HTTPException from apply_movement
            report.fail(number, getattr(exc, "detail", None) or str(exc))

    await service.session.commit()
    return report.as_dict()


async def export_products(service: InventoryService):
    products = sorted(await service.products.list(), key=lambda p: p.sku)
    return csvio.csv_response(
        "products.csv",
        ["sku", "name", "category", "barcode", "unit", "sale_price", "tax_rate", "low_stock_threshold", "stock_qty", "avg_cost", "active"],
        [
            [p.sku, p.name, p.category, p.barcode or "", p.unit, p.sale_price, p.tax_rate * 100, p.low_stock_threshold, p.stock_qty, p.avg_cost, "yes" if p.is_active else "no"]
            for p in products
        ],
    )


def template():
    return csvio.csv_response("products-template.csv", COLUMNS, TEMPLATE_ROWS)
