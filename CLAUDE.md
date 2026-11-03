# SolBot — note per Claude Code

Agente di paper trading su memecoin Solana (vedi README.md per l'architettura completa). Gira 24/7 sul Mac mini dell'utente.

## Stato e preferenze dell'utente
- Comunica in italiano, in modo semplice: l'utente non è uno sviluppatore. Esegui tu i comandi invece di chiederglieli.
- NON vuole caricare crediti API: le decisioni e la riflessione devono usare il suo abbonamento Claude Pro tramite la CLI `claude -p` (decider `claude_cli`, prioritario in `DECIDER=auto`). In futuro, col live, si può usare tutta la quota della sessione (`cli_calls_per_window` più alto).
- Trading di BREVE periodo (minuti, holding massimo 1h). Gli indicatori di rischio (rug/dump) si imparano entro 1h, mai su 24h.
- Vuole vedere tutto nella dashboard (http://127.0.0.1:8787, anche da telefono con HOST=0.0.0.0), non nel terminale.

## Comandi
- Avvio: `./scripts/start.sh` (crea .venv, compila web/, avvia). Se il bot è già attivo come servizio launchd, lo script lo dice ed esce.
- Servizio: `./scripts/install_launchd.sh`; riavvio `launchctl kickstart -k gui/$(id -u)/com.solbot.agent`; stop `launchctl bootout gui/$(id -u)/com.solbot.agent`.
- Stato: `.venv/bin/python -m solbot report`; log: `tail -f logs/solbot.log` (servizio: `logs/launchd.err.log`).
- Test: `.venv/bin/python -m pytest -q`.

## Da verificare sul Mac (primo avvio)
1. Una sola istanza attiva (servizio launchd OPPURE terminale, non entrambi): `curl -s 127.0.0.1:8787/api/overview`.
2. In dashboard in alto deve comparire `decide: claude_cli (abbonamento)`. Se no: `claude --version` e login con `claude` → `/login`. Con launchd la CLI potrebbe non essere nel PATH: impostare `CLAUDE_CLI_PATH` in `.env` con il percorso di `which claude`.
3. Dopo ~25 min deve esserci una riga `Ciclo claude_cli` nel log e decisioni con decider `claude_cli` in dashboard.
4. `.env` deve avere `HOST=0.0.0.0` se l'utente vuole la dashboard dal telefono (stessa Wi-Fi).
