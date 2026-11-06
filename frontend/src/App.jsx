import { useEffect, useState } from "react";
import { api, getToken, setToken, Notice } from "./shared.jsx";
import { Customers, Invoices, Organization } from "./pages/Base.jsx";
import Collections from "./pages/Collections.jsx";
import Reconciliation from "./pages/Reconciliation.jsx";

const TABS = [
  ["organization", "Organization", Organization],
  ["customers", "Customers", Customers],
  ["invoices", "Invoices", Invoices],
  ["collections", "Collections", Collections],
  ["reconciliation", "Bank reconciliation", Reconciliation],
];

function Login({ onDone }) {
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await api("/api/auth/login", { method: "POST", body: form });
      setToken(result.access_token);
      onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>AcmeCorp Collections</h1>
        <p className="muted">Accounts Team login</p>
        <Notice error={error} />
        <label>Username
          <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoFocus />
        </label>
        <label>Password
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        <button type="submit">Log in</button>
      </form>
    </div>
  );
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(getToken()));
  const [tab, setTab] = useState("customers");
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState({});

  useEffect(() => {
    const out = () => setLoggedIn(false);
    window.addEventListener("logout", out);
    return () => window.removeEventListener("logout", out);
  }, []);

  if (!loggedIn) return <Login onDone={() => setLoggedIn(true)} />;

  async function reset() {
    const ok = window.confirm("Reset demo data? This restores the original data and clears conversations, bank transactions and payments.");
    if (!ok) return;
    try {
      await api("/api/admin/reset", { method: "POST" });
      setVersion((v) => v + 1);
      setMessage({ info: "Demo data restored. Customer emails are back to the originals." });
    } catch (err) {
      setMessage({ error: err.message });
    }
  }

  function logout() {
    setToken("");
    setLoggedIn(false);
  }

  const Page = TABS.find(([key]) => key === tab)[2];
  return (
    <div className="app">
      <header>
        <h1>AcmeCorp Collections</h1>
        <nav>
          {TABS.map(([key, label]) => (
            <button key={key} className={key === tab ? "tab active" : "tab"} onClick={() => setTab(key)}>{label}</button>
          ))}
        </nav>
        <div className="header-actions">
          <button className="danger" onClick={reset}>Reset demo data</button>
          <button className="secondary" onClick={logout}>Log out</button>
        </div>
      </header>
      <main>
        <Notice {...message} />
        <Page key={`${tab}-${version}`} />
      </main>
    </div>
  );
}