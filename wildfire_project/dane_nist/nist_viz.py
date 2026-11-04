#!/usr/bin/env python3
"""Wizualizacja rzeczywistego przebiegu Camp Fire (8-9 XI 2018) z danych NIST.

Dane: NIST TN 2135, Appendix F "Fire Spread Data" (https://data.nist.gov/od/id/mds2-2954).
Każdy wiersz to obserwacja ognia z czasem i współrzędnymi GPS.

    python3 nist_viz.py "NIST TN 2135 Appendix F Fire Spread Data.xlsx" --out wyniki --woda osm_woda.json

Opcjonalnie --woda: rzeki i jezioro z OpenStreetMap (zapytanie w woda.overpassql), rysowane na mapach.

Tworzy:
    mapa_obserwacje.png  - wszystkie obserwacje, kolor = godzina
    pozar_nist.gif       - animacja: gdzie płonęło w kolejnych chwilach
    klatki/*.png         - wybrane klatki animacji
    odleglosc_czas.png   - odległość ognia od miejsca zapłonu w czasie
    rejony_czas.png      - kiedy ogień dotarł do poszczególnych rejonów
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import PillowWriter

# Miejsce zapłonu (pierwsza obserwacja NIST, linia przesyłowa koło Pulga)
LAT0, LON0 = 39.81461, -121.434004
KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LON = 111.32 * np.cos(np.radians(LAT0))

# Przybliżone położenia miejscowości (do podpisów na mapie)
TOWNS = {
    "Pulga": (39.8007, -121.4513),
    "Concow": (39.7724, -121.5297),
    "Magalia": (39.8121, -121.5783),
    "Paradise": (39.7596, -121.6219),
}

TYPES = {
    "V": ("roślinność", "o"),
    "S": ("ognisko od żaru (spot fire)", "^"),
    "R": ("domy", "s"),
    "C": ("budynki komercyjne", "D"),
    "O": ("inne (pojazdy itp.)", "x"),
}


# Linie wody (rzeki, brzeg jeziora) w km od zapłonu: lista (nazwa, xs, ys); ustawiane w main()
WATER = []


def to_km(lat, lon):
    return (lon - LON0) * KM_PER_DEG_LON, (lat - LAT0) * KM_PER_DEG_LAT


def load_water(path):
    """Linie z odpowiedzi Overpass (`out geom`): drogi wodne i obrysy jeziora."""
    text = Path(path).read_text()
    try:
        elements = json.loads(text)["elements"]
    except (json.JSONDecodeError, KeyError):
        raise SystemExit(f"{path} to nie jest odpowiedź Overpass w JSON. Początek pliku:\n{text[:300]}")
    lines = []
    for el in elements:
        name = el.get("tags", {}).get("name", "")
        parts = [el.get("geometry")] if el["type"] == "way" else [m.get("geometry") for m in el.get("members", [])]
        for geom in parts:
            if geom:
                xs, ys = to_km(np.array([g["lat"] for g in geom]), np.array([g["lon"] for g in geom]))
                lines.append((name, xs, ys))
    return lines


def load(path):
    sheets = pd.read_excel(path, sheet_name=None)
    d = pd.concat(sheets, names=["rejon", "i"]).reset_index()
    # W pliku rok jest wpisany jako 2021; pożar był w 2018
    day = d["Date"].astype(str).str[:10].str.replace("2021", "2018", regex=False)
    d["czas"] = pd.to_datetime(day + " " + d["Time"].astype(str), errors="coerce")
    d = d.dropna(subset=["czas", "Latitude", "Longitude"])
    d["x"], d["y"] = to_km(d["Latitude"], d["Longitude"])
    t0 = d["czas"].min()
    d["godz"] = (d["czas"] - t0).dt.total_seconds() / 3600
    d["odl"] = np.hypot(d["x"], d["y"])
    return d.sort_values("czas"), t0


def base_axes(ax, d):
    pad = 1.0
    ax.set_xlim(d["x"].min() - pad, d["x"].max() + pad)
    ax.set_ylim(d["y"].min() - pad, d["y"].max() + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("km na wschód od zapłonu")
    ax.set_ylabel("km na północ od zapłonu")
    ax.grid(alpha=0.3)
    labelled = set()
    for name, xs, ys in WATER:
        lake = "Lake" in name
        ax.plot(xs, ys, color="tab:blue", lw=0.8 if lake else 1.6, alpha=0.8, zorder=1,
                label="rzeki i jezioro (OSM)" if not labelled else None)
        labelled.add("_any")
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        inside = np.flatnonzero((xs > x0) & (xs < x1) & (ys > y0) & (ys < y1))
        if name and not lake and name not in labelled and len(inside) > 10:
            labelled.add(name)
            i = inside[len(inside) // 2]
            ax.text(xs[i], ys[i], name, color="tab:blue", fontsize=7, style="italic", zorder=2)
    for name, (lat, lon) in TOWNS.items():
        x, y = to_km(lat, lon)
        ax.plot(x, y, "k+", ms=10, mew=1.5, zorder=5)
        ax.annotate(name, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=9, weight="bold")
    ax.plot(0, 0, "*", color="red", ms=16, mec="k", zorder=6, label="zapłon 6:25")


def mapa(d, out):
    fig, ax = plt.subplots(figsize=(9, 7))
    base_axes(ax, d)
    for code, (label, marker) in TYPES.items():
        s = d[d["Type of Fire"] == code]
        sc = ax.scatter(s["x"], s["y"], c=s["godz"], cmap="plasma_r", vmin=0, vmax=12,
                        marker=marker, s=14, alpha=0.8, label=label)
    fig.colorbar(sc, ax=ax, label="godziny od zapłonu (6:25, 8 XI 2018)", extend="max")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title("Camp Fire - obserwacje ognia (NIST, n = %d)" % len(d))
    fig.tight_layout()
    fig.savefig(out / "mapa_obserwacje.png", dpi=130)
    plt.close(fig)


def animacja(d, t0, out, step_min=10, end_h=14, keep_h=1.0):
    frames_dir = out / "klatki"
    frames_dir.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 6.5))
    base_axes(ax, d)
    old = ax.scatter([], [], s=8, color="0.6", alpha=0.5, label="wcześniej")
    new = ax.scatter([], [], s=22, c=[], cmap="autumn_r", vmin=0, vmax=keep_h,
                     edgecolors="k", linewidths=0.3, label="ostatnia godzina")
    ax.legend(loc="lower left", fontsize=8)
    title = ax.set_title("")
    times = np.arange(0, end_h + 1e-9, step_min / 60)
    snapshots = {1, 2, 3, 4, 6, 9, 12}
    writer = PillowWriter(fps=8)
    with writer.saving(fig, out / "pozar_nist.gif", dpi=90):
        for h in times:
            seen = d[d["godz"] <= h]
            recent = seen["godz"] > h - keep_h
            old.set_offsets(seen.loc[~recent, ["x", "y"]].to_numpy().reshape(-1, 2))
            new.set_offsets(seen.loc[recent, ["x", "y"]].to_numpy().reshape(-1, 2))
            new.set_array((h - seen.loc[recent, "godz"]).to_numpy())
            clock = t0 + pd.Timedelta(hours=h)
            title.set_text(f"Camp Fire, {clock:%d.%m.%Y %H:%M}  (+{h:.1f} h, obserwacji: {len(seen)})")
            writer.grab_frame()
            if round(h, 6) in snapshots:
                fig.savefig(frames_dir / f"klatka_{int(h):02d}h.png", dpi=110)
    plt.close(fig)


def odleglosc(d, out):
    first_day = d[d["godz"] <= 14]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(first_day["godz"], first_day["odl"], s=6, alpha=0.4, label="obserwacje")
    front = first_day.groupby(first_day["godz"].round(1).rename("h"))["odl"].max().cummax()
    ax.step(front.index, front.values, where="post", color="red", lw=2,
            label="najdalszy zaobserwowany ogień")
    for name, (lat, lon) in TOWNS.items():
        r = np.hypot(*to_km(lat, lon))
        ax.axhline(r, color="k", ls=":", lw=0.8)
        ax.text(13.9, r + 0.2, name, ha="right", fontsize=8)
    ax.set_xlabel("godziny od zapłonu (6:25)")
    ax.set_ylabel("odległość od zapłonu [km]")
    ax.set_title("Jak szybko ogień oddalał się od miejsca zapłonu")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "odleglosc_czas.png", dpi=130)
    plt.close(fig)


def rejony(d, t0, out):
    g = d.groupby("rejon")["godz"].agg(["min", lambda s: s.quantile(0.9)])
    g.columns = ["start", "p90"]
    g = g.sort_values("start")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(g.index, g["p90"] - g["start"], left=g["start"], color="tab:orange", alpha=0.8)
    ax.plot(g["start"], g.index, "k|", ms=12)
    ax.invert_yaxis()
    end = float(np.ceil(g["p90"].max() / 4) * 4)
    ticks = np.arange(0, end + 1e-9, 4)
    ax.set_xticks(ticks, [f"{(t0 + pd.Timedelta(hours=float(t))):%d.%m\n%H:%M}" for t in ticks])
    ax.set_xlim(0, end)
    ax.set_xlabel("data i godzina (pasek: od pierwszej obserwacji do 90% obserwacji w rejonie)")
    ax.set_title("Kiedy ogień dotarł do poszczególnych rejonów")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "rejony_czas.png", dpi=130)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", type=Path)
    p.add_argument("--out", type=Path, default=Path("wyniki"))
    p.add_argument("--woda", type=Path, help="osm_woda.json z Overpass (rzeki, jezioro)")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.woda:
        WATER.extend(load_water(args.woda))
        print(f"woda: {len(WATER)} linii z {args.woda}")

    d, t0 = load(args.xlsx)
    print(f"{len(d)} obserwacji, od {d['czas'].min()} do {d['czas'].max()}")
    mapa(d, args.out)
    odleglosc(d, args.out)
    rejony(d, t0, args.out)
    animacja(d, t0, args.out)
    print(f"gotowe: {args.out}")


if __name__ == "__main__":
    main()
