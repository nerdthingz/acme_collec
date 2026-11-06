import { useState } from "react";
import { api, Badge, day, money, Notice, useAsync } from "../shared.jsx";

function Fact({ label, value }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function Organization() {
  const { data: org, error } = useAsync(() => api("/api/organization"));
  if (error) return <Notice error={error} />;
  if (!org) return <p>Loading...</p>;
  return (
    <div className="grid">
      <section className="card">
        <h2>{org.name}</h2>
        <dl>
          <Fact label="Address" value={org.address} />
          <Fact label="Accounts contact" value={`${org.accounts_contact_name} (${org.accounts_email})`} />
          <Fact label="Phone" value={org.phone} />
          <Fact label="Reporting currency" value={org.default_currency} />
          <Fact label="Accepted currencies" value={org.accepted_currencies.join(", ")} />
          <Fact label="Payment methods" value={org.payment_methods.join(", ")} />
          <Fact label="Payment terms" value={org.payment_terms} />
        </dl>
      </section>
      <section className="card">
        <h2>Bank details</h2>
        <dl>
          {Object.entries(org.bank_details).map(([key, value]) => (
            <Fact key={key} label={key.replace(/_/g, " ")} value={value} />
          ))}
        </dl>
      </section>
      <section className="card">
        <h2>Policies</h2>
        <dl>
          {Object.entries(org.policies).map(([key, value]) => (
            <Fact key={key} label={key.replace(/_/g, " ")} value={value} />
          ))}
        </dl>
      </section>
    </div>
  );
}

function EmailCell({ customer, onSaved }) {
  const [value, setValue] = useState(customer.contact_email);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError("");
    try {
      await api(`/api/customers/${customer.customer_id}/email`, { method: "PATCH", body: { contact_email: value } });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="email-cell">
      <div className="inline">
        <input value={value} onChange={(e) => setValue(e.target.value)} />
        <button disabled={saving || value === customer.contact_email} onClick={save}>Save</button>
      </div>
      {error && <small className="error-text">{error}</small>}
    </div>
  );
}

export function Customers() {
  const { data, error, reload } = useAsync(() => api("/api/customers"));
  if (error) return <Notice error={error} />;
  if (!data) return <p>Loading...</p>;
  return (
    <section className="card">
      <h2>Customers</h2>
      <p className="muted">Edit a customer's email to your own test inbox, then save.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>ID</th><th>Company</th><th>Contact</th><th>Email</th><th>Currency</th><th>Outstanding</th><th>Overdue</th></tr>
          </thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.customer_id}>
                <td>{c.customer_id}</td>
                <td>{c.name}<br /><small className="muted">{c.city}, {c.country}</small></td>
                <td>{c.contact_name}<br /><small className="muted">{c.phone}</small></td>
                <td><EmailCell key={c.contact_email} customer={c} onSaved={reload} /></td>
                <td>{c.currency}</td>
                <td>{money(c.outstanding, c.currency)}</td>
                <td>
                  {c.overdue_invoices > 0
                    ? <Badge tone="red">{c.overdue_invoices} invoice(s), {money(c.overdue_amount, c.currency)}</Badge>
                    : <Badge tone="green">None</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const FILTERS = [
  ["all", "All"],
  ["overdue", "Overdue"],
  ["unpaid", "Unpaid (sent)"],
  ["draft", "Draft"],
  ["paid", "Paid"],
];

function matches(filter, invoice) {
  if (filter === "overdue") return invoice.is_overdue;
  if (filter === "unpaid") return invoice.amount_owed > 0;
  if (filter === "draft") return invoice.status === "draft";
  if (filter === "paid") return invoice.status === "paid";
  return true;
}

function StatusBadge({ invoice }) {
  if (invoice.is_overdue) return <Badge tone="red">Overdue {invoice.days_overdue} days</Badge>;
  if (invoice.status === "paid") return <Badge tone="green">Paid</Badge>;
  if (invoice.status === "draft") return <Badge>Draft</Badge>;
  return <Badge tone="blue">Sent</Badge>;
}

export function Invoices() {
  const { data, error } = useAsync(() => api("/api/invoices"));
  const [filter, setFilter] = useState("overdue");
  if (error) return <Notice error={error} />;
  if (!data) return <p>Loading...</p>;

  const rows = data.filter((i) => matches(filter, i));
  const unpaid = {};
  data.forEach((i) => {
    if (i.amount_owed > 0) unpaid[i.currency] = (unpaid[i.currency] || 0) + i.amount_owed;
  });

  return (
    <section className="card">
      <h2>Invoices</h2>
      <div className="chips">
        {Object.entries(unpaid).map(([currency, amount]) => (
          <Badge key={currency} tone="blue">Unpaid {currency}: {money(amount, currency)}</Badge>
        ))}
        <Badge tone="red">{data.filter((i) => i.is_overdue).length} overdue</Badge>
      </div>
      <div className="inline filters">
        {FILTERS.map(([key, label]) => (
          <button key={key} className={filter === key ? "tab active" : "tab"} onClick={() => setFilter(key)}>{label}</button>
        ))}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Invoice</th><th>Customer</th><th>Date</th><th>Due</th><th>Total</th><th>Still unpaid</th><th>Status</th></tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.invoice_number}>
                <td>{i.invoice_number}{i.po_number && <><br /><small className="muted">PO {i.po_number}</small></>}</td>
                <td>{i.customer_name}</td>
                <td>{day(i.invoice_date)}</td>
                <td>{day(i.due_date)}</td>
                <td>{money(i.total, i.currency)}</td>
                <td>{money(i.amount_owed, i.currency)}</td>
                <td><StatusBadge invoice={i} /></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="7" className="muted">No invoices.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}