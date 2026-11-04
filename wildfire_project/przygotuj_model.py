#!/usr/bin/env python3
"""Przelicza prawdziwe dane o Camp Fire na kwadrat [0, 100]^2 modelu IGA-ADS.

Wejście (z dane_nist/, patrz dane_nist/README.md):
    wyniki/landfire_fbfm40_campfire.npz  - paliwo LANDFIRE 2016 (FBFM40)
    osm_woda.json                        - rzeki i jezioro Oroville (OpenStreetMap)
    jarbo_gap.csv                        - wiatr ze stacji RAWS Jarbo Gap (IEM)

Wyjście (obok tego skryptu):
    camp_fire_data.hpp  - dla fire.hpp: siatka klas paliwa, tabela wiatru, punkt zapłonu
    model_data.json     - dla animate.py: rzeki, miejscowości, wiatr, skala czasu
    model_paliwo.png    - podgląd mapy klas paliwa w układzie modelu

Wagi paliwa (0..1) dla klas NIE są tutaj, tylko w fire.hpp (struct fire_params), i można je
zmieniać bez kompilacji: just run SH=1 TU=0.3

    python3 przygotuj_model.py
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "dane_nist"
sys.path.insert(0, str(DATA))
import nist_viz  # noqa: E402  (to_km, load_water, TOWNS, zapłon)
import wiatr_jarbo  # noqa: E402

# Kwadrat modelu w km od zapłonu: 30 x 30 km, 1 jednostka modelu = 0,3 km
X0_KM, Y0_KM, SIZE_KM = -28.0, -24.0, 30.0
UNIT_KM = SIZE_KM / 100.0

# Czas: t = 0 to zapłon (6:25), 1 jednostka czasu modelu = 0,5 h, więc t in [0, 10] to 6:25-11:25
T0_HOUR = 6 + 25 / 60
HOURS_PER_UNIT = 0.5
# Wiatr: m/s -> jednostki modelu. Szczyt ok. 14 m/s daje ok. 12, jak u kolegi (stabilne przy dt = 1e-3)
WIND_SCALE = 0.85

N = 201  # siatka paliwa N x N na [0, 100]^2 (co 0,5 jednostki = 150 m)
RIVER_HALF_WIDTH_KM = 0.15  # pas wokół rzek z OSM, w którym paliwo = min(klasa, waga "river")

# Klasy paliwa: (nazwa w C++ i w just run, kody LANDFIRE FBFM40 od-do, opis, kolor podglądu).
# Kolejność = numer klasy w FUEL_CLASS. Wartość z flagą RIVER (+16) to ta sama klasa przy rzece.
CLASSES = [
    ("urban", 91, 91, "zabudowa", "#e7298a"),
    ("snow", 92, 92, "śnieg, lód", "#ffffff"),
    ("agri", 93, 93, "pola uprawne", "#b3de69"),
    ("water", 98, 98, "woda", "#1f78b4"),
    ("rock", 99, 99, "skały, piach", "#bdbdbd"),
    ("GR", 101, 109, "GR trawy", "#f6e27f"),
    ("GS", 121, 124, "GS trawy z krzewami", "#d9c35a"),
    ("SH", 141, 149, "SH krzewy (chaparral)", "#c0712b"),
    ("TU", 161, 165, "TU podszyt leśny", "#5f9e4f"),
    ("TL", 181, 189, "TL ściółka leśna", "#2e6b34"),
    ("SB", 201, 204, "SB pozostałości po wycince", "#7b3f99"),
    ("other", 0, -1, "inne kody", "#000000"),
]
OTHER = len(CLASSES) - 1
RIVER_FLAG = 16


def km_to_model(x_km, y_km):
    return (np.asarray(x_km) - X0_KM) / UNIT_KM, (np.asarray(y_km) - Y0_KM) / UNIT_KM


def model_to_latlon(mx, my):
    x_km = X0_KM + np.asarray(mx) * UNIT_KM
    y_km = Y0_KM + np.asarray(my) * UNIT_KM
    lat = nist_viz.LAT0 + y_km / nist_viz.KM_PER_DEG_LAT
    lon = nist_viz.LON0 + x_km / nist_viz.KM_PER_DEG_LON
    return lat, lon


def class_from_codes(codes):
    cls = np.full(codes.shape, OTHER, dtype=np.uint8)
    for k, (_name, lo, hi, _desc, _color) in enumerate(CLASSES):
        cls[(codes >= lo) & (codes <= hi)] = k
    return cls


def segment_distance(px, py, xs, ys):
    """Odległość punktów (px, py) od łamanej (xs, ys)."""
    d = np.full(px.shape, np.inf)
    for ax, ay, bx, by in zip(xs[:-1], ys[:-1], xs[1:], ys[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / L2, 0, 1)
        d = np.minimum(d, np.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return d


def build_fuel(water):
    lf = np.load(DATA / "wyniki" / "landfire_fbfm40_campfire.npz")
    lats, lons, codes = lf["lat"], lf["lon"], lf["fbfm40"]  # lat malejąco (północ u góry)

    g = np.linspace(0, 100, N)
    MX, MY = np.meshgrid(g, g)  # wiersz j = y modelu (z południa na północ), kolumna i = x
    lat, lon = model_to_latlon(MX, MY)
    rows = np.clip(np.rint((lats[0] - lat) / (lats[0] - lats[-1]) * (len(lats) - 1)).astype(int), 0, len(lats) - 1)
    cols = np.clip(np.rint((lon - lons[0]) / (lons[-1] - lons[0]) * (len(lons) - 1)).astype(int), 0, len(lons) - 1)
    cls = class_from_codes(codes[rows, cols])

    # Rzeki (bez obrysu jeziora - jezioro jest już w LANDFIRE jako woda)
    half = RIVER_HALF_WIDTH_KM / UNIT_KM
    for name, mxs, mys in water["rivers"]:
        mxs, mys = np.array(mxs), np.array(mys)
        near = segment_distance(MX, MY, mxs, mys) < half
        cls[near] |= RIVER_FLAG
    return cls


def build_water():
    rivers, lakes = [], []
    for name, xs, ys in nist_viz.load_water(DATA / "osm_woda.json"):
        mx, my = km_to_model(xs, ys)
        inside = (mx > -5) & (mx < 105) & (my > -5) & (my < 105)
        if inside.sum() < 2:
            continue
        item = (name, np.round(mx, 2).tolist(), np.round(my, 2).tolist())
        (lakes if "Lake" in name else rivers).append(item)
    return {"rivers": rivers, "lakes": lakes}


def build_wind():
    w = wiatr_jarbo.load(DATA / "jarbo_gap.csv")
    hour = (w["czas"] - nist_viz.pd.Timestamp("2018-11-08")).dt.total_seconds() / 3600
    t = (hour - T0_HOUR) / HOURS_PER_UNIT
    keep = (t > -3) & (t < 14)
    return {
        "t": np.round(t[keep], 4).tolist(),
        "bx": np.round(w["bx"][keep] * WIND_SCALE, 3).tolist(),
        "by": np.round(w["by"][keep] * WIND_SCALE, 3).tolist(),
        "ms": np.round(w["v"][keep], 2).tolist(),
    }


def cpp_array(name, values, per_line=12, fmt="{:.3g}", ctype="double"):
    vals = [fmt.format(v) for v in values]
    lines = [", ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    return f"inline constexpr {ctype} {name}[] = {{\n    " + ",\n    ".join(lines) + "\n};\n"


def write_header(cls, wind, ign):
    path = HERE / "camp_fire_data.hpp"
    with open(path, "w") as f:
        f.write("// Wygenerowane przez przygotuj_model.py - nie edytować ręcznie.\n")
        f.write("// Camp Fire 2018 na kwadracie [0, 100]^2 (1 jednostka = %.2f km, x na wschód, y na północ).\n" % UNIT_KM)
        f.write("// Paliwo: LANDFIRE 2016 FBFM40 + rzeki z OpenStreetMap. Wiatr: stacja RAWS Jarbo Gap (JBGC1).\n")
        f.write("// Czas: t = 0 to zapłon 8 XI 2018 6:25, 1 jednostka czasu = %.2f h.\n\n" % HOURS_PER_UNIT)
        f.write("#ifndef CAMP_FIRE_DATA_HPP\n#define CAMP_FIRE_DATA_HPP\n\nnamespace camp_fire {\n\n")
        f.write(f"inline constexpr double IGNITION_X = {ign[0]:.2f};  // zapłon (NIST), linia przesyłowa koło Pulga\n")
        f.write(f"inline constexpr double IGNITION_Y = {ign[1]:.2f};\n\n")
        f.write("// Klasy paliwa LANDFIRE (wagi 0..1 w fire_params w fire.hpp)\n")
        f.write("enum fuel_class : unsigned char {\n")
        for k, (name, lo, hi, desc, _color) in enumerate(CLASSES):
            codes = f"kody {lo}-{hi}" if hi >= lo else "pozostałe kody"
            f.write(f"    {name.upper()} = {k},  // {desc}, {codes}\n")
        f.write(f"    RIVER = {RIVER_FLAG},  // flaga: pas {RIVER_HALF_WIDTH_KM * 1000:.0f} m od rzeki z OSM\n}};\n\n")
        f.write(f"// Klasy na siatce {N} x {N}: FUEL_CLASS[j * FUEL_N + i] w punkcie (x, y) = (100 i / (N-1), 100 j / (N-1))\n")
        f.write(f"inline constexpr int FUEL_N = {N};\n")
        f.write(cpp_array("FUEL_CLASS", cls.ravel(), per_line=40, fmt="{:d}", ctype="unsigned char"))
        f.write(f"\n// Wiatr (jednostki modelu = {WIND_SCALE} * m/s), pomiary co godzinę w chwilach WIND_T modelu\n")
        f.write(f"inline constexpr int WIND_N = {len(wind['t'])};\n")
        f.write(cpp_array("WIND_T", wind["t"], fmt="{:.4f}"))
        f.write(cpp_array("WIND_BX", wind["bx"], fmt="{:.3f}"))
        f.write(cpp_array("WIND_BY", wind["by"], fmt="{:.3f}"))
        f.write("\n}  // namespace camp_fire\n\n#endif  // CAMP_FIRE_DATA_HPP\n")
    print(f"zapisano {path} ({path.stat().st_size // 1024} KB)")


def preview(cls, water, towns, ign):
    from matplotlib.colors import ListedColormap
    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    base = cls & ~np.uint8(RIVER_FLAG)
    colors = [c for *_x, c in CLASSES]
    ax.imshow(base, origin="lower", extent=[0, 100, 0, 100], interpolation="nearest",
              cmap=ListedColormap(colors), vmin=-0.5, vmax=len(CLASSES) - 0.5)
    for k, (name, *_x, desc, color) in enumerate(CLASSES):
        share = (base == k).mean() * 100
        if share > 0.05:
            ax.plot([], [], "s", color=color, ms=9, label=f"{name}: {desc} ({share:.0f}%)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, frameon=False)
    draw_overlay(ax, water, towns, ign)
    ax.set_title("Klasy paliwa w modelu (LANDFIRE 2016 + rzeki OSM)")
    ax.set_xlabel("x (wschód) [1 = 300 m]")
    ax.set_ylabel("y (północ)")
    fig.tight_layout()
    fig.savefig(HERE / "model_paliwo.png", dpi=120)
    plt.close(fig)


def draw_overlay(ax, water, towns, ign):
    """To samo co rysuje animate.py: rzeki, jezioro, miejscowości, zapłon."""
    for _name, xs, ys in water["lakes"]:
        ax.plot(xs, ys, color="tab:blue", lw=0.6, alpha=0.8)
    for _name, xs, ys in water["rivers"]:
        ax.plot(xs, ys, color="tab:blue", lw=1.2, alpha=0.9)
    for name, (x, y) in towns.items():
        ax.plot(x, y, "k+", ms=9, mew=1.5)
        ax.annotate(name, (x, y), xytext=(3, 3), textcoords="offset points", fontsize=8, weight="bold")
    ax.plot(*ign, "*", color="red", ms=13, mec="k")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)


def main():
    water = build_water()
    towns = {name: [round(float(v), 2) for v in km_to_model(*nist_viz.to_km(lat, lon))]
             for name, (lat, lon) in nist_viz.TOWNS.items()}
    ign = [round(float(v), 2) for v in km_to_model(0.0, 0.0)]
    cls = build_fuel(water)
    wind = build_wind()

    write_header(cls, wind, ign)
    meta = {
        "unit_km": UNIT_KM, "t0_hour": T0_HOUR, "hours_per_unit": HOURS_PER_UNIT,
        "wind_scale": WIND_SCALE, "ignition": ign, "towns": towns, "wind": wind,
        "rivers": water["rivers"], "lakes": water["lakes"],
    }
    (HERE / "model_data.json").write_text(json.dumps(meta))
    preview(cls, water, towns, ign)
    print(f"zapłon w modelu: {ign}, miejscowości: {towns}")
    for k, (name, *_x, desc, _color) in enumerate(CLASSES):
        print(f"  {name:6s} {desc:28s} {((cls & ~np.uint8(RIVER_FLAG)) == k).mean() * 100:5.1f}%")
    print(f"  przy rzece: {((cls & RIVER_FLAG) > 0).mean() * 100:.1f}%")
    print(f"wiatr: {len(wind['t'])} pomiarów, t od {wind['t'][0]:.1f} do {wind['t'][-1]:.1f}")


if __name__ == "__main__":
    main()
