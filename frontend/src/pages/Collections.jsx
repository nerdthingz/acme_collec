import { useState } from "react";
import { api, Badge, Notice, stamp, useAsync } from "../shared.jsx";

function AttentionCard({ item, onDone }) {
  const [draft, setDraft] = useState(item.attention.draft || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const problems = item.attention.problems || [];

  async function send(confirm = false) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/collections/attention/${item.id}/send`, { method: "POST", body: { body: draft, confirm } });
      onDone();
    } catch (err) {
      if (!confirm && err.message.includes("Send again with confirm") && window.confirm(`${err.message}\n\nSend it anyway?`)) {
        await send(true);
        return;
      }
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function dismiss() {
    setBusy(true);
    try {
      await api(`/api/collections/attention/${item.id}/dismiss`, { method: "POST" });
      onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="item">
      <div className="item-head">
        <strong>{item.customer_name || item.from_email}</strong>
        <span className="muted">{item.from_email} · {stamp(item.created_at)}</span>
        <Badge tone="orange">{(item.intent || "other").replace(/_/g, " ")}</Badge>
      </div>
      <p className="reason">{item.attention.reason}</p>
      <div className="quote"><strong>{item.subject}</strong><pre>{item.body}</pre></div>
      {problems.length > 0 && (
        <ul className="problems">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      <label>Reply (edit before sending)
        <textarea rows="9" value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <Notice error={error} />
      <div className="inline">
        <button disabled={busy || !draft.trim()} onClick={() => send(false)}>Send reply</button>
        <button className="secondary" disabled={busy} onClick={dismiss}>Dismiss</button>
      </div>
    </div>
  );
}

function Conversation({ id }) {
  const { data, error } = useAsync(() => api(`/api/collections/conversations/${id}`), [id]);
  if (error) return <Notice error={error} />;
  if (!data) return <p>Loading...</p>;
  return (
    <div>
      <h3>{data.customer_name}</h3>
      {data.payment_claims.length > 0 && (
        <div className="notice info">
          <strong>Payment claims (not verified, no invoice was changed):</strong>
          <ul>
            {data.payment_claims.map((c) => (
              <li key={c.message_id}>{stamp(c.noted_at)}: {c.summary} {c.invoices.length > 0 && `(${c.invoices.join(", ")})`}</li>
            ))}
          </ul>
        </div>
      )}
      {data.delivery_issue && <Notice error="A delivery failure (bounce) was received for this contact." />}
      {data.messages.map((m) => (
        <div key={m.id} className={`message ${m.direction}`}>
          <div className="message-head">
            <Badge tone={m.direction === "inbound" ? "blue" : "green"}>{m.kind.replace(/_/g, " ")}</Badge>
            <span className="muted">{m.direction === "inbound" ? "from" : "to"} {m.direction === "inbound" ? m.from_email : m.to_email} · {stamp(m.created_at)}</span>
          </div>
          <strong>{m.subject}</strong>
          <pre>{m.body}</pre>
          {m.intent && <small className="muted">AI intent: {m.intent.replace(/_/g, " ")}</small>}
        </div>
      ))}
    </div>
  );
}

export default function Collections() {
  const customers = useAsync(() => api("/api/customers"));
  const attention = useAsync(() => api("/api/collections/attention"));
  const conversations = useAsync(() => api("/api/collections/conversations"));
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");
  const [remindId, setRemindId] = useState("");
  const [openId, setOpenId] = useState("");

  function refresh() {
    attention.reload();
    conversations.reload();
  }

  async function run(action) {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      setInfo(await action());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      refresh();
    }
  }

  const remind = (body) => run(async () => {
    const results = await api("/api/collections/reminders", { method: "POST", body });
    const count = (status) => results.filter((r) => r.status === status).length;
    const failed = results.filter((r) => r.status === "failed").map((r) => r.reason).join("; ");
    return `Reminders: ${count("sent")} sent, ${count("skipped")} skipped (already reminded or nothing overdue), ${count("failed")} failed. ${failed}`;
  });

  const checkInbox = () => run(async () => {
    const s = await api("/api/collections/inbox/check", { method: "POST" });
    return `Inbox checked: ${s.fetched} new, ${s.auto_answered} answered automatically, ${s.needs_attention} need attention, ${s.ignored} ignored, ${s.duplicate} duplicates, ${s.errors} errors.`;
  });

  return (
    <div>
      <section className="card">
        <h2>Actions</h2>
        <div className="inline wrap">
          <button disabled={busy} onClick={() => remind({})}>Send reminders (all overdue)</button>
          <select value={remindId} onChange={(e) => setRemindId(e.target.value)}>
            <option value="">One customer...</option>
            {(customers.data || []).map((c) => <option key={c.customer_id} value={c.customer_id}>{c.name}</option>)}
          </select>
          <button className="secondary" disabled={busy || !remindId} onClick={() => remind({ customer_id: remindId, force: true })}>Remind now</button>
          <button className="secondary" disabled={busy} onClick={checkInbox}>Check inbox now</button>
        </div>
        <Notice error={error} info={info} />
      </section>

      <section className="card">
        <h2>Needs attention {attention.data && <Badge tone="orange">{attention.data.length}</Badge>}</h2>
        <Notice error={attention.error} />
        {attention.data && attention.data.length === 0 && <p className="muted">Nothing is waiting for a person.</p>}
        {(attention.data || []).map((item) => <AttentionCard key={item.id} item={item} onDone={refresh} />)}
      </section>

      <section className="card">
        <h2>Conversations</h2>
        <Notice error={conversations.error} />
        <div className="split">
          <div className="list">
            {(conversations.data || []).map((c) => (
              <button key={c.conversation_id} className={openId === c.conversation_id ? "row active" : "row"} onClick={() => setOpenId(c.conversation_id)}>
                <strong>{c.customer_name}</strong>
                {c.needs_attention && <Badge tone="orange">attention</Badge>}
                {c.kind === "unknown" && <Badge>unknown sender</Badge>}
                {c.delivery_issue && <Badge tone="red">bounce</Badge>}
                <small className="muted">{c.message_count} messages · {stamp(c.last_message_at)}</small>
                <small>{c.last_snippet}</small>
              </button>
            ))}
            {conversations.data && conversations.data.length === 0 && <p className="muted">No conversations yet. Send a reminder first.</p>}
          </div>
          <div className="detail">
            {openId ? <Conversation id={openId} key={openId} /> : <p className="muted">Select a conversation.</p>}
          </div>
        </div>
      </section>
    </div>
  );
}