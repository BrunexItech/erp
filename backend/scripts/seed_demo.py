"""Creates a fully populated sample shop to explore the ERP with.

    python scripts/seed_demo.py                       # API on localhost:8000
    python scripts/seed_demo.py http://localhost:8020  # or any running API
    docker compose exec backend python scripts/seed_demo.py

Signs up "Mwangaza Hardware Ltd" (login demo@mwangaza.co.ke / Demo1234!),
puts it on the Enterprise package, makes that user platform admin, and fills
it through the public API with six months of realistic activity: customers,
suppliers, two shops with stock, invoices and payments, POS sales, expense
bills, a quote, staff with two paid payroll runs, fixed assets and
depreciation. Safe to re-run: it stops if the demo account already exists.
"""

import asyncio
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.cli import _set_admin  # noqa: E402

random.seed(7)
B = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/api/v1"
EMAIL, PASSWORD = "demo@mwangaza.co.ke", "Demo1234!"
c = httpx.Client(timeout=60)

r = c.post(f"{B}/auth/signup", json={"email": EMAIL, "password": PASSWORD, "full_name": "Amina Otieno", "workspace_name": "Mwangaza Hardware Ltd"})
if r.status_code == 409:
    sys.exit(f"Demo shop already exists — sign in as {EMAIL} / {PASSWORD}")
r.raise_for_status()
h = {"Authorization": f"Bearer {r.json()['access_token']}"}
ws = c.get(f"{B}/workspaces", headers=h).json()[0]["id"]

asyncio.run(_set_admin(EMAIL, True))
enterprise = next(p for p in c.get(f"{B}/admin/packages", headers=h).json() if p["key"] == "enterprise")
c.patch(f"{B}/admin/workspaces/{ws}", headers=h, json={"package_id": enterprise["id"]}).raise_for_status()
h["X-Workspace-Id"] = ws


def post(path, body):
    r = c.post(B + path, headers=h, json=body)
    if r.status_code >= 300:
        print("FAIL", path, r.text[:200])
    return r.json()


c.patch(f"{B}/workspaces/branding", headers=h, json={
    "address": "Kenyatta Avenue, Nakuru", "phone": "+254 700 123 456", "billing_email": "accounts@mwangaza.co.ke",
    "website": "www.mwangaza.co.ke", "tax_pin": "P051987654Z", "mpesa_paybill": "522533",
    "bank_details": "KCB Bank, Nakuru Branch\nMwangaza Hardware Ltd\nA/C 1234567890",
    "invoice_terms": "Payment due within 30 days. Goods remain our property until paid in full.",
    "invoice_footer_note": "Thank you for building with Mwangaza."})

customers = [post("/crm/parties", {"name": n, "kind": "customer", "is_company": True, "email": e, "tax_id": pin, "billing_address": a})
             for n, e, pin, a in [("Acme Builders Ltd", "accounts@acme.co.ke", "P051234567X", "Moi Avenue, Nairobi"),
                                  ("Kilimo Farm Supplies", "pay@kilimo.co.ke", "P052200011A", "Eldoret"),
                                  ("Baraka Construction", "finance@baraka.co.ke", "P051777001Q", "Naivasha Road, Nakuru"),
                                  ("Jua Kali Welders", "juakali@gmail.com", "", "Gikomba, Nairobi"),
                                  ("Tumaini Schools", "bursar@tumaini.ac.ke", "P053300912K", "Kisumu")]]
vendors = [post("/crm/parties", {"name": n, "kind": "vendor", "is_company": True}) for n in ["Bamburi Cement", "Mabati Rolling Mills", "Kenya Power", "Landlord - Nakuru Plaza"]]
main = post("/inventory/warehouses", {"name": "Nakuru Main Store", "code": "NKR"})
shop = post("/inventory/warehouses", {"name": "Naivasha Shop", "code": "NVS"})
catalog = [("CEM-50", "Cement 50kg", 850, 620, "6161100000013"), ("MAB-30", "Mabati 30G 3m", 1450, 1050, "6161100000020"),
           ("NAIL-4", "Nails 4\" (kg)", 280, 190, "6161100000037"), ("PNT-4L", "Crown Paint 4L", 2350, 1700, "6161100000044"),
           ("ROD-12", "Steel rod Y12", 1150, 880, "6161100000051"), ("PIP-25", "PVC pipe 25mm", 420, 290, "6161100000068"),
           ("WHB-S", "Wheelbarrow standard", 5200, 3900, "6161100000075"), ("SND-T", "River sand (tonne)", 3200, 2300, "6161100000082")]
products = []
for sku, name, price, cost, bc in catalog:
    p = post("/inventory/products", {"sku": sku, "name": name, "sale_price": str(price), "tax_rate": "0.16", "barcode": bc, "low_stock_threshold": "10"})
    products.append((p, price, cost))
    for wh, q in ((main, 400), (shop, 120)):
        post("/inventory/stock/adjustments", {"product_id": p["id"], "warehouse_id": wh["id"], "qty_delta": str(q), "unit_cost": str(cost), "is_opening": True, "reason": "opening"})
post("/accounting/journal-entries", {"date": str(date.today() - timedelta(days=200)), "memo": "Owner capital",
     "lines": [{"account_id": next(a["id"] for a in c.get(f"{B}/accounting/accounts", headers=h).json() if a["code"] == k), "debit": d, "credit": cr}
               for k, d, cr in (("1000", "2500000", "0"), ("3000", "0", "2500000"))]})
today = date.today()
for m in range(6, -1, -1):
    for _ in range(random.randint(4, 7)):
        d = today - timedelta(days=30 * m + random.randint(0, 25))
        if d > today: d = today
        cust = random.choice(customers)
        lines = [{"product_id": p["id"], "qty": str(random.randint(2, 30)), "unit_price": str(price), "tax_rate": "0.16",
                  "discount_pct": random.choice(["0", "0", "5"])} for p, price, _ in random.sample(products, random.randint(1, 3))]
        inv = post("/sales/invoices", {"party_id": cust["id"], "issue_date": str(d), "warehouse_id": main["id"], "lines": lines, "reference": f"LPO-{random.randint(1000, 9999)}"})
        if m > 1 or random.random() < 0.4:
            post("/sales/invoices/payments", {"invoice_id": inv["id"], "amount": inv["total"], "method": random.choice(["mpesa", "bank"]), "payment_date": str(min(today, d + timedelta(days=10))), "reference": "QK" + str(random.randint(10**6, 10**7))})
    for v, amt in ((vendors[3], 85000), (vendors[2], random.randint(9000, 16000))):
        post("/purchasing/vendor-bills", {"party_id": v["id"], "subtotal": str(amt), "tax_total": str(round(amt * 0.16, 2)), "bill_date": str(today - timedelta(days=30 * m)), "memo": "Rent" if v is vendors[3] else "Electricity"})
for p, price, _ in random.sample(products, 3):
    post("/sales/pos/checkout", {"warehouse_id": shop["id"], "payment_method": random.choice(["cash", "mpesa"]), "lines": [{"product_id": p["id"], "qty": "2", "unit_price": str(price), "tax_rate": "0.16"}]})
post("/sales/quotes", {"party_id": customers[4]["id"], "lines": [{"product_id": products[0][0]["id"], "qty": "200", "unit_price": "820", "tax_rate": "0.16"}]})
ops = post("/hr/departments", {"name": "Operations"}); sales_d = post("/hr/departments", {"name": "Sales"}); fin = post("/hr/departments", {"name": "Finance"})
staff = [("Wanjiru", "Kamau", ops, "Store Manager", 85000), ("Otieno", "Odhiambo", sales_d, "Sales Rep", 45000), ("Fatuma", "Hassan", fin, "Accountant", 70000),
         ("Kiprop", "Cheruiyot", ops, "Driver", 32000), ("Achieng", "Were", sales_d, "Cashier", 28000)]
for fn, ln, d, title, pay in staff:
    e = post("/hr/employees", {"first_name": fn, "last_name": ln, "department_id": d["id"], "job_title": title, "hire_date": "2024-03-01", "basic_salary": str(pay), "kra_pin": f"A0{random.randint(10**8, 10**9)}Z", "nssf_no": str(random.randint(10**8, 10**9))})
    post(f"/hr/employees/{e['id']}/pay-items", {"kind": "earning", "name": "House allowance", "amount": str(int(pay * 0.15))})
def months_back(n):
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return y, m


for n in (2, 1):
    y, mo = months_back(n)
    run = post("/hr/payroll/runs", {"period_year": y, "period_month": mo})
    c.post(f"{B}/hr/payroll/runs/{run['id']}/approve", headers=h); c.post(f"{B}/hr/payroll/runs/{run['id']}/mark-paid", headers=h, json={})
post("/hr/payroll/runs", {"period_year": today.year, "period_month": today.month})
cat = post("/assets/categories", {"name": "Motor vehicles", "method": "declining_balance", "annual_rate": "0.25"})
post("/assets", {"name": "Isuzu FRR truck KDA 123X", "category_id": cat["id"], "acquisition_date": "2025-06-01", "cost": "4800000"})
post("/assets", {"name": "Dell laptops (x4)", "acquisition_date": "2026-01-15", "cost": "320000", "useful_life_months": 36})
y, mo = months_back(1)
post("/assets/depreciation-runs", {"year": y, "month": mo})
print(f"Demo shop ready — sign in as {EMAIL} / {PASSWORD}")
