# Lezioni di SolBot

_Versione iniziale, scritta a mano prima di qualsiasi dato. Tutte le regole sono IPOTESI con 0 campioni: vanno confermate o smentite dai dati._

## Ipotesi di partenza (0 campioni)
- [ipotesi, n=0] I costi di round-trip (impatto + MEV + fee) sono 3-8%: comprare solo se ci si aspetta un movimento molto superiore.
- [ipotesi, n=0] Token con rapporto acquisti/vendite 1h molto sbilanciato (>0.8) e prezzo già +100% in 1h tendono a ritracciare: rischio di comprare il top.
- [ipotesi, n=0] Volume 1h alto rispetto alla liquidità (>1x) indica interesse reale, ma anche possibile wash trading: guardare il numero di transazioni.
- [ipotesi, n=0] Concentrazione top-10 bassa e nessun insider rilevato riducono il rischio di dump, non lo eliminano.
- [ipotesi, n=0] Meglio poche posizioni piccole che molte: senza vantaggio misurato, la size deve restare minima.
