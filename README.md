# AcceptZone — NQ futures : lecture du marché par zones d'acceptation

Systèmes long-only NQ (Nasdaq futures) : on détecte une **balance 2 jours**
(POC2 dans la value du jour 1), on y ancre une **Value Area composite 70 %**,
et on trade l'**acceptation** du 3e jour au-delà — ou son **échec** (flip).
Moteur DCA : entrée limite au niveau, renforts ±1×ATR (cap 3), TP moyenne
±1×ATR, urgence −40 k$, expiry 10 j, sizing 1 %/ATR. Capital 1M fixe,
sans compounding, hors frais/slippage. NQ 1-min 2022-12 → 2025-12.

## Résultats en 30 secondes (pool, tous les ans positifs)

| Système | Cycles | WR | Net | t | PF |
|---|---|---|---|---|---|
| **S1 long socle** (zones rebid) | 197 | 83.2 % | **+$675 240** | 2.69 | 1.62 |
| **S2 reverse-long** (ex-zones vendeuses flippées : POC revenu dedans) | 94 | 88.3 % | **+$401 675** | 2.74 | 2.08 |

Variantes : TP 2× documentée (non adoptée, défaut 1.0× figé). Short abandonné
(7 variantes + fade : aucune ne qualifie — voir `strategy/acceptzone_strategy.md` §3).

## Détection des niveaux

Triplets J1/J2/J3 de jours calendaires (≥ 800 barres 1-min) : balance
`VAL1 ≤ POC2 ≤ VAH1`, composite = barres J1+J2 → VA 70 % recalculée,
acceptation `POC3 > POC1,POC2 + VAHc+2t` → **rebid** (support/long), miroir
`< VALc−2t` → **reoffer** (résistance/short). Flip : premier jour F (≤ J3+10j)
où le POC revient dans `[VALc, VAHc]` → la zone change de sens (fake short
50.0 %, fake long 34.5 %). 145 zones (83 bull / 62 bear), 61 flips.

## Indicateur NinjaTrader 8

`nt8/AcceptZone.cs` (classe `AcceptZone`) : affiche les zones sur chart H1,
template ETH — rectangle VAL→VAH + POC + label, extension jusqu'au dernier
prix, aucun ordre, pas de repeinture. Déploiement : copier `nt8/AcceptZone.cs`
(+ `nt8/SwingCore/`) vers `Documents\NinjaTrader 8\bin\Custom\Indicators\`,
compiler (F5), charger ~10 jours minimum. Écart documenté vs Python : rows
4 ticks contre tick-level (quelques ticks). Spec : `strategy/acceptzone-indicator.md`.

## Rebuild Python

```bash
python -m venv venv && venv\Scripts\activate
# Aucune dependance : stdlib uniquement (pandas optionnel, non requis).
# Dépendance externe : python/mgi_contact (data_loader, session_clock),
# repo séparé à venir — copier le dossier au même niveau que python/
python -m python.mgi_initialzone.dca_atr --detector accept --side long --out-dir backtest_out/essai
```

Smoke (sample 10 jours fourni, warmup partiel) :
`--start 2025-01-06 --end 2025-01-17 --data-dir sample`.
Données réelles : exports NT8 1-min ETH dans `donnees/market/` (voir
`sample/LISEZMOI.md`, jamais committés : `.gitignore`).

## Entrer dans le projet

- Référence systèmes : [`strategy/acceptzone_strategy.md`](strategy/acceptzone_strategy.md)
  (S1/S2, variantes écartées, garde-fous, matrice config→dossier).
- Moteur DCA : [`strategy/dca_engine.md`](strategy/dca_engine.md).
- Études : [`bilan/REVERSE_ACCEPT.md`](bilan/REVERSE_ACCEPT.md) (flips, retours,
  fade), [`bilan/FILTRE_ACCEPTZONE.md`](bilan/FILTRE_ACCEPTZONE.md) (régime macro),
  [`bilan/WEEKLY_CONFLUENCE.md`](bilan/WEEKLY_CONFLUENCE.md) (rejections weekly).

## Limites (lire avant usage)

t surestimés (cycles chevauchants) · urgences = déclencheurs, pas stops garantis ·
concurrence illimitée (nets = sommes, pas equity) · DST non modélisé ·
2023-2025 haussiers (biais d'époque) · portefeuille S1+S2 jamais testé joint.

## Licence

MIT — voir [LICENSE](LICENSE).
