"""Applique le biais directionnel du regime aux trades backtestes (exclusion + rapport).

Pour chaque trade (market, date, dir) : config du jour = dernier event STRICTEMENT
avant le jour du trade (anti-lookahead : un CPI 8h30 ne filtre pas un trade 8h31
le meme jour). Biais par config (cf. bilan/REGIME_MACRO.md §5) :
  R/down, R/flat -> LONG (shorts exclus) | R/up, N/*, A/down -> NEUTRE (gardes)
  A/up, A/flat  -> SHORT (longs exclus, VETO en A/up)

Sorties par fichier d'entree :
  <nom>_regime.csv (colonnes d'origine + regime_config, regime_biais, regime_decision)
  rapport console + --report FILE.md (avant/apres : N, winrate, PF, expectancy, P&L)

Colonne P&L auto-detectee (priorite : conservateur > net > gross_$ > profit/pnl),
sens normalise (1/-1, long/short, L/S, B/S), dates multi-formats, delimiteur auto.

Lancer avec le venv du projet :
  .\\venv\\Scripts\\python.exe scripts/apply_regime_filter.py <trades1.csv> [<trades2.csv> ...] [--report rapport.md]
"""
import argparse
import csv
import glob
import os
import re
import sys
from statistics import mean

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIME = os.path.join(BASE, "donnees", "regime")

BIAS = {"R/down": "LONG", "R/flat": "LONG", "R/up": "NEUTRE", "N/down": "NEUTRE",
        "N/up": "NEUTRE", "N/flat": "NEUTRE", "A/down": "NEUTRE",
        "A/up": "SHORT", "A/flat": "SHORT"}


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def detect_pnl(fieldnames):
    norm = {norm_key(f): f for f in fieldnames}
    for cand in ("conservateur",):
        for k, f in norm.items():
            if cand in k:
                return f
    for k, f in norm.items():
        if k.startswith("net"):
            return f
    for exact in ("gross$", "gross", "profit", "pnl", "netprofit"):
        if exact in norm:
            return norm[exact]
    for k, f in norm.items():
        if "profit" in k or k == "pnl":
            return f
    return None


def norm_dir(v):
    s = str(v or "").strip().lower()
    if s in ("1", "long", "l", "buy", "b"):
        return 1
    if s in ("-1", "short", "s", "sell"):
        return -1
    try:
        return 1 if float(s) > 0 else -1
    except ValueError:
        return None


def norm_date(v):
    s = str(v or "").strip()[:10]
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (2022 <= int(y) <= 2026):
            return None
        return f"{y}-{b:02d}-{a:02d}" if a > 12 else f"{y}-{a:02d}-{b:02d}"
    return None


def norm_inst(v):
    s = str(v or "").strip().upper()
    if s.startswith("NQ") or s.startswith("MNQ"):
        return "NQ"
    if s.startswith("ES") or s.startswith("MES"):
        return "ES"
    return None


def read_trades(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;") if sample.strip() else csv.excel
        rows = list(csv.DictReader(fh, dialect=dialect))
    return rows


def load_configs():
    p = os.path.join(REGIME, "stance_index_fwd.csv")
    cfg = {}
    with open(p, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cfg.setdefault(r["date"], r["config"])
    return cfg


def metrics(pnls):
    n = len(pnls)
    if n == 0:
        return {"n": 0, "wr": None, "pf": None, "exp": None, "tot": 0.0}
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    gp, gl = sum(wins), sum(losses)
    return {"n": n, "wr": len(wins) / n,
            "pf": (gp / gl) if gl else float("inf"),
            "exp": mean(pnls), "tot": sum(pnls)}


def fmtm(m, unit=""):
    if m["n"] == 0:
        return "N=0"
    pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
    return (f"N={m['n']} WR={m['wr']:.0%} PF={pf} "
            f"exp={m['exp']:+.2f}{unit} tot={m['tot']:+.2f}{unit}")


def process(path, configs):
    rows = read_trades(path)
    if not rows:
        return [f"## {path} : fichier vide ou illisible"], []
    fn = {norm_key(k): k for k in rows[0].keys()}
    c_date = next((fn[k] for k in ("date", "tradedate", "day") if k in fn), None)
    if c_date is None:  # repli : colonnes temporelles (entrytime, signaltime...)
        c_date = next((fn[k] for k in fn if "time" in k), None)
    c_dir = next((fn[k] for k in fn if k in ("dir", "direction", "side", "sens", "marketpos",
                                            "position", "marketposition")), None)
    c_inst = next((fn[k] for k in fn if k in ("market", "instrument", "symbol")), None)
    pnl_col = detect_pnl(list(rows[0].keys()))
    if None in (c_date, c_dir, pnl_col):
        return ([f"## {path} : colonnes introuvables "
                 f"(date={c_date}, dir={c_dir}, pnl={pnl_col}, cols={list(rows[0].keys())[:8]})"], [])
    days = sorted(configs)
    out, skipped = [], {"date": 0, "dir": 0, "pnl": 0, "inst": 0, "sans_config": 0}
    for r in rows:
        d = norm_date(r[c_date])
        s = norm_dir(r[c_dir])
        try:
            p = float(str(r[pnl_col]).replace(",", "."))
        except ValueError:
            p = None
        inst = norm_inst(r[c_inst]) if c_inst else "?"
        if d is None:
            skipped["date"] += 1
            continue
        if s is None:
            skipped["dir"] += 1
            continue
        if p is None:
            skipped["pnl"] += 1
            continue
        # l'instrument ne sert pas a la decision (config = date) : "?" si absent
        ref = next((x for x in reversed(days) if x < d), None)
        if ref is None:
            skipped["sans_config"] += 1
            continue
        cfg = configs[ref]
        biais = BIAS.get(cfg, "NEUTRE")
        exclu = (biais == "LONG" and s < 0) or (biais == "SHORT" and s > 0)
        nr = dict(r)
        nr.update({"regime_config": cfg, "regime_biais": biais,
                   "regime_decision": "exclu" if exclu else "garde"})
        out.append((nr, p, exclu))
    if not out:
        return [f"## {path} : aucun trade exploitable (skipped={skipped})"], []
    outp = os.path.splitext(path)[0] + "_regime.csv"
    with open(outp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0][0].keys()))
        w.writeheader()
        w.writerows([r for r, _, _ in out])
    allp = [p for _, p, _ in out]
    kept = [p for _, p, e in out if not e]
    excl = [p for _, p, e in out if e]
    unit = " ($)" if "$" in pnl_col else (" (ticks)" if "tick" in pnl_col.lower() else "")
    lines = [f"## {os.path.basename(path)} -> {os.path.basename(outp)}",
             f"- P&L utilise : `{pnl_col}` | config = dernier event < jour du trade",
             f"- AVANT : {fmtm(metrics(allp), unit)}",
             f"- APRES (gardes) : {fmtm(metrics(kept), unit)}",
             f"- EXCLUS : {fmtm(metrics(excl), unit)}",
             f"- gardes: {len(kept)}/{len(out)} ({len(kept) / len(out):.0%}) "
               f"| skipped parsing: {skipped}"]
    return lines, out


def main(argv=None):
    p = argparse.ArgumentParser(description="Filtre directionnel du regime sur trades backtestes.")
    p.add_argument("trades", nargs="+", help="fichiers trades.csv (wildcards acceptes)")
    p.add_argument("--report", default=None, help="fichier .md de synthese (append)")
    a = p.parse_args(argv)
    paths = []
    for pat in a.trades:
        paths.extend(glob.glob(pat) if any(c in pat for c in "*?") else [pat])
    paths = [x for x in paths if os.path.exists(x)]
    if not paths:
        sys.exit("aucun fichier trouve.")
    configs = load_configs()
    report = ["# Filtre regime sur backtests", ""]
    for path in paths:
        lines, _ = process(path, configs)
        report.extend(lines + [""])
        print("\n".join(lines) + "\n")
    if a.report:
        with open(a.report, "a", encoding="utf-8") as fh:
            fh.write("\n".join(report) + "\n")
        print(f"rapport ajoute a {a.report}")


if __name__ == "__main__":
    main()
