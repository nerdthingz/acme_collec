import { useCallback, useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
let token = sessionStorage.getItem("token") || "";

export const getToken = () => token;

export function setToken(value) {
  token = value;
  if (value) sessionStorage.setItem("token", value);
  else sessionStorage.removeItem("token");
}

function errorText(data, status) {
  if (!data || !data.detail) return `Request failed (${status})`;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  return `Request failed (${status})`;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(BASE + path, { method, headers, body: payload });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running?");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401 && path !== "/api/auth/login") {
    setToken("");
    window.dispatchEvent(new Event("logout"));
  }
  if (!response.ok) throw new Error(errorText(data, response.status));
  return data;
}

export function money(amount, currency) {
  const locale = currency === "INR" ? "en-IN" : "en-US";
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(amount);
}

export function day(iso) {
  if (!iso) return "";
  return new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric",
  });
}

export function stamp(iso) {
  if (!iso) return "";
  return new Date(iso.replace(/(\.\d{3})\d+/, "$1")).toLocaleString("en-GB");
}

export function useAsync(load, deps = []) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  const run = useCallback(async () => {
    try {
      setState({ data: await load(), error: "", loading: false });
    } catch (error) {
      setState({ data: null, error: error.message, loading: false });
    }
  }, deps);
  useEffect(() => {
    run();
  }, [run]);
  return { ...state, reload: run };
}

export function Notice({ error, info }) {
  if (error) return <div className="notice error">{error}</div>;
  if (info) return <div className="notice info">{info}</div>;
  return null;
}

export function Badge({ tone = "grey", children }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}