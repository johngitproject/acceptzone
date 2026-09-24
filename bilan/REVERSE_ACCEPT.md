# Reverse AcceptZone (fake acceptance) + retours en zone — résultats

Date : 2026-09-18. NQ 1-min 2022-12-18 → 2025-12-12, 1M fixe, sans compounding,
hors frais/slippage (`costRT=0.00`, même économie que les runs AcceptZone :
unité `floor(10k/(ATR×20))`, TP `avg±ATR`, renforts ±1 ATR cap 3, urgence −$40k,
expiry 10j).

## 1. Protocole (décisions verrouillées)

- **Flip** (`python/mgi_initialzone/detect_accept.py :: detect_reverse`) :
  même profil §2 ; premier jour F (jours gardés, J3 < F ≤ J3+10 calendaires)
  où le POC daily revient **strictement dans [VALc, VAHc]** (bornes incluses,
  sans buffer) → flip de sens, **symétrique** (reoffer→acheteuse,
  rebid→vendeuse), un seul flip par zone (le premier). Signal : composite
  inchangé, `trend_date = F`, `init_date = J3` (délai flip = trend − init),
  `atr_ref` Wilder-DCA avant F, expiry DCA 10j depuis F.
- **Retour** (étude `scripts/analyze_accept_retest.py`, `donnees/backtest/accept_retest/zones_retest.csv`) :
  premier jour F (J3 < F ≤ J3+10j) avec **close daily dans [VALc, VAHc]**.
  Issue sur 5 closes : hold (jamais recloturé au-delà VALc−2t rebid / VAHc+2t
  reoffer) vs fail. Base : 148 zones §2 brutes (dont 3 sans warmup ATR,
  écartées du DCA → 145 zones, 83 rebid / 62 reoffer).
- Validation : synthétiques flip (once, bornes, symétrie, flat→0), parité
  `detect_accept` inchangée (8 zones / 4 de 01/2025 au tick), smoke + re-run
  byte-identique (sha256).

## 2. Fake-rate : les shorts fakent plus que les longs

61 flips / 148 zones (41.2 %) :
- **Fake short (reoffer→long) : 32/64 = 50.0 %** — une zone vendeuse sur deux
  voit son POC revenir dedans sous 10j.
- Fake long (rebid→short) : 29/84 = 34.5 %.
- Délais étalés 1-10j, pas de pic : immédiat ≤3j = 16/32 (shorts) et 16/29
  (longs) — le retour immédiat représente ~la moitié des flips, pas plus.

## 3. Retours close ≤10j : 75/148 (50.7 %)

- **rebid** : retour 38/84 (45.2 %). Hold par délai : F1 33 % (2/6), F2-3 37.5 %
  (6/16), F4-5 20 % (2/10), F6-10 16.7 % (1/6) → **immédiat ≤3j : 36.4 % vs
  >3j : 18.8 %**. Un retour tardif en zone acheteuse tient 2× moins.
- **reoffer** : retour 37/64 (57.8 %). Hold : F1 22 %, F2-3 43 %, F4-5 67 %
  (n=3), F6-10 36 % ; ≤3j 34.8 % vs >3j 42.9 % — pas de dégradation franche,
  buckets trop petits pour conclure.
- **Conditions** : largeur/ATR, migration POC/ATR et config macro ne discriminent
  pas (hold 27-38 % partout ; seule exception reoffer larges >0.75 ATR : 80 %
  mais n=5). Le **délai est le seul discriminant** (côté rebid).

## 4. Sell dissimulé : confirmé sur les retests faillis

Drift moyen sur les 5 closes post-échec (en ATR_F, sens de l'échec) :
- **rebid faillis (n=26) : drift −0.34 ATR, 16/26 dans le sens de l'échec,
  18/26 (69 %) enfoncent ≥ 1 ATR sous VALc sous 5j.** Le short de récupération
  existe : quand le retour en zone acheteuse échoue, la continuation baissière
  est la règle, pas l'exception.
- Miroir reoffer faillis (n=23) : drift −0.92 ATR (sens hausse), 19/23 dans le
  sens, 16/23 deep ≥ 1 ATR — « buy dissimulé » symétrique, encore plus marqué.
- n petits (26/23) : signal à confirmer, pas un système. Piste naturelle :
  fade DCA systématique des retests faillis (short sur échec rebid, long sur
  échec reoffer).

## 5. DCA sur zones flippées (`backtest_out/reverse_dca/`, `--detector reverse`)

| Run | Zones | Cycles | WR | Net | t | PF | TP/Urg/Exp |
|---|---|---|---|---|---|---|---|
| **Long (= ex-reoffer flippées)** | 32 | 94 | 88.3 % | **+$401 675** | 2.74 | 2.08 | 83/9/2 |
| Short (= ex-rebid flippées) | 29 | 93 | 68.8 % | −$82 616 | −0.42 | 0.89 | 64/10/19 |

Par année (entrée) :
- Reverse long : 2023 N=33 +$84k t 0.76 PF 1.40 | 2024 N=34 +$114k t 1.19
  PF 1.71 | **2025 N=27 +$204k, 27/27 TP, 0 urgence** (perfection sur n=27 :
  lire avec prudence, année haussière + cycles chevauchants).
- Reverse short : négatif les 3 ans (2023 −$46k, 2024 −$23k, 2025 −$13k),
  t entre −0.12 et −0.36 : plat-négatif, aucun edge.

**Lecture : trader le fake short vendeur fonctionne (t 2.74, PF 2.08 —
meilleur PF que le long socle AcceptZone à 1.62) ; trader le fake long ne
fonctionne pas.** Cohérent avec §4 : l'échec vendeur se paie, l'échec acheteur
aussi — mais seules les zones reoffer flippées portent un système complet.

## 6. Fade short des retours acheteurs (`scripts/backtest_fade_rebid.py`)

Donnees `donnees/backtest/accept_fade/fades.csv`. Montage A : short au close F
du retour (38 retours → 37 signaux, 1 F sans suite). Montage B : short au close
E de la cassure sous VALc−2t dans F+1..F+5 (26 signaux). Entry market au close,
stop VAHc+2t (variante high+2t), cibles −0.5/−1.0/−1.5×ATR jour d'entrée,
first-touch stop-prioritaire sur 5 closes. n faibles : indicatif.

| Montage / stop | T1 | T2 | T3 |
|---|---|---|---|
| A / zone (N=37) | hit 27 %, +0.28R, PF 0.95 | hit 24 %, **+1.17R, PF 1.66** | hit 22 %, **+1.76R, PF 2.06** |
| A / zone / ≤3j (N=22) | +0.45R PF 1.12 | +1.47R PF 1.68 | +1.99R PF 1.58 |
| A / zone / >3j (N=15) | +0.03R PF 0.82 | +0.73R PF 1.65 | +1.43R PF 2.47 |
| A / tight (N=37) | −0.10R PF 0.73 | +0.17R PF 0.82 | +0.28R PF 0.87 |
| B / zone (N=26) | −0.24R PF 0.39 | −0.28R PF 0.38 | −0.15R PF 0.51 |
| B / zone / ≤3j (N=14) | −0.66R PF 0.12 | −0.66R PF 0.10 | −0.65R PF 0.11 |
| B / zone / >3j (N=12) | +0.26R PF 1.71 | +0.17R PF 1.14 | +0.43R PF 1.60 |
| B / tight | pire que zone partout (pool T1 −0.16R PF 0.57) | — | — |

**Lecture :**
1. **A avec stop large fonctionne (T2/T3 positifs, PF jusqu'à 2.06) ; stop
   serré tue le montage** (stoppé par le bruit intra-zone).
2. **B échoue en pool** malgré le drift −0.34 ATR mesuré : shorter la cassure
   constatée, c'est entrer après le mouvement avec un stop énorme (zone entière
   + distance) et se faire reprendre par les snap-backs — surtout ≤3j
   (PF ~0.1, catastrophe). Le drift était réel mais pas actionnable à E.
3. Seule exception : B tardif >3j (N=12, PF 1.6-2.6) — intéressant mais n=12.
4. Réponse au paradoxe §6 : les longs DCA gagnent autrement (entrée limite au
   niveau + TP +1 ATR intraday + moyennage), mais le fade A montre que le
   flux vendeur sur retour existe aussi en version « pure » (faible hit rate,
   R élevé).

## 7. Fade-DCA short : le DCA dégrade le fade pur

`detect_fade()` (`detect_accept.py`, `--detector fade`, label `FadeZone`) :
zones rebid retournées (close F, même population que A pur, 37 signaux tous
bearish, parité étude OK), `trend=F`, expiry 10j, run `--side short`
(`backtest_out/fade_dca/short/`, smoke + sha256 OK) :

| | Cycles | WR | Net | t | PF | TP/Urg/Exp |
|---|---|---|---|---|---|---|
| Fade-DCA short | 125 (3.4/zone) | 66.4 % | **−$291 466** | −1.23 | 0.75 | 81/18/26 |
| Par année | 2023 N=43 −$196k PF 0.61 | 2024 N=32 −$123k PF 0.61 | 2025 N=50 +$28k (t 0.22, plat) | — | — | — |
| Rappel fade pur A / zone | T2 +1.17R PF 1.66 | T3 +1.76R PF 2.06 | (N=37) | — | — | — |

**Lecture : non, le DCA ne fait pas mieux — il inverse le profil.**
Le fade pur (hit ~22 %, R élevé) devient high-WR / negative-expectancy :
1. **Population élargie** : entrées au touch sur 10j (mèches incluses, parfois
   avant tout retour-close) → 125 cycles vs 37 signaux, dont des touches
   précoces qui n'auraient jamais compté en A pur.
2. **Mauvais prix** : shorter VAH en limite, c'est shorter le haut de zone
   quand le flux pousse encore — traversée → renforts → urgence (18 × −$40k).
   Le close F offrait un prix médian « confirmé ».
3. **TP dynamique adverse ici** : `avg−ATR` encaisse souvent petit (81 TP)
   pendant que urgences (18) et expirations (26) saignent : PF 0.75.
4. Aucune année positive significative (2025 plat, t 0.22).

Conclusion : sur cet objet, la formule gagnante est **entrée tardive (close) +
stop large + cible fixe**, pas limite + moyennage. Le fade-DCA est écarté ;
le fade pur A reste piste à confirmer (N=37).

## 8. Fade-close moyenné : moyenner ne bat pas le stop large

`scripts/backtest_fade_close.py` (`donnees/backtest/accept_fade_close/cycles.csv`) :
même population que A pur (37 retours, entrée short close F), renforts même
qty aux closes > dernier fill + 1×ATR (cap 2), **pas de SL** (kill-switch
latent ≤ −$40k + expiry 10j), TP principal `avg−1×ATR` + témoins fixes :

| TP | Pool (N=37) | Immédiat ≤3j (N=22) | Tardif >3j (N=15) |
|---|---|---|---|
| avg (principal) | WR 70 %, −$49k, t −0.38, PF 0.84 (26 TP/2 Emg/9 Exp, adds 21/12/4) | −$84k PF 0.62 (2 urgences ici) | **+$35k PF 1.45** (13 TP/0 Emg, 2e add jamais utilisé) |
| fixe −0.5× | −$66k PF 0.72 | −$37k PF 0.77 | −$29k PF 0.63 |
| fixe −1.0× | −$22k PF 0.93 | −$40k PF 0.82 | +$18k PF 1.20 |
| fixe −1.5× | −$32k PF 0.90 | −$82k PF 0.65 | +$50k PF 1.56 |

**Lecture :**
1. Moyenner sur closes ne bat pas le fade pur A (T2 +1.17R PF 1.66) : le
   meilleur (fixe −1.0×, −$22k PF 0.93) reste négatif/plat.
2. Cohérent avec §3 : les retours tardifs faillissent plus (81 %) → le fade y
   est meilleur (tardif positif sur avg/f10/f15) ; les immédiats tiennent plus
   (36 %) → le fade y saigne (2 urgences, 4 doubles adds, tous ≤3j).
3. Les adds se concentrent où ça fait mal : 12/22 immédiats moyennés (dont les
   2 urgences) contre 4/15 tardifs. Moyenner un fade qui tient, c'est
   grossir la perte — miroir de la leçon InitialZone (adds perdants).
4. Hiérarchie sur cet objet : **fade pur A (stop large, 1 unité) > fade-close
   moyenné (≈ plat/négatif) > fade-DCA touch (−$291k)**. Plus l'entrée est
   précoce/haute et plus on moyenne, pire c'est.

## 9. Conclusion

1. Oui, les zones short fakent souvent : **50 %** (vs 34.5 % côté long).
2. Retour immédiat (≤3j) en zone acheteuse tient 2× mieux que tardif
   (36 % vs 19 %) ; côté vendeur, pas d'effet délai exploitable.
3. Le sell de récupération dissimulé est mesuré : 69 % des retests acheteurs
   faillis enfoncent ≥ 1 ATR — fade short à tester en DCA.
4. Système : **reverse-long qualifie** (94 cycles, t 2.74) aux côtés du long
   socle AcceptZone (t 2.69). Reverse-short écarté.
5. Fade A (stop zone, T2/T3) positif sur N=37 — piste short à confirmer,
   montage B (chasse la cassure) écarté sauf tardif (n=12).
6. Gardes-fous : t surestimés (chevauchements), 2025 reverse-long parfait =
   outlier probable, hors frais/slippage, concurrence illimitée, urgences non
   garanties.
