# Confluence rejection-daily × biais dayswing sur zones weekly — résultats

Date : 2026-09-19. Question : les rejections daily sont-elles des signaux des
biais dayswing ? NQ 1-min 2022-12-18 → 2025-12-12. Outil :
`scripts/study_reject_confluence.py` (stdlib), données
`donnees/backtest/weekly_confluence/rejects.csv`.

## 1. Protocole (décisions verrouillées)

- Semaines ISO lun–dim sur dates fichier (drift assumé vs semaines NT8).
- Zones InitialZone-weekly : trend-week `|OC| > ATR Wilder(12)` avant (warmup
  index ≥ 15) + VA 70 % **rows 4 ticks** de la semaine précédente
  (`value_area_70`, parité `MGIHtfInitialZone` weekly). Variante (b) : VA
  semaine précédente **toutes semaines**, sans filtre trend (`--no-trend`).
- Biais (a) : par jour, `|C−O| > 0.5×ATR Wilder(20)` → bull/bear/sinon neutre.
- Rejection : poke (`high ≥ VAHw+2t` → fade short / `low ≤ VALw−2t` → fade
  long) **et** close back inside `[VALw, VAHw]`, ≤10j calendaires après fin
  de trend-week (variante b : après fin de semaine).
- Accord : sens du fade vs biais du même jour (neutre = colonne à part).
- Issue hold-5 : jamais reclôturé au-delà VALw−2t (long) / VAHw+2t (short)
  sur les 5 closes suivantes.
- Règle de lecture : écart hold|accord vs hold|désaccord ≥ 15 pp avec n ≥ 30
  par bras → route gate ; sinon indépendance ; désaccord meilleur → contrarien.

## 2. Variante (a) trend-week : inexploitable

19 zones en 3 ans (trend-week `|OC| > ATR12` ultra-sélectif) → **8 rejections**,
bras n ≤ 2. Écart +100 pp non interprétable. Exemples pour parité NT8 manuelle
(`MGIHtfInitialZone` weekly) : sem 2023-05-22 bull VAH 13948 / POC 13850.5 /
VAL 13511 ; sem 2023-09-18 bear VAH 15408 / POC 15401.5 / VAL 15396 ;
sem 2023-10-30 bull VAH 14706 / POC 14324.5 / VAL 14144.

## 3. Variante (b) toutes semaines : 148 zones → 163 rejections (162 évaluables)

| Bras | n | hold |
|---|---|---|
| Accord global | 72 | 50.0 % |
| Désaccord global | 18 | 44.4 % |
| **Écart** | — | **+5.6 pp (≪ seuil 15 pp)** |
| short/accord | 38 | 36.8 % |
| short/désaccord | 8 | 12.5 % (trop petit) |
| long/accord | 34 | 64.7 % |
| long/désaccord | 10 | 70.0 % (trop petit) |
| short/neutre | 35 | **0.0 %** (spot-checké : 30 jours distincts, pas un bug) |
| long/neutre | 37 | 67.6 % |

Coupes : VAH 18.5 % (n=81) vs **VAL 66.7 %** (n=81) ; délai ≤5j 43 % vs >5j 42 %
(aucun effet) ; macro sans discrimination franche (R/flat : long 66 % / short 17 %).

## 4. Décision : pas de gate — indépendance

Écart +5.6 pp < 15 pp, bras désaccord sous-dimensionnés (n=18) → **les
rejections daily ne portent pas le biais dayswing à un niveau exploitable en
gate**. Pas de lecture contrarienne non plus (désaccord inexploitable).
Route : objet indépendant — s'il est tradé un jour, c'est en fade seul
(plan précédent), pas en confluence.

## 5. Résultat collatéral : asymétrie directionnelle massive

Fades VAL (long) : 66.7 % de hold ; fades VAH (short) : 18.5 %, et 0 % quand le
biais du jour est neutre (0/35). Lecture : fenêtre 2023-2025 haussière NQ —
les plus hauts hebdo se font traverser, les plus bas tiennent. Biais d'époque
majeur : aucune semaine A/up-A/flat dans les coupes macro, à ne pas extrapoler
en marché baissier.

## 6. Gardes-fous

- Fenêtres de zones qui se chevauchent (148 zones × 10j) : rejections corrélées
  (35 rejections sur 30 jours pour short/neutre) — n surestime l'indépendance.
- VA hebdo à 12 pts de large observée (sem 2023-09-11) : semaines mortes =
  zones dégénérées, aucun filtre de largeur appliqué (à ajouter si suite).
- Hors frais/slippage, closes daily (pas d'intraday), parité NT8 non vérifiée
  (zones §2 à contrôler manuellement dans `MGIHtfInitialZone`).
