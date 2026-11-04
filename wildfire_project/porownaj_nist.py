#!/usr/bin/env python3
"""Porównanie symulacji z obserwacjami ognia NIST (TN 2135) - do strojenia parametrów i raportu.

Czyta fuel_*.data z przebiegu (domyślnie /tmp/wildfire w kontenerze) i liczy dla każdego punktu
modelu czas dojścia ognia (pierwsza klatka, w której paliwo spadło o ponad 40%). Potem dla każdej
obserwacji NIST z kwadratu modelu sprawdza, kiedy ogień dotarł tam w symulacji.

    python3 porownaj_nist.py --docker iga-ads-dev --data /tmp/wildfire --out anim

Wypisuje:
    trafione     - ile obserwacji NIST ogień w symulacji objął do końca przebiegu
    na czas      - ile z nich nie później niż 30 min po obserwacji
    opóźnienie   - mediana (czas w symulacji - czas NIST) dla trafionych, w minutach
    spalone      - jaka część palnego obszaru spłonęła w symulacji
    poza NIST    - jaka część spalonego jest dalej niż 1,5 km od jakiejkolwiek obserwacji NIST
    miejscowości - kiedy ogień doszedł do Concow, Magalia, Paradise (symulacja i NIST)
Rysuje porownanie_nist.png: mapa czasu dojścia ognia w symulacji z punktami NIST.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "dane_nist"))
import animate  # noqa: E402
import nist_viz  # noqa: E402
import przygotuj_model as pm  # noqa: E402

NIST_XLSX = HERE / "dane_nist" / "NIST TN 2135 Appendix F Fire Spread Data.xlsx"
ON_TIME_MIN = 30
FAR_KM = 1.5
TOWN_RADIUS = 4.0  # jednostki modelu (1,2 km)


def arrival_map(source, every):
    """Czas dojścia ognia (jednostki modelu) na siatce wyjścia; inf = nie spłonęło."""
    steps = source.list_steps("fuel")[::every]
    grid0, extent = source.read_frame("fuel", steps[0])
    arrival = np.full(grid0.shape, np.inf)
    for step in steps[1:]:
        loaded = source.read_frame("fuel", step)
        if loaded is None:
            continue
        burned = (grid0 > 0.05) & (loaded[0] < 0.6 * grid0)
        arrival[burned & np.isinf(arrival)] = step * animate.DT
    return grid0, arrival, extent


def nist_points(t_end):
    fire, _t0 = nist_viz.load(NIST_XLSX)
    mx, my = pm.km_to_model(fire["x"].to_numpy(), fire["y"].to_numpy())
    hour = (fire["czas"] - nist_viz.pd.Timestamp("2018-11-08")).dt.total_seconds().to_numpy() / 3600
    t = (hour - pm.T0_HOUR) / pm.HOURS_PER_UNIT
    keep = (mx > 0) & (mx < 100) & (my > 0) & (my < 100) & (t <= t_end) & np.isfinite(t)
    return mx[keep], my[keep], t[keep]


def sample(grid, extent, x, y):
    ny, nx = grid.shape
    i = np.clip(np.rint((x - extent[0]) / (extent[1] - extent[0]) * (nx - 1)).astype(int), 0, nx - 1)
    j = np.clip(np.rint((y - extent[2]) / (extent[3] - extent[2]) * (ny - 1)).astype(int), 0, ny - 1)
    return grid[j, i]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="/tmp/wildfire")
    p.add_argument("--docker", default="", help="nazwa kontenera; puste = katalog lokalny")
    p.add_argument("--out", type=Path, default=HERE / "anim")
    p.add_argument("--every", type=int, default=1, help="co który plik fuel_*.data czytać")
    p.add_argument("--model", type=Path, default=HERE / "model_data.json")
    args = p.parse_args()
    animate.load_model(args.model)

    source = animate.DataSource(args.data, args.docker or None)
    params = source.read_params()
    animate.DT = float(params.get("dt", animate.DT))
    t_end = float(params.get("t_end", 10))

    fuel0, arrival, extent = arrival_map(source, args.every)
    nx_, ny_, nt = nist_points(t_end)
    sim_t = sample(arrival, extent, nx_, ny_)
    hit = np.isfinite(sim_t)
    delay = (sim_t[hit] - nt[hit]) * pm.HOURS_PER_UNIT * 60
    on_time = delay <= ON_TIME_MIN

    ny, nx = arrival.shape
    gx, gy = np.meshgrid(np.linspace(extent[0], extent[1], nx), np.linspace(extent[2], extent[3], ny))
    burnable = fuel0 > float(params.get("fuel_min", 0.2))
    burned = np.isfinite(arrival)
    # odległość każdego punktu siatki od najbliższej obserwacji NIST (siatka co 1 jednostkę wystarcza)
    far = np.ones_like(burned)
    radius = FAR_KM / pm.UNIT_KM
    for x, y in zip(nx_, ny_):
        far &= (gx - x) ** 2 + (gy - y) ** 2 > radius ** 2

    print(f"obserwacje NIST w kwadracie do t = {t_end:g}: {len(nt)}")
    print(f"trafione:    {hit.mean() * 100:5.1f}%")
    print(f"na czas:     {(hit.sum() and on_time.sum() / len(nt)) * 100:5.1f}%  (do {ON_TIME_MIN} min po NIST)")
    if hit.any():
        print(f"opóźnienie:  mediana {np.median(delay):+.0f} min  (ujemne = symulacja szybsza)")
    print(f"spalone:     {burned[burnable].mean() * 100:5.1f}% palnego obszaru")
    print(f"poza NIST:   {(burned & far).sum() / max(burned.sum(), 1) * 100:5.1f}% spalonego "
          f"(dalej niż {FAR_KM} km od obserwacji)")
    print("miejscowości (symulacja / NIST):")
    for name, (x, y) in animate.MODEL["towns"].items():
        near = (gx - x) ** 2 + (gy - y) ** 2 < TOWN_RADIUS ** 2
        t_sim = arrival[near].min()
        near_n = (nx_ - x) ** 2 + (ny_ - y) ** 2 < TOWN_RADIUS ** 2
        t_obs = nt[near_n].min() if near_n.any() else np.inf
        fmt = lambda t: animate.clock(t) if np.isfinite(t) else "  -  "
        print(f"  {name:9s} {fmt(t_sim)} / {fmt(t_obs)}")

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    shown = np.ma.masked_invalid(np.where(burned, arrival, np.nan))
    im = ax.imshow(shown, origin="lower", extent=extent, cmap="plasma_r", vmin=0, vmax=t_end)
    ax.scatter(nx_, ny_, c=nt, cmap="plasma_r", vmin=0, vmax=t_end, s=10, edgecolors="k", linewidths=0.4)
    cb = fig.colorbar(im, ax=ax)
    ticks = np.arange(0, t_end + 1e-9, 2)
    cb.set_ticks(ticks, labels=[animate.clock(t) for t in ticks])
    cb.set_label("dojście ognia: symulacja (tło), NIST (punkty)")
    animate.draw_overlay(ax)
    ax.set_title("Symulacja a obserwacje NIST")
    ax.set_xlabel("x (wschód) [1 = 300 m]")
    ax.set_ylabel("y (północ)")
    fig.tight_layout()
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out / "porownanie_nist.png", dpi=120)
    print(f"mapa: {args.out / 'porownanie_nist.png'}")


if __name__ == "__main__":
    main()
