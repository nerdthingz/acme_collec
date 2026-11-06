import { useState } from "react";
import { api, Badge, day, money, Notice, useAsync } from "../shared.jsx";

const LEVEL_TONE = { high: "green", medium: "orange", low: "red" };

function Decision({ txn, openInvoices, onChanged }) {
  const suggested = txn.invoices.map((i) => i.invoice_number);
  const [pick, setPick] = useState("");
  const [action, setAction] = useState(txn.suggested_action === "close_tds" ? "close_tds" : "leave_open");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const choices = openInvoices.filter((i) => i.currency === txn.currency);
  const showAction = Boolean(pick) || ["close_tds", "leave_open"].includes(txn.suggested_action);

  async function decide(kind) {
    setBusy(true);
    setError("");
    try {
      const body = kind === "approve" ? { ...(pick ? { invoice_numbers: [pick] } : {}), action } : {};
      await api(`/api/reconciliation/transactions/${txn.txn_id}/${kind}`, { method: "POST", body });
      onChanged();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="decision">
      <select value={pick} onChange={(e) => setPick(e.target.value)}>
        <option value="">{suggested.length ? `Use suggestion (${suggested.join(", ")})` : "Choose invoice..."}</option>
        {choices.map((i) => (
          <option key={i.invoice_number} value={i.invoice_number}>
            {i.invoice_number} · {i.customer_name} · {money(i.balance_due, i.currency)}
          </option>
        ))}
      </select>
      {showAction && (
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="leave_open">If less: leave balance open</option>
          <option value="close_tds">If less: close invoice (TDS deducted)</option>
        </select>
      )}
      <div className="inline">
        <button disabled={busy || (!pick && suggested.length === 0)} onClick={() => decide("approve")}>Approve</button>
        <button className="secondary" disabled={busy} onClick={() => decide("reject")}>Reject</button>
      </div>
      {error && <small className="error-text">{error}</small>}
    </div>
  );
}

function Outcome({ txn }) {
  if (txn.review_status === "approved") {
    return (
      <div>
        <Badge tone="green">Approved</Badge>
        {(txn.applied || []).map((a) => (
          <small key={a.invoice_number} className="block">
            {a.invoice_number}: {a.new_status}, balance {money(a.new_balance, txn.currency)}
            {a.tds_amount > 0 && ` (TDS ${money(a.tds_amount, txn.currency)})`}
          </small>
        ))}
      </div>
    );
  }
  if (txn.review_status === "rejected") return <Badge tone="red">Rejected</Badge>;
  if (txn.review_status === "duplicate") return <Badge>Duplicate</Badge>;
  return <Badge>Ignored</Badge>;
}

function Row({ txn, openInvoices, onChanged }) {
  const decidable = ["pending", "unmatched"].includes(txn.review_status);
  const credit = txn.direction === "credit";
  return (
    <tr>
      <td>{day(txn.txn_date)}</td>
      <td>{txn.narration}{txn.reference && <small className="block muted">Ref {txn.reference}</small>}</td>
      <td className={credit ? "credit" : "debit"}>{credit ? "+" : "-"}{money(txn.amount, txn.currency)}</td>
      <td>
        {txn.invoices.length > 0 ? txn.invoices.map((i) => i.invoice_number).join(" + ") : <span className="muted">None</span>}
        {txn.customer_name && txn.invoices.length > 0 && <small className="block muted">{txn.customer_name}</small>}
      </td>
      <td>{txn.confidence > 0 && <Badge tone={LEVEL_TONE[txn.level]}>{txn.confidence}</Badge>}</td>
      <td>{txn.reason}</td>
      <td>{decidable ? <Decision txn={txn} openInvoices={openInvoices} onChanged={onChanged} /> : <Outcome txn={txn} />}</td>
    </tr>
  );
}

export default function Reconciliation() {
  const batches = useAsync(() => api("/api/reconciliation/batches"));
  const invoices = useAsync(() => api("/api/invoices?status=sent"));
  const [batch, setBatch] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function open(id) {
    setError("");
    try {
      setBatch(await api(`/api/reconciliation/batches/${id}`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function upload() {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      setBatch(await api("/api/reconciliation/upload", { method: "POST", body: form }));
      batches.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function changed() {
    await open(batch.batch_id);
    invoices.reload();
    batches.reload();
  }

  const openInvoices = (invoices.data || []).filter((i) => i.amount_owed > 0).map((i) => ({ ...i, balance_due: i.amount_owed }));

  return (
    <div>
      <section className="card">
        <h2>Upload bank statement</h2>
        <div className="inline wrap">
          <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files[0] || null)} />
          <button disabled={busy || !file} onClick={upload}>Upload and match</button>
          <select value={batch ? batch.batch_id : ""} onChange={(e) => e.target.value && open(e.target.value)}>
            <option value="">Previous uploads...</option>
            {(batches.data || []).map((b) => (
              <option key={b.batch_id} value={b.batch_id}>{b.filename} · {Object.entries(b.summary).map(([k, v]) => `${v} ${k}`).join(", ")}</option>
            ))}
          </select>
        </div>
        <Notice error={error} />
        <p className="muted">Nothing is applied to an invoice until you approve it.</p>
      </section>

      {batch && (
        <section className="card">
          <h2>{batch.filename}</h2>
          <div className="chips">
            {Object.entries(batch.summary).map(([status, count]) => <Badge key={status} tone="blue">{count} {status}</Badge>)}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Date</th><th>Narration</th><th>Amount</th><th>Suggested</th><th>Score</th><th>Reason</th><th>Decision</th></tr>
              </thead>
              <tbody>
                {batch.transactions.map((t) => <Row key={t.txn_id} txn={t} openInvoices={openInvoices} onChanged={changed} />)}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}