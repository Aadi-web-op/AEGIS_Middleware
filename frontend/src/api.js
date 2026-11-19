/**
 * Thin API client. Every number on screen comes through here.
 *
 * Errors are classified so pages can show the right state:
 *   unavailable – 404/405 on a collection endpoint (backend lacks the route)
 *   notfound    – 404 on a specific resource (caller decides)
 *   offline     – 503, or a payload flagged graph_available:false
 *   network     – fetch failed (backend not running / CORS)
 *   http        – anything else
 */
import { useCallback, useEffect, useRef, useState } from "react";

export const API = import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(kind, message, { status = null, path = "", body = null } = {}) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.path = path;
    this.body = body;
  }
}

function detailText(body, fallback) {
  if (!body) return fallback;
  const d = body.detail ?? body.reason ?? body.message;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((x) => (x?.loc ? `${x.loc.slice(1).join(".")}: ${x.msg}` : String(x?.msg ?? x))).join("; ");
  }
  if (d) return JSON.stringify(d);
  return fallback;
}

export async function request(method, path, body) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("network", `API unreachable at ${API}`, { path });
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const msg = detailText(data, `HTTP ${res.status}`);
    let kind = "http";
    if (res.status === 503 || data?.graph_available === false) kind = "offline";
    else if (res.status === 404 && data?.detail === "Not Found") kind = "unavailable";
    else if (res.status === 404) kind = "notfound";
    else if (res.status === 405) kind = "unavailable";
    throw new ApiError(kind, msg, { status: res.status, path, body: data });
  }
  return data;
}

export const apiGet = (path) => request("GET", path);
export const apiPost = (path, body) => request("POST", path, body ?? {});
export const apiPatch = (path, body) => request("PATCH", path, body ?? {});

/**
 * useApi(path) – GET with loading / error / data and reload().
 * Pass null to skip. Keeps the previous data while reloading.
 */
export function useApi(path, { interval = 0 } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) });
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const n = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await apiGet(path);
      if (n === seq.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (n === seq.current) setState({ data: null, error, loading: false });
    }
  }, [path]);

  useEffect(() => {
    load();
    if (!interval) return undefined;
    const id = setInterval(load, interval);
    return () => clearInterval(id);
  }, [load, interval]);

  return { ...state, reload: load };
}

export const enc = (s) => encodeURIComponent(s);
