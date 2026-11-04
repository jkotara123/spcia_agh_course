#!/usr/bin/env python3
"""Wiatr ze stacji RAWS Jarbo Gap (JBGC1) w czasie Camp Fire.

Dane: archiwum DCP/HADS Iowa Environmental Mesonet (IEM), CSV pobrany komendą z README:

    python3 wiatr_jarbo.py jarbo_gap.csv --out wyniki

Kolumny SHEF w pliku IEM (jednostki angloamerykańskie):
    USIRGZ  prędkość wiatru [mph]
    UPHRGZ  poryw [mph]
    UDIRGZ  kierunek, SKĄD wieje [stopnie, 0 = z północy, 90 = ze wschodu]
    TAIRGZ  temperatura [°F]
    XRIRGZ  wilgotność względna [%]

Tworzy:
    wiatr_jarbo.png       - prędkość, porywy, kierunek, wilgotność w czasie (czas lokalny PST)
    wiatr_jarbo_8xi.csv   - tabela godzinowa z 8 XI 2018 w m/s i składowych bx, by
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MPH = 0.44704  # m/s
IGNITION = pd.Timestamp("2018-11-08 06:25")  # PST, pierwsza obserwacja NIST


def load(path):
    d = pd.read_csv(path)
    d = d.dropna(subset=["USIRGZ"])  # tylko wiersze z pomiarem wiatru
    # IEM podaje czas UTC; w listopadzie Kalifornia ma PST = UTC - 8 h
    d["czas"] = pd.to_datetime(d["utc_valid"]) - pd.Timedelta(hours=8)
    d["v"] = d["USIRGZ"] * MPH
    d["poryw"] = d["UPHRGZ"] * MPH
    d["kier"] = d["UDIRGZ"]
    d["temp_C"] = (d["TAIRGZ"] - 32) * 5 / 9
    d["wilg"] = d["XRIRGZ"]
    # Wektor prędkości (dokąd wieje): kierunek meteorologiczny mówi SKĄD wieje
    rad = np.radians(d["kier"])
    d["bx"] = -d["v"] * np.sin(rad)  # składowa wschodnia
    d["by"] = -d["v"] * np.cos(rad)  # składowa północna
    return d.sort_values("czas")


def plot(d, out):
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    a1.plot(d["czas"], d["v"], "o-", ms=3, label="prędkość średnia")
    a1.plot(d["czas"], d["poryw"], "o-", ms=3, alpha=0.7, label="porywy")
    a1.set_ylabel("wiatr [m/s]")
    a1.legend(loc="upper right")
    a1.set_title("Stacja RAWS Jarbo Gap (JBGC1) - wiatr w czasie Camp Fire")

    a2.scatter(d["czas"], d["kier"], s=12)
    a2.set_ylim(0, 360)
    a2.set_yticks([0, 45, 90, 135, 180, 225, 270, 315, 360], ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"])
    a2.set_ylabel("skąd wieje")

    a3.plot(d["czas"], d["wilg"], "o-", ms=3, color="tab:green")
    a3.set_ylabel("wilgotność [%]")
    a3.set_xlabel("czas lokalny (PST)")

    for ax in (a1, a2, a3):
        ax.axvline(IGNITION, color="red", ls="--", lw=1)
        ax.grid(alpha=0.3)
    a1.text(IGNITION, a1.get_ylim()[1] * 0.92, " zapłon 6:25", color="red")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "wiatr_jarbo.png", dpi=130)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", type=Path)
    p.add_argument("--out", type=Path, default=Path("wyniki"))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    d = load(args.csv)
    print(f"{len(d)} pomiarów wiatru, od {d['czas'].min()} do {d['czas'].max()} (PST)")
    plot(d, args.out)

    day = d[d["czas"].dt.date == IGNITION.date()]
    cols = ["czas", "v", "poryw", "kier", "bx", "by", "temp_C", "wilg"]
    day = day[cols].round({c: 2 for c in cols[1:]})
    day.to_csv(args.out / "wiatr_jarbo_8xi.csv", index=False)
    print(day.to_string(index=False))
    print(f"gotowe: {args.out}")


if __name__ == "__main__":
    main()
