import React, { useEffect, useState } from "react";
import { api, usePoll } from "../api";
import { Empty, Section } from "../ui";

const GROUPS = [
  ["Filtri (codice, prima di Claude)", ["min_liquidity_usd", "max_liquidity_usd", "min_mcap_usd", "max_mcap_usd", "min_age_minutes", "max_age_hours", "min_volume_h1_usd", "min_txns_h1", "min_sells_h1", "max_top10_pct", "max_single_holder_pct", "max_insider_pct", "min_holders", "max_rugcheck_score_norm", "require_no_mint_authority", "require_no_freeze_authority", "require_sell_route"]],
  ["Limiti di rischio (fuori dall'agente)", ["max_position_pct", "min_position_usd", "max_open_positions", "stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "trailing_activation_pct", "max_hold_hours", "daily_loss_limit_pct", "min_liquidity_to_hold_usd"]],
  ["Costi simulati", ["swap_fee_pct", "priority_fee_sol", "network_fee_sol", "mev_buffer_pct", "execution_delay_s", "fallback_slippage_floor_pct"]],
  ["Cicli (secondi)", ["collect_interval_s", "agent_interval_s", "monitor_interval_s", "evaluate_interval_s"]],
  ["Claude", ["claude_model", "claude_effort", "claude_fallbacks", "max_claude_calls_per_day", "max_claude_tokens_per_day", "max_claude_usd_per_day", "max_candidates_per_cycle", "reflect_every_n_closed_trades"]],
  ["Gate paper → live", ["gate_min_days", "gate_min_trades", "gate_min_pnl_usd", "gate_max_drawdown_pct", "gate_min_profit_factor"]],
];

function Field({ k, value, def, onChange }) {
  const changed = JSON.stringify(value) !== JSON.stringify(def);
  if (typeof def === "boolean") {
    return (
      <label className="flex items-center justify-between gap-2 py-1.5 text-sm">
        <span className={changed ? "text-warn" : "text-ink-2"}>{k}</span>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(k, e.target.checked)} />
      </label>
    );
  }
  return (
    <label className="grid grid-cols-[1fr_140px] items-center gap-2 py-1 text-sm">
      <span className={changed ? "text-warn" : "text-ink-2"} title={`default: ${def}`}>
        {k}
      </span>
      <input
        className="inp"
        value={value ?? ""}
        onChange={(e) => onChange(k, typeof def === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)}
      />
    </label>
  );
}

function Gate() {
  const g = usePoll("/live/gate", 60000);
  if (!g.data) return null;
  const confirm = async (v) => {
    try {
      await api("/live/confirm", { method: "POST", body: { confirm: v } });
      g.reload();
    } catch (e) {
      alert(e.message);
    }
  };
  return (
    <Section title="Modalità live (disabilitata)">
      <ul className="text-sm space-y-1 mb-3">
        {Object.entries(g.data.checks).map(([k, ok]) => (
          <li key={k} className="flex items-center gap-2">
            <span className={ok ? "text-good" : "text-bad"}>{ok ? "✓" : "✗"}</span>
            <span className="text-ink-2">{k}</span>
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className={g.data.live_trading_enabled_env ? "text-good" : "text-bad"}>{g.data.live_trading_enabled_env ? "✓" : "✗"}</span>
          <span className="text-ink-2">LIVE_TRADING_ENABLED nel file .env</span>
        </li>
      </ul>
      <div className="text-xs text-ink-3 mb-2">
        Giorni di paper trading: {g.data.days}. Anche superato il gate, il LiveEngine è ancora uno stub: nessun ordine reale viene inviato.
      </div>
      <button className="btn-ghost" disabled={!g.data.passed} onClick={() => confirm(!g.data.manual_confirmed)}>
        {g.data.manual_confirmed ? "Revoca conferma manuale" : "Conferma passaggio a live"}
      </button>
    </Section>
  );
}

export default function Settings() {
  const [s, setS] = useState(null);
  const [draft, setDraft] = useState({});
  const [msg, setMsg] = useState("");
  const load = () => api("/settings").then((d) => { setS(d); setDraft({}); });
  useEffect(() => { load(); }, []);
  if (!s) return <Empty>Caricamento…</Empty>;
  const vals = { ...s.values, ...draft };
  const onChange = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  const save = async () => {
    try {
      const d = await api("/settings", { method: "PUT", body: draft });
      setS(d);
      setDraft({});
      setMsg("Salvato.");
    } catch (e) {
      setMsg(`Errore: ${e.message}`);
    }
  };
  const reset = async () => {
    if (!window.confirm("Ripristinare tutti i valori di default?")) return;
    setS(await api("/settings/reset", { method: "POST" }));
    setDraft({});
  };
  return (
    <div className="space-y-4">
      <div className="card flex items-center gap-3 flex-wrap text-sm">
        <span className="text-ink-2">
          Queste impostazioni le modifichi solo tu: l'agente non ha strumenti per cambiarle. In giallo i valori diversi dal default.
        </span>
        <span className="ml-auto text-ink-3">{msg}</span>
        <button className="btn-ghost" onClick={reset}>Default</button>
        <button className="btn bg-series-1 text-white" disabled={!Object.keys(draft).length} onClick={save}>
          Salva ({Object.keys(draft).length})
        </button>
      </div>
      <div className="grid lg:grid-cols-2 gap-4">
        {GROUPS.map(([title, keys]) => (
          <Section key={title} title={title}>
            {keys.filter((k) => k in s.defaults).map((k) => (
              <Field key={k} k={k} value={vals[k]} def={s.defaults[k]} onChange={onChange} />
            ))}
          </Section>
        ))}
        <Gate />
      </div>
    </div>
  );
}
