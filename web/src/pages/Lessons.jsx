import React, { useMemo, useState } from "react";
import { diffLines } from "diff";
import { api, time, usd, usePoll } from "../api";
import { Empty, Section } from "../ui";
import RugModel from "./RugModel.jsx";

function MetricBox({ title, m }) {
  return (
    <div className="bg-surface-2 rounded-lg p-3 text-xs">
      <div className="text-ink-3 mb-1">{title}</div>
      {!m || !m.n ? (
        <div className="text-ink-3">nessun trade</div>
      ) : (
        <div className="num space-y-0.5">
          <div>trade: {m.n}</div>
          <div>win rate: {m.win_rate}%</div>
          <div>PnL: {usd(m.pnl_usd)}</div>
          <div>expectancy: {usd(m.expectancy_usd)}</div>
        </div>
      )}
    </div>
  );
}

export default function Lessons() {
  const v = usePoll("/lessons", 60000);
  const [sel, setSel] = useState(null);
  const [mode, setMode] = useState("diff");
  const list = v.data || [];
  const idx = sel === null ? 0 : list.findIndex((x) => x.id === sel);
  const cur = list[idx];
  const prev = list[idx + 1];
  const parts = useMemo(() => (cur && prev ? diffLines(prev.content, cur.content) : null), [cur, prev]);
  const reflect = async () => {
    await api("/reflect", { method: "POST" });
    alert("Riflessione avviata: la nuova versione comparirà tra qualche minuto (serve l'abbonamento via Claude Code o una API key).");
  };
  if (!list.length) return <RugModel />;
  return (
    <div className="space-y-4">
    <RugModel />
    <div className="grid lg:grid-cols-[260px_1fr] gap-4">
      <Section title="Versioni" right={<button className="btn-ghost text-xs" onClick={reflect}>Rifletti ora</button>}>
        <ul className="space-y-1">
          {list.map((x, i) => (
            <li key={x.id}>
              <button
                onClick={() => setSel(x.id)}
                className={`w-full text-left px-2 py-1.5 rounded-lg text-sm ${i === idx ? "bg-surface-3" : "hover:bg-surface-2"}`}
              >
                <span className="font-medium">v{x.id}</span> <span className="text-ink-3 text-xs">{x.trigger}</span>
                <div className="text-xs text-ink-3">{time(x.ts)}</div>
              </button>
            </li>
          ))}
        </ul>
      </Section>
      {cur && (
        <Section
          title={`lezioni.md — v${cur.id}`}
          right={
            <div className="flex gap-1">
              {["diff", "testo"].map((m) => (
                <button key={m} onClick={() => setMode(m)} className={`btn text-xs ${mode === m ? "bg-series-1 text-white" : "bg-surface-2 text-ink-2"}`}>
                  {m}
                </button>
              ))}
            </div>
          }
        >
          <div className="grid sm:grid-cols-2 gap-3 mb-4">
            <MetricBox title={`Metriche alla scrittura (${cur.closed_trades} trade chiusi)`} m={cur.metrics_before} />
            <MetricBox title="Trade aperti con questa versione" m={cur.metrics_after} />
          </div>
          {mode === "diff" && parts ? (
            <pre className="text-xs whitespace-pre-wrap font-mono bg-surface-0 rounded-lg p-3 overflow-x-auto">
              {parts.map((p, i) => (
                <span
                  key={i}
                  className={p.added ? "bg-good/15 text-[#7fd77f]" : p.removed ? "bg-bad/15 text-[#f0a0a0] line-through" : "text-ink-2"}
                >
                  {p.value}
                </span>
              ))}
            </pre>
          ) : (
            <pre className="text-sm whitespace-pre-wrap font-mono bg-surface-0 rounded-lg p-3 text-ink-2">{cur.content}</pre>
          )}
          {mode === "diff" && !prev && <div className="text-xs text-ink-3 mt-2">Prima versione: nessun confronto disponibile.</div>}
        </Section>
      )}
    </div>
    </div>
  );
}
