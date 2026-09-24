# Backtest fade short des retours en zone acheteuse (rebid §2).
# Montage A (anticipe) : short au close F du retour (close_F dans [VALc,VAHc]).
# Montage B (confirme) : short au close E du premier jour apres F
# (F < E <= F+5) avec close_E < VALc-2t (cassure constatee).
# Communs : sens short, stop = VAHc+2t (variante high_entry+2t),
# cibles -0.5/-1.0/-1.5 x ATR (ATR Wilder-DCA avant le jour d'entree),
# evaluees sur les 5 closes daily suivantes, stop prioritaire ex-aequo
# (pattern first_touch_daily de backtest_rebid_3prof.py).
# Sortie : donnees/backtest/accept_fade/fades.csv + tableaux console
# (pool, delai F<=3j vs >3j, largeur, migration). Stdlib uniquement.
# n attendu ~38 (A) / ~27 (B) : puissance faible, resultats indicatifs.
import csv
import os
import sys
from collections import defaultdict
from statistics import mean

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUTDIR = os.path.join(BASE, "donnees", "backtest", "accept_fade")

sys.path.insert(0, os.path.join(BASE, "scripts"))
from python.mgi_contact.data_loader import load_and_merge
from python.mgi_initialzone.detector import clean_bars, wilder_atr_before
from python.mgi_initialzone.detect_accept import _base_zones
from python.mgi_initialzone.reject2_atr import FILE_RANGES

TICK = 0.25
BUF = 2 * TICK
HOLD = 10
WIN = 5
TARGETS = (("T1", 0.5), ("T2", 1.0), ("T3", 1.5))


def first_touch(fwd, tgt, stp):
    """fwd : [(o,h,l,c)] ; short : target si low<=tgt, stop si high>=stp.
    Stop prioritaire ex-aequo. Retourne (res, i)."""
    for i, (_o, h, l, _c) in enumerate(fwd):
        hs = h >= stp
        ht = l <= tgt
        if hs:
            return "stop", i
        if ht:
            return "target", i
    return "eod", len(fwd) - 1


def main():
    import pathlib
    data_dir = pathlib.Path(BASE) / "donnees" / "market"
    paths = [data_dir / n for n in FILE_RANGES if (data_dir / n).exists()]
    bars = load_and_merge(paths)
    bars, _, _, _ = clean_bars(bars)
    bases, ctx = _base_zones(bars)
    closes, ohlc = ctx["closes"], ctx["ohlc"]
    trs, idx_of = ctx["trs"], ctx["idx_of"]
    rebid = [b for b in bases if b["bullish"]]
    print(f"[ZONES rebid] {len(rebid)}", flush=True)

    sigs = []
    for b in rebid:
        k3, pc = b["k3"], b["pc"]
        vah, val = pc["vah"], pc["val"]
        # retour F : premier close dans la zone sous 10j
        kf = None
        for kc in closes:
            if kc <= k3 or (kc - k3).days > HOLD:
                continue
            if val <= ohlc[kc][3] <= vah:
                kf = kc
                break
        if kf is None:
            continue
        delay = (kf - k3).days
        jf = idx_of[kf]
        atrf = wilder_atr_before(trs, 20, jf)
        fwd_a = [closes[k] for k in range(jf + 1, min(jf + 1 + WIN, len(closes)))]
        if not fwd_a or not atrf or atrf <= 0:
            continue
        ohl_a = [(ohlc[k][0], ohlc[k][1], ohlc[k][2], ohlc[k][3]) for k in fwd_a]
        # --- montage A : entree close F ---
        sigs.append({"m": "A", "j3": str(k3.date()), "f": str(kf.date()),
                     "entry": str(kf.date()), "delay": delay,
                     "px": ohlc[kf][3], "hi": ohlc[kf][1], "atr": atrf,
                     "vah": vah, "val": val, "fwd": ohl_a})
        # --- montage B : premier close < VAL-2t dans F+1..F+5 ---
        for k in fwd_a:
            if ohlc[k][3] < val - BUF:
                je = idx_of[k]
                atre = wilder_atr_before(trs, 20, je)
                fwd_b = [closes[q] for q in range(je + 1, min(je + 1 + WIN, len(closes)))]
                if not fwd_b or not atre or atre <= 0:
                    break
                ohl_b = [(ohlc[q][0], ohlc[q][1], ohlc[q][2], ohlc[q][3]) for q in fwd_b]
                sigs.append({"m": "B", "j3": str(k3.date()), "f": str(kf.date()),
                             "entry": str(k.date()), "delay": delay,
                             "px": ohlc[k][3], "hi": ohlc[k][1], "atr": atre,
                             "vah": vah, "val": val, "fwd": ohl_b})
                break
    print(f"[SIGNAUX] A={sum(1 for s in sigs if s['m'] == 'A')} "
          f"B={sum(1 for s in sigs if s['m'] == 'B')}", flush=True)

    rows = []
    for s in sigs:
        for stop_tag, stp in (("zone", s["vah"] + BUF),
                              ("tight", s["hi"] + BUF)):
            if stp <= s["px"]:
                continue  # stop invalide (jamais le cas en B, garde-fou en A)
            risk = stp - s["px"]
            for tname, mult in TARGETS:
                tgt = s["px"] - mult * s["atr"]
                res, i = first_touch(s["fwd"], tgt, stp)
                px = tgt if res == "target" else (stp if res == "stop" else s["fwd"][-1][3])
                pts = s["px"] - px  # >0 = gain short, en points
                rows.append({"m": s["m"], "stop": stop_tag, "tgt": tname,
                             "j3": s["j3"], "entry": s["entry"],
                             "delay": s["delay"], "imm": int(s["delay"] <= 3),
                             "res": res, "pts": round(pts, 2),
                             "R": round(pts / risk, 3),
                             "width_atr": round((s["vah"] - s["val"]) / s["atr"], 3)})

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "fades.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["m", "stop", "tgt", "j3", "entry",
                                          "delay", "imm", "res", "pts", "R",
                                          "width_atr"])
        w.writeheader()
        w.writerows(rows)

    def show(title, sel):
        Tn = sorted({r["tgt"] for r in sel})
        print(f"\n== {title} ==")
        for t in Tn:
            s = [r for r in sel if r["tgt"] == t]
            if not s:
                continue
            w = sum(1 for r in s if r["res"] == "target")
            exp_pts = mean([r["pts"] for r in s])
            exp_r = mean([r["R"] for r in s])
            gp = sum(r["pts"] for r in s if r["pts"] > 0)
            gl = -sum(r["pts"] for r in s if r["pts"] <= 0)
            pf = (gp / gl) if gl else float("inf")
            eod = sum(1 for r in s if r["res"] == "eod")
            print(f"  {t}: N={len(s)} hit={100.0 * w / len(s):.1f}% "
                  f"exp={exp_pts:+.1f}pts ({exp_r:+.2f}R) PF={pf:.2f} eod={eod}")

    for m in ("A", "B"):
        for st in ("zone", "tight"):
            sel = [r for r in rows if r["m"] == m and r["stop"] == st]
            show(f"Montage {m} / stop {st} (pool)", sel)
            show(f"Montage {m} / stop {st} / immediat<=3j",
                 [r for r in sel if r["imm"]])
            show(f"Montage {m} / stop {st} / tardif>3j",
                 [r for r in sel if not r["imm"]])


if __name__ == "__main__":
    main()
