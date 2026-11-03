import React, { useState } from "react";
import { usePoll } from "../api";
import { Empty, Section } from "../ui";

function Box({ label, value, sub }) {
  return (
    <div className="bg-surface-2 rounded-lg p-3">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="num text-lg">{value}</div>
      {sub && <div className="text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export default function RugModel() {
  const l = usePoll("/learning", 60000);
  const [target, setTarget] = useState("rug");
  const d = l.data;
  if (!d) return null;
  const m = d.model;
  const h = `${d.horizon_hours}h`;
  const rows = target === "rug" ? d.buckets : d.dump_buckets;
  return (
    <Section
      title={`Indicatori di rischio a breve (entro ${h}, appresi in automatico)`}
      right={
        <span className={`pill ${d.active ? "bg-good/20 text-[#7fd77f]" : "bg-warn/15 text-warn"}`}>
          {d.active ? `filtro rug attivo · soglia ${Math.round(d.threshold * 100)}%` : "in raccolta dati"}
        </span>
      }
    >
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 text-sm mb-4">
        <Box label="Token etichettati" value={m ? m.n : 0} sub={!d.active ? `il filtro parte con ${d.needs.total} token e ${d.needs.rugs} rug` : null} />
        <Box label={`Rug (−${d.rug_drop_pct}% o liquidità sparita)`} value={m ? m.rugs : 0} sub={m ? `tasso base ${Math.round(m.base_rate * 100)}%` : null} />
        <Box label={`Dump (−${d.dump_drop_pct}%: stop loss)`} value={d.dump ? d.dump.rugs : 0} sub={d.dump ? `tasso base ${Math.round(d.dump.base_rate * 100)}%` : null} />
        <Box label="Bloccati (24h)" value={d.blocked_24h} sub={`${d.blacklisted_creators} creator in blacklist`} />
        <Box label="Trade finiti in rug" value={`${d.rug_trades}/${d.closed_trades}`} sub="perdita ≥ 50%" />
      </div>
      <div className="flex gap-1 mb-2">
        {[
          ["rug", "Rischio rug"],
          ["dump", "Rischio dump"],
        ].map(([k, label]) => (
          <button key={k} onClick={() => setTarget(k)} className={`btn text-xs ${target === k ? "bg-series-1 text-white" : "bg-surface-2 text-ink-2"}`}>
            {label}
          </button>
        ))}
      </div>
      {!rows.length ? (
        <Empty>Ancora nessun token etichettato: le etichette arrivano {h} dopo che il bot vede un token.</Empty>
      ) : (
        <div className="overflow-x-auto max-h-96">
          <table className="tbl">
            <thead>
              <tr>
                <th>Indicatore</th>
                <th>Fascia</th>
                <th>Casi / token</th>
                <th>Rischio stimato</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b, i) => (
                <tr key={i} className={b.used ? "" : "opacity-50"}>
                  <td className="text-ink-2">{b.feature}</td>
                  <td className="num">{b.bucket}</td>
                  <td className="num">
                    {b.rugs}/{b.n}
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-2">
                      <span className="w-24 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                        <span className="block h-full" style={{ width: `${Math.round(b.rate * 100)}%`, background: b.rate >= d.threshold ? "#e66767" : "#3987e5" }} />
                      </span>
                      <span className="num text-xs">{Math.round(b.rate * 100)}%</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-2 text-xs text-ink-3">
        Sono probabilità, non certezze. Le fasce in grigio hanno ancora pochi campioni e non vengono usate. I token scartati continuano a
        essere misurati: se il filtro sbaglia, il modello si corregge.
      </div>
    </Section>
  );
}
