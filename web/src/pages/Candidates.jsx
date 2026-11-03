import React, { useState } from "react";
import { compact, pct, short, time, usePoll } from "../api";
import { Badge, Conf, Empty, Section, Signed } from "../ui";

const FILTERS = [
  ["all", "Tutti", ""],
  ["passed", "Passano i filtri", "&passed=true"],
  ["rejected", "Scartati", "&passed=false"],
];

export default function Candidates() {
  const [f, setF] = useState("passed");
  const q = FILTERS.find((x) => x[0] === f)[2];
  const c = usePoll(`/candidates?limit=200${q}`, 15000);
  const st = usePoll("/candidates/stats?hours=24", 60000);
  return (
    <div className="space-y-4">
      {st.data && (
        <div className="card text-sm flex flex-wrap gap-x-6 gap-y-2">
          <span>
            Ultime 24h: <b className="num">{st.data.total}</b> valutati, <b className="num">{st.data.passed}</b> passano i filtri
          </span>
          <span className="text-ink-3">Motivi di scarto principali:</span>
          {st.data.top_reject_reasons.map(([k, n]) => (
            <span key={k} className="text-ink-2">
              {k} <span className="num text-ink-3">{n}</span>
            </span>
          ))}
        </div>
      )}
      <Section
        title="Feed live dei candidati"
        right={
          <div className="flex gap-1">
            {FILTERS.map(([id, label]) => (
              <button key={id} onClick={() => setF(id)} className={`btn text-xs ${f === id ? "bg-series-1 text-white" : "bg-surface-2 text-ink-2"}`}>
                {label}
              </button>
            ))}
          </div>
        }
      >
        {!c.data?.length ? (
          <Empty>Nessun candidato.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Ora</th>
                  <th>Token</th>
                  <th>Liq / MCap</th>
                  <th>Età</th>
                  <th>Esito / decisione</th>
                  <th>1h</th>
                  <th>6h</th>
                  <th>24h</th>
                </tr>
              </thead>
              <tbody>
                {c.data.map((x) => (
                  <tr key={x.id}>
                    <td className="num text-xs text-ink-2 whitespace-nowrap">{time(x.ts)}</td>
                    <td>
                      <a href={`https://dexscreener.com/solana/${x.mint}`} target="_blank" rel="noreferrer" className="font-semibold hover:text-series-1">
                        {x.symbol || "?"}
                      </a>
                      <div className="text-xs text-ink-3 num">{short(x.mint)}</div>
                    </td>
                    <td className="num text-xs">
                      ${compact(x.liquidity_usd)} / ${compact(x.mcap_usd)}
                    </td>
                    <td className="num text-xs text-ink-2">
                      {x.age_minutes != null ? (x.age_minutes < 120 ? `${Math.round(x.age_minutes)}m` : `${(x.age_minutes / 60).toFixed(1)}h`) : "—"}
                    </td>
                    <td className="max-w-md">
                      <div className="flex items-center gap-2">
                        <Badge kind={x.status} />
                        <Conf v={x.decision_confidence} />
                      </div>
                      {x.passed ? (
                        x.decision_reason && <div className="text-xs text-ink-2 mt-1 line-clamp-2">{x.decision_reason}</div>
                      ) : (
                        <div className="text-xs text-ink-3 mt-1">{(x.reasons || []).join(" · ")}</div>
                      )}
                    </td>
                    {["ret_1h", "ret_6h", "ret_24h"].map((k) => (
                      <td key={k} className="text-xs">
                        <Signed v={x[k]}>{pct(x[k], 0)}</Signed>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-2 text-xs text-ink-3">
          Gli esiti 1h/6h/24h sono calcolati dal codice sul prezzo di mercato (senza costi), anche per i token scartati o saltati.
        </div>
      </Section>
    </div>
  );
}
