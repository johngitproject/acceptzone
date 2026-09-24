# Backtest Module 02 Volume Profile (Nick4aTick) — NQ + ES, donnees NT8 2025
# Usage perso. Stdlib uniquement.
# Hypotheses H1 (rotation), H2/H2b (fade VAH/VAL -> POC), H3 (acceptance + miroir), H4 (POC aimant).
import csv, os
from collections import defaultdict
from datetime import date

MARKET = "donnees/market"
OUTDIR = "donnees/backtest/vp02"
TICK = 0.25
PTVAL = {"NQ": 20.0, "ES": 50.0}          # $ par point / contrat
COST_RT = {                                # couts aller-retour / contrat ($)
    "NT-Lifetime": 4.36, "NT-Monthly": 5.16, "NT-Free": 5.76,
    "Conservateur-2ticks": None,           # rempli par marche : NQ=10, ES=25
}
CONS_RT = {"NQ": 10.0, "ES": 25.0}
ORDER = ["H", "M", "U", "Z"]
NEXT = {"H": "M", "M": "U", "U": "Z", "Z": "H"}
ROLL_LEAD_DAYS = 8                         # bascule J-8 calendaires avant echeance
MIN_RTH_BARS = 300
BUF = 2                                    # buffer stop/poke en ticks
ACC_N = 5                                  # closes consecutives pour acceptance
POKE_T = 2                                 # profondeur mèche en ticks

from datetime import timedelta

def third_friday(year, month):
    d = date(year, month, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)

def expiry_for(year, letter):
    return third_friday(year, {"H": 3, "M": 6, "U": 9, "Z": 12}[letter])

def roll_date_for(year, letter):
    return expiry_for(year, letter) - timedelta(days=ROLL_LEAD_DAYS)

# Compat : memes noms qu'avant, annee 2025 (le run vp02 d'origine est inchange)
def roll_date(letter):
    return roll_date_for(2025, letter)

EXPIRY = {L: expiry_for(2025, L) for L in ORDER}
ROLLS = [(roll_date(L), L) for L in ORDER]  # conserve pour compatibilite

def parse_file(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            p = line.split(";")
            if len(p) != 6:
                continue
            try:
                dt, o, h, l, c, v = p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
                d = date(int(dt[0:4]), int(dt[4:6]), int(dt[6:8]))
                t = int(dt[9:11]) * 3600 + int(dt[11:13]) * 60 + int(dt[13:15])
                rows.append((d, t, o, h, l, c, v))
            except ValueError:
                continue
    return rows

def contract_of(fname):
    # "NQ 03-25.Last.txt" -> ("NQ", "H") ; "ES 12-25" -> ("ES","Z")
    base = os.path.basename(fname)
    inst = "NQ" if base.startswith("NQ") else "ES"
    mm = base.split(" ")[1].split("-")[0]
    return inst, {"03": "H", "06": "M", "09": "U", "12": "Z"}[mm]

def active_contract(day):
    # Multi-annees : a chaque roll (J-8 echeance) on passe au contrat suivant.
    # Avant le 1er roll pertinent : H. Apres le roll Z : H (annee+1, repli sinon).
    Y = day.year
    seq = [(roll_date_for(Y - 1, "Z"), "Z")] + [(roll_date_for(Y, L), L) for L in ORDER]
    cur = "H"
    for (r, L) in sorted(seq):
        if r <= day:
            cur = NEXT[L]
        else:
            break
    return cur

def file_year(fname):
    # "NQ 03-24.Last.txt" -> "24"
    return os.path.basename(fname).split(" ")[1].split("-")[1].split(".")[0]

def load_market(inst, years=None):
    # jour -> (contrat, [bars]) ; bar = (t,o,h,l,c,v)
    # years : ex. {"24","25"} pour restreindre (None = tout, comportement d'origine)
    per = defaultdict(lambda: defaultdict(list))
    files = [os.path.join(MARKET, f) for f in os.listdir(MARKET)
             if f.startswith(inst + " ") and f.endswith(".txt")
             and (years is None or file_year(f) in years)]
    for fp in files:
        _, letter = contract_of(fp)
        for (d, t, o, h, l, c, v) in parse_file(fp):
            per[d][letter].append((t, o, h, l, c, v))
    # serie continue : un contrat par jour
    daily, log = {}, []
    for d in sorted(per):
        want = active_contract(d)
        avail = sorted(per[d], key=ORDER.index)
        if want in per[d]:
            daily[d] = (want, sorted(per[d][want]))
        elif avail:
            daily[d] = (avail[0], sorted(per[d][avail[0]]))
            log.append(f"{inst} {d}: contrat voulu {want} absent, repli {avail[0]}")
        else:
            continue
    return daily, log

def rth_bars(bars):
    return [b for b in bars if 8 * 3600 + 30 * 60 < b[0] <= 15 * 3600]

def profile_70(bars):
    # volume par prix (ticks), distribution uniforme intra-barre
    vol = defaultdict(float)
    for (t, o, h, l, c, v) in bars:
        lo = int(round(l / TICK))
        hi = int(round(h / TICK))
        n = max(1, hi - lo + 1)
        q = v / n
        for k in range(lo, hi + 1):
            vol[k] += q
    if not vol:
        return None
    tot = sum(vol.values())
    poc = max(vol, key=lambda k: (vol[k], -abs(k)))
    lo = hi = poc
    acc = vol[poc]
    keys = sorted(vol)
    while acc < 0.70 * tot:
        up = vol[hi + 1] if hi + 1 <= keys[-1] else -1
        dn = vol[lo - 1] if lo - 1 >= keys[0] else -1
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi += 1
            acc += vol.get(hi, 0.0)
        else:
            lo -= 1
            acc += vol.get(lo, 0.0)
    return {"poc": poc * TICK, "vah": hi * TICK, "val": lo * TICK, "tot": tot}

def first_touch(bars, start, target, stop, direction):
    # direction +1 long (target>entry>stop), -1 short. regle conservatrice : stop gagne ex-aequo.
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
    _, _, _, _, c, _ = bars[-1]
    return "eod", len(bars) - 1

def run_market(inst, years=frozenset({"25"})):
    # years fige a {"25"} : le run vp02 de reference reste inchange meme si
    # d'autres millesimes sont deposes. run_vp2425 passe years={"24","25"}.
    daily, log = load_market(inst, years=years)
    days = sorted(d for d, (ct, b) in daily.items() if len(rth_bars(b)) >= MIN_RTH_BARS)
    rth = {d: rth_bars(daily[d][1]) for d in days}
    prof = {d: profile_70(rth[d]) for d in days}
    trades = []
    cov = {"n_days": len(days, ), "first": str(days[0]) if days else "-", "last": str(days[-1]) if days else "-",
           "contracts_used": sorted(set(daily[d][0] for d in days)), "fallbacks": log}
    for k in range(1, len(days)):
        d, dp = days[k], days[k - 1]
        P = prof[dp]
        if not P:
            continue
        bars = rth[d]
        o = bars[0][1]
        vah, val, poc = P["vah"], P["val"], P["poc"]
        mid = (vah + val) / 2
        # ---- H1 rotation ----
        if val + BUF * TICK < o < vah - BUF * TICK:
            if o <= mid:
                tgt, stp, dr = vah, val - BUF * TICK, 1
            else:
                tgt, stp, dr = val, vah + BUF * TICK, -1
            res, i = first_touch(bars, 0, tgt, stp, dr)
            px = tgt if res == "target" else (stp if res == "stop" else bars[-1][4])
            trades.append(mk(inst, d, "H1", dr, o, px, res, i, P))
        # ---- H2 fade VAH ----
        sig = find_poke(bars, vah, +1)
        if sig:
            i0, pkh = sig
            res, i1, px = fade_after(bars, i0, vah, poc, +1, pkh)
            trades.append(mk(inst, d, "H2", -1, bars[i0][4], px, res, i1, P, note=f"poke_hi={pkh}"))
        # ---- H2b fade VAL ----
        sig = find_poke(bars, val, -1)
        if sig:
            i0, pkl = sig
            res, i1, px = fade_after(bars, i0, val, poc, -1, pkl)
            trades.append(mk(inst, d, "H2b", +1, bars[i0][4], px, res, i1, P, note=f"poke_lo={pkl}"))
        # ---- H3 acceptance VAH + miroir ----
        for lvl, dr in ((vah, +1), (val, -1)):
            e = find_accept(bars, lvl, dr)
            if e is not None:
                en = bars[e][4]
                width = vah - val
                stp = (lvl - BUF * TICK) if dr == 1 else (lvl + BUF * TICK)
                tgt = en + dr * 0.5 * width
                res, i1 = first_touch(bars, e, tgt, stp, dr)
                px = tgt if res == "target" else (stp if res == "stop" else bars[-1][4])
                mfe30 = mfe(bars, e, en, dr, 30)
                mfe60 = mfe(bars, e, en, dr, 60)
                trades.append(mk(inst, d, "H3" if dr == 1 else "H3b", dr, en, px, res, i1, P,
                                 note=f"mfe30={mfe30:.2f} mfe60={mfe60:.2f}"))
    return trades, cov

def find_poke(bars, lvl, dr):
    # premier poke >= lvl+POKE_T* tick puis close back inside sous 5 barres. retour (i_entry, extreme)
    for i in range(len(bars)):
        _, _, h, l, c, _ = bars[i]
        if (dr == 1 and h >= lvl + POKE_T * TICK) or (dr == -1 and l <= lvl - POKE_T * TICK):
            ext = h if dr == 1 else l
            for j in range(i, min(i + 5, len(bars))):
                _, _, h2, l2, c2, _ = bars[j]
                ext = max(ext, h2) if dr == 1 else min(ext, l2)
                if (dr == 1 and c2 < lvl) or (dr == -1 and c2 > lvl):
                    return j, ext
            return None
    return None

def fade_after(bars, i0, lvl, poc, dr, ext):
    # dr=+1 : contexte rejet VAH -> on vend (entree short gere par appelant) ; ici calcule sortie vers poc
    en = bars[i0][4]
    if dr == 1:   # short VAH->POC
        stp, tgt = ext + BUF * TICK, poc
        res, i1 = first_touch(bars, i0, tgt, stp, -1)
    else:         # long VAL->POC
        stp, tgt = ext - BUF * TICK, poc
        res, i1 = first_touch(bars, i0, tgt, stp, +1)
    px = tgt if res == "target" else (stp if res == "stop" else bars[-1][4])
    return res, i1, px

def find_accept(bars, lvl, dr):
    run = 0
    for i in range(len(bars)):
        c = bars[i][4]
        if (dr == 1 and c > lvl) or (dr == -1 and c < lvl):
            run += 1
            if run >= ACC_N:
                return i
        else:
            run = 0
    return None

def mfe(bars, e, en, dr, n):
    seg = bars[e:min(e + n, len(bars))]
    if not seg:
        return 0.0
    if dr == 1:
        return max(b[2] - en for b in seg)
    return max(en - b[3] for b in seg)

def mk(inst, d, hyp, dr, en, px, res, ib, P, note=""):
    gross_pts = dr * (px - en)
    gross = gross_pts * PTVAL[inst]
    row = {"market": inst, "date": str(d), "hyp": hyp, "dir": dr,
           "entry": round(en, 2), "exit": round(px, 2), "res": res,
           "bars": ib, "pdVAH": round(P["vah"], 2), "pdVAL": round(P["val"], 2),
           "pdPOC": round(P["poc"], 2), "gross_pts": round(gross_pts, 2),
           "gross_$": round(gross, 2), "note": note}
    for plan, c in COST_RT.items():
        c = CONS_RT[inst] if (plan == "Conservateur-2ticks") else c
        row[f"net_{plan}_$"] = round(gross - c, 2)
    return row

def summarize(trades):
    import statistics as st
    lines = []
    header = ("hypothese", "N", "hit%", "exp-NT-Lifetime-$", "exp-NT-Monthly-$",
              "exp-NT-Free-$", "exp-Conserv-$", "PF-gross", "duree_med_barres")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for hyp in ["H1", "H2", "H2b", "H3", "H3b"]:
        t = [x for x in trades if x["hyp"] == hyp]
        if not t:
            lines.append(f"| {hyp} | 0 | - | - | - | - | - | - | - |")
            continue
        wins = [x for x in t if x["gross_$"] > 0]
        hit = 100.0 * len(wins) / len(t)
        exp = {k: sum(x[f"net_{k}_$"] for x in t) / len(t)
               for k in ["NT-Lifetime", "NT-Monthly", "NT-Free", "Conservateur-2ticks"]}
        gp = sum(x["gross_$"] for x in wins)
        gl = -sum(x["gross_$"] for x in t if x["gross_$"] <= 0)
        pf = (gp / gl) if gl > 0 else float("inf")
        dur = st.median(x["bars"] for x in t)
        lines.append(f"| {hyp} | {len(t)} | {hit:.1f} | {exp['NT-Lifetime']:.2f} | "
                     f"{exp['NT-Monthly']:.2f} | {exp['NT-Free']:.2f} | "
                     f"{exp['Conservateur-2ticks']:.2f} | {pf:.2f} | {dur:.0f} |")
    return "\n".join(lines)

def monthly(t, key):
    from collections import defaultdict as dd
    m = dd(list)
    for x in t:
        m[x["date"][:7]].append(x[f"net_{key}_$"])
    return {k: round(sum(v), 2) for k, v in sorted(m.items())}

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    all_t, rep = [], []
    for inst in ("NQ", "ES"):
        t, cov = run_market(inst)
        all_t += t
        rep.append(f"## {inst} — couverture: {cov['n_days']} jours RTH valides "
                   f"({cov['first']} → {cov['last']}), contrats: {', '.join(cov['contracts_used'])}")
        for fb in cov["fallbacks"][:10]:
            rep.append(f"- repli contrat: {fb}")
    # split IS/OOS chronologique 70/30
    all_t.sort(key=lambda x: (x["date"], x["market"], x["hyp"]))
    cut = all_t[len(all_t) * 7 // 10]["date"] if all_t else "-"
    IS = [x for x in all_t if x["date"] < cut]
    OOS = [x for x in all_t if x["date"] >= cut]
    with open(os.path.join(OUTDIR, "trades.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_t[0].keys()))
        w.writeheader()
        w.writerows(all_t)
    L = ["# Backtest Module 02 — Volume Profile (NQ + ES, 2025, RTH 8:30–15:00 CT)",
         "", "_Usage perso. Profils veille = RTH J−1, zone 70%, volume intra-barre uniforme "
         "(approximation declaree). Globex exclu. Rollover J−8. Cout AR/contrat: Lifetime $4.36, "
         "Monthly $5.16, Free $5.76, Conservateur NQ $10 / ES $25._", ""]
    L += rep + [""]
    for title, t in (("Échantillon complet", all_t),
                     (f"In-sample (< {cut})", IS), (f"Out-of-sample (≥ {cut})", OOS)):
        L.append(f"### {title} — N={len(t)}")
        for inst in ("NQ", "ES"):
            sub = [x for x in t if x["market"] == inst]
            L.append(f"#### {inst} (N={len(sub)})")
            L.append(summarize(sub))
            L.append("")
    L.append("### H4 — POC aimant (taux d'atteinte du POC sur H2/H2b, même session)")
    for inst in ("NQ", "ES"):
        h = [x for x in all_t if x["market"] == inst and x["hyp"] in ("H2", "H2b")]
        hit = [x for x in h if abs(x["exit"] - x["pdPOC"]) < 1e-9 and x["res"] == "target"]
        # atteinte POC même sans target-first (prix touché avant stop) : approx via res==target
        L.append(f"- {inst}: {len(hit)}/{len(h)} trades sortis au POC "
                 f"({100.0 * len(hit) / max(1, len(h)):.1f}%)")
    L.append("")
    L.append("### Nets mensuels (Lifetime, $/contrat)")
    for inst in ("NQ", "ES"):
        L.append(f"- {inst}: " + ", ".join(
            f"{k} {v:+.0f}" for k, v in monthly(
                [x for x in all_t if x["market"] == inst], "NT-Lifetime").items()))
    with open(os.path.join(OUTDIR, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"TRADES={len(all_t)} cut={cut}")
    print(f"NQ={sum(1 for x in all_t if x['market']=='NQ')} "
          f"ES={sum(1 for x in all_t if x['market']=='ES')}")

if __name__ == "__main__":
    main()
