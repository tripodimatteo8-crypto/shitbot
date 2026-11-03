import React from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compact, usd, usePoll } from "../api";
import { Empty, Section, Stat, axis, tooltipStyle } from "../ui";

export default function Costs() {
  const c = usePoll("/costs?days=30", 60000);
  if (!c.data) return <Empty>Caricamento…</Empty>;
  const t = c.data.today;
  const days = c.data.days;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Spesa oggi" value={usd(t.usd)} />
        <Stat label="Chiamate oggi" value={t.calls} />
        <Stat label="Token oggi" value={compact(t.tokens)} sub={`input ${compact(t.input)} · output ${compact(t.output)}`} />
        <Stat label="Cache letta oggi" value={compact(t.cache_read)} sub="token serviti dalla prompt cache" />
      </div>
      <Section title="Spesa Claude per giorno (USD)">
        {!days.length ? (
          <Empty>Nessuna chiamata a Claude ancora (senza ANTHROPIC_API_KEY decide la baseline a regole, gratis).</Empty>
        ) : (
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={days} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid stroke="#262624" vertical={false} />
                <XAxis dataKey="day" {...axis} />
                <YAxis tickFormatter={(v) => `$${v}`} width={48} {...axis} />
                <Tooltip {...tooltipStyle} cursor={{ fill: "#ffffff08" }} formatter={(v, n) => [usd(v, 3), n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: "#c3c2b7" }} />
                <Bar dataKey="decision_usd" name="Decisioni" stackId="a" fill="#3987e5" stroke="#1a1a19" strokeWidth={2} />
                <Bar dataKey="reflection_usd" name="Riflessione" stackId="a" fill="#d95926" stroke="#1a1a19" strokeWidth={2} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Section>
      <Section title="Dettaglio">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Giorno (UTC)</th>
                <th>Chiamate</th>
                <th>Input</th>
                <th>Output</th>
                <th>Cache read</th>
                <th>Cache write</th>
                <th>USD</th>
              </tr>
            </thead>
            <tbody>
              {[...days].reverse().map((d) => (
                <tr key={d.day} className="num">
                  <td>{d.day}</td>
                  <td>{d.calls}</td>
                  <td>{compact(d.input)}</td>
                  <td>{compact(d.output)}</td>
                  <td>{compact(d.cache_read)}</td>
                  <td>{compact(d.cache_write)}</td>
                  <td>{usd(d.usd, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
