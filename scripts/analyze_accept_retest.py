# Etude retours close sur AcceptZone §2 + sell dissimule post-echec.
# Pour chaque zone (J3, type, composite) : premier jour F (J3 < F <= J3+10
# calendaires) avec close_F strictement dans [VALc, VAHc] -> "retour".
# Delai (F-J3) en jours, buckets 1 / 2-3 / 4-5 / 6-10 (immediat = <=3j).
# Issue sur les 5 closes suivantes : hold (jamais recloture au-dela de
# VALc-2t rebid / VAHc+2t reoffer) vs fail. Conditions : largeur/ATR,
# migration POC/ATR, config macro du jour F (stance_index_fwd, strict-avant),
# weekday. Sell dissimule : sur retests faillis, drift moyen / ATR_F et
# continuation profonde (low < VALc-ATR_F rebid, high > VAHc+ATR_F reoffer).
# Stdlib uniquement. Sortie : donnees/backtest/accept_retest/zones_retest.csv
# + tableaux console. Aucun trade simule (etude descriptive).
import csv
import os
import sys
from collections import defaultdict
from statistics import mean

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUTDIR = os.path.join(BASE, "donnees", "backtest", "accept_retest")

sys.path.insert(0, os.path.join(BASE, "scripts"))
from python.mgi_contact.data_loader import load_and_merge
from python.mgi_initialzone.detector import clean_bars, wilder_atr_before
from python.mgi_initialzone.detect_accept import _base_zones
from python.mgi_initialzone.reject2_atr import FILE_RANGES

TICK = 0.25
BUF = 2 * TICK
HOLD = 10
FWD = 5


def bucket(d):
    if d <= 1:
        return "1"
    if d <= 3:
        return "2-3"
    if d <= 5:
        return "4-5"
    return "6-10"


def load_macro():
    cfg = {}
    p = os.path.join(BASE, "donnees", "regime", "stance_index_fwd.csv")
    with open(p, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cfg.setdefault(r["date"], r["config"])
    return cfg


def main():
    import pathlib
    data_dir = pathlib.Path(BASE) / "donnees" / "market"
    paths = [data_dir / n for n in FILE_RANGES if (data_dir / n).exists()]
    print(f"[LOAD] files: {len(paths)}", flush=True)
    bars = load_and_merge(paths)
    print(f"[LOAD] 1min: {len(bars)} {bars[0][0]} -> {bars[-1][0]}", flush=True)
    bars, n_sat, n_sun, n_bad = clean_bars(bars)
    print(f"[CLEAN] {n_sat} sam + {n_sun} dim + {n_bad} corrompues", flush=True)
    cfgs = load_macro()
    days = sorted(cfgs)

    bases, ctx = _base_zones(bars)
    closes, ohlc = ctx["closes"], ctx["ohlc"]
    trs, idx_of = ctx["trs"], ctx["idx_of"]
    print(f"[ZONES] {len(bases)} (rebid={sum(1 for b in bases if b['bullish'])})",
          flush=True)

    rows = []
    for b in bases:
        k3, pc = b["k3"], b["pc"]
        vah, val = pc["vah"], pc["val"]
        long = b["bullish"]
        j3 = idx_of[k3]
        atr3 = wilder_atr_before(trs, 20, j3)
        width_atr = (vah - val) / atr3 if atr3 else 0.0
        migr = ((b["p3"]["poc"] - max(b["p1"]["poc"], b["p2"]["poc"])) / atr3
                if long else
                (min(b["p1"]["poc"], b["p2"]["poc"]) - b["p3"]["poc"]) / atr3) if atr3 else 0.0
        rec = {"j1": str(b["k1"].date()), "j2": str(b["k2"].date()),
               "j3": str(k3.date()), "type": "rebid" if long else "reoffer",
               "vah": round(vah, 2), "val": round(val, 2),
               "poc": round(pc["poc"], 2), "width_atr": round(width_atr, 3),
               "migr_atr": round(migr, 3), "delay": "", "bucket": "",
               "returned": 0, "hold_fail": "noret", "closeF": "",
               "macro": "", "weekday": "", "drift_atr": "", "deep": ""}
        # premier retour close dans la fenetre 10j
        fkey = None
        for kf in closes:
            if kf <= k3 or (kf - k3).days > HOLD:
                continue
            c = ohlc[kf][3]
            if val <= c <= vah:
                fkey = kf
                break
        if fkey is None:
            rows.append(rec)
            continue
        delay = (fkey - k3).days
        rec.update({"delay": delay, "bucket": bucket(delay), "returned": 1,
                    "closeF": round(ohlc[fkey][3], 2),
                    "weekday": fkey.weekday()})
        ref = next((x for x in reversed(days) if x < fkey.strftime("%Y-%m-%d")), None)
        rec["macro"] = cfgs[ref] if ref else ""
        jf = idx_of[fkey]
        atrf = wilder_atr_before(trs, 20, jf)
        fwd = [closes[k] for k in range(jf + 1, min(jf + 1 + FWD, len(closes)))]
        if not fwd:
            rec["hold_fail"] = "n/a"
            rows.append(rec)
            continue
        fwd_c = [ohlc[k][3] for k in fwd]
        if long:
            fail = any(c < val - BUF for c in fwd_c)
            deep = min(ohlc[k][2] for k in fwd) < val - (atrf or 0)
        else:
            fail = any(c > vah + BUF for c in fwd_c)
            deep = max(ohlc[k][1] for k in fwd) > vah + (atrf or 0)
        rec["hold_fail"] = "fail" if fail else "hold"
        if atrf:
            rec["drift_atr"] = round((mean(fwd_c) - ohlc[fkey][3]) / atrf, 3)
        rec["deep"] = int(deep)
        rows.append(rec)

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "zones_retest.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def pct(a, b):
        return f"{100.0 * a / max(1, b):.1f}%"

    print(f"\n== RETOURS close<=10j : {sum(r['returned'] for r in rows)}/{len(rows)} "
          f"({pct(sum(r['returned'] for r in rows), len(rows))}) ==")
    for typ in ("rebid", "reoffer"):
        t = [r for r in rows if r["type"] == typ]
        rt = [r for r in t if r["returned"]]
        print(f"- {typ}: retour {len(rt)}/{len(t)} ({pct(len(rt), len(t))})")
        for bk in ("1", "2-3", "4-5", "6-10"):
            s = [r for r in rt if r["bucket"] == bk]
            h = [r for r in s if r["hold_fail"] == "hold"]
            f_ = [r for r in s if r["hold_fail"] == "fail"]
            print(f"    F{bk}: n={len(s)} hold={len(h)} fail={len(f_)} "
                  f"(hold {pct(len(h), len(s))})")
        imm = [r for r in rt if r["delay"] != "" and r["delay"] <= 3]
        late = [r for r in rt if r["delay"] != "" and r["delay"] > 3]
        hi = sum(1 for r in imm if r["hold_fail"] == "hold")
        hl = sum(1 for r in late if r["hold_fail"] == "hold")
        print(f"    immediat<=3j: n={len(imm)} hold {pct(hi, len(imm))} | "
              f">3j: n={len(late)} hold {pct(hl, len(late))}")
    print("\n== CONDITIONS (retournes, hold%) ==")
    for tag, flt in (("larg<=0.75ATR", lambda r: r["width_atr"] <= 0.75),
                     ("larg>0.75ATR", lambda r: r["width_atr"] > 0.75),
                     ("migr>=0.5ATR", lambda r: r["migr_atr"] >= 0.5),
                     ("migr<0.5ATR", lambda r: r["migr_atr"] < 0.5)):
        for typ in ("rebid", "reoffer"):
            s = [r for r in rows if r["returned"] and r["type"] == typ and flt(r)]
            h = sum(1 for r in s if r["hold_fail"] == "hold")
            print(f"  {typ} {tag}: n={len(s)} hold {pct(h, len(s))}")
    mc = defaultdict(list)
    for r in rows:
        if r["returned"] and r["macro"]:
            mc[(r["type"], r["macro"])].append(r)
    for k in sorted(mc):
        s = mc[k]
        h = sum(1 for r in s if r["hold_fail"] == "hold")
        print(f"  {k[0]} {k[1]}: n={len(s)} hold {pct(h, len(s))}")
    print("\n== SELL DISSIMULE : retests faillis, drift post-echec ==")
    for typ, sgn in (("rebid", 1), ("reoffer", -1)):
        f_ = [r for r in rows if r["type"] == typ and r["hold_fail"] == "fail"
              and r["drift_atr"] != ""]
        if not f_:
            print(f"  {typ} faillis: n=0")
            continue
        d = [sgn * float(r["drift_atr"]) for r in f_]  # <0 = sens echec
        deep = sum(1 for r in f_ if r["deep"])
        print(f"  {typ} faillis: n={len(f_)} drift_moy={mean(d):+.2f} ATR "
              f"negatifs={sum(1 for x in d if x < 0)}/{len(d)} deep1ATR={deep}/{len(f_)}")


if __name__ == "__main__":
    main()
