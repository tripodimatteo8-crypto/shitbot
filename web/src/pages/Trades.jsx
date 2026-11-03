import React, { useState } from "react";
import { api, pct, short, time, usd, usePoll } from "../api";
import { Conf, Empty, Section, Signed } from "../ui";

function Reason({ text, label }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="text-xs text-ink-2 mt-1 max-w-xl">
      <span className="text-ink-3">{label}: </span>
      <span className={open ? "" : "line-clamp-2"}>{text}</span>
      {text.length > 140 && (
        <button className="text-series-1 ml-1" onClick={() => setOpen(!open)}>
          {open ? "meno" : "altro"}
        </button>
      )}
    </div>
  );
}

export default function Trades() {
  const open = usePoll("/positions?status=open", 10000);
  const closed = usePoll("/positions?status=closed&limit=200", 30000);
  const closePos = async (id) => {
    if (!window.confirm("Chiudere manualmente questa posizione?")) return;
    try {
      await api(`/positions/${id}/close`, { method: "POST" });
    } catch (e) {
      alert(e.message);
    }
    open.reload();
    closed.reload();
  };
  return (
    <div className="space-y-4">
      <Section title={`Posizioni aperte (${open.data?.length ?? 0})`}>
        {!open.data?.length ? (
          <Empty>Nessuna posizione aperta.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Token</th>
                  <th>Aperta</th>
                  <th>Costo</th>
                  <th>PnL (mercato)</th>
                  <th>Liquidità</th>
                  <th>Motivo di Claude</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {open.data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <b>{p.symbol}</b>
                      <div className="text-xs text-ink-3 num">{short(p.mint)}</div>
                    </td>
                    <td className="num text-ink-2">{time(p.opened_at)}</td>
                    <td className="num">{usd(p.cost_usd)}</td>
                    <td>
                      <Signed v={p.pnl_usd}>
                        {usd(p.pnl_usd)} ({pct(p.pnl_pct)})
                      </Signed>
                    </td>
                    <td className="num text-ink-2">{usd(p.last_liquidity, 0)}</td>
                    <td>
                      <Conf v={p.buy_confidence} />
                      <Reason text={p.buy_reason} label={p.decider} />
                    </td>
                    <td>
                      <button className="btn-ghost text-xs" onClick={() => closePos(p.id)}>
                        Chiudi
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={`Storico trade (${closed.data?.length ?? 0})`}>
        {!closed.data?.length ? (
          <Empty>Nessun trade chiuso ancora.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Token</th>
                  <th>Periodo</th>
                  <th>Costo → incasso</th>
                  <th>PnL</th>
                  <th>Costi</th>
                  <th>Uscita</th>
                  <th>Motivo di ingresso</th>
                </tr>
              </thead>
              <tbody>
                {closed.data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <b>{p.symbol}</b>
                      <div className="text-xs text-ink-3">{p.decider}</div>
                    </td>
                    <td className="num text-xs text-ink-2 whitespace-nowrap">
                      {time(p.opened_at)}
                      <br />
                      {time(p.closed_at)}
                    </td>
                    <td className="num whitespace-nowrap">
                      {usd(p.cost_usd)} → {usd(p.proceeds_usd)}
                    </td>
                    <td>
                      <Signed v={p.pnl_usd}>
                        {usd(p.pnl_usd)}
                        <br />
                        {pct(p.pnl_pct)}
                      </Signed>
                    </td>
                    <td className="num text-xs text-ink-2">
                      {p.fills.map((f, i) => (
                        <div key={i}>
                          {f.side}: fee {usd(f.fees_usd)} · slip {pct(f.slippage_pct)} · {f.source}
                        </div>
                      ))}
                    </td>
                    <td className="text-xs text-ink-2 max-w-48">{p.exit_reason}</td>
                    <td>
                      <Conf v={p.buy_confidence} />
                      <Reason text={p.buy_reason} label="ingresso" />
                      <Reason text={p.sell_reason} label="uscita" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
