import React from "react";
import { usePoll } from "../api";
import { Empty, Section } from "../ui";

export default function RugModel() {
  const l = usePoll("/learning", 60000);
  const d = l.data;
  if (!d) return null;
  const m = d.model;
  return (
    <Section
      title="Apprendimento dai rug (automatico, in codice)"
      right={
        <span className={`pill ${d.active ? "bg-good/20 text-[#7fd77f]" : "bg-warn/15 text-warn"}`}>
          {d.active ? `filtro attivo · soglia ${Math.round(d.threshold * 100)}%` : "in raccolta dati"}
        </span>
      }
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm mb-4">
        <div className="bg-surface-2 rounded-lg p-3">
          <div className="text-xs text-ink-3">Token etichettati</div>
          <div className="num text-lg">{m ? m.n : 0}</div>
          {!d.active && <div className="text-xs text-ink-3">servono {d.needs.total} e {d.needs.rugs} rug</div>}
        </div>
        <div className="bg-surface-2 rounded-lg p-3">
          <div className="text-xs text-ink-3">Rug osservati</div>
          <div className="num text-lg">{m ? m.rugs : 0}</div>
          <div className="text-xs text-ink-3">tasso base {m ? Math.round(m.base_rate * 100) : "—"}%</div>
        </div>
        <div className="bg-surface-2 rounded-lg p-3">
          <div className="text-xs text-ink-3">Bloccati (24h)</div>
          <div className="num text-lg">{d.blocked_24h}</div>
          <div className="text-xs text-ink-3">{d.blacklisted_creators} creator in blacklist</div>
        </div>
        <div className="bg-surface-2 rounded-lg p-3">
          <div className="text-xs text-ink-3">Trade finiti in rug</div>
          <div className="num text-lg">
            {d.rug_trades}/{d.closed_trades}
          </div>
          <div className="text-xs text-ink-3">perdita ≥ 50%</div>
        </div>
      </div>
      {!d.buckets.length ? (
        <Empty>Ancora nessun token etichettato: servono alcune ore di dati (un token è "rug" se crolla dell'80% entro 6h).</Empty>
      ) : (
        <div className="overflow-x-auto max-h-96">
          <table className="tbl">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Fascia</th>
                <th>Rug / token</th>
                <th>Rischio stimato</th>
              </tr>
            </thead>
            <tbody>
              {d.buckets.map((b, i) => (
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
        Le fasce in grigio hanno ancora pochi campioni e non vengono usate. I token scartati dal filtro appreso continuano a essere misurati: se il
        filtro sbaglia, il modello si corregge.
      </div>
    </Section>
  );
}
