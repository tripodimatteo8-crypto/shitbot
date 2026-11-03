# SolBot

Agente di trading autonomo (paper trading) su memecoin Solana, basato su Claude.

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
