import React from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { pct, time, usd, usePoll, tone } from "../api";
import { Badge, Conf, Empty, Section, Stat, axis, tooltipStyle } from "../ui";

export default function Overview({ ov }) {
  const eq = usePoll("/equity?days=14", 30000);
  const dec = usePoll("/decisions?limit=12", 15000);
  const ev = usePoll("/events?limit=12", 15000);
  if (!ov) return <Empty>Caricamento…</Empty>;
  const tr = ov.trades || {};
  const data = (eq.data || []).map((r) => ({ ...r, t: new Date(r.ts).getTime() }));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="Valore portafoglio" value={usd(ov.equity_usd)} sub={`cash ${usd(ov.cash_usd)} · posizioni ${usd(ov.positions_usd)}`} />
        <Stat
          label="PnL totale"
          value={usd(ov.pnl_usd)}
          valueClass={tone(ov.pnl_usd)}
          sub={`${pct(ov.pnl_pct, 2)} su ${usd(ov.initial_capital_usd, 0)}`}
        />
        <Stat label="Win rate" value={tr.n ? `${tr.win_rate}%` : "—"} sub={`${tr.n || 0} trade chiusi · PF ${tr.profit_factor ?? "—"}`} />
        <Stat label="Max drawdown" value={`${ov.max_drawdown_pct}%`} sub={`expectancy ${usd(tr.expectancy_usd)}`} />
        <Stat
          label="Posizioni aperte"
          value={ov.open_positions}
          sub={`Claude oggi: ${ov.costs_today.calls} chiamate · ${usd(ov.costs_today.usd)}`}
        />
      </div>

      <Section title="Curva di equity (valore di liquidazione prudente)">
        {data.length < 2 ? (
          <Empty>Servono almeno due rilevazioni (una ogni 5 minuti).</Empty>
        ) : (
          <div className="h-72">
            <ResponsiveContainer>
              <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3987e5" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#3987e5" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#262624" vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(t) => new Date(t).toLocaleString("it-IT", { day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                  {...axis}
                />
                <YAxis domain={["auto", "auto"]} tickFormatter={(v) => `$${v.toFixed(2)}`} width={72} {...axis} />
                <ReferenceLine y={ov.initial_capital_usd} stroke="#8d8c84" strokeDasharray="4 4" />
                <Tooltip
                  {...tooltipStyle}
                  labelFormatter={(t) => new Date(t).toLocaleString("it-IT")}
                  formatter={(v, n) => [usd(v), n === "equity" ? "Equity" : n]}
                />
                <Area type="linear" dataKey="equity" stroke="#3987e5" strokeWidth={2} fill="url(#eqfill)" dot={false} activeDot={{ r: 4 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="mt-2 text-xs text-ink-3">Linea tratteggiata: capitale iniziale. Il paper trading sovrastima i risultati reali.</div>
      </Section>

      <div className="grid lg:grid-cols-2 gap-4">
        <Section title="Ultime decisioni">
          {!dec.data?.length ? (
            <Empty>Nessuna decisione ancora.</Empty>
          ) : (
            <ul className="divide-y divide-surface-2">
              {dec.data.map((d) => (
                <li key={d.id} className="py-2">
                  <div className="flex items-center gap-2 text-sm">
                    <Badge kind={d.action} />
                    <b>{d.symbol || d.mint.slice(0, 6)}</b>
                    <Conf v={d.confidence} />
                    <span className="ml-auto text-xs text-ink-3">
                      {time(d.ts)} · {d.decider}
                    </span>
                  </div>
                  <div className="text-xs text-ink-2 mt-1 line-clamp-2">{d.reason}</div>
                  {d.blocked_reason && <div className="text-xs text-warn mt-0.5">risk manager: {d.blocked_reason}</div>}
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Eventi">
          {!ev.data?.length ? (
            <Empty>Nessun evento.</Empty>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {ev.data.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-ink-3 num whitespace-nowrap">{time(e.ts)}</span>
                  <span className={e.level === "error" ? "text-bad" : e.level === "warning" ? "text-warn" : "text-ink-2"}>{e.message}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
