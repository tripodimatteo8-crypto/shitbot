# SolBot

Agente di trading autonomo su memecoin Solana basato su Claude. Oggi opera **solo in paper trading**: soldi finti, prezzi e quote reali. Impara da un diario di lezioni (`lezioni.md`) che rilegge a ogni decisione e che riscrive periodicamente in base a esiti misurati dal codice.

> ⚠️ Il paper trading **sovrastima** i risultati reali: sniper, MEV, latenza, quote che cambiano tra la decisione e il fill, rug improvvisi. SolBot simula i costi in modo volutamente pessimista, ma un risultato positivo in paper non garantisce nulla in live.

## Piano (10 righe)
1. Fonti dati dietro un'interfaccia `DataProvider`: DexScreener (universo/prezzi), RugCheck (sicurezza), Jupiter (quote reali per simulare swap). GMGN: API solo su richiesta, quindi non usata ora.
2. Collector ogni 3 min: token nuovi/trending/boost Solana + snapshot prezzo/liquidità/volume nel DB SQLite.
3. Filtri hard in codice: mint/freeze authority, liquidità minima, top-10, insider, età, rug → Claude vede solo chi passa.
4. Agente Claude (tool use): get_token_data, get_security_report, get_portfolio, paper_buy, paper_sell, skip_token; motivo + confidence salvati.
5. Paper engine prudente: quote Jupiter reali + buffer MEV, fee, priority fee, ritardo di esecuzione simulato.
6. Risk manager fuori dall'agente: size max, posizioni max, SL/TP/tempo max eseguiti dal codice, perdita giornaliera, kill switch.
7. Valutatore oggettivo: esito a 1h/6h/24h di OGNI candidato (anche scartati/saltati) + win rate, PnL, DD, profit factor, expectancy.
8. Riflessione giornaliera e ogni N trade: Claude riscrive `lezioni.md` (ipotesi con n. campioni), versioni salvate nel DB.
9. FastAPI + dashboard React/Vite/Tailwind/Recharts; un comando di avvio; servizio launchd per il Mac mini.
10. LiveEngine predisposto ma disabilitato dietro un gate di performance + conferma manuale.

## Avvio rapido (Mac mini)

Requisiti: Python ≥ 3.12 e Node ≥ 18 (`brew install python@3.12 node`).

```bash
git clone <repo> solbot && cd solbot
cp .env.example .env        # poi inserisci ANTHROPIC_API_KEY
./scripts/start.sh          # crea .venv, compila la dashboard, avvia il bot
```

Dashboard: <http://127.0.0.1:8787>. Report da terminale: `.venv/bin/python -m solbot report`.

Senza `ANTHROPIC_API_KEY` il bot **gira lo stesso** con una strategia `baseline` a regole (gratis): raccoglie dati, valuta gli esiti e fa paper trade. Appena aggiungi la chiave e riavvii, decide Claude (`DECIDER=auto`). Le due strategie restano distinguibili nel DB (`decider`), utile per il confronto in Fase 3.

### Servizio 24/7 con riavvio automatico
```bash
./scripts/install_launchd.sh
```
Installa `~/Library/LaunchAgents/com.solbot.agent.plist` (`RunAtLoad` + `KeepAlive`): il bot riparte dopo crash, logout/login e riavvio del Mac. Stop: `launchctl bootout gui/$(id -u)/com.solbot.agent`.

### Impedire lo sleep del Mac
`start.sh` avvia il bot sotto `caffeinate -is` (niente sleep di sistema finché il bot gira). Per sicurezza imposta anche:
```bash
sudo pmset -a sleep 0 disksleep 0 displaysleep 10
sudo pmset -a autorestart 1     # riaccende dopo un'interruzione di corrente
sudo pmset -a womp 1            # wake on network
```
Inoltre: Impostazioni di Sistema → Utenti e gruppi → login automatico per l'utente che esegue il bot (i LaunchAgent partono al login).

### Kill switch
- Pulsante **KILL SWITCH** in dashboard, oppure `touch KILL` nella cartella del repo.
- Blocca ogni nuova apertura. Stop loss / take profit / trailing restano attivi (proteggono le posizioni aperte). Per liquidare tutto: `POST /api/close_all`.

## Architettura

```
solbot/
  providers/      DataProvider astratto + DexScreener, RugCheck, Jupiter (composite)
  collector.py    scoperta token, snapshot, filtri, creazione candidati
  filters.py      filtri hard (codice, non LLM)
  agent.py        agente Claude con tool use (+ baseline a regole)
  execution/      ExecutionEngine: PaperEngine (attivo), LiveEngine (stub disabilitato)
  portfolio.py    apertura/chiusura posizioni, equity a valore di liquidazione
  risk.py         protezioni hard-coded fuori dall'agente
  evaluator.py    esiti 1h/6h/24h di ogni candidato, metriche, gate live
  reflection.py   riscrittura di lezioni.md + versioni nel DB
  costs.py        token/costi Claude e budget giornaliero
  scheduler.py    cicli APScheduler
  api.py          FastAPI (+ serve web/dist)
web/              dashboard React + Vite + Tailwind + Recharts
```

Cicli (modificabili da dashboard): collector 180s, agente 180s, monitor SL/TP 30s, valutatore 600s, equity 300s, riflessione giornaliera alle 03:17 (ora locale) e ogni N trade chiusi (default 15).

### Flusso di una decisione
1. Il **collector** prende da DexScreener i token Solana appena profilati, in boost/trending, community takeover e le coppie trovate cercando pumpswap/pump.fun/raydium/meteora. Salva uno snapshot per ogni token seguito (per 26 ore).
2. **Prefiltro di mercato** (gratis): prezzo, liquidità, mcap, età, volume 1h, numero di transazioni, presenza di vendite.
3. **Filtro di sicurezza** (RugCheck): mint/freeze authority, transfer fee, top-10 e singolo holder (escludendo pool AMM e locker), insider, numero holder, score, rischi critici, flag rugged.
4. **Test di vendita** (Jupiter): una quote token→SOL da 20$ deve esistere e restituire almeno il 70%, altrimenti è un probabile honeypot.
5. Solo i candidati che passano arrivano all'**agente**, che deve chiamare `paper_buy` o `skip_token` per ciascuno, con `reason` e `confidence`. Tutto finisce nel DB.
6. Il **risk manager** ridimensiona o blocca l'ordine; il **PaperEngine** attende il ritardo simulato, chiede una quote reale a Jupiter e applica i costi.
7. Il **monitor** (ogni 30s) aggiorna i prezzi ed esegue stop loss, take profit, trailing stop, tempo massimo e uscita per liquidità crollata.
8. Il **valutatore** calcola l'esito a 1h/6h/24h di ogni candidato, compresi quelli scartati, saltati o scaduti. È la base oggettiva della riflessione.

### Costi simulati (prudenti)
| Voce | Default |
|---|---|
| Prezzo di esecuzione | quote reale Jupiter presa *dopo* il ritardo (include impatto e fee AMM); se manca, modello constant-product con slippage minimo 1,5% |
| Buffer MEV/sniper | 1% per lato |
| Fee aggregatore/piattaforma | 0,25% per lato |
| Priority fee + tip | 0,0015 SOL per transazione |
| Ritardo di esecuzione | 3 s |
| Valutazione delle posizioni aperte | valore di liquidazione (prezzo − slippage stimato − MEV − fee) |

Con 30$ su token da 30-100k$ di liquidità un round-trip costa tipicamente il 4-10%.

### Protezioni (non modificabili dall'agente)
Max 5% dell'equity per trade, max 6 posizioni, stop loss −25%, take profit +60%, trailing stop 25% dal massimo (attivo oltre +30%), holding massimo 24h, stop giornaliero a −8% dall'equity di inizio giornata, kill switch. L'agente non ha alcun tool per cambiarli: li modifichi solo tu dalla dashboard (Impostazioni) o dal `.env` (prefisso `SB_`).

### Controllo dei costi di Claude
- Claude viene chiamato solo se ci sono candidati che hanno superato i filtri (max 6 per ciclo).
- System prompt + lezioni in prompt cache.
- Limiti giornalieri configurabili: chiamate (400), token (3M), spesa (15$). Superati, i candidati scadono senza trade (ma il valutatore ne misura comunque l'esito).
- Modello di default `claude-opus-5-5` con `effort` medium; modificabili da dashboard (es. `claude-sonnet-5-5` per spendere meno). È abilitato il fallback server-side in caso di refusal (`claude_fallbacks`).

## GMGN: verifica dell'API (3 novembre 2026)
- GMGN **non ha un'API dati pubblica e aperta**. La documentazione ufficiale ([docs.gmgn.ai — integrazione API di trading Solana](https://docs.gmgn.ai/cn/he-zuo-api-ji-cheng-gmgn-solana-jiao-yi-api)) descrive un'API di **trading/routing** concessa **su richiesta**: l'approvazione dipende dal volume fatto su GMGN, la revisione richiede fino a 24h, la chiave arriva via email e si passa in un header (`x-route-key`), con un limite di 1 chiamata ogni 5 secondi. Esiste anche un CLI più recente che usa una `GMGN_API_KEY` generata da gmgn.ai/ai. Prima di usarli, verifica lo stato attuale su docs.gmgn.ai: il processo di accesso potrebbe essere cambiato.
- Gli endpoint interni del sito (`gmgn.ai/defi/quotation/...`) sono dietro Cloudflare: da qui rispondono **403** alla prima richiesta. Non vengono usati. Niente scraping e niente aggiramento delle protezioni anti-bot.
- Per questo SolBot ricostruisce lo stesso universo (nuove coppie, migrazioni da Pump.fun verso PumpSwap, trending) con **DexScreener + RugCheck + Jupiter**. Se ottieni una chiave GMGN basta scrivere un `GmgnProvider(DataProvider)` in `solbot/providers/` e restituirlo in `get_provider()`.

Dati ottenuti oggi: market cap, liquidità, volumi (5m/1h/6h/24h), transazioni buy/sell, variazioni di prezzo, età della coppia, holder totali, concentrazione top-10, % insider (proxy bundle/sniper da RugCheck), authority, rischi. **Non disponibili gratis:** % sniper e bundle precisa e wallet smart money (campi già presenti in `SecurityData`, da riempire in Fase 3 con GMGN/Birdeye/Helius). I token ancora sulla bonding curve Pump.fun non hanno liquidità su DexScreener e vengono scartati (prudenza).

## Modalità live: GMGN o Jupiter?
| | Jupiter (diretto) | GMGN |
|---|---|---|
| Accesso | API pubblica (lite gratis, pro con chiave) | su richiesta, legata al volume, 1 req/5s |
| Routing | aggregatore su tutti i DEX, incluse pumpswap e bonding curve | proprio router, ottimizzato per memecoin |
| Protezione MEV | da gestire noi (Jito bundle / priority fee) | anti-MEV dichiarato da GMGN (da verificare) |
| Fee | nessuna fee di piattaforma con l'API base | fee di piattaforma da verificare nei termini dell'API |
| Firma | locale con la nostra chiave | locale con la nostra chiave |
| Dipendenza | open, documentata, stabile | servizio chiuso, termini mutevoli |

**Raccomandazione:** Jupiter Swap API come esecuzione primaria. È la stessa fonte delle quote usate in paper, quindi paper e live restano coerenti; è pubblica e senza fee aggiuntive. Si aggiungono priority fee dinamica e invio via Jito per ridurre il MEV. GMGN resta un'alternativa da valutare se l'anti-MEV integrato si dimostra migliore nei confronti reali.

Stato attuale: `LiveEngine` è uno **stub** che solleva `NotImplementedError`. Diventa selezionabile solo se: `LIVE_TRADING_ENABLED=true` **e** gate superato (≥21 giorni, ≥150 trade, PnL netto > 0, drawdown ≤ 20%, profit factor ≥ 1,3, tutto configurabile) **e** conferma manuale dalla dashboard. La chiave privata del wallet dedicato si leggerà solo dalla variabile d'ambiente `SOLBOT_WALLET_PRIVATE_KEY`, solo dentro il LiveEngine: mai loggata, mai salvata nel DB, mai accessibile all'agente.

## Comandi utili
```bash
.venv/bin/python -m solbot report    # stato da terminale
.venv/bin/python -m solbot once      # un giro singolo (debug)
.venv/bin/python -m solbot reflect   # forza la riscrittura di lezioni.md
.venv/bin/python -m pytest -q        # test
tail -f logs/solbot.log
cd web && npm run dev                # dashboard in sviluppo su :5173 (proxy verso :8787)
```
La dashboard è in ascolto solo su `127.0.0.1` e non ha autenticazione: non esporla su Internet.

## Fasi
- **Fase 1 (fatta):** DB, collector, filtri, paper portfolio, agente con tool use, valutatore, protezioni, log su console e file, avvio, test.
- **Fase 2 (fatta in versione base):** dashboard completa (panoramica, posizioni/storico con i motivi, feed candidati, "Cosa ha imparato" con diff tra versioni e metriche prima/dopo, impostazioni, costi), riflessione giornaliera automatica.
- **Fase 3 (da fare):** confronto tra versioni di strategia (claude vs baseline, versioni delle lezioni), feature smart money/bundle da GMGN/Birdeye/Helius, ottimizzazione costi (modello più piccolo per lo screening, batch).
