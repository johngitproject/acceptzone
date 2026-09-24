# Etude confluence : rejections daily sur zones weekly vs biais dayswing.
# Zones : InitialZone-weekly — trend-week |OC| > ATR Wilder(12) evalue avant
# (warmup index >= 15), zone = VA 70 % rows 4 ticks de la semaine precedente
# (value_area_70, parite NT8 MGIHtfInitialZone weekly).
# Semaines ISO lun-dim sur dates fichier (drift assume vs semaines NT8).
# Biais (a) : par jour calendaire, |C-O| > 0.5 x ATR Wilder(20) -> bull si C>O,
# bear si C<O, neutre sinon (machinerie SwingAtrEngine, warmup index >= 23).
# Rejection : jour daily qui poke (high >= VAHw+2t -> fade short potentiel,
# low <= VALw-2t -> fade long) ET close back inside [VALw, VAHw],
# dans les 10j calendaires apres fin de trend-week.
# Accord : sens du fade vs biais (a) du meme jour (neutre = colonne à part).
# Issue hold-5 : jamais recloture au-dela VALw-2t (fade long) / VAHw+2t
# (fade short) sur les 5 closes suivantes.
# Regle de lecture : ecart hold|accord vs hold|desaccord >= 15 pp avec n >= 30
# par bras -> les rejections portent le biais (route gate) ; sinon
# independance (route fade seul) ; desaccord meilleur -> signal contrarien.
# Stdlib uniquement. Sortie : donnees/backtest/weekly_confluence/rejects.csv
# + tableaux console.
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUTDIR = os.path.join(BASE, "donnees", "backtest", "weekly_confluence")

sys.path.insert(0, os.path.join(BASE, "scripts"))
from python.mgi_contact.data_loader import load_and_merge
from python.mgi_initialzone.detector import (
    build_period, clean_bars, value_area_70, wilder_atr_before,
)
from python.mgi_initialzone.reject2_atr import FILE_RANGES

TICK = 0.25
BUF = 2 * TICK
WATR_N = 12
WARM_W = WATR_N + 3
DATR_N = 20
BODY_K = 0.5
MIN_WEEK_BARS = 2000
REJ_WINDOW = 10
HOLD_FWD = 5


def monday_of(d):
    return d - timedelta(days=d.weekday())


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-trend", action="store_true",
                    help="variante (b) : VA semaine precedente toutes semaines, sans filtre trend-week")
    a = ap.parse_args(argv)
    import pathlib
    data_dir = pathlib.Path(BASE) / "donnees" / "market"
    paths = [data_dir / n for n in FILE_RANGES if (data_dir / n).exists()]
    bars = load_and_merge(paths)
    print(f"[LOAD] 1min: {len(bars)} {bars[0][0]} -> {bars[-1][0]}", flush=True)
    bars, n_sat, n_sun, n_bad = clean_bars(bars)
    print(f"[CLEAN] {n_sat} sam + {n_sun} dim + {n_bad} corrompues", flush=True)

    # --- semaines ISO ---
    per_w = defaultdict(list)
    for b in bars:
        per_w[monday_of(b[0].date())].append(b)
    wks = sorted(per_w)
    wohlc = {}
    for k in wks:
        lst = sorted(per_w[k])
        wohlc[k] = (lst[0][1], max(x[2] for x in lst),
                    min(x[3] for x in lst), lst[-1][4])
    wtrs, prev_c = [], None
    for k in wks:
        o, h, l, c = wohlc[k]
        wtrs.append((h - l) if prev_c is None else
                    max(h - l, abs(h - prev_c), abs(l - prev_c)))
        prev_c = c

    # --- zones InitialZone-weekly (ou variante b : toutes semaines) ---
    zones = []
    for j in range(1, len(wks)):
        if len(per_w[wks[j]]) < MIN_WEEK_BARS:
            continue
        if a.no_trend:
            if j < 1:
                continue
            o, h, l, c = wohlc[wks[j]]
            bull = c > o  # info seule, pas de filtre
        else:
            if j < WARM_W:
                continue
            atr = wilder_atr_before(wtrs, WATR_N, j)
            if atr is None or atr <= 0:
                continue
            o, h, l, c = wohlc[wks[j]]
            if abs(c - o) <= atr:
                continue
            bull = c > o
        va = value_area_70(sorted(per_w[wks[j - 1]]), TICK, 4, 70.0)
        if va is None:
            continue
        vah, poc, val = va
        if not (val < vah):
            continue
        zones.append({"wt": wks[j], "wi": wks[j - 1], "bull": bull,
                      "vah": vah, "poc": poc, "val": val,
                      "wend": wks[j] + timedelta(days=6)})
    print(f"[ZONES weekly] {len(zones)} "
          f"(bull={sum(1 for z in zones if z['bull'])})", flush=True)
    for z in zones[:3]:
        print(f"  trend sem {z['wt']} {'bull' if z['bull'] else 'bear'} "
              f"VAH={z['vah']:.2f} POC={z['poc']:.2f} VAL={z['val']:.2f}")

    # --- daily + biais (a) ---
    closes, ohlc, _per = build_period(bars, 1440)
    trs, prev_c, idx_of = [], None, {k: i for i, k in enumerate(closes)}
    for k in closes:
        o, h, l, c = ohlc[k]
        trs.append((h - l) if prev_c is None else
                   max(h - l, abs(h - prev_c), abs(l - prev_c)))
        prev_c = c

    def bias_of(k):
        j = idx_of[k]
        a = wilder_atr_before(trs, DATR_N, j)
        if a is None or a <= 0:
            return None
        o, _h, _l, c = ohlc[k]
        if abs(c - o) <= BODY_K * a:
            return "neutre"
        return "bull" if c > o else "bear"

    # --- macro (coupes) ---
    cfg = {}
    with open(os.path.join(BASE, "donnees", "regime", "stance_index_fwd.csv"),
              newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cfg.setdefault(r["date"], r["config"])
    mdays = sorted(cfg)

    # --- rejections ---
    rows = []
    zid = 0
    for z in zones:
        zid += 1
        for k in closes:
            d = k.date()
            if d <= z["wend"] or (d - z["wend"]).days > REJ_WINDOW:
                continue
            o, h, l, c = ohlc[k]
            for lvl, is_vah in (("VAH", True), ("VAL", False)):
                px = z["vah"] if is_vah else z["val"]
                if is_vah and not (h >= px + BUF):
                    continue
                if not is_vah and not (l <= px - BUF):
                    continue
                if not (z["val"] <= c <= z["vah"]):
                    continue
                fade = "short" if is_vah else "long"
                b = bias_of(k)
                if b is None:
                    continue
                agree = ("accord" if (fade == "short") == (b == "bear") and b != "neutre"
                         else ("neutre" if b == "neutre" else "desaccord"))
                jf = idx_of[k]
                fwd = [closes[q] for q in range(jf + 1, min(jf + 1 + HOLD_FWD, len(closes)))]
                if not fwd:
                    outcome = "n/a"
                else:
                    fc = [ohlc[q][3] for q in fwd]
                    if is_vah:
                        outcome = "fail" if any(x > z["vah"] + BUF for x in fc) else "hold"
                    else:
                        outcome = "fail" if any(x < z["val"] - BUF for x in fc) else "hold"
                ref = next((x for x in reversed(mdays)
                            if x < k.strftime("%Y-%m-%d")), None)
                rows.append({
                    "zid": zid, "wt": str(z["wt"]), "wtype": "bull" if z["bull"] else "bear",
                    "vah": round(z["vah"], 2), "val": round(z["val"], 2),
                    "poc": round(z["poc"], 2), "lvl": lvl, "day": str(d),
                    "delay": (d - z["wend"]).days, "fade": fade, "bias": b,
                    "agree": agree, "outcome": outcome, "closeD": round(c, 2),
                    "macro": cfg[ref] if ref else "", "weekday": d.weekday()})

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "rejects.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def pct(a, b):
        return f"{100.0 * a / max(1, b):.1f}%"

    ok = [r for r in rows if r["outcome"] in ("hold", "fail")]
    print(f"\n== REJECTIONS : {len(rows)} (evaluable {len(ok)}) ==")
    for fd in ("short", "long"):
        s = [r for r in ok if r["fade"] == fd]
        for ag in ("accord", "desaccord", "neutre"):
            t = [r for r in s if r["agree"] == ag]
            h = sum(1 for r in t if r["outcome"] == "hold")
            print(f"  {fd}/{ag}: n={len(t)} hold {pct(h, len(t))}")
    a = [r for r in ok if r["agree"] == "accord"]
    d = [r for r in ok if r["agree"] == "desaccord"]
    ha = sum(1 for r in a if r["outcome"] == "hold")
    hd = sum(1 for r in d if r["outcome"] == "hold")
    pa, pd = (100.0 * ha / max(1, len(a)), 100.0 * hd / max(1, len(d)))
    print(f"  ACCORD global: n={len(a)} hold {pa:.1f}% | DESACCORD: n={len(d)} "
          f"hold {pd:.1f}% | ecart {pa - pd:+.1f} pp")
    print("\n== COUPES (evaluables, hold%) ==")
    for tag, flt in (("VAH", lambda r: r["lvl"] == "VAH"),
                     ("VAL", lambda r: r["lvl"] == "VAL"),
                     ("delai<=5j", lambda r: r["delay"] <= 5),
                     ("delai>5j", lambda r: r["delay"] > 5)):
        s = [r for r in ok if flt(r)]
        h = sum(1 for r in s if r["outcome"] == "hold")
        print(f"  {tag}: n={len(s)} hold {pct(h, len(s))}")
    mc = defaultdict(list)
    for r in ok:
        if r["macro"]:
            mc[(r["fade"], r["macro"])].append(r)
    for k in sorted(mc):
        s = mc[k]
        h = sum(1 for r in s if r["outcome"] == "hold")
        print(f"  {k[0]} {k[1]}: n={len(s)} hold {pct(h, len(s))}")


if __name__ == "__main__":
    main()
