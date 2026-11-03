import { useEffect, useState, useCallback } from "react";

export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export function usePoll(path, ms = 15000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api(path)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [path]);
  useEffect(() => {
    load();
    const id = setInterval(load, ms);
    return () => clearInterval(id);
  }, [load, ms]);
  return { data, error, reload: load };
}

export const usd = (x, d = 2) =>
  x === null || x === undefined
    ? "—"
    : `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (x, d = 1) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}%`);
export const compact = (x) =>
  x === null || x === undefined ? "—" : Intl.NumberFormat("it-IT", { notation: "compact", maximumFractionDigits: 1 }).format(x);
export const time = (iso) =>
  iso ? new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
export const short = (m) => (m ? `${m.slice(0, 4)}…${m.slice(-4)}` : "");
export const tone = (x) => (x > 0 ? "text-good" : x < 0 ? "text-bad" : "text-ink-2");
