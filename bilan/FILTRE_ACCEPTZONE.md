# Filtre régime macro sur AcceptZone (socle DCA)

Date : 2026-09-18. Application post-hoc de `scripts/apply_regime_filter.py`
(biais `bilan/REGIME_MACRO.md §5`, protocole §6 : config = dernier event
**strictement avant** le jour d'entrée, anti-lookahead) sur les socles
`backtest_out/acceptzone_dca/long+short/cycles.csv` (NQ 2022-12-18 → 2025-12-12,
1M fixe, hors frais, sans compounding).

Fichiers d'entrée : copies + colonne `side` (socle intact) dans
`backtest_out/acceptzone_regime/{long,short}/cycles.csv` →
`cycles_regime.csv` (colonnes d'origine + `regime_config`, `regime_biais`,
`regime_decision`). P&L utilisé : `net_dollar`. Parsing : 0 skip partout
(`sans_config: 0` — couverture `stance_index_fwd.csv` 2022-02 → 2026-02 OK).

## Long — cycles.csv -> cycles_regime.csv

- AVANT : N=197 WR=83% PF=1.62 exp=+$3428 tot=+$675240
- APRES (gardés) : N=197 WR=83% PF=1.62 exp=+$3428 tot=+$675240
- EXCLUS : N=0 — gardes 197/197 (100%)
- Configs des fills : R/flat 117, N/flat 39, R/down 21, R/up 20 → biais LONG 138,
  NEUTRE 59, **aucun fill en jour A/up ou A/flat**.

**Lecture : filtre transparent pour les longs.** Aucun long ne s'est déclenché
en config SHORT-biais sur toute la fenêtre : rien à exclure, rien à gagner.

## Short — cycles.csv -> cycles_regime.csv

- AVANT : N=146 WR=58% PF=0.54 exp=−$4964 tot=−$724724
- APRES (gardés) : N=39 WR=62% PF=0.54 exp=−$4958 tot=−$193352
- EXCLUS : N=107 WR=57% PF=0.54 exp=−$4966 tot=−$531372
- gardes 39/146 (27%). Configs : R/flat 91, R/up 26, R/down 16, N/flat 13 →
  107 exclus (biais LONG), 39 gardés (NEUTRE : R/up 26 + N/flat 13).

**Lecture : le filtre coupe le volume, pas l'edge.** Les gardés ont la même
exp/cycle que les exclus (−$4958 vs −$4966) et le même PF (0.54) : même sur
jours NEUTRE, le short AcceptZone perd autant par trade. Le problème du short
n'est pas le régime macro — même verdict que monthly-open (−$470k),
régime-VA (−$168k) et VWAP+mfilter (−$45k) : aucune variante short ne tient,
seul le VWAP seul est plat (+$54k, t 0.40, non démontré).

## Conclusion

- Long socle (+$675k, t 2.69) : inchangé et confirmé, insensible au filtre régime.
- Short : 5 filtres testés (socle, monthly-open, régime-VA, VWAP, VWAP+mfilter,
  régime-macro), aucun edge. Piste short AcceptZone à abandonner en l'état ;
  seul le long qualifie comme système.
- Gardes-fous : t surestimés (cycles chevauchants), urgences −40k $ non
  garanties, concurrence illimitée, hors frais/slippage.
