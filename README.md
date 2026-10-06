# ERP

A modular-monolith SME ERP built for East African businesses. Modules:

| Module | What it covers |
| --- | --- |
| **Accounting / GL** | Double-entry ledger, chart of accounts, P&L, balance sheet, trial balance, general ledger, journals (manual + reversing), budgets vs actual, period lock |
| **Sales & Invoicing (AR)** | Quotes → orders → deliveries → numbered tax invoices with discounts and VAT, invoice-and-ship, payments with receipts, credit notes (with restock), voids, AR aging, customer statements |
| **Purchasing (AP)** | Purchase orders, goods receipts at actual/landed cost, supplier bills and direct expense bills, payments, AP aging |
| **Inventory** | FIFO / weighted-average valuation, multi-warehouse stock, transfers, adjustments, opening stock |
| **POS** | One-step walk-in checkout (stock, COGS, invoice and payment in one transaction) |
| **HR & Payroll** | Employees, departments, leave with balances and approvals; Kenyan payroll (PAYE, NSSF, SHIF, Housing Levy, NITA), payslips, statutory schedules (CSV), P9A |
| **Fixed Assets** | Asset register, straight-line / reducing-balance depreciation runs, disposals with gain/loss |
| **Manufacturing** | Bills of materials with scrap, cost roll-up and availability, work orders |
| **CRM** | Contacts (customers/vendors/leads), deals, interactions, tasks |

Every module posts to the general ledger through the event bus, so the
financial statements always tie out to stock, receivables, payables, payroll
liabilities and the asset register. Invoices, quotes, credit notes, receipts,
statements, payslips and P9s render as branded PDFs on the workspace's own
letterhead (logo, KRA PIN, brand colour, M-Pesa/bank payment details). Backend: FastAPI + SQLAlchemy
2.0 (async) + PostgreSQL + Alembic. See `.claude` plan history for the full
architecture rationale (multi-tenancy via RLS, FIFO/weighted-average valuation
engine, event-driven GL posting).

## Running the whole stack

```bash
docker compose up --build
```

Brings up Postgres, Redis, the FastAPI backend, the Next.js frontend, and an
nginx reverse proxy in front of both. Once it's up, run migrations once
(only needed the first time, or after adding a new migration):

```bash
docker compose exec backend alembic upgrade head
```

- App (via nginx): `http://localhost:8090`
- Frontend directly: `http://localhost:3000`
- Backend API docs: `http://localhost:8000/docs`

### Sample shop

To explore everything with realistic data, create the demo company (six
months of sales, stock in two shops, POS sales, bills, staff and payroll,
fixed assets):

```bash
docker compose exec backend python scripts/seed_demo.py
```

Then sign in as **demo@mwangaza.co.ke / Demo1234!** — an owner on the
Enterprise package who is also platform admin (so `/admin` works too).

## Local development without Docker for the backend

```bash
docker compose up -d postgres redis

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust DATABASE_URL/REDIS_URL if you changed compose ports

alembic upgrade head
uvicorn app.main:app --reload
```

## Tests

```bash
docker exec <postgres-container> psql -U erp -d postgres -c "CREATE DATABASE erp_test OWNER erp;"
cd backend && source .venv/bin/activate
DATABASE_URL="postgresql+asyncpg://erp:erp@localhost:5435/erp_test" alembic upgrade head
pytest tests/ -v
```

## Architecture at a glance

- `app/core/` — cross-cutting: DB/tenancy (`db.py`, `rls.py`), auth/RBAC/feature-gating
  (`actor.py`, `features.py`, `security.py`), the in-process event bus (`events.py`).
- `app/modules/<domain>/` — one package per bounded context (`platform`, `crm`,
  `inventory`, `sales`, `purchasing`, `accounting`, `hr`, `assets`,
  `manufacturing`), each with `models.py`,
  `schemas.py`, `service.py`, `router.py`. Modules call each other's `service.py`
  only, never each other's `models.py` — cross-module side effects go through
  `core/events.py` so a module can be split into its own service later without a
  rewrite.
- Multi-tenancy: every tenant table gets a `workspace_id` (via `TenantMixin`), all
  reads/writes go through `TenantRepository` (structurally can't return unscoped
  rows), and Postgres Row-Level Security is a second line of defense
  (`SET LOCAL`/`set_config` per request in `get_tenant_session`).
- Stock valuation (`app/modules/inventory/valuation.py`): FIFO cost layers or
  weighted-average, configurable per product. `inventory/service.py::apply_movement`
  is the single place stock quantity/cost can change.
- Accounting (`app/modules/accounting/posting.py`): other modules publish events
  (`InvoicePosted`, `DeliveryConfirmed`, `GoodsReceiptPosted`, `PaymentReceived/Made`,
  `VendorBillPosted`, `CreditNoteIssued`, `PayrollRunApproved/Paid`, `DepreciationPosted`,
  `ProductionCompleted`, ...) and this module turns them into balanced journal entries — COGS posted from the
  delivery's exact valuation-engine cost, so the GL and physical stock value always
  reconcile.

- Payroll rules (`app/modules/hr/kenya_payroll.py`): pure functions over dated
  rulesets, so a Finance Act change is a new `PayrollRules` entry, not a code
  change. Verify the rates against current KRA/NSSF/SHA guidance before filing.
- Documents (`app/core/pdf.py`): shared letterhead/stamp/footer engine used by
  `sales/documents.py` and `hr/documents.py`.

## Feature gating

Workspaces are assigned a `Package` (`starter`/`growth`/`enterprise`, seeded on
first migration) whose `modules` list gates entire routers via `require_feature`
in `app/main.py`. `accounting` is auto-enabled whenever `sales` or `purchasing` is
(see `MODULE_DEPENDENCIES` in `app/core/features.py`).

## Platform super admin (turning modules on/off per customer)

Make yourself the platform operator once (the account must already exist):

```bash
docker compose exec backend python -m app.cli make-admin you@yourcompany.com
```

Then open **/admin** (an "Admin console" link also appears in the sidebar).
For every customer workspace you can change its package, switch individual
modules on or off, and suspend or reactivate the account.

- Switching a module off hides it from the menu **and** blocks its API with a
  403 for everyone in that workspace — it isn't just cosmetic.
- Modules that depend on it go off too (e.g. Inventory off ⇒ Sales, POS,
  Purchasing and Manufacturing off), because they can't run without it.
- A per-user override can never switch back on something you've disabled.
- Nothing is deleted: switching a module back on restores all of its data.

## Setting up a POS till on a physical machine

The till is a separate full-screen app at **/pos**.

1. **Install it.** Open `https://your-domain/pos` in Chrome or Edge on the till
   PC/tablet and click **Install app** (top bar) or the install icon in the
   address bar. It then launches from the desktop/taskbar full-screen, like a
   native program. On Android tablets use "Add to Home screen". Installing
   requires HTTPS (or `localhost`).
2. **Choose the till's shop** from the top bar — it's remembered on that device.
3. **Barcode scanner:** any USB or Bluetooth scanner in keyboard mode works
   out of the box — the scan box keeps focus and each scan adds the item
   (matched on barcode or SKU). No drivers needed.
4. **Receipt printer:** install your 80mm thermal printer (Epson TM-T20/T82,
   Xprinter, Bixolon…) as a normal system printer and set it as the default.
   Receipts are laid out for 80mm paper. Turn on **auto-print** (printer icon)
   to print after every sale. For silent printing with no dialog, start Chrome
   with `--kiosk --kiosk-printing https://your-domain/pos`.
5. **Cash drawer:** connect it to the receipt printer's RJ11 port and enable
   "open cash drawer" in the printer driver's settings — it then opens on
   every receipt print.
6. **Shortcuts:** `F2` scan box · `F9` take payment · `Enter` next sale ·
   `Esc` cancel.
7. **End of day:** the chart icon shows the till summary — takings by cash,
   M-Pesa and card — to count the drawer and match the M-Pesa statement.

**Selling without internet.** If the connection drops the till keeps selling
(cash, card, or M-Pesa by typing the customer's confirmation code). Each sale
is saved on that device, the receipt prints with a "recorded offline"
reference, and the sales are sent automatically, in order, when the connection
returns — the top bar shows how many are waiting. Every sale carries its own
reference, so one that is sent twice is still recorded once. Things to know:

- The till must have been opened online at least once on that device (that is
  when it saves the product list), and it uses the stock figures it last saw.
- If two tills sell the last item while offline, the second sale is refused
  when it syncs. It stays in the "waiting to send" list with the reason; receive
  or adjust the stock and press **Send now**. Nothing is silently dropped.
- Waiting sales live in that browser. Don't clear the browser's site data or
  uninstall the app while sales are waiting.
- M-Pesa phone prompts need a connection.

**M-Pesa prompts (STK push).** Settings → M-Pesa: enter the paybill/till and
the Daraja consumer key, consumer secret and passkey from
developer.safaricom.co.ke, then switch it on. The till's M-Pesa option and
every unpaid invoice then get a "send a prompt to the customer's phone"
button; when the customer enters their PIN the payment is recorded with the
M-Pesa code. The keys are stored encrypted (`ENCRYPTION_KEY`) and never shown
again. Safaricom must be able to reach `API_PUBLIC_URL` over https, so results
only arrive once the system is hosted publicly. This has been tested against a
simulated Safaricom, not yet with live keys.

## Running it as a business (billing, support, operations)

**Packages and prices** — Admin console → Packages. Each package has the
modules it includes, user/product limits, a monthly and yearly price and a
free-trial length. One package is the default for new sign-ups. The three
seeded prices (2,500 / 7,500 / 20,000 KES) are placeholders: set your own.

**Subscriptions** — a new business starts on its package's free trial. A
renewal invoice (SUB-000001…) is raised a week before the trial or paid
period ends. When the customer pays (M-Pesa, bank…), record it under Admin
console → Billing: their access is extended at once. If they don't pay there
is a grace period (default 7 days, Platform settings), after which the
account pauses — they can still sign in and see how to pay, and no data is
deleted. Free packages are never billed; mark your own or partner accounts
"Complimentary". Businesses that existed before billing launched were given
an open-ended active subscription.

Raise invoices on a schedule (optional — they are also raised whenever a
billing screen is opened):

```bash
0 6 * * * cd /srv/erp && docker compose exec -T backend python -m app.cli billing-cycle
```

**Support** — in a customer's drawer: sign in as their owner for 30 minutes
(shown to you with a red banner, and written to the audit log), create a
password-reset link for any of their users, or create a new business on a
customer's behalf and invite them as owner.

**Email** — set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`MAIL_FROM` and `APP_URL` in `backend/.env`. Until then every email
(invitations, password resets, invoices) is saved as an `.eml` file in
`backend/media/outbox` and the app says so rather than pretending it was sent.

**Security** — turn on two-step sign-in for the platform admin account
(Settings → Security). Sign-in and password-reset attempts are rate-limited;
changing a password signs out every other device.

**Backups** — `backend/scripts/backup.sh` dumps the database and uploaded
logos and keeps 14 days; see the cron line and restore commands at the top of
the script. Copy the backups off the server.

**Monitoring** — point your uptime monitor at `/health/ready` (checks the
database). Unhandled errors are logged with a short reference the user sees.

## Day-to-day operations

- **Prices include VAT** (Settings → Company & documents): on for shops — the
  price typed is what the customer pays and VAT is worked out from inside it,
  so 2 × 116.00 is exactly 232.00. Off for business-to-business, where VAT is
  added on top. Applies to the till, invoices, quotes and recurring invoices.
- **Stock take** (Inventory → Stock take): start a count for a shop (all of it
  or one category), type what is on the shelf, save as you go, then post. Only
  the difference between what was expected when the sheet was made and what
  was counted is adjusted, so sales made during the count are not undone. The
  value of the difference posts to the ledger.
- **Reorder** (Inventory → Reorder): everything at or below its reorder level
  with a suggested quantity; tick lines to create a draft purchase order.
- **Returns to suppliers** (Purchasing → Returns to suppliers): raises a debit
  note, takes the goods out of stock and reduces what is owed on the bill.
- **Recurring invoices** (Sales → Recurring): weekly, monthly, quarterly or
  yearly; optionally emailed. Raise them from the screen, or daily by cron
  (missed days are caught up):

  ```bash
  5 6 * * * cd /srv/erp && docker compose exec -T backend python -m app.cli recurring-invoices
  ```
- **Files**: attach PDFs, images, spreadsheets or documents (10 MB each) to
  invoices, supplier bills and products. They are private to the business.
- **Product pictures**: add one from the product window; it shows in the
  product list and on the till.

## Data isolation between businesses

Every table that holds a business's data has Postgres Row-Level Security, and
every request runs as the restricted `erp_app` database role with that
business's id set — so even a query that forgot its filter cannot return
another business's rows. The role is created by the migrations; `DB_APP_ROLE`
names it. `tests/test_tenancy.py` proves it against a real database.

## Finance: reconciliation, VAT, year end

- **Separate ledgers per payment method.** Cash (1000), M-Pesa (1010) and
  Bank (1020) are separate accounts; each payment posts to the one for its
  method. Point a method at a different account (a second bank, say) under
  Accounting → Year-end & Settings.
- **Reconciliation** (Accounting → Banking): import the CSV statement from your
  bank or the M-Pesa portal. Lines that clearly match your books are matched
  automatically; match the rest by hand, or "Record" things that were never
  entered (bank charges, interest, an unrecorded deposit).
- **VAT return** (Accounting → VAT Return): output VAT by rate less credit
  notes, input VAT per supplier bill with PINs, and the net payable; CSV export.
- **Year-end close**: moves the year's profit to Retained Earnings and locks the
  year; reversible.
- **Activity log** (Settings → Activity log): every change, who made it and when.
- **KRA eTIMS**: the workflow is built (status on each invoice, the KRA number
  and QR code on the PDF, retry), with a clearly marked test mode. Live
  submission is not connected — it needs the business's eTIMS device
  credentials; see `backend/app/modules/sales/etims.py`.
