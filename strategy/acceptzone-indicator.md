# MGIAcceptZone — Spécification indicateur NT8 (affichage AcceptZones)

Session de codage : implémenter l'indicateur NinjaTrader 8 `MGIAcceptZone` qui
affiche les AcceptZones sur le chart. **Affichage seul — aucun ordre, aucun
signal d'entrée, aucun backtest dans cet indicateur.**

## 1. Références figées (lire avant de coder)

| Référence | Rôle |
|---|---|
| `MGIHtfInitialZone.cs:1-480` | **Patron direct** : indicateur overlay multi-BIP, VA 70 % sur BIP 1-min (`BuildValueArea`, `MGIHtfInitialZone.cs:155-217`), dessin `Draw.Rectangle` zone (`:328`) + `Draw.Line` (`:338`), extension jusqu'au dernier prix (`RedrawAll`/`DrawSignal`, `:302-330`), gestion `MaxZones` + suppression objets évincés (`AddSignal`, `:288-299`), messages `Print` si historique insuffisant (`:224-227`), params couleurs/opacité (`:59-94`) |
| `python/mgi_initialzone/detect_accept.py` | Règles §2 à porter (balance, composite, acceptation, mapping rebid/reoffer) |
| `scripts/backtest_swing_s2.py:53-75` | Méthode d'origine (triplets J1/J2/J3, `POC2 dans VA1`, composite J1+J2 recalculé 70 %, triple condition POC3 + `BUF 2t`) |
| `SwingCore/SwingUniformProfile.cs` | Profil uniforme réutilisable (convention volume uniforme intra-barre) |

## 2. Cadre d'exécution

- **Chart cible : H1** (série primaire `BarsPeriodType.Hour, 1`).
- Séries ajoutées en `State.Configure` (pattern `MGIHtfInitialZone.cs:95-104`) :
  - BIP 1 : `BarsPeriodType.Day, 1` (bougies J1/J2/J3 : O/H/L/C).
  - BIP 2 : `BarsPeriodType.Minute, 1` (distribution volume des profils).
- Template **ETH** requis (journées complètes ~1380 barres 1-min, comme les exports `donnees/market/`).
- `Calculate = Calculate.OnBarClose`, `IsOverlay = true`, `DisplayInDataBox = false`,
  `DrawOnPricePanel = true`, `PaintPriceMarkers = false`, `IsAutoScale = false`,
  `BarsRequiredToPlot = 2`, `MaximumBarsLookBack = MaximumBarsLookBack.Infinite`
  (le profil composite J1+J2 balaye ~2800 barres 1-min).
- `TickSize` via `Instrument.MasterInstrument.TickSize` (NQ 0.25) ; `BUF = BufferTicks × TickSize`.

## 3. Calcul (miroir §2, adapté NT8)

Pour chaque triplet de jours Daily **consécutifs et complets** du BIP 1
(J1 < J2 < J3, exiger un nombre minimal de barres 1-min par jour — défaut 800,
param `MinDayBars`, miroir `MIN_ETH_BARS`) :

1. **Profils P1/P2/P3** : VA 70 % sur les barres 1-min de chaque jour
   (fenêtre `[open J, close J]` du BIP 1, balayage du BIP 2 comme `BuildValueArea`).
   `RowHeightTicks = 4` (**défaut verrouillé**, convention NT8).
2. **Balance** : `VAL1 <= POC2 <= VAH1`, sinon triplet suivant.
3. **Composite** : fusionner les barres 1-min J1+J2 → VA 70 % recalculée
   (`VAHc/VALc/POCc`). Ignorer si `VALc >= VAHc` ou volume nul.
4. **Acceptation** (avec `BUF = BufferTicks × TickSize`) :
   - `POC3 > POC1 ET POC3 > POC2 ET POC3 > VAHc + BUF` → zone **rebid** (biais long).
   - `POC3 < POC1 ET POC3 < POC2 ET POC3 < VALc − BUF` → zone **reoffer** (biais short).
   - Sinon : pas de zone.
5. **Déclenchement** : évaluer uniquement à la **clôture du jour J3** (BIP 1),
   une fois par jour (garde `DateTime _lastJ3`, pattern `_lastDailyClose`,
   `MGIHtfInitialZone.cs:44,230-231`). **Jamais de recalcul intra-jour : pas de
   repeinture.**
6. Warmup : exiger `CurrentBars[1] >= 23` daily avant toute détection (miroir
   ATR-DCA `period + 3`) + `Print` d'avertissement unique si historique
   insuffisant (jours à charger conseillés dans le message).

> **Écart documenté vs backtest** : le Python utilise un profil tick-level
> (`profile_70`, `scripts/backtest_vp02.py:115-143`) alors que l'indicateur
> utilise des rows de 4 ticks par défaut. Attendre un écart de quelques ticks
> sur VAH/VAL/POC entre chart et `backtest_out/acceptzone_dca/`. Ne pas chercher
> à le « corriger » : passer `RowHeightTicks = 1` si parité exacte voulue.

L'`atr_ref` Wilder (sizing DCA) est **hors scope** : l'indicateur n'en a pas besoin.

## 4. Dessin

Par zone retenue (objet interne : `Tag`, `J1/J2/J3`, `Vah/Val/Poc`, `Type`,
`Poc3`) :

- **Rectangle** `Draw.Rectangle(this, Tag+"_Z", false, openJ3, VAHc, endT, VALc,
  color, color, ZoneOpacity)` avec `endT = Times[0][0]` (dernier prix) —
  **extension jusqu'au dernier prix**, pas de HOLD/expiry (décision verrouillée).
- **Ligne POC** `Draw.Line(this, Tag+"_P", false, openJ3, POCc, endT, POCc, …)`.
- **Label** `Draw.Text` : `REBID J1→J3 POC x` / `REOFFER J1→J3 POC x`
  (dates `yyyy-MM-dd`), ancré à droite sur le POC.
- **Couleurs par type** : `RebidColor` (support/long) vs `ReofferColor`
  (résistance/short), `ZoneOpacity` pour le remplissage.
- **Cap** : `MaxZones` (défaut 5) les plus récentes ; à l'éviction, `RemoveDrawObject`
  des 3 objets (`_Z`, `_P`, label) — pattern `AddSignal`.
- Toggles : `ShowRebid`, `ShowReoffer`, `ShowPoc` (masquer = `RemoveDrawObject`).

## 5. Paramètres (`NinjaScriptProperty`, groupe `MGIAcceptZone`)

| Param | Défaut | Rôle |
|---|---|---|
| `BufferTicks` | 2 | `BUF` balance/acceptation (miroir `BUF 2t`) |
| `ValueAreaPct` | 70 | Part du profil |
| `RowHeightTicks` | **4** | Rows du profil (1 = parité backtest exacte) |
| `MinDayBars` | 800 | Barres 1-min min/jour pour un jour valide |
| `MaxZones` | 5 | Zones conservées (plus récentes) |
| `ShowRebid` / `ShowReoffer` / `ShowPoc` | true | Toggles d'affichage |
| `RebidColor` / `ReofferColor` | Vert / Rouge | Couleurs par type |
| `ZoneOpacity` | 20 | Opacité remplissage |
| `ZoneBorderWidth` | 1 | Épaisseur bordure |

## 6. Cas limites

- Volume nul / jour incomplet → triplet ignoré silencieusement.
- `VALc >= VAHc` ou NaN → zone ignorée.
- Historique insuffisant → un seul `Print`, aucune zone (ne jamais dessiner partiel).
- Trous week-ends/feriés : les triplets exigent des jours Daily **consécutifs du
  BIP 1** (un jour manquant casse la séquence, comme les jours filtrés `< 800`
  barres côté Python).
- `State.DataLoaded` / `Terminated` : vider les listes (pattern `:105-119`).

## 7. Critères d'acceptation de la session de codage

1. Compile NT8 8.1 64-bit, **0 erreur**, déployé via F5 depuis
   `Documents\NinjaTrader 8\bin\Custom\Indicators\`
   (fichier indicateur à placer sous ce dossier).
2. Sur chart NQ H1 template ETH avec historique ≥ 6 mois : zones visibles sur
   janvier 2025 conformes au socle Python — **10/01 reoffer**, **17/01, 22/01,
   30/01 rebid** (`backtest_out/acceptzone_dca/` — 4 zones de référence :
   `(21383.0/21286.75)`, `(21446.5/21290.25)`, `(21762.25/21621.75)`,
   `(21600.0/21399.5)` ; tolérance ±1 pt vu rows 4 ticks, §3).
3. Extension live jusqu'au dernier prix vérifiée (nouvelle barre H1 → rectangles
   prolongés sans recalcul des niveaux).
4. Aucune repeinture intra-jour (niveaux figés entre deux closes daily).
5. `MaxZones` + toggles vérifiés (éviction supprime les objets, pas de tags orphelins).
