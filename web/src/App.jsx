import React, { useEffect, useState } from "react";
import { api, usePoll } from "./api";
import Overview from "./pages/Overview.jsx";
import Trades from "./pages/Trades.jsx";
import Candidates from "./pages/Candidates.jsx";
import Lessons from "./pages/Lessons.jsx";
import Settings from "./pages/Settings.jsx";
import Costs from "./pages/Costs.jsx";

const PAGES = [
  ["overview", "Panoramica", Overview],
  ["trades", "Posizioni e trade", Trades],
  ["candidates", "Feed candidati", Candidates],
  ["lessons", "Cosa ha imparato", Lessons],
  ["costs", "Costi", Costs],
  ["settings", "Impostazioni", Settings],
];

function useHash() {
  const [h, setH] = useState(window.location.hash.slice(1) || "overview");
  useEffect(() => {
    const f = () => setH(window.location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h;
}

function KillSwitch({ ov, reload }) {
  const active = ov?.kill_switch;
  const toggle = async () => {
    const msg = active
      ? "Disattivare il kill switch? Il bot potrà riaprire posizioni."
      : "Attivare il KILL SWITCH? Il bot smette di aprire posizioni (SL/TP restano attivi).";
    if (!window.confirm(msg)) return;
    await api("/kill", { method: "POST", body: { active: !active } });
    reload();
  };
  return (
    <button onClick={toggle} className={active ? "btn bg-good/80 hover:bg-good text-white" : "btn-danger"}>
      {active ? "Riattiva bot" : "KILL SWITCH"}
    </button>
  );
}

export default function App() {
  const page = useHash();
  const ov = usePoll("/overview", 10000);
  const Page = (PAGES.find((p) => p[0] === page) || PAGES[0])[2];
  const status = ov.data?.halt ? "fermo" : ov.error ? "offline" : "attivo";
  const dot = status === "attivo" ? "bg-good" : status === "fermo" ? "bg-warn" : "bg-bad";
  return (
    <div className="min-h-screen">
      <header className="border-b border-surface-3 bg-surface-1/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-series-1 to-series-3" />
            <span className="font-semibold tracking-tight">SolBot</span>
            <span className="pill bg-surface-3 text-ink-2">PAPER</span>
          </div>
          <div className="flex items-center gap-2 text-sm text-ink-2">
            <span className={`w-2 h-2 rounded-full ${dot}`} />
            <span>
              {status}
              {ov.data?.halt ? ` — ${ov.data.halt}` : ""}
            </span>
            {ov.data && (
              <span className="text-ink-3">
                · decide: <b className="text-ink-2">{ov.data.decider}</b>
                {ov.data.decider === "claude" ? ` (${ov.data.model})` : ""}
              </span>
            )}
          </div>
          <div className="ml-auto">{ov.data && <KillSwitch ov={ov.data} reload={ov.reload} />}</div>
        </div>
        <nav className="max-w-7xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {PAGES.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 ${
                page === id ? "border-series-1 text-ink-1" : "border-transparent text-ink-3 hover:text-ink-2"
              }`}
            >
              {label}
            </a>
          ))}
        </nav>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-5">
        {ov.error && !ov.data ? (
          <div className="card text-bad">API non raggiungibile: {ov.error}</div>
        ) : (
          <Page ov={ov.data} reloadOv={ov.reload} />
        )}
      </main>
    </div>
  );
}
