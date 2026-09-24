# Backtest Swing v03 — Swing Levels ATR20 + Zones Reoffer/Rebid (RTH Paris 15h30-21h, DST)
# ES + NQ, donnees NT8 1-min Last, stdlib uniquement.
# Spec validee user:
#  - RTH = 15h30-21h00 Europe/Paris, DST pris en compte (diff Paris-Chicago 7h normal, 6h semaines mixtes).
#  - Swing Daily RTH: body |C-O| > 0.5*ATR20 (ATR20 = moyenne 20j True Range RTH).
#    bullish -> Swing Low = low du jour ; bearish -> Swing High = high du jour.
#  - Zone valide uniquement si journee de retest cloturee. Zone = VAH/POC/VAL RTH (70%) du jour de retest.
#    retest Swing High -> reoffer (biais short), retest Swing Low -> rebid (biais long).
#  - Signaux en 5min RTH (2 closes) et 1H RTH (1 close), fade de chaque sous-niveau VAH/POC/VAL.
#  - H8: POC daily RTH veille dans zone = balance (fade), POC au-dela = acceptation (continuation).
import csv
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, "scripts")
from backtest_vp02 import load_market, profile_70, active_contract, ORDER  # reuse roll + profil

MARKET = "donnees/market"
OUTDIR = "donnees/backtest/swing03"
TICK = 0.25
PTVAL = {"NQ": 20.0, "ES": 50.0}
COST_RT = {"NT-Lifetime": 4.36, "NT-Monthly": 5.16, "NT-Free": 5.76, "Conservateur-2ticks": None}
CONS_RT = {"NQ": 10.0, "ES": 25.0}
BUF = 2
POKE_T = 2
ATR_N = 20
SWING_K = 0.5
LOOKBACK_SWING = 20
HOLD_ZONE = 5  # fraicheur max en jours (H6)
MIN_RTH_BARS = 200  # ~5.5h=330 bars 1-min, tolerance jours partiels
ACC_N_5M = 2
ACC_N_1H = 1
REJ_WINDOW_5M = 5
REJ_WINDOW_1H = 3


# ---------- DST / RTH Paris ----------
def _nth_weekday(year, month, n, weekday):
    # n>=1: n-ieme, n=-1: dernier. weekday lundi=0..dimanche=6
    if n > 0:
        d = date(year, month, 1)
        off = (weekday - d.weekday()) % 7
        return d + timedelta(days=off + (n - 1) * 7)
    # dernier
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    off = (d.weekday() - weekday) % 7
    return d - timedelta(days=off)


def us_dst_on(chicago_date):
    # US DST: 2e dimanche mars -> 1er dimanche nov
    y = chicago_date.year
    start = _nth_weekday(y, 3, 2, 6)
    end = _nth_weekday(y, 11, 1, 6)
    return start <= chicago_date < end


def eu_dst_on(dt_date):
    # EU DST: dernier dimanche mars -> dernier dimanche oct (jours locaux approx = date Chicago pour RTH)
    y = dt_date.year
    start = _nth_weekday(y, 3, -1, 6)
    end = _nth_weekday(y, 10, -1, 6)
    return start <= dt_date < end


def paris_diff_hours(d):
    return 6 if (us_dst_on(d) != eu_dst_on(d)) else 7


def rth_paris_bars(bars_1m, day):
    """Filtre 15h30-21h Paris depuis barres 1-min heure Chicago. bar=(t_sec,o,h,l,c,v)."""
    diff = paris_diff_hours(day)
    out = []
    for (t, o, h, l, c, v) in bars_1m:
        paris_sec = t + diff * 3600
        if 15 * 3600 + 30 * 60 < paris_sec <= 21 * 3600:
            out.append((t, o, h, l, c, v))
    return sorted(out)


# ---------- Agregation ----------
def resample(bars, minutes):
    if not bars:
        return []
    step = minutes * 60
    buckets = defaultdict(list)
    for b in bars:
        key = (b[0] // step) * step
        buckets[key].append(b)
    out = []
    for k in sorted(buckets):
        g = buckets[k]
        o = g[0][1]
        c = g[-1][4]
        h = max(x[2] for x in g)
        l = min(x[3] for x in g)
        v = sum(x[5] for x in g)
        out.append((k, o, h, l, c, v))
    return out


def daily_ohlc(rth):
    return {"o": rth[0][1], "h": max(b[2] for b in rth), "l": min(b[3] for b in rth), "c": rth[-1][4]}


def first_touch(bars, start, target, stop, direction):
    for i in range(start, len(bars)):
        _, _, h, l, c, _ = bars[i]
        if direction == 1:
            hit_t = h >= target
            hit_s = l <= stop
        else:
            hit_t = l <= target
            hit_s = h >= stop
        if hit_s and hit_t:
            return "stop", i
        if hit_s:
            return "stop", i
        if hit_t:
            return "target", i
    return "eod", len(bars) - 1


def find_signal(bars, lvl, bias_dir, acc_n, rej_window, width):
    """bias_dir=+1 resistance (reoffer/short-fade). Exige crossing: close precedente du bon cote.
    + proximite entree (<=0.5*largeur+8t) pour eviter signaux a 250pts. Continue si 1er poke echoue."""
    max_dist = 0.5 * max(width, TICK) + 8 * TICK
    for i in range(len(bars)):
        _, o_i, h, l, c, _ = bars[i]
        # crossing requis: etait dessous (bias long-resistance) ou dessus (support)
        if i == 0:
            prev_close = bars[i][1]  # open du premier bar comme proxy
        else:
            prev_close = bars[i - 1][4]
        if bias_dir == 1:
            if not (prev_close < lvl + BUF * TICK):
                continue
            poked = h >= lvl + POKE_T * TICK
        else:
            if not (prev_close > lvl - BUF * TICK):
                continue
            poked = l <= lvl - POKE_T * TICK
        if not poked:
            continue
        ext = h if bias_dir == 1 else l
        run = 0
        found = None
        for j in range(i, min(i + rej_window + acc_n + 2, len(bars))):
            _, _, h2, l2, c2, _ = bars[j]
            ext = max(ext, h2) if bias_dir == 1 else min(ext, l2)
            beyond = (c2 > lvl) if bias_dir == 1 else (c2 < lvl)
            back = (c2 < lvl) if bias_dir == 1 else (c2 > lvl)
            if back and (j - i) < rej_window:
                if abs(c2 - lvl) <= max_dist:
                    found = ("fade", j, ext)
                break
            if beyond:
                run += 1
                if run >= acc_n:
                    if abs(c2 - lvl) <= max_dist:
                        found = ("accept", j, ext)
                    break
            else:
                run = 0
        if found:
            return found
        # sinon continuer la recherche (pas de return None immediat)
    return None


def mk(inst, d, hyp, dr, en, px, res, ib, zone, lvl_name, ut, extra=""):
    gross_pts = dr * (px - en)
    gross = gross_pts * PTVAL[inst]
    row = {"market": inst, "date": str(d), "hyp": hyp, "dir": dr,
           "entry": round(en, 2), "exit": round(px, 2), "res": res, "bars": ib,
           "ut": ut, "lvl": lvl_name,
           "zone_type": zone["ztype"], "zone_date": str(zone["zdate"]),
           "zVAH": round(zone["vah"], 2), "zVAL": round(zone["val"], 2), "zPOC": round(zone["poc"], 2),
           "swing_ref": round(zone["swing"], 2), "fresh": zone["fresh"],
           "poc_pos": zone.get("poc_pos", "-"),
           "gross_pts": round(gross_pts, 2), "gross_$": round(gross, 2), "note": extra}
    for plan, c in COST_RT.items():
        cc = CONS_RT[inst] if plan == "Conservateur-2ticks" else c
        row[f"net_{plan}_$"] = round(gross - cc, 2)
    return row


def run_market(inst):
    daily_all, fallbacks = load_market(inst)
    days_all = sorted(daily_all)
    # RTH Paris
    rth1 = {}
    for d in days_all:
        _, bars_1m = daily_all[d]
        rb = rth_paris_bars(sorted(bars_1m), d)
        if len(rb) >= MIN_RTH_BARS:
            rth1[d] = rb
    days = sorted(rth1)
    ohlc = {d: daily_ohlc(rth1[d]) for d in days}
    prof = {d: profile_70(rth1[d]) for d in days}
    # ATR20 + swings (besoin prev close)
    atr = {}
    swings = {}  # d -> ("high"/"low", prix)
    prev_c = None
    trs = []
    for d in days:
        o = ohlc[d]
        if prev_c is None:
            tr = o["h"] - o["l"]
        else:
            tr = max(o["h"] - o["l"], abs(o["h"] - prev_c), abs(o["l"] - prev_c))
        trs.append(tr)
        if len(trs) > ATR_N:
            a = sum(trs[-ATR_N - 1:-1]) / ATR_N
            atr[d] = a
            body = abs(o["c"] - o["o"])
            if body > SWING_K * a:
                if o["c"] > o["o"]:
                    swings[d] = ("low", o["l"])
                else:
                    swings[d] = ("high", o["h"])
        prev_c = o["c"]
    # Zones: jour D qui reteste un swing des 20j precedents -> zone = VP(D)
    zones_by_date = defaultdict(list)  # date creation -> [zones]
    swing_list = sorted(swings.items())  # (d,(side,px))
    for idx, d in enumerate(days):
        if d not in prof or prof[d] is None:
            continue
        o = ohlc[d]
        # swings actifs = 20 derniers jours avant D
        active = [(sd, s) for (sd, s) in swing_list if sd < d and (d - sd).days <= LOOKBACK_SWING]
        if not active:
            continue
        made = set()
        for (sd, (side, px)) in active:
            if side == "high":
                touched = o["h"] >= px - BUF * TICK
                ztype = "reoffer"
            else:
                touched = o["l"] <= px + BUF * TICK
                ztype = "rebid"
            if touched and ztype not in made:
                P = prof[d]
                zones_by_date[d].append({"zdate": d, "ztype": ztype, "vah": P["vah"],
                                         "val": P["val"], "poc": P["poc"], "swing": px,
                                         "swing_date": sd, "fresh": 0})
                made.add(ztype)
    trades = []
    cov = {"n_days": len(days), "first": str(days[0]) if days else "-",
           "last": str(days[-1]) if days else "-", "fallbacks": fallbacks,
           "n_swings": len(swings), "n_zonedays": len(zones_by_date)}
    # Signaux: pour chaque zone creee en D, tester F=D+1..D+5, chaque sous-niveau, 2 UT
    zone_days = sorted(zones_by_date)
    day_index = {d: i for i, d in enumerate(days)}
    for zd in zone_days:
        for z in zones_by_date[zd]:
            bias = 1 if z["ztype"] == "reoffer" else -1  # 1=resistance->fade short
            for fwd in range(1, HOLD_ZONE + 1):
                if zd not in day_index:
                    continue
                fi = day_index[zd] + fwd
                if fi >= len(days):
                    break
                fd = days[fi]
                zc = dict(z)
                zc["fresh"] = fwd
                # H8: position POC veille (fd-1) vs zone
                pd = days[fi - 1]
                Pprev = prof.get(pd)
                if Pprev is None:
                    poc_pos = "-"
                else:
                    pp = Pprev["poc"]
                    if zc["val"] <= pp <= zc["vah"]:
                        poc_pos = "inside"
                    elif pp > zc["vah"]:
                        poc_pos = "above"
                    else:
                        poc_pos = "below"
                zc["poc_pos"] = poc_pos
                r5 = resample(rth1[fd], 5)
                r60 = resample(rth1[fd], 60)
                for lvl_name, lvl_px in (("VAH", zc["vah"]), ("POC", zc["poc"]), ("VAL", zc["val"])):
                    width = zc["vah"] - zc["val"]
                    # --- UT 5min ---
                    sig = find_signal(r5, lvl_px, bias, ACC_N_5M, REJ_WINDOW_5M, width)
                    if sig:
                        kind, ie, ext = sig
                        en = r5[ie][4]
                        if kind == "fade":
                            dr = -1 if bias == 1 else 1
                            if bias == 1:  # short reoffer
                                tgt = zc["poc"] if lvl_name == "VAH" else zc["val"]
                                stp = ext + BUF * TICK
                            else:
                                tgt = zc["poc"] if lvl_name == "VAL" else zc["vah"]
                                stp = ext - BUF * TICK
                            hyp = f"S3-{zc['ztype']}-{lvl_name}-5m-fade"
                            res, i1 = first_touch(r5, ie, tgt, stp, dr)
                            px = tgt if res == "target" else (stp if res == "stop" else r5[-1][4])
                            trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, zc, lvl_name, "5m",
                                             f"poc_prev={poc_pos} fwd={fwd}"))
                        else:
                            dr = 1 if bias == 1 else -1
                            hyp = f"S3-{zc['ztype']}-{lvl_name}-5m-accept"
                            stp = lvl_px - BUF * TICK if dr == 1 else lvl_px + BUF * TICK
                            tgt = en + dr * 0.5 * max(width, TICK)
                            res, i1 = first_touch(r5, ie, tgt, stp, dr)
                            px = tgt if res == "target" else (stp if res == "stop" else r5[-1][4])
                            trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, zc, lvl_name, "5m",
                                             f"poc_prev={poc_pos} fwd={fwd}"))
                    # --- UT 1H ---
                    sig1 = find_signal(r60, lvl_px, bias, ACC_N_1H, REJ_WINDOW_1H, width)
                    if sig1:
                        kind, ie, ext = sig1
                        en = r60[ie][4]
                        if kind == "fade":
                            dr = -1 if bias == 1 else 1
                            if bias == 1:
                                tgt = zc["poc"] if lvl_name == "VAH" else zc["val"]
                                stp = ext + BUF * TICK
                            else:
                                tgt = zc["poc"] if lvl_name == "VAL" else zc["vah"]
                                stp = ext - BUF * TICK
                            hyp = f"S3-{zc['ztype']}-{lvl_name}-1h-fade"
                            res, i1 = first_touch(r60, ie, tgt, stp, dr)
                            px = tgt if res == "target" else (stp if res == "stop" else r60[-1][4])
                            trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, zc, lvl_name, "1h",
                                             f"poc_prev={poc_pos} fwd={fwd}"))
                        else:
                            dr = 1 if bias == 1 else -1
                            hyp = f"S3-{zc['ztype']}-{lvl_name}-1h-accept"
                            stp = lvl_px - BUF * TICK if dr == 1 else lvl_px + BUF * TICK
                            tgt = en + dr * 0.5 * max(width, TICK)
                            res, i1 = first_touch(r60, ie, tgt, stp, dr)
                            px = tgt if res == "target" else (stp if res == "stop" else r60[-1][4])
                            trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, zc, lvl_name, "1h",
                                             f"poc_prev={poc_pos} fwd={fwd}"))
    return trades, cov, {"swings": swings, "atr_n": len(atr)}


def summarize(trades):
    import statistics as st
    hyps = sorted(set(x["hyp"] for x in trades))
    header = ("hypothese", "N", "hit%", "exp-Lifetime-$", "exp-Conserv-$", "PF-gross", "duree_med")
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for hyp in hyps:
        t = [x for x in trades if x["hyp"] == hyp]
        wins = [x for x in t if x["gross_$"] > 0]
        hit = 100.0 * len(wins) / len(t) if t else 0
        expL = sum(x["net_NT-Lifetime_$"] for x in t) / len(t) if t else 0
        expC = sum(x["net_Conservateur-2ticks_$"] for x in t) / len(t) if t else 0
        gp = sum(x["gross_$"] for x in wins)
        gl = -sum(x["gross_$"] for x in t if x["gross_$"] <= 0)
        pf = (gp / gl) if gl > 0 else float("inf")
        dur = st.median([x["bars"] for x in t]) if t else 0
        lines.append(f"| {hyp} | {len(t)} | {hit:.1f} | {expL:.2f} | {expC:.2f} | {pf:.2f} | {dur:.0f} |")
    return "\n".join(lines)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    all_t = []
    reps = []
    for inst in ("NQ", "ES"):
        t, cov, dbg = run_market(inst)
        all_t += t
        reps.append(f"## {inst} — {cov['n_days']} jours RTH Paris valides ({cov['first']} -> {cov['last']}), "
                    f"swings={cov['n_swings']}, jours-zones={cov['n_zonedays']}")
    all_t.sort(key=lambda x: (x["date"], x["market"], x["hyp"]))
    if all_t:
        with open(os.path.join(OUTDIR, "trades.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_t[0].keys()))
            w.writeheader()
            w.writerows(all_t)
        cut = all_t[len(all_t) * 7 // 10]["date"]
        IS = [x for x in all_t if x["date"] < cut]
        OOS = [x for x in all_t if x["date"] >= cut]
    else:
        cut, IS, OOS = "-", [], []
    L = ["# Backtest Swing v03 — ATR20 + Zones Reoffer/Rebid (RTH Paris 15h30-21h, DST)",
         "",
         "_Usage perso. RTH Paris 15h30-21h (Chicago +7h normal, +6h semaines mixtes Mar/Oct-Nov). "
         "Profils RTH 70% volume intra-barre uniforme (approximation). Swing si body>0.5*ATR20. "
         "Zone = VP du jour de retest cloture (reoffer si retest high, rebid si retest low). "
         "Fade/accept 5min (2 closes, fenetre 5) et 1H (1 close, fenetre 3). "
         "Stop=extreme+2t, fade VAH->POC / POC->bord oppose, accept 0.5*largeur. "
         "Rollover J-8. Couts Lifetime $4.36, Conserv NQ $10 / ES $25._", ""]
    L += reps + [""]
    for title, t in (("Complet", all_t), (f"IS (< {cut})", IS), (f"OOS (>= {cut})", OOS)):
        L.append(f"### {title} — N={len(t)}")
        for inst in ("NQ", "ES"):
            sub = [x for x in t if x["market"] == inst]
            L.append(f"#### {inst} (N={len(sub)})")
            L.append(summarize(sub) if sub else "_aucun trade_")
            L.append("")
    # H8 split
    L.append("### H8 — POC veille vs zone (tous UT, fade vs accept separes)")
    for inst in ("NQ", "ES"):
        L.append(f"#### {inst}")
        for pos in ("inside", "above", "below"):
            for kind in ("fade", "accept"):
                sub = [x for x in all_t if x["market"] == inst and x["poc_pos"] == pos and kind in x["hyp"]]
                if not sub:
                    continue
                wins = sum(1 for x in sub if x["gross_$"] > 0)
                expL = sum(x["net_NT-Lifetime_$"] for x in sub) / len(sub)
                L.append(f"- {pos}/{kind}: N={len(sub)} hit={100.0*wins/len(sub):.1f}% expL={expL:.2f}$")
        L.append("")
    # Fraicheur
    L.append("### H6 — Fraicheur (fwd=jours depuis creation zone)")
    for inst in ("NQ", "ES"):
        L.append(f"#### {inst}")
        for fwd in range(1, HOLD_ZONE + 1):
            sub = [x for x in all_t if x["market"] == inst and x["fresh"] == fwd and "fade" in x["hyp"]]
            if not sub:
                continue
            wins = sum(1 for x in sub if x["gross_$"] > 0)
            expL = sum(x["net_NT-Lifetime_$"] for x in sub) / len(sub)
            L.append(f"- fwd={fwd} fade: N={len(sub)} hit={100.0*wins/len(sub):.1f}% expL={expL:.2f}$")
        L.append("")
    with open(os.path.join(OUTDIR, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"TRADES={len(all_t)} cut={cut}")
    print(f"NQ={sum(1 for x in all_t if x['market']=='NQ')} ES={sum(1 for x in all_t if x['market']=='ES')}")


if __name__ == "__main__":
    main()
