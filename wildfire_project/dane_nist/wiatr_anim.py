#!/usr/bin/env python3
"""Animacja wiatru ze stacji Jarbo Gap na mapie obszaru Camp Fire.

Mamy jedną stację, więc pole wiatru jest jednorodne w przestrzeni: strzałki pokazują kierunek
i prędkość zmierzone w danej chwili (interpolowane liniowo między pomiarami co godzinę).
Na mapie: rzeki i jezioro z OpenStreetMap, miejscowości, stacja, zapłon, wykres prędkości w czasie
i opcjonalnie obserwacje ognia z NIST.

    python3 wiatr_anim.py jarbo_gap.csv --woda osm_woda.json --out wyniki \\
        --nist "NIST TN 2135 Appendix F Fire Spread Data.xlsx"

Tworzy:
    wiatr_anim.gif          - animacja co 10 min, 8 XI 2018 od 4:00 do 22:00
    klatki_wiatr/*.png      - klatki co 2 godziny (do raportu)
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import PillowWriter

import nist_viz
import wiatr_jarbo

STATION = (39.7358, -121.4889)  # RAWS Jarbo Gap (JBGC1)
DAY = pd.Timestamp("2018-11-08")


def interp_wind(w, times):
    """Liniowa interpolacja składowych bx, by (nie kąta, żeby nie było skoków przez 0/360)."""
    t = (w["czas"] - DAY).dt.total_seconds().to_numpy() / 3600
    bx = np.interp(times, t, w["bx"])
    by = np.interp(times, t, w["by"])
    gust = np.interp(times, t, w["poryw"])
    return bx, by, gust


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", type=Path, help="jarbo_gap.csv z IEM")
    p.add_argument("--woda", type=Path, help="osm_woda.json (rzeki, jezioro)")
    p.add_argument("--nist", type=Path, help="xlsx NIST - nanosi obserwacje ognia")
    p.add_argument("--out", type=Path, default=Path("wyniki"))
    p.add_argument("--start", type=float, default=4.0, help="godzina startu (8 XI)")
    p.add_argument("--end", type=float, default=22.0, help="godzina końca (8 XI)")
    p.add_argument("--step", type=int, default=10, help="krok animacji [min]")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    frames_dir = args.out / "klatki_wiatr"
    frames_dir.mkdir(exist_ok=True)

    w = wiatr_jarbo.load(args.csv)
    if args.woda:
        nist_viz.WATER.extend(nist_viz.load_water(args.woda))
    fire = None
    if args.nist:
        fire, t0 = nist_viz.load(args.nist)
        fire["h"] = (fire["czas"] - DAY).dt.total_seconds() / 3600

    hours = np.arange(args.start, args.end + 1e-9, args.step / 60)
    bx, by, gust = interp_wind(w, hours)
    speed = np.hypot(bx, by)
    vmax = float(np.ceil(speed.max()))

    # Zakres mapy: jak na mapach NIST (albo prostokąt wokół zapłonu, gdy nie ma danych NIST)
    frame = fire if fire is not None else pd.DataFrame({"x": [-28.0, 1.0], "y": [-23.0, 3.0]})

    fig = plt.figure(figsize=(8.4, 9.3))
    ax = fig.add_axes([0.08, 0.30, 0.84, 0.66])
    ts = fig.add_axes([0.08, 0.06, 0.84, 0.17])
    nist_viz.base_axes(ax, frame)

    sx, sy = nist_viz.to_km(*STATION)
    ax.plot(sx, sy, "^", color="tab:green", ms=10, mec="k", zorder=6, label="stacja Jarbo Gap")

    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    gx, gy = np.meshgrid(np.linspace(x0 + 1.5, x1 - 1.5, 11), np.linspace(y0 + 1.5, y1 - 1.5, 10))
    spacing = gx[0, 1] - gx[0, 0]
    # najsilniejszy wiatr = strzałka na ~90% odstępu siatki
    quiver = ax.quiver(gx, gy, np.zeros_like(gx), np.zeros_like(gy), color="#1f3b73",
                       angles="xy", scale_units="xy", scale=vmax / (0.9 * spacing),
                       width=0.006, headwidth=4, headlength=5, alpha=0.6, zorder=4)
    ax.quiverkey(quiver, 0.84, -0.075, 10, "= 10 m/s", labelpos="E", coordinates="axes")

    old = new = None
    if fire is not None:
        old = ax.scatter([], [], s=6, color="0.55", alpha=0.5, zorder=3, label="ogień (wcześniej)")
        new = ax.scatter([], [], s=16, color="orangered", edgecolors="k", linewidths=0.3,
                         zorder=5, label="ogień (ostatnia godzina)")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.95).set_zorder(10)
    for t in ax.texts:
        t.set_bbox(dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))
        t.set_zorder(7)
    title = ax.set_title("")

    ts.plot(hours, speed, color="tab:blue", label="prędkość")
    ts.plot(hours, gust, color="tab:orange", alpha=0.7, label="porywy")
    ts.axvline(6 + 25 / 60, color="red", ls="--", lw=1)
    marker = ts.axvline(hours[0], color="k", lw=1.5)
    ts.set_xlim(hours[0], hours[-1])
    ts.set_xlabel("godzina, 8 XI 2018 (PST)")
    ts.set_ylabel("m/s")
    ts.grid(alpha=0.3)
    ts.legend(loc="upper right", fontsize=8)

    writer = PillowWriter(fps=8)
    with writer.saving(fig, args.out / "wiatr_anim.gif", dpi=80):
        for i, h in enumerate(hours):
            n = speed[i]
            quiver.set_UVC(np.full_like(gx, bx[i]), np.full_like(gy, by[i]))
            # kierunek meteorologiczny: skąd wieje
            frm = (np.degrees(np.arctan2(-bx[i], -by[i])) + 360) % 360
            clock = DAY + pd.Timedelta(hours=float(h))
            title.set_text(f"Wiatr Jarbo Gap, {clock:%d.%m.%Y %H:%M}  -  {n:.1f} m/s z {frm:.0f}°")
            marker.set_xdata([h, h])
            if fire is not None:
                seen = fire[fire["h"] <= h]
                recent = seen["h"] > h - 1
                old.set_offsets(seen.loc[~recent, ["x", "y"]].to_numpy().reshape(-1, 2))
                new.set_offsets(seen.loc[recent, ["x", "y"]].to_numpy().reshape(-1, 2))
            writer.grab_frame()
            if abs(h - round(h)) < 1e-6 and int(round(h)) % 2 == 0:
                fig.savefig(frames_dir / f"wiatr_{int(round(h)):02d}h.png", dpi=110)
    plt.close(fig)
    print(f"gotowe: {args.out / 'wiatr_anim.gif'}, klatki w {frames_dir}")


if __name__ == "__main__":
    main()
