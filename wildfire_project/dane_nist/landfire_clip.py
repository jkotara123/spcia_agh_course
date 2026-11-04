#!/usr/bin/env python3
"""Wycina mapę paliwa LANDFIRE FBFM40 (40 modeli Scotta i Burgana) dla obszaru Camp Fire.

Wejście: LF2016_FBFM40_CONUS.zip z landfire.gov (wersja sprzed pożaru, cała USA, ok. 3,1 GB).
Wymaga rasterio:  conda install -c conda-forge rasterio

    python3 landfire_clip.py ~/Downloads/LF2016_FBFM40_CONUS.zip --out wyniki

Tworzy:
    landfire_fbfm40_campfire.tif  - wycinek (oryginalne kody FBFM40, siatka 30 m)
    landfire_fbfm40_campfire.npz  - kody na regularnej siatce lat/lon (do fuel_map w modelu)
    landfire_paliwo.png           - mapa grup paliwa
"""

import argparse
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap
from rasterio.warp import transform, transform_bounds
from rasterio.windows import from_bounds

# Obszar pożaru (jak w woda.overpassql): zachód, południe, wschód, północ
AOI = (-121.85, 39.50, -121.35, 39.90)
LAT0, LON0 = 39.81461, -121.434004  # zapłon (NIST)

# Grupy kodów FBFM40: (od, do, nazwa, kolor)
GROUPS = [
    (91, 99, "niepalne (zabudowa, woda, pola, skały)", "#bdbdbd"),
    (101, 109, "GR - trawy", "#f6e27f"),
    (121, 124, "GS - trawy z krzewami", "#d9c35a"),
    (141, 149, "SH - krzewy", "#c0712b"),
    (161, 165, "TU - podszyt leśny", "#5f9e4f"),
    (181, 189, "TL - ściółka leśna", "#2e6b34"),
    (201, 204, "SB - pozostałości po wycince", "#7b3f99"),
]
NONBURNABLE = {91: "zabudowa", 92: "śnieg/lód", 93: "pola uprawne", 98: "woda", 99: "skały"}


def find_tif(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        tifs = [n for n in z.namelist() if n.lower().endswith(".tif")]
    if not tifs:
        raise SystemExit(f"brak pliku .tif w {zip_path}")
    return f"zip://{Path(zip_path).resolve()}!{tifs[0]}"


def group_index(codes):
    idx = np.full(codes.shape, -1, dtype=int)
    for i, (lo, hi, _name, _color) in enumerate(GROUPS):
        idx[(codes >= lo) & (codes <= hi)] = i
    return idx


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="LF2016_FBFM40_CONUS.zip albo rozpakowany .tif")
    p.add_argument("--out", type=Path, default=Path("wyniki"))
    p.add_argument("--n", type=int, default=400, help="rozmiar siatki lat/lon w pliku .npz")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    src_path = find_tif(args.src) if args.src.suffix.lower() == ".zip" else str(args.src)
    print(f"czytam {src_path}")
    with rasterio.open(src_path) as src:
        bounds = transform_bounds("EPSG:4326", src.crs, *AOI, densify_pts=21)
        window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=window)
        wtransform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(height=data.shape[0], width=data.shape[1], transform=wtransform, compress="deflate")
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile["tiled"] = False
        crs = src.crs
    print(f"wycinek {data.shape[1]} x {data.shape[0]} pikseli, kody: {sorted(np.unique(data))[:30]}")
    with rasterio.open(args.out / "landfire_fbfm40_campfire.tif", "w", **profile) as dst:
        dst.write(data, 1)

    # Próbkowanie na regularnej siatce lat/lon (północ u góry), wygodne do przeliczenia na model
    lons = np.linspace(AOI[0], AOI[2], args.n)
    lats = np.linspace(AOI[3], AOI[1], args.n)
    LON, LAT = np.meshgrid(lons, lats)
    xs, ys = transform("EPSG:4326", crs, LON.ravel(), LAT.ravel())
    inv = ~wtransform
    cols, rows = inv * (np.array(xs), np.array(ys))
    rows = np.clip(np.floor(rows).astype(int), 0, data.shape[0] - 1)
    cols = np.clip(np.floor(cols).astype(int), 0, data.shape[1] - 1)
    codes = data[rows, cols].reshape(LAT.shape)
    np.savez_compressed(args.out / "landfire_fbfm40_campfire.npz", lat=lats, lon=lons, fbfm40=codes)

    # Mapa grup paliwa w km od zapłonu (ten sam układ co mapy NIST)
    km_lon = 111.32 * np.cos(np.radians(LAT0))
    extent = [(AOI[0] - LON0) * km_lon, (AOI[2] - LON0) * km_lon,
              (AOI[1] - LAT0) * 110.57, (AOI[3] - LAT0) * 110.57]
    g = np.ma.masked_less(group_index(codes), 0)
    fig, ax = plt.subplots(figsize=(9, 7.5))
    ax.imshow(g, extent=extent, origin="upper", interpolation="nearest",
              cmap=ListedColormap([c for *_x, c in GROUPS]), vmin=-0.5, vmax=len(GROUPS) - 0.5)
    ax.plot(0, 0, "*", color="red", ms=16, mec="k")
    for _lo, _hi, name, color in GROUPS:
        ax.plot([], [], "s", color=color, ms=10, label=name)
    ax.legend(loc="lower left", fontsize=8)
    ax.set_xlabel("km na wschód od zapłonu")
    ax.set_ylabel("km na północ od zapłonu")
    ax.set_title("LANDFIRE 2016 FBFM40 - paliwo przed Camp Fire")
    fig.tight_layout()
    fig.savefig(args.out / "landfire_paliwo.png", dpi=130)
    plt.close(fig)

    for code, name in NONBURNABLE.items():
        share = (codes == code).mean() * 100
        if share > 0:
            print(f"  {code} {name}: {share:.1f}% obszaru")
    print(f"gotowe: {args.out}")


if __name__ == "__main__":
    main()
