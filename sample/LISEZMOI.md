# Sample NQ 1-min (10 jours, 2025-01-06 → 2025-01-17)

Extrait d'export NinjaTrader 8 (barres Minute / Last, heure Chicago/CME).
13 233 barres, 0.7 Mo. Suffit pour un smoke test du moteur
(`--start 2025-01-06 --end 2025-01-17`) — pas pour valider une stratégie
(fenêtre trop courte : warmup ATR 23 jours non couvert).

## Format (une barre par ligne, `;` sans en-tête)

```
aaaammjj HHmmss;open;high;low;close;volume
20250106 000000;21269;21282.75;21253.5;21261.25;393
```

## Fournir ses propres données (requis pour un vrai backtest)

1. NinjaTrader 8 → export ASCII des barres 1-min (Last) NQ/ES, template ETH
   (24h, ~1380 barres/jour calendaire).
2. Nommer `NQ 03-25.Last.txt` (format `NQ MM-AA.Last.txt`), placer dans
   `donnees/market/` (rollover J-8 géré par `scripts/backtest_vp02.py`).
3. Lancer, ex. : `python -m python.mgi_initialzone.dca_atr --detector accept
   --side long --data-dir donnees/market --out-dir backtest_out/essai`.
