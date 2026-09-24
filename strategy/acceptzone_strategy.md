# AcceptZone — Stratégies figées (NQ, 1-min 2022-12 → 2025-12)

Référence des systèmes validés par backtest Python (`python/mgi_initialzone/`
avec `--detector accept` / `reverse`). Les zones AcceptZone remplacent les InitialZone,
le moteur DCA est inchangé (`strategy/dca_engine.md`).
Données : exports NT8 1-min NQ, timestamps **UTC** (halt 21h UTC, RTH 13h30-20h UTC).
Nettoyage : 65 samedis + 120 dimanches-fantômes + 0 barre corrompue écartés.
Capital 1M fixe, **sans compounding, hors frais/slippage**.

> **Doctrine figée le 2026-09-18** : 2 systèmes long-only NQ — S1 long socle,
> S2 reverse-long (fake short). Short abandonné (7 variantes + fade-DCA +
> fade-close : aucune ne qualifie). Fade pur A = piste documentée (§3), pas un
> système. **TP 2× = variante documentée, défaut figé 1.0×** (S1/S2). Plus de
> tests short sauf signal nouveau ; code non gelé (chantier h7
> coexistant sur `dca_atr.py`).

## 1. Socle commun DCA

- **Détection** (`python/mgi_initialzone/detect_accept.py`, méthode
  `scripts/backtest_swing_s2.py:53-75`) : triplets J1/J2/J3 de jours calendaires
  consécutifs (≥ 800 barres 1-min) ; profils 70 % tick-level volume uniforme ;
  balance `VAL1 ≤ POC2 ≤ VAH1` ; composite = barres J1+J2 fusionnées → VA 70 %
  recalculée ; acceptation `POC3 > POC1,POC2 + VAHc+2t` → **rebid** (bullish),
  miroir `< VALc−2t` → **reoffer** (bearish), `creation = J3`. `atr_ref` =
  ATR Wilder(20) DCA évalué avant J3 (warmup index ≥ 23) — sert au TP, aux
   renforts ET au sizing. 145 zones : 83 bull / 62 bear.
- **Variante reverse** (`detect_reverse`, `--detector reverse`) : même socle §2 ;
  premier jour F (J3 < F ≤ J3+10j calendaires) où le POC daily revient
  strictement dans [VALc, VAHc] (bornes incluses, sans buffer) → flip de sens
  symétrique (reoffer→acheteuse, rebid→vendeuse), un seul flip par zone.
  Signal : composite inchangé, `trend_date = F`, `init_date = J3`,
  `atr_ref` Wilder avant F. 61 flips / 148 zones (fake short 32/64 = 50 %).
- **Entrée** : limite au niveau brut (fill à L, open si gap) ; 1er rebond par
  (zone, niveau) ; re-trigger jours calendaires différents uniquement.
- **Gestion** : unité `floor(10 000 $ / (ATR × 20 $/pt))` figée par cycle
  (1 %/ATR) ; renforts même qty à chaque ±1×ATR depuis le dernier fill,
  **cap 3 adds** (4 unités max) ; TP = **moyenne + 1×ATR** (touche 1-min,
  prioritaire sur tout dans la barre) ; **urgence −$40k** de latent au close
  1-min (reprise J+1).
- **Sorties** : `cycles.csv` (1 ligne/cycle : `regime`, `min_latent_d`,
  `mfe_t/mae_t`), `legs.csv` (fills + `drift15_t`), `stats.md`.

## 2. Stratégies retenues

### S1 — Long socle (`backtest_out/acceptzone_dca/long/`)

- TF Daily, expiry zone/trade **10 j**, session all, entry immediate, sans filtre.
- 197 cycles | WR 83.2 % | **+$675 240** | t 2.69 | PF 1.62 | 160 TP / 23 Urg / 12 Exp / 2 EOD | adds 0/1/2/3 = 113/42/38/4.
- MAE~ 1201 ticks | MFE~ 800 ticks | drift +15min −11 ticks.
- Robustesse inter-annuelle (année d'entrée) : 2023 N=49 +$142k t 1.19 PF 1.51 |
  2024 N=52 +$135k t 1.11 PF 1.51 | 2025 N=96 +$398k t 2.14 PF 1.73 — positif les
  3 ans (2022 sans trade : warmup ATR + formation des zones).
- Insensible au filtre régime macro : 197/197 gardés, aucun fill en jour A/up
  ou A/flat (`bilan/FILTRE_ACCEPTZONE.md`).
- Variante TP (défaut figé **1.0×**, TP seul, rung/sizing inchangés) : 1.5× → 150 cycles,
  +$699k, t 2.58, PF 1.65 (≈ socle, sans gain) ; **2.0× → 134 cycles, +$1 153k,
  t 3.96, PF 2.24**, positif les 3 ans (2023 +$238k t 1.83 / 2024 +$212k t 1.49 /
  2025 +$703k t 3.22) — **classée variante, pas adoptée** : t gonflé par
  chevauchements accentués, 61 % du net en 2025, MAE~ 1456 ticks (+21 %),
  expirations 39 vs 12 (cycles ouverts bloquant les re-triggers).
  Dossiers `backtest_out/acceptzone_dca_tp15|tp20/long/`.

### S2 — Reverse-long / « long fake short » (`backtest_out/reverse_dca/long/`)

- Zones ex-reoffer flippées (POC revenu dedans), `--detector reverse --side long`,
  TF Daily, expiry 10 j depuis F, session all, entry immediate, sans filtre.
- 32 zones → 94 cycles | WR 88.3 % | **+$401 675** | t 2.74 | PF 2.08 | 83 TP / 9 Urg / 2 Exp / 0 EOD | adds 0/1/2/3 = 68/16/10/0.
- MAE~ 807 ticks | MFE~ 952 ticks | drift +15min +32 ticks.
- Par année (entrée) : 2023 N=33 +$84k t 0.76 PF 1.40 | 2024 N=34 +$114k
  t 1.19 PF 1.71 | 2025 N=27 +$204k, 27/27 TP, 0 urgence (perfection sur n=27 :
  outlier probable, année haussière) — positif les 3 ans.
- Variante TP (défaut figé **1.0×**) : 1.5× → 70 cycles, +$389k, t 2.46, PF 2.05 (≈ socle, sans gain) ;
  **2.0× → 66 cycles, +$625k, t 3.61, PF 2.88**, positif les 3 ans (2023 +$222k
  t 1.66 / 2024 +$208k t 1.86 / 2025 +$195k) — **classée variante, mêmes
  réserves que S1** (chevauchements, concentration 2025).
  Dossiers `backtest_out/reverse_dca_tp15|tp20/long/`.
- Détail : `bilan/REVERSE_ACCEPT.md §2+§5`.

### Short — aucune retenue

Toutes les variantes short sont négatives ou plates (voir §3) : socle, filtres
(monthly-open, régime-VA, VWAP, VWAP+mfilter, régime-macro), reverse-short,
fade-DCA, fade-close moyenné. Piste short abandonnée en l'état ; seuls
**S1 + S2 (long-only)** qualifient comme systèmes.

## 3. Variantes écartées (testées, ne pas retenir en l'état)

| Variante | Résultat pool | Par année (entrée) | Raison de l'écart |
|---|---|---|---|
| Long + âge ≥ 3j (`acceptzone_dca_sweep/age3_long/`, 53 599 refus âge) | 166 cycles, WR 80.7 %, +$316k, t 1.26, PF 1.28 | 2023 −$6k / 2024 +$84k / 2025 +$238k | Divise le net par 2 sans gain d'efficience ; 2023 négatif (inverse d'InitialZone où ce filtre aidait) |
| Long + VWAP monthly (`acceptzone_dca_vwap/long/`, 88 577 refus) | 131 cycles, WR 81.7 %, +$313k, t 1.46, PF 1.39 | 2023 +$81k / 2024 +$166k / 2025 +$66k (t 0.38) | Coupe du bon comme du mauvais ; 2025 plat |
| Short socle (`acceptzone_dca/short/`) | 146 cycles, WR 58.2 %, −$725k, t −2.96, PF 0.54 | 2023 −$102k / 2024 −$153k / 2025 −$469k (t −3.18) | Toxique tous les ans, pire en 2025 |
| Short + monthly-open (`acceptzone_dca_mfilter/short_mfilter/`) | 71 cycles, WR 54.9 %, −$470k, t −2.76, PF 0.44 | 2023 −$169k / 2024 −$9k / 2025 −$292k | Divise l'échantillon sans sauver l'edge, t toujours significatif négatif |
| Short + régime monthly VA (`acceptzone_dca_regime/short_regime/`) | 23 cycles, WR 52.2 %, −$168k, t −1.67, PF 0.40 | 2024 +$54k (n=5) mais 2023 −$59k / 2025 −$164k | n trop faible, pas de robustesse (2024 = 5 trades) |
| Short + VWAP monthly (`acceptzone_dca_vwap/short/`, 313 717 refus) | 58 cycles, WR 70.7 %, +$54k, t 0.40, PF 1.14 | 2023 −$47k / 2024 +$146k (t 3.23, n=17) / 2025 −$45k | Seule variante short positive mais t 0.40, années contradictoires : edge non démontré, à confirmer pas à jeter |
| Short + VWAP + monthly-open (`acceptzone_dca_vwap_mfilter/short_vwap_mfilter/`) | 46 cycles, WR 65.2 %, −$45k, t −0.38, PF 0.87 | 2023 −$84k / 2024 +$95k / 2025 −$57k | Ajouter monthly-open au VWAP refait passer en négatif (coupe plus de gagnants que de perdants) |
| Short + régime macro post-hoc (`acceptzone_regime/short/`, `bilan/FILTRE_ACCEPTZONE.md`) | 39/146 gardés (27 %), WR 61.5 %, −$193k, PF 0.54 | 2023 −$136k / 2024 +$21k (n=3) / 2025 −$79k | Gardés et exclus : même exp/cycle (−$4958 vs −$4966) — le filtre coupe le volume, pas l'edge ; le problème du short n'est pas le régime macro |
| Short fade-DCA retours rebid (`fade_dca/short/`, `--detector fade`, `bilan/REVERSE_ACCEPT.md §7`) | 37 zones → 125 cycles, WR 66.4 %, −$291k, t −1.23, PF 0.75 | 2023 −$196k / 2024 −$123k / 2025 +$28k (t 0.22, plat) | Le DCA inverse le profil du fade pur A (T2 +1.17R PF 1.66) : touches précoces au lieu du close F, short du haut de zone, TP petits vs urgences — high-WR / negative-expectancy. Formule gagnante = entrée tardive + stop large + cible fixe, pas limite + moyennage |
| Short fade-close moyenné (`accept_fade_close/`, `bilan/REVERSE_ACCEPT.md §8`) | 37 signaux, TP avg : WR 70 %, −$49k, t −0.38, PF 0.84 (meilleur témoin fixe −1.0× : −$22k PF 0.93) | Tardif >3j positif (avg +$35k PF 1.45, f15 +$50k PF 1.56, n=15) / immédiat ≤3j négatif (−$84k, 2 urgences) | Moyenner ne bat pas le stop large : les adds se concentrent sur les retours immédiats qui tiennent (leçon InitialZone). Hiérarchie : fade pur A > fade-close moyenné > fade-DCA touch |
| Reverse-short / ex-rebid flippées (`reverse_dca/short/`, `bilan/REVERSE_ACCEPT.md §5`) | 29 zones → 93 cycles, WR 68.8 %, −$83k, t −0.42, PF 0.89 | 2023 −$46k / 2024 −$23k / 2025 −$13k (négatif les 3 ans) | Plat-négatif partout : trader le fake long ne fonctionne pas, miroir du S2 qui fonctionne |
| Fade pur A — short au close F, stop VAHc+2t, 1 unité (`accept_fade/`, `bilan/REVERSE_ACCEPT.md §6`) | **Piste (pas un système)** : T2 N=37 hit 24 %, +26pts (+1.17R) PF 1.66 ; T3 hit 22 %, +43pts (+1.76R) PF 2.06 (T1 PF 0.95 écarté) | ≤3j T2 +1.47R / >3j T3 +1.43R PF 2.47 | t jamais calculé (probablement < 1.5), pas d'annuel, risque $/trade non borné, tout in-sample, NQ seul : à promouvoir seulement après t + annuel + ES + coûts + distribution risque $ |

## 4. Garde-fous transverses (non négociables à la lecture)

1. **Échantillons faibles** (n=23 régime, n=39 macro-gardés) : t indicatifs, jamais seuls.
2. **t sur cycles chevauchants** : corrélés (mêmes zones/jours) → t surestimés.
   Ne comparer les t qu'entre variantes (même biais), jamais au standard académique.
   Rappel : t = avg / (std/√n) ; |t| > 2 ≈ significatif à 95 %.
3. **Hors frais/slippage**, sizing en contrats entiers (paliers), pas de compounding.
4. **Buckets UTC fixes** (RTH 14-20h, warmup 00-03h) : DST américain non modélisé
   (±1h de glissement été/hiver sur les frontières de session).
5. **Urgences non garanties** : −$40k est un seuil de déclenchement, pas un stop garanti.
6. **Concurrence non plafonnée** : les nets sont des sommes de cycles, pas une
   equity tradable. Aucune mise en production sans `--max-open-cycles` + marge.
7. **Parité Python ↔ NT8** : backtest en profil tick-level, indicateur
   `strategy/acceptzone-indicator.md` en rows 4 ticks par défaut (écart documenté
   de quelques ticks sur VAH/VAL/POC).
8. **Biais d'époque** : aucun fill long en config macro A/up-A/flat sur 2022-2025,
   années 2023-2025 toutes haussières NQ — la robustesse affichée vaut pour ce régime.
9. **Déterminisme vérifié** : re-runs byte-identiques (sha256), parité zones S2
   au tick sur 01/2025, 1 cycle avec renforts vérifié à la main (rungs/moyenne/TP/net).
10. **Portefeuille S1+S2 jamais testé** : populations disjointes (rebid vs
    ex-reoffer flippées) mais même sous-jacent/période → cycles concurrents
    possibles, net joint et drawdown joint inconnus. Somme des nets ≠ equity
    tradable (cf. §4.6).

## 5. Matrice de décision (config → dossier)

| Question | Config de référence | Dossier |
|---|---|---|
| Long socle (S1) | `--detector accept --side long` (défauts) | `backtest_out/acceptzone_dca/long/` |
| S1 + TP 1.5× / 2.0× | `--detector accept --side long --tp-mult 1.5|2.0` (TP seul) | `backtest_out/acceptzone_dca_tp15|tp20/long/` |
| Reverse-long (S2) | `--detector reverse --side long` (flip POC strict inside, trend=F, expiry 10j) | `backtest_out/reverse_dca/long/` |
| S2 + TP 1.5× / 2.0× | `--detector reverse --side long --tp-mult 1.5|2.0` (TP seul) | `backtest_out/reverse_dca_tp15|tp20/long/` |
| Short socle (écarté) | `--detector accept --side short` | `backtest_out/acceptzone_dca/short/` |
| Long + âge | `--side long --min-zone-age 3` | `backtest_out/acceptzone_dca_sweep/age3_long/` |
| Short + monthly-open | `--side short --monthly-filter short` | `backtest_out/acceptzone_dca_mfilter/short_mfilter/` |
| Short + régime monthly VA | `--side short --regime-filter both` | `backtest_out/acceptzone_dca_regime/short_regime/` |
| Long/Short + VWAP monthly | `--side both --vwap-filter both` (ancre monthly) | `backtest_out/acceptzone_dca_vwap/{long,short}/` |
| Short + VWAP + monthly-open | `--side short --vwap-filter short --monthly-filter short` | `backtest_out/acceptzone_dca_vwap_mfilter/short_vwap_mfilter/` |
| Short + régime macro post-hoc | `scripts/apply_regime_filter.py` sur cycles.csv + colonne `side` | `backtest_out/acceptzone_regime/{long,short}/` + `bilan/FILTRE_ACCEPTZONE.md` |
| Short fade retours rebid | `--detector fade --side short` (zones retournées trend=F, expiry 10j) | `backtest_out/fade_dca/short/` + `bilan/REVERSE_ACCEPT.md §7` |
| Short fade-close moyenné | `scripts/backtest_fade_close.py` (entrée close F, adds closes +1ATR cap2, −$40k, TP avg−ATR) | `donnees/backtest/accept_fade_close/` + `bilan/REVERSE_ACCEPT.md §8` |
| Short fade pur A (piste) | `scripts/backtest_fade_rebid.py` (montage A : short close F, stop VAHc+2t, cibles −0.5/−1/−1.5 ATR, 5 closes) | `donnees/backtest/accept_fade/` + `bilan/REVERSE_ACCEPT.md §6` |

Commande type : `venv\Scripts\python -m python.mgi_initialzone.dca_atr --detector accept --side long --out-dir backtest_out/...` (voir `--help`).
