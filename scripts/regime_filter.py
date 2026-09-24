"""Filtre de conviction : taille des setups selon le regime (stance x momentum 10Y).

Matrice calibree sur stance_index_report.md (ES/NQ 2022-2025, forwards 5/20/60j).
Multiplicateur de la taille standard. 0.0 = VETO (pas de trade dans ce sens).

LONG (avec la tendance quand R, contre-tendance quand A ; horizons intraday/5-20j en premier) :
  R/down 1.0  (ES20 +2.90% hit 89, ES60 +6.96% hit 96 : la config soft-landing)
  R/up   0.5  (tension late-cycle : ES5 -0.01% hit 46, ES60 +2.94% hit 57, moitie moins)
  R/flat 0.75 (ES20 +1.52% hit 71, ES60 +5.13% hit 88)
  N/*    0.5  (echantillon mince : N=48 j)
  A/down 0.5  (jamais observe 2022-25 : prudence mediane)
  A/up   0.0  VETO (NQ20 -2.88% hit 40, ES5 -0.38% hit 48 : la pire config court terme)
  A/flat 0.25 (ES60 med -3.13% hit 29, NQ60 med -6.61% hit 26 : bear qui saigne)
SHORT (miroir, shorts en R = contre-tendance) :
  R/down 0.25 | R/up 0.5 | R/flat 0.5 | N/* 0.5
  A/down 0.5 | A/up 1.0 | A/flat 0.75

Limites rappelees a chaque sortie : un seul cycle observe, labels = marqueurs
d'epoque, forwards chevauchants. Filtre de conviction, pas signal autonome.

Usage :
  .\\venv\\Scripts\\python.exe scripts/regime_filter.py --date AAAA-MM-JJ --sens long|short
"""
import argparse
import csv
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIME = os.path.join(BASE, "donnees", "regime")
SRC = os.path.join(REGIME, "sources")
SEUIL_MOM = 50.0  # bp (mom60 = (tnx[t]-tnx[t-60 seances])*100)

LONG = {"R/down": 1.0, "R/up": 0.5, "R/flat": 0.75,
        "N/down": 0.5, "N/up": 0.5, "N/flat": 0.5,
        "A/down": 0.5, "A/up": 0.0, "A/flat": 0.25}
SHORT = {"R/down": 0.25, "R/up": 0.5, "R/flat": 0.5,
         "N/down": 0.5, "N/up": 0.5, "N/flat": 0.5,
         "A/down": 0.5, "A/up": 1.0, "A/flat": 0.75}
WHY = {"R/down": "soft-landing : restrictif + 10Y qui baisse >50bp (ES60 +7.20% hit 99)",
       "R/up": "tension late-cycle : restrictif + 10Y qui monte >50bp (ES60 +2.02% hit 56)",
       "R/flat": "restrictif, 10Y sans direction franche (ES60 +5.15% hit 89)",
       "N/down": "neutre, echantillon mince", "N/up": "neutre, echantillon mince",
       "N/flat": "neutre, echantillon mince",
       "A/down": "jamais observe 2022-25 (10Y 60j jamais < -50bp en stance A)",
       "A/up": "pire config court terme : retard Fed + 10Y qui flambe (NQ20 -2.36% hit 40)",
       "A/flat": "bear qui saigne : ES60 med -2.76% hit 30, NQ60 med -5.52% hit 26"}


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def side(label):
    if label in ("restrictif", "nettement restrictif"):
        return "R"
    if label in ("accommodant", "nettement accommodant"):
        return "A"
    if label == "neutre":
        return "N"
    return ""


def momdir(m):
    if m is None:
        return ""
    return "up" if m > SEUIL_MOM else ("down" if m < -SEUIL_MOM else "flat")


def config_of(day):
    """Rend (config, detail) as-of : dernier event <= jour + momentum 10Y."""
    stance = sorted(load_csv(os.path.join(REGIME, "fed_stance.csv")),
                    key=lambda r: (r["date_et"], r["variant"]))
    ev_days = sorted({r["date_et"][:10] for r in stance})
    ref = next((d for d in reversed(ev_days) if d <= day), None)
    if ref is None:
        return None, "aucun etat de regime avant cette date."
    s = [r for r in stance if r["date_et"][:10] == ref][-1]
    px = {r["date"]: r for r in load_csv(os.path.join(SRC, "market_pricing_daily.csv"))
          if r.get("tnx")}
    tdays = sorted(px)
    m60 = None
    past = [d for d in tdays if d <= day]  # jour non trade : dernier pricing dispo
    if len(past) > 60:
        m60 = round((float(px[past[-1]]["tnx"]) - float(px[past[-61]]["tnx"])) * 100)
    sd, md = side(s["stance_label"]), momdir(m60)
    if not sd or not md:
        return None, f"config indescriptible (stance={s['stance_label']}, mom60={m60})."
    detail = {"event_day": ref, "stance_label": s["stance_label"],
              "real_gap_bps": s["real_gap_bps"], "mom60_bp": m60,
              "guidance": f"{s['guidance_stance']} ({s['guidance_date']})"}
    return f"{sd}/{md}", detail


def filtre(day, sens):
    cfg, detail = config_of(day)
    if cfg is None:
        return f"filtre {day} {sens} : {detail}"
    mult = (LONG if sens == "long" else SHORT)[cfg]
    verdict = "VETO - pas de trade" if mult == 0.0 else (
        f"taille x{mult:g} ({mult * 100:.0f}% du standard)")
    flip = ("passe up si mom60 > +50 bp" if detail and "down" in cfg else
            "passe down si mom60 < -50 bp" if detail and "up" in cfg else
            "direction des que mom60 sort de [-50,+50] bp")
    return (f"filtre {day} {sens} : config {cfg} [{WHY[cfg]}]\n"
            f"  stance {detail['stance_label']} (real gap {detail['real_gap_bps']} bp, "
            f"event {detail['event_day']}), mom60 10Y {detail['mom60_bp']} bp, "
            f"guidance {detail['guidance']}\n"
            f"  => {verdict}\n"
            f"  invalidation : changement de config ({flip}) ou surprise contre le sens.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Filtre de conviction par regime.")
    p.add_argument("--date", required=True)
    p.add_argument("--sens", required=True, choices=("long", "short"))
    a = p.parse_args(argv)
    print(filtre(a.date, a.sens))


if __name__ == "__main__":
    main()
