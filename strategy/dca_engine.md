# Moteur DCA — spécification réutilisable (`python/mgi_initialzone/`)

Moteur de backtest générique : il prend une liste de **zones** (quelconques —
InitialZone ou autre stratégie) et simule des cycles DCA/averaging dessus.
Pour tester une nouvelle stratégie avec le même moteur, fournir ses zones au
format `ZoneSignal` et appeler `run_side` (voir §6). Aucune logique InitialZone
n'est câblée dans le moteur lui-même (détection = `detector.py`, interchangeable).

## 1. Contrat d'entrée — `ZoneSignal` (`detector.py`)

| Champ | Type | Rôle moteur |
|---|---|---|
| `trend_date` | date | Début de vie (daily) / jour de la trend (H1) |
| `trend_dt` | datetime \| None | Fin de trend-candle (requis si `hourly=True`) |
| `bullish` | bool | Filtré par `side` : long garde `True`, short `False` |
| `vah`, `val` | float | Les 2 niveaux tradés (VAL + VAH) ; zone ignorée si `val >= vah` ou NaN |
| `poc` | float | Informatif uniquement (jamais tradé en l'état) |
| `atr_ref` | float | TP = avg ± ATR ; pas des renforts ; sizing de l'unité |
| `has_zone` | bool | `False` → zone ignorée |

Le moteur ne retient que `bullish`, `val/vah`, `atr_ref`, `trend_date/trend_dt`.

## 2. Données

- Barres 1-min `(dt, o, h, l, c, v)`, timestamps **UTC** (fichier prouvé UTC).
- `clean_bars` obligatoire en amont : samedis + dimanches 00h-21h59 UTC
  (+ dimanche 22h si plat/vol≤2) + barres corrompues (range > 5 % ou hors
  bande [0.5×, 2×]) écartés, comptés dans `stats.md`.
- Resample floor (timestamps = open) pour 5-min (`confirm`) et H1 (régime daily).

## 3. Cycle de vie d'un cycle (clé = (zone, niveau))

1. **Activation** : daily `trend_date < jour ≤ +10 j` ; H1 `trend_dt < dt ≤ +expiry_hours`
   (`--no-expiry` : jamais d'expiration, évaluation indexée par prix).
2. **Fill** : limite au niveau brut (`low ≤ L` long / `high ≥ L` short,
   prix = min/max(open, L)) ; 1er fill par (zone, niveau) ; re-trigger jours
   différents uniquement ; anti-refill (mode no-expiry : pas de fill installé
   de l'autre côté de toute la zone sans reclaim).
3. **Modes d'entrée** (`--entry-mode`) : `immediate` (défaut, prouvé meilleur),
   `confirm` (close 5-min du bon côté + rattrapage TP), `second-touch` (2e touche
   du jour), `delay` (market +N min, défaut 15).
4. **Renforts** : même qty, au close 1-min au-delà du rung (dernier fill ∓ 1×ATR),
   **cap 3 adds** (4 unités max).
5. **Sorties** : TP = moyenne + sgn×ATR touché en 1-min (**prioritaire** dans la
   barre) ; urgence si latent ≤ −`emerg_dollars` au close ; expiry sinon
   (jamais en no-expiry) ; EOD fin de données.
6. Sizing : `qty = max(1, floor(10 000 $ / (ATR × 20 $/pt NQ)))` figé par cycle.

## 4. Gates d'entrée (évalués à la touche, dans cet ordre, refus comptés)

`monthly-open` → `daily-open` → `rth-open` → `régime monthly` → `régime daily`
→ `âge zone` → `session`. Chaque gate : `none | long | short | both`
(`both` = appliqué aux deux côtés). Refus warmup : J1-J3 du mois (régime
monthly), 00h-02h59 UTC (régime daily).

## 5. Paramètres (`dca_atr.py`, CLI)

| Flag | Défaut | Rôle |
|---|---|---|
| `--side` | both | long / short / both (runs séparés, jamais mélangés) |
| `--timeframe` | daily | daily (expiry 10 j calendaires) / h1 (`--expiry-hours`, défaut 10) |
| `--atr-mult` | 1.0 | Seuil détection `body ≥ mult×ATR` (sélection zones, pas gestion) |
| `--tick` | 0.25 | NQ |
| `--emerg-dollars` | 40000.0 | Urgence latent par cycle |
| `--entry-mode` / `--entry-delay-min` | immediate / 15 | Voir §3 |
| `--min-zone-age` | 0 | Jours (daily) ou heures (H1) entre trend et fill |
| `--session-filter` | all | all / rth (14-20h UTC) / on |
| `--monthly-filter` / `--dailyopen-filter` / `--rthopen-filter` | none | Position vs open mois / jour / RTH (14h UTC) |
| `--regime-filter` / `--dayregime-filter` | none | POC developing vs VA période précédente (mois / jour) |
| `--no-expiry` | off | Zones et trades sans expiration |

## 6. Brancher une nouvelle stratégie

1. Écrire `detect_mastrat()` → `List[ZoneSignal]` (mêmes champs §1 ;
   `atr_ref` > 0 obligatoire — sert au TP, aux renforts ET au sizing).
2. Appeler `run_side(bars_1min, signals, side, out_dir, tick, start_dt, mo, ...)`
   avec les caches dont ses gates ont besoin (`None` = gate inactif).
3. Sorties automatiques : `cycles.csv` (dont `regime`, `min_latent_d`,
   `mfe_t/mae_t`), `legs.csv` (fills + `drift15_t`), `stats.md`
   (n, WR, net, t, PF, motifs, adds, MAE/MFE, refus par gate).
4. Valider : smoke 1 mois + contrôle déterminisme (re-run byte-identique),
   test synthétique des gates (warmup/régime), vérification manuelle
   rung/moyenne/TP/net sur 1 cycle avec renforts.

## 7. Limites connues (ne pas régresser en modifiant le moteur)

- Pas de frais/slippage, pas de compounding, contrats entiers, concurrence
  plafonnable (`--max-open-cycles`, défaut 0 ; adopted : 3, short-regime 5),
  marge non modélisée.
- t-stat sur cycles chevauchants (surestimé) ; urgences = seuil déclencheur,
  pas stop garanti (dépassements à −$50k observés).
- Buckets UTC fixes (DST non modélisé) ; MAE/MFE = excursions vs 1re entrée ;
  `min_latent_d` = pire latent aux closes (pas intrabarre).
- Chemin expiry-on prouvé byte-identique entre refactors (smoke 46 cycles
  H1 short janvier) : toute modification du moteur exige le même contrôle
  avant de publier des chiffres.
