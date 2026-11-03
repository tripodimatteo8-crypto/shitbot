import React from "react";
import { tone } from "./api";

export function Stat({ label, value, sub, valueClass = "" }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-ink-3">{label}</div>
      <div className={`mt-1 text-2xl font-semibold num ${valueClass}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-2">{sub}</div>}
    </div>
  );
}

export function Section({ title, right, children }) {
  return (
    <section className="card min-w-0">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-ink-1">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Signed({ v, children }) {
  return <span className={`num ${tone(v)}`}>{children}</span>;
}

const KIND = {
  buy: "bg-series-1/20 text-[#86b6ef]",
  sell: "bg-series-2/20 text-[#ec835a]",
  skip: "bg-surface-3 text-ink-2",
  filtered: "bg-surface-2 text-ink-3",
  pending: "bg-warn/15 text-warn",
  expired: "bg-surface-2 text-ink-3",
  open: "bg-series-1/20 text-[#86b6ef]",
  closed: "bg-surface-3 text-ink-2",
};
const LABEL = { buy: "COMPRATO", sell: "VENDUTO", skip: "SALTATO", filtered: "FILTRATO", pending: "IN ATTESA", expired: "SCADUTO" };

export function Badge({ kind, text }) {
  return <span className={`pill ${KIND[kind] || "bg-surface-3 text-ink-2"}`}>{text || LABEL[kind] || kind}</span>;
}

export function Conf({ v }) {
  if (v === null || v === undefined) return null;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-ink-2" title="confidence">
      <span className="w-12 h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <span className="block h-full bg-series-1" style={{ width: `${Math.round(v * 100)}%` }} />
      </span>
      <span className="num">{v.toFixed(2)}</span>
    </span>
  );
}

export function Empty({ children }) {
  return <div className="text-sm text-ink-3 py-6 text-center">{children}</div>;
}

export const tooltipStyle = {
  contentStyle: { background: "#242422", border: "1px solid #3a3a37", borderRadius: 8, fontSize: 12, color: "#f0efec" },
  labelStyle: { color: "#c3c2b7" },
  itemStyle: { color: "#f0efec" },
  cursor: { stroke: "#8d8c84", strokeDasharray: "3 3" },
};

export const axis = { stroke: "#3a3a37", tick: { fill: "#8d8c84", fontSize: 11 }, tickLine: false };
