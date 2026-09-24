# Backtest S2 — Impulsion zone: 3 profils ETH, composite J1+J2, accept J3, exec RTH Paris
# Spec verrouillee: balance=POC2 dans VA1 ; composite=addition tick-a-tick 70% ; valide close J3 ETH ;
# exec RTH 15h30-21h Paris DST ; primaire 1H-2closes fade + daily continuation ; secondaire 5m/1H-1c ;
# bon cote: reoffer short VAHc/POCc, rebid long VALc ; HOLD 5 vs 20, buckets 1-5/6-10/11-20, priorite plus fraiche.
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
from backtest_vp02 import load_market, profile_70
from backtest_swing_v03 import (rth_paris_bars, resample, find_signal, first_touch,
                                TICK, PTVAL, COST_RT, CONS_RT, BUF, POKE_T, ATR_N,
                                SWING_K, MIN_RTH_BARS)

OUTDIR = "donnees/backtest/swingS2"
MIN_ETH_BARS = 800
HOLD_MAX = 20


def build_frames(inst):
    daily_all, fb = load_market(inst)
    # ETH: toutes barres du jour calendaire Chicago
    eth = {}
    for d in sorted(daily_all):
        bars = sorted(daily_all[d][1])
        if len(bars) >= MIN_ETH_BARS:
            eth[d] = bars
    eth_days = sorted(eth)
    eth_prof = {d: profile_70(eth[d]) for d in eth_days}
    # RTH Paris
    rth1 = {}
    for d in sorted(daily_all):
        rb = rth_paris_bars(sorted(daily_all[d][1]), d)
        if len(rb) >= MIN_RTH_BARS:
            rth1[d] = rb
    rth_days = sorted(rth1)
    rth_ohlc = {d: {"o": rth1[d][0][1], "h": max(b[2] for b in rth1[d]),
                    "l": min(b[3] for b in rth1[d]), "c": rth1[d][-1][4]} for d in rth_days}
    rth_prof = {d: profile_70(rth1[d]) for d in rth_days}
    # ATR RTH
    atr, prev_c, trs = {}, None, []
    for d in rth_days:
        o = rth_ohlc[d]
        tr = (o["h"] - o["l"]) if prev_c is None else max(o["h"] - o["l"], abs(o["h"] - prev_c), abs(o["l"] - prev_c))
        trs.append(tr)
        if len(trs) > ATR_N:
            atr[d] = sum(trs[-ATR_N - 1:-1]) / ATR_N
        prev_c = o["c"]
    return eth_days, eth, eth_prof, rth_days, rth1, rth_ohlc, rth_prof, atr, fb


def detect_zones(eth_days, eth, eth_prof):
    zones = []
    for i in range(2, len(eth_days)):
        j1, j2, j3 = eth_days[i - 2], eth_days[i - 1], eth_days[i]
        p1, p2, p3 = eth_prof.get(j1), eth_prof.get(j2), eth_prof.get(j3)
        if not (p1 and p2 and p3):
            continue
        if not (p1["val"] <= p3["poc"] or True):
            pass
        balance = (p1["val"] <= p2["poc"] <= p1["vah"])
        if not balance:
            continue
        comp_bars = eth[j1] + eth[j2]
        pc = profile_70(comp_bars)
        if not pc:
            continue
        if p3["poc"] > p1["poc"] and p3["poc"] > p2["poc"] and p3["poc"] > pc["vah"] + BUF * TICK:
            zones.append({"creation": j3, "ztype": "rebid", "vah": pc["vah"], "val": pc["val"],
                          "poc": pc["poc"], "j1": j1, "j2": j2, "poc3": p3["poc"]})
        elif p3["poc"] < p1["poc"] and p3["poc"] < p2["poc"] and p3["poc"] < pc["val"] - BUF * TICK:
            zones.append({"creation": j3, "ztype": "reoffer", "vah": pc["vah"], "val": pc["val"],
                          "poc": pc["poc"], "j1": j1, "j2": j2, "poc3": p3["poc"]})
    return zones


def mk(inst, d, hyp, dr, en, px, res, ib, info):
    gross_pts = dr * (px - en)
    gross = gross_pts * PTVAL[inst]
    row = {"market": inst, "date": str(d), "hyp": hyp, "dir": dr, "entry": round(en, 2),
           "exit": round(px, 2), "res": res, "bars": ib, "zone_type": info["ztype"],
           "zone_creation": str(info["creation"]), "lvl": info["lvl_name"],
           "lvl_px": round(info["lvl_px"], 2), "ut": info["ut"], "kind": info["kind"],
           "target": info["tname"], "fresh": info["fwd"], "hold": info["hold"],
           "is_freshest": info["is_freshest"], "n_actives": info["n_actives"],
           "good_side": info["good_side"], "ut_scope": info["ut_scope"],
           "poc_rth": round(info["poc_rth"], 2), "poc_pos": info["poc_pos"],
           "dist_atr": round(info["dist_atr"], 2),
           "gross_pts": round(gross_pts, 2), "gross_$": round(gross, 2)}
    for plan, c in COST_RT.items():
        cc = CONS_RT[inst] if plan == "Conservateur-2ticks" else c
        row[f"net_{plan}_$"] = round(gross - cc, 2)
    return row


def run_market(inst):
    eth_days, eth, eth_prof, rth_days, rth1, ro, rp, atr, fb = build_frames(inst)
    zones = detect_zones(eth_days, eth, eth_prof)
    rth_idx = {d: i for i, d in enumerate(rth_days)}
    trades = []
    for z in zones:
        zc = {"ztype": z["ztype"], "creation": z["creation"], "vah": z["vah"], "val": z["val"], "poc": z["poc"]}
        width = zc["vah"] - zc["val"]
        bias = -1 if z["ztype"] == "reoffer" else 1  # reoffer->short tests (bias=1 resistance), rebid->long (bias=-1)
        tbias = 1 if z["ztype"] == "reoffer" else -1
        # jours RTH posterieurs a creation
        for fwd in range(1, HOLD_MAX + 1):
            # trouver le fwd-ieme jour RTH > creation
            later = [d for d in rth_days if d > z["creation"]]
            if fwd > len(later):
                break
            fd = later[fwd - 1]
            if fd not in atr or rp.get(fd) is None:
                continue
            a = atr[fd]
            Pr = rp[fd]
            hold = "HOLD5" if fwd <= 5 else ("HOLD6-10" if fwd <= 10 else "HOLD11-20")
            # actives ce jour en distance RTH (pas calendaire) : fwd_zz = nb jours RTH (creation, fd]
            actives = []
            for zz in zones:
                if not (zz["creation"] < fd):
                    continue
                fwd_zz = sum(1 for d in rth_days if zz["creation"] < d <= fd)
                if 1 <= fwd_zz <= HOLD_MAX:
                    actives.append(zz)
            # is_freshest: cette zone est-elle la plus recente parmi actives ?
            is_fresh = 1 if z["creation"] == max(zz["creation"] for zz in actives) else 0
            n_act = len(actives)
            r5 = resample(rth1[fd], 5)
            r60 = resample(rth1[fd], 60)
            levels = (("VAH", zc["vah"]), ("POC", zc["poc"]), ("VAL", zc["val"]))
            for (lname, lpx) in levels:
                good = 1 if ((z["ztype"] == "reoffer" and lname in ("VAH", "POC")) or (z["ztype"] == "rebid" and lname == "VAL")) else 0
                # --- 1H 2 closes (primaire) ---
                sig = find_signal(r60, lpx, tbias, 2, 3, max(width, a))
                if sig:
                    kind, ie, ext = sig
                    en = r60[ie][4]
                    await_emit(trades, inst, fd, z, zc, lname, lpx, width, a, "1h2", "primary", kind, ie, ext, en, r60, fwd, hold, is_fresh, n_act, good, Pr)
                # --- 1H 1 close (secondaire) ---
                sig1 = find_signal(r60, lpx, tbias, 1, 3, max(width, a))
                if sig1 and (sig is None or sig1[0] != sig[0] or sig1[1] != sig[1]):
                    kind, ie, ext = sig1
                    en = r60[ie][4]
                    await_emit(trades, inst, fd, z, zc, lname, lpx, width, a, "1h1", "secondary", kind, ie, ext, en, r60, fwd, hold, is_fresh, n_act, good, Pr)
                # --- 5m 2 closes (secondaire) ---
                sig5 = find_signal(r5, lpx, tbias, 2, 5, max(width, a))
                if sig5:
                    kind, ie, ext = sig5
                    en = r5[ie][4]
                    await_emit(trades, inst, fd, z, zc, lname, lpx, width, a, "5m", "secondary", kind, ie, ext, en, r5, fwd, hold, is_fresh, n_act, good, Pr)
            # --- daily continuation/rejet (primaire) ---
            o = ro[fd]
            di = rth_idx[fd]
            if lname_daily_ok(z, o):
                # accept up/down
                if o["c"] > zc["vah"] + BUF * TICK:
                    emit_daily(trades, inst, fd, z, zc, a, 1, o, rth_days, ro, di, fwd, hold, is_fresh, n_act, Pr, "accept")
                elif o["c"] < zc["val"] - BUF * TICK:
                    emit_daily(trades, inst, fd, z, zc, a, -1, o, rth_days, ro, di, fwd, hold, is_fresh, n_act, Pr, "accept")
                elif zc["val"] <= o["c"] <= zc["vah"] and ((o["h"] >= zc["vah"] + POKE_T * TICK) or (o["l"] <= zc["val"] - POKE_T * TICK)):
                    emit_daily(trades, inst, fd, z, zc, a, 0, o, rth_days, ro, di, fwd, hold, is_fresh, n_act, Pr, "rejet")
    cov = {"n_eth": len(eth_days), "n_rth": len(rth_days), "n_zones": len(zones),
           "first": str(rth_days[0]) if rth_days else "-", "last": str(rth_days[-1]) if rth_days else "-"}
    return trades, cov, zones


def lname_daily_ok(z, o):
    return True


def base_info(z, zc, lname, lpx, ut, ut_scope, kind_raw, fwd, hold, is_fresh, n_act, good, Pr, a, en):
    kind = "rejet" if kind_raw == "fade" else "accept"
    poc = Pr["poc"] if Pr else lpx
    poc_pos = "above" if en > poc + BUF * TICK else ("below" if en < poc - BUF * TICK else "inside")
    return {"ztype": z["ztype"], "creation": z["creation"], "lvl_name": lname, "lvl_px": lpx,
            "ut": ut, "kind": kind, "fwd": fwd, "hold": hold, "is_freshest": is_fresh,
            "n_actives": n_act, "good_side": good, "ut_scope": ut_scope,
            "poc_rth": poc, "poc_pos": poc_pos, "dist_atr": abs(lpx - poc) / max(a, TICK)}


def await_emit(trades, inst, fd, z, zc, lname, lpx, width, a, ut, scope, kind_raw, ie, ext, en, bars, fwd, hold, is_fresh, n_act, good, Pr):
    info0 = base_info(z, zc, lname, lpx, ut, scope, kind_raw, fwd, hold, is_fresh, n_act, good, Pr, a, en)
    if info0["kind"] == "rejet":
        dr = -1 if z["ztype"] == "reoffer" else 1
        stp = ext + BUF * TICK if dr == -1 else ext - BUF * TICK
        tgts = [("T1-poc", zc["poc"]), ("T2-w05", en + dr * 0.5 * max(width, TICK)),
                ("T3-bord", zc["val"] if dr == -1 else zc["vah"])]
    else:
        dr = 1 if z["ztype"] == "reoffer" else -1
        # accept intraday: suivi dans le sens du break du niveau (haut->long, bas->short)
        # ici break de VAH->long, break de VAL->short, break POC->sens zone inverse? on prend sens du close: au-dela => continuation
        dr = 1 if en > lpx else -1
        stp = lpx - BUF * TICK if dr == 1 else lpx + BUF * TICK
        tgts = [("T1-a05", en + dr * 0.5 * max(width, a)), ("T2-a10", en + dr * 1.0 * max(width, a)),
                ("T3-a15", en + dr * 1.5 * max(width, a))]
    for (tname, tgt) in tgts:
        res, i1 = first_touch(bars, ie, tgt, stp, dr)
        px = tgt if res == "target" else (stp if res == "stop" else bars[-1][4])
        info = dict(info0)
        info["tname"] = tname
        hyp = f"S2-{z['ztype']}-{lname}-{ut}-{info['kind']}-{tname.split('-')[0]}"
        trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, info))


def emit_daily(trades, inst, fd, z, zc, a, direction, o, rth_days, ro, di, fwd, hold, is_fresh, n_act, Pr, kind):
    en = o["c"]
    poc = Pr["poc"] if Pr else en
    poc_pos = "above" if en > poc + BUF * TICK else ("below" if en < poc - BUF * TICK else "inside")
    fwd_daily = []
    for k in range(di + 1, min(di + 6, len(rth_days))):
        dd = rth_days[k]
        fwd_daily.append((0, ro[dd]["o"], ro[dd]["h"], ro[dd]["l"], ro[dd]["c"], 0))
    if not fwd_daily:
        return
    if kind == "accept":
        dr = direction
        stp = zc["vah"] - BUF * TICK if dr == 1 else zc["val"] + BUF * TICK
        tgts = [(f"T{i}-atr{m}", en + dr * m * a) for i, m in ((1, 0.5), (2, 1.0), (3, 1.5))]
    else:
        # rejet daily: fade vers POCc
        poked_up = o["h"] >= zc["vah"] + POKE_T * TICK
        dr = -1 if poked_up else 1
        stp = o["h"] + BUF * TICK if dr == -1 else o["l"] - BUF * TICK
        tgts = [("T1-poc", zc["poc"]), ("T2-w05", en + dr * 0.5 * max(zc["vah"] - zc["val"], TICK)),
                ("T3-bord", zc["val"] if dr == -1 else zc["vah"])]
    for (tname, tgt) in tgts:
        res, i1 = first_touch(fwd_daily, 0, tgt, stp, dr)
        px = tgt if res == "target" else (stp if res == "stop" else fwd_daily[-1][4])
        info = {"ztype": z["ztype"], "creation": z["creation"], "lvl_name": "ZONE", "lvl_px": zc["vah"] if dr == -1 else zc["val"],
                "ut": "daily", "kind": kind, "tname": tname, "fwd": fwd, "hold": hold,
                "is_freshest": is_fresh, "n_actives": n_act, "good_side": 1, "ut_scope": "primary",
                "poc_rth": poc, "poc_pos": poc_pos, "dist_atr": abs(en - poc) / max(a, TICK)}
        hyp = f"S2-{z['ztype']}-ZONE-daily-{kind}-{tname.split('-')[0]}"
        trades.append(mk(inst, fd, hyp, dr, en, px, res, i1, info))


def summarize(trades):
    import statistics as st
    lines = []
    groups = sorted(set((x["ut"], x["kind"]) for x in trades))
    lines.append("| groupe | N | hit% | expL-$ | PF |")
    lines.append("| --- | --- | --- | --- | --- |")
    for (ut, kind) in groups:
        t = [x for x in trades if x["ut"] == ut and x["kind"] == kind]
        wins = [x for x in t if x["gross_$"] > 0]
        hit = 100.0 * len(wins) / len(t) if t else 0
        expL = sum(x["net_NT-Lifetime_$"] for x in t) / len(t) if t else 0
        gp = sum(x["gross_$"] for x in wins)
        gl = -sum(x["gross_$"] for x in t if x["gross_$"] <= 0)
        pf = (gp / gl) if gl > 0 else float("inf")
        lines.append(f"| {ut}/{kind} | {len(t)} | {hit:.1f} | {expL:.2f} | {pf:.2f} |")
    return "\n".join(lines)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    all_t, reps, zones_all = [], [], {}
    for inst in ("NQ", "ES"):
        t, cov, zones = run_market(inst)
        all_t += t
        zones_all[inst] = zones
        reps.append(f"## {inst} — ETH {cov['n_eth']}j / RTH {cov['n_rth']}j ({cov['first']}->{cov['last']}), zones={cov['n_zones']}")
    all_t.sort(key=lambda x: (x["date"], x["market"], x["hyp"]))
    if all_t:
        with open(f"{OUTDIR}/trades_s2.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_t[0].keys()))
            w.writeheader()
            w.writerows(all_t)
        cut = all_t[len(all_t) * 7 // 10]["date"]
    else:
        cut = "-"
    L = ["# Backtest S2 — Impulsion zone (3 ETH, composite J1+J2, exec RTH Paris)",
         "_Balance=POC2 dans VA1. Composite=addition tick-a-tick 70%. Accept J3: POC3 au-dela POC1,POC2 et VAHc/VALc+2t. "
         "Zone valide close J3 ETH. Exec RTH 15h30-21h Paris DST. Primaire 1H-2c fade + daily continuation 0.5/1/1.5 ATR 5j. "
         "Secondaire 5m/1H-1c. Bon cote: reoffer short VAHc/POCc, rebid long VALc. Stop ext+2t/niveau. Couts Lifetime 4.36._", ""]
    L += reps + [""]
    prim = [x for x in all_t if x["ut_scope"] == "primary" and int(x["good_side"]) == 1 and int(x["is_freshest"]) == 1]
    L.append(f"### Scope primaire (1H2+daily, bon cote, plus fraiche) N={len(prim)}")
    for inst in ("NQ", "ES"):
        sub = [x for x in prim if x["market"] == inst]
        L.append(f"#### {inst} N={len(sub)}")
        L.append(summarize(sub) if sub else "_vide_")
    L.append("")
    L.append("### HOLD5 vs HOLD20 (primaire, bon cote, freshest)")
    for h in ("HOLD5", "HOLD6-10", "HOLD11-20"):
        sub = [x for x in prim if x["hold"] == h]
        if not sub:
            continue
        wins = sum(1 for x in sub if x["gross_$"] > 0)
        expL = sum(x["net_NT-Lifetime_$"] for x in sub) / len(sub)
        L.append(f"- {h}: N={len(sub)} hit={100.0*wins/len(sub):.1f}% expL={expL:.2f}$")
    L.append("")
    for title, t in ((f"Complet N={len(all_t)}", all_t),):
        L.append(f"### {title}")
        for inst in ("NQ", "ES"):
            sub = [x for x in t if x["market"] == inst]
            L.append(f"#### {inst} N={len(sub)}")
            L.append(summarize(sub) if sub else "_vide_")
    open(f"{OUTDIR}/summary_s2.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    prim5 = [x for x in prim if x["hold"] == "HOLD5"]
    prim20 = [x for x in prim if x["hold"] in ("HOLD6-10", "HOLD11-20")]
    print(f"S2 TRADES={len(all_t)} PRIM={len(prim)} PRIM5={len(prim5)} PRIM6-20={len(prim20)} cut={cut}")


if __name__ == "__main__":
    main()
