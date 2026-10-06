import type { Branding } from "@/lib/api/types";
import { fmtMoney, num } from "@/lib/format";

export interface ReceiptLine {
  name: string;
  qty: number;
  price: number;
  total: number;
}

export interface ReceiptData {
  receipt_no: string;
  invoice_no: string;
  issued_at: string;
  lines: ReceiptLine[];
  subtotal: string;
  tax_total: string;
  total: string;
  payment_method: string;
  payment_reference: string;
  amount_tendered: string;
  change_due: string;
  customer?: string;
  till?: string;
  cashier?: string;
  /** Set for a sale rung up with no connection: it has no receipt number yet. */
  pending_ref?: string;
}

const METHOD = { cash: "Cash", mpesa: "M-Pesa", card: "Card" } as Record<string, string>;

/**
 * 80mm thermal receipt (≈72mm printable). Rendered on screen as a preview and
 * printed through the OS driver — works with any ESC/POS printer installed as
 * a system printer (Epson TM-T20/T82, Xprinter, Bixolon…). Most drivers can
 * also kick the cash drawer on every print; set that in the printer's options.
 */
export function Receipt({ data, branding }: { data: ReceiptData; branding?: Branding }) {
  // The API returns naive UTC timestamps — mark them as UTC so the receipt
  // prints the till's local time.
  const when = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(data.issued_at) ? data.issued_at : `${data.issued_at}Z`);
  return (
    <div id="pos-receipt" className="mx-auto w-[72mm] bg-white px-2 py-3 font-mono text-[11px] leading-snug text-black">
      <div className="text-center">
        <p className="text-[13px] font-bold uppercase">{branding?.name ?? "Receipt"}</p>
        {branding?.address && <p>{branding.address}</p>}
        {branding?.phone && <p>Tel: {branding.phone}</p>}
        {branding?.tax_pin && <p>PIN: {branding.tax_pin}</p>}
      </div>
      <Divider />
      {data.pending_ref ? (
        <>
          <Row left={`Sale ref: ${data.pending_ref}`} right={when.toLocaleDateString("en-GB")} />
          <Row left="Recorded offline" right={when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} />
        </>
      ) : (
        <>
          <Row left={`Receipt: ${data.receipt_no}`} right={when.toLocaleDateString("en-GB")} />
          <Row left={`Invoice: ${data.invoice_no}`} right={when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} />
        </>
      )}
      {data.till && <Row left={`Till: ${data.till}`} right={data.cashier ?? ""} />}
      {data.customer && data.customer !== "Walk-in Customer" && <p>Customer: {data.customer}</p>}
      <Divider />
      {data.lines.map((l, i) => (
        <div key={i} className="mb-1">
          <p className="font-semibold">{l.name}</p>
          <Row left={`  ${l.qty} x ${fmtMoney(l.price)}`} right={fmtMoney(l.total)} />
        </div>
      ))}
      <Divider />
      <Row left="Before VAT" right={fmtMoney(data.subtotal)} />
      <Row left="VAT" right={fmtMoney(data.tax_total)} />
      <div className="my-1 flex justify-between text-[14px] font-bold">
        <span>TOTAL</span>
        <span>{fmtMoney(data.total, branding?.currency)}</span>
      </div>
      <Divider />
      <Row left={`Paid (${METHOD[data.payment_method] ?? data.payment_method})`} right={fmtMoney(data.amount_tendered)} />
      {num(data.change_due) > 0 && <Row left="Change" right={fmtMoney(data.change_due)} />}
      {data.payment_reference && <Row left="Ref" right={data.payment_reference} />}
      <Divider />
      <p className="text-center">{branding?.invoice_footer_note || "Thank you for shopping with us!"}</p>
      <p className="mt-1 text-center text-[9px]">Goods once sold are not returnable without this receipt.</p>
    </div>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="truncate">{left}</span>
      <span className="whitespace-nowrap">{right}</span>
    </div>
  );
}

function Divider() {
  return <div className="my-1.5 border-t border-dashed border-black" />;
}
