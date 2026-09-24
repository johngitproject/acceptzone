# Fade short moyenne sur closes (alternative au SL large et au DCA-touch).
# Population : zones §2 rebid avec retour close F (J3 < F <= J3+10j),
# meme definition que l'etude retest (n attendu ~37).
# Mecanique (miroir moteur DCA transpose en closes daily) :
# - entree short au close F, qty = floor(10 000 / (ATR_F x 20 $/pt NQ)), min 1.
# - renforts meme qty a chaque close daily > dernier fill + 1xATR_F, cap 2 adds
#   (3 unites max). Pas de SL large : kill-switch latent <= -40 000 $ au close.
# - TP principal : avg - 1xATR_F touche par le low daily (prioritaire dans le
#   jour, re-verifie apres chaque renfort). Temoins : TP fixes entree -0.5/-1/-1.5
#   x ATR_F avec les memes renforts (isole l'effet TP sous moyennage).
# - expiry : entree + 10j calendaires, sinon EOD fin de donnees.
# Ordre intra-jour (miroir run_side) : TP touche -> renfort -> latent/urgence ->
# expiry -> MAE/MFE vs 1re entree (ticks). Stdlib uniquement.
# Sortie : donnees/backtest/accept_fade_close/cycles.csv + tableaux console
# (pool + delai F<=3j vs >3j). n faible : resultats indicatifs.
import csv
import os
import sys
from collections import defaultdict
from statistics import mean

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUTDIR = os.path.join(BASE, "donnees", "backtest", "accept_fade_close")

sys.path.insert(0, os.path.join(BASE, "scripts"))
from python.mgi_contact.data_loader import load_and_merge
from python.mgi_initialzone.detector import clean_bars, wilder_atr_before
from python.mgi_initialzone.detect_accept import _base_zones
from python.mgi_initialzone.reject2_atr import FILE_RANGES

TICK = 0.25
PTVAL = 20.0
UNIT_RISK = 10_000.0
EMERG = -40_000.0
MAX_ADDS = 2
HOLD = 10
EXPIRY_D = 10
TP_MODES = (("avg", None), ("f05", 0.5), ("f10", 1.0), ("f15", 1.5))


def unit_qty(atr_pts):
    return max(1, int(UNIT_RISK // (atr_pts * PTVAL)))


def run_cycle(days, entry_idx, entry_px, atr, qty, tp_mode, tp_mult):
    """days : liste [(date, o, h, l, c)] indices croissants, entry_idx = jour F.
    Retourne dict cycle (reason, exit_px, fills, avg, min_latent, mfe_t, mae_t)."""
    fills = [entry_px]
    avg = entry_px
    last = entry_px
    min_latent = 0.0
    mfe = mae = 0.0
    f0 = entry_px
    exp_last = entry_idx + EXPIRY_D  # compare sur date, voir boucle
    d0 = days[entry_idx][0]
    for k in range(entry_idx + 1, len(days)):
        dt, _o, h, l, c = days[k]
        if (dt - d0).days > EXPIRY_D:
            return {"reason": "Expired", "exit_px": c, "fills": fills,
                    "avg": avg, "min_latent": min_latent,
                    "mfe_t": mfe, "mae_t": mae}
        tp = avg - atr if tp_mode == "avg" else entry_px - tp_mult * atr
        if l <= tp:  # TP prioritaire
            return {"reason": "TP", "exit_px": tp, "fills": fills,
                    "avg": avg, "min_latent": min_latent,
                    "mfe_t": mfe, "mae_t": mae}
        if c > last + atr and len(fills) < 1 + MAX_ADDS:  # renfort close
            fills.append(c)
            last = c
            avg = sum(fills) / len(fills)
            tp = avg - atr if tp_mode == "avg" else entry_px - tp_mult * atr
            if l <= tp:  # re-verifie TP apres renfort (miroir moteur)
                return {"reason": "TP", "exit_px": tp, "fills": fills,
                        "avg": avg, "min_latent": min_latent,
                        "mfe_t": mfe, "mae_t": mae}
        latent = sum((f - c) for f in fills) * PTVAL * qty
        if latent < min_latent:
            min_latent = latent
        if latent <= EMERG:  # kill-switch
            return {"reason": "Emergency", "exit_px": c, "fills": fills,
                    "avg": avg, "min_latent": min_latent,
                    "mfe_t": mfe, "mae_t": mae}
        mfe = max(mfe, (f0 - l) / TICK)
        mae = max(mae, (h - f0) / TICK)
    # fin de donnees
    _dt, _o, _h, _l, c = days[-1]
    return {"reason": "EOD", "exit_px": c, "fills": fills, "avg": avg,
            "min_latent": min_latent, "mfe_t": mfe, "mae_t": mae}


def main():
    import pathlib
    data_dir = pathlib.Path(BASE) / "donnees" / "market"
    paths = [data_dir / n for n in FILE_RANGES if (data_dir / n).exists()]
    bars = load_and_merge(paths)
    bars, _, _, _ = clean_bars(bars)
    bases, ctx = _base_zones(bars)
    closes, ohlc = ctx["closes"], ctx["ohlc"]
    trs, idx_of = ctx["trs"], ctx["idx_of"]
    days = [(k.date(), ohlc[k][0], ohlc[k][1], ohlc[k][2], ohlc[k][3])
            for k in closes]
    pos_of = {k: i for i, k in enumerate(closes)}

    sigs = []
    for b in bases:
        if not b["bullish"]:
            continue
        k3, pc = b["k3"], b["pc"]
        vah, val = pc["vah"], pc["val"]
        kf = None
        for kc in closes:
            if kc <= k3 or (kc - k3).days > HOLD:
                continue
            if val <= ohlc[kc][3] <= vah:
                kf = kc
                break
        if kf is None:
            continue
        jf = idx_of[kf]
        atr = wilder_atr_before(trs, 20, jf)
        if atr is None or atr <= 0:
            continue
        sigs.append({"j3": k3.date(), "f": kf.date(), "fi": pos_of[kf],
                     "px": ohlc[kf][3], "atr": atr, "vah": vah, "val": val,
                     "delay": (kf - k3).days,
                     "width_atr": round((vah - val) / atr, 3)})
    print(f"[SIGNAUX fade-close] {len(sigs)}", flush=True)

    rows = []
    for s in sigs:
        qty = unit_qty(s["atr"])
        for tp_mode, tp_mult in TP_MODES:
            cy = run_cycle(days, s["fi"], s["px"], s["atr"], qty,
                           tp_mode, tp_mult)
            n = len(cy["fills"])
            net = sum((f - cy["exit_px"]) for f in cy["fills"]) * PTVAL * qty
            rows.append({"tp": tp_mode, "j3": str(s["j3"]), "f": str(s["f"]),
                         "delay": s["delay"], "imm": int(s["delay"] <= 3),
                         "qty": qty, "atr": round(s["atr"], 2),
                         "n_units": n, "entry": round(s["px"], 2),
                         "avg": round(cy["avg"], 2),
                         "exit": round(cy["exit_px"], 2),
                         "reason": cy["reason"], "net": round(net, 2),
                         "min_latent": round(cy["min_latent"], 2),
                         "mfe_t": round(cy["mfe_t"], 1),
                         "mae_t": round(cy["mae_t"], 1),
                         "width_atr": s["width_atr"]})

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "cycles.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tp", "j3", "f", "delay", "imm",
                                          "qty", "atr", "n_units", "entry",
                                          "avg", "exit", "reason", "net",
                                          "min_latent", "mfe_t", "mae_t",
                                          "width_atr"])
        w.writeheader()
        w.writerows(rows)

    import math
    def show(title, sel):
        n = len(sel)
        print(f"\n== {title} ==")
        if not n:
            print("  N=0")
            return
        wins = [r for r in sel if r["net"] > 0]
        avg = mean([r["net"] for r in sel])
        var = sum((r["net"] - avg) ** 2 for r in sel) / (n - 1) if n > 1 else 0
        t = avg / math.sqrt(var / n) if var > 0 else 0.0
        gp = sum(r["net"] for r in wins)
        gl = -sum(r["net"] for r in sel if r["net"] <= 0)
        pf = (gp / gl) if gl else float("inf")
        rs = defaultdict(int)
        ad = defaultdict(int)
        for r in sel:
            rs[r["reason"]] += 1
            ad[r["n_units"] - 1] += 1
        print(f"  N={n} WR={100.0 * len(wins) / n:.1f}% "
              f"net={sum(r['net'] for r in sel):+,.0f} avg={avg:+,.0f} "
              f"t={t:.2f} PF={pf:.2f} TP/Emg/Exp/EOD={rs.get('TP', 0)}/"
              f"{rs.get('Emergency', 0)}/{rs.get('Expired', 0)}/{rs.get('EOD', 0)} "
              f"adds0/1/2={ad.get(0, 0)}/{ad.get(1, 0)}/{ad.get(2, 0)}")

    for tp, _ in TP_MODES:
        sel = [r for r in rows if r["tp"] == tp]
        show(f"TP {tp} (pool)", sel)
        show(f"TP {tp} / immediat<=3j", [r for r in sel if r["imm"]])
        show(f"TP {tp} / tardif>3j", [r for r in sel if not r["imm"]])


if __name__ == "__main__":
    main()
