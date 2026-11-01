#!/usr/bin/env python3
"""GIF-y z wynikow symulacji Camp Fire.

Czyta out_<krok>.data (temperatura) i fuel_<krok>.data (paliwo).
Wiatr nie jest zapisywany przez program — klatki sa liczone z tej samej
formuly co wind_velocity w fire.hpp.

Dane zostaja w kontenerze, skrypt sciaga tylko klatki, ktore rysuje:

    python3 animate.py --docker iga-ads-dev --data /tmp/wildfire --out anim
"""

import argparse
import io
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

DT = 1e-3  # timesteps_config w fire.cpp
T_END = 10.0


def canyon_distance(x, y):
    ax, ay = 90.0, 80.0
    bx, by = 40.0, 16.0
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = ((x - ax) * dx + (y - ay) * dy) / L2
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(x - (ax + t * dx), y - (ay + t * dy))


def wind_velocity(x, y, t):
    """Ta sama formula co fire::wind_velocity."""
    morning = np.exp(-((t / 2.2) ** 2))
    evening = np.exp(-(((t - 7.0) / 1.8) ** 2))
    strength = 0.25 + 0.75 * morning + 0.40 * evening
    channel = np.exp(-((canyon_distance(x, y) / 22.0) ** 2))
    speed = 12.0 * strength * (0.62 + 0.38 * channel)
    turn = 1.0 - morning
    dirx = -0.96 + 0.16 * turn
    diry = -0.28 - 0.32 * turn
    norm = np.hypot(dirx, diry)
    return speed * dirx / norm, speed * diry / norm


class DataSource:
    """Katalog z plikami .data, lokalny albo w kontenerze Dockera."""

    def __init__(self, data_dir, container=None):
        self.data_dir = str(data_dir).rstrip("/")
        self.container = container

    def list_steps(self, prefix):
        if self.container:
            listing = subprocess.check_output(
                ["docker", "exec", self.container, "ls", self.data_dir],
                text=True,
            )
            names = listing.split()
        else:
            names = [path.name for path in Path(self.data_dir).glob(f"{prefix}_*.data")]
        steps = []
        for name in names:
            match = re.fullmatch(rf"{prefix}_(\d+)\.data", name)
            if match:
                steps.append(int(match.group(1)))
        return sorted(steps)

    def read_frame(self, prefix, step):
        name = f"{prefix}_{step}.data"
        path = f"{self.data_dir}/{name}"
        try:
            if self.container:
                raw = subprocess.check_output(
                    ["docker", "exec", self.container, "cat", path]
                )
                if len(raw) < 20:
                    return None
                data = np.loadtxt(io.BytesIO(raw))
            else:
                file_path = Path(path)
                if file_path.stat().st_size < 20:
                    return None
                data = np.loadtxt(file_path)
        except Exception as exc:
            print(f"pomijam {name}: {exc}")
            return None
        grid, extent = grid_from_table(data, name)
        if not np.isfinite(grid).all():
            return None
        return grid, extent


def grid_from_table(data, name):
    """Plik gnuplot: kolumny x, y, wartosc, x zmienia sie wolniej niz y."""
    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError(f"zly format: {name}")
    x, y, z = data[:, 0], data[:, 1], data[:, 2]
    jumps = np.where(np.diff(x) != 0)[0]
    ny = int(jumps[0] + 1) if len(jumps) else len(x)
    if len(x) % ny != 0:
        raise ValueError(f"nieprostokatna siatka: {name}")
    nx = len(x) // ny
    grid = z.reshape(nx, ny).T
    extent = [float(x.min()), float(x.max()), float(y.min()), float(y.max())]
    return grid, extent


def finite_frames(source, prefix, every):
    steps = source.list_steps(prefix)
    frames = []
    skipped = 0
    chosen = steps[::every]
    print(f"{prefix}: {len(steps)} plikow, czytam {len(chosen)}")
    for step in chosen:
        loaded = source.read_frame(prefix, step)
        if loaded is None:
            skipped += 1
            continue
        grid, extent = loaded
        frames.append((step, grid, extent))

    # Rzadkie probkowanie moze trafic w same NaN. Wtedy bierzemy dobre klatki od poczatku.
    if len(frames) < 5:
        frames = []
        skipped = 0
        bad_run = 0
        for step in steps:
            loaded = source.read_frame(prefix, step)
            if loaded is None:
                skipped += 1
                bad_run += 1
                if bad_run >= 2 and frames:
                    break
                continue
            bad_run = 0
            grid, extent = loaded
            frames.append((step, grid, extent))
    return frames, skipped


def save_gif(images, path: Path, fps: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    duration = int(round(1000 / fps))
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        disposal=2,
    )
    print(f"{path}  ({len(images)} klatek, {fps} fps)")


def figure_image(fig, dpi):
    fig._anim_buf.seek(0)
    fig._anim_buf.truncate()
    fig.savefig(fig._anim_buf, format="png", dpi=dpi)
    fig._anim_buf.seek(0)
    image = Image.open(fig._anim_buf).convert("RGB")
    image.load()
    return image.copy()


def animate_scalar(frames, out_dir: Path, name: str, title, cmap, vmin, vmax, fps, dpi):
    import io

    png_dir = out_dir / "png" / name
    png_dir.mkdir(parents=True, exist_ok=True)
    images = []
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    fig._anim_buf = io.BytesIO()
    step0, grid0, extent = frames[0]
    image = ax.imshow(
        grid0,
        origin="lower",
        extent=extent,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
        aspect="equal",
    )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.set_xlabel("x (wschod)")
    ax.set_ylabel("y (polnoc)")

    for step, grid, _extent in frames:
        image.set_data(grid)
        ax.set_title(f"{title},  t = {step * DT:.3f}")
        fig.tight_layout()
        shot = figure_image(fig, dpi)
        images.append(shot)
        shot.save(png_dir / f"{name}_{step:05d}.png")
    plt.close(fig)
    save_gif(images, out_dir / f"{name}.gif", fps)


def animate_wind(out_dir: Path, frames_n: int, fps: int, dpi: int):
    import io

    png_dir = out_dir / "png" / "wind"
    png_dir.mkdir(parents=True, exist_ok=True)
    xs = np.linspace(0.0, 100.0, 35)
    ys = np.linspace(0.0, 100.0, 35)
    X, Y = np.meshgrid(xs, ys)
    times = np.linspace(0.0, T_END, frames_n)
    images = []
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    fig._anim_buf = io.BytesIO()

    bx, by = wind_velocity(X, Y, times[0])
    speed = np.hypot(bx, by)
    # Stala skala: poranny poryw ma zostac najciemniejszy, poludnie jasniejsze.
    vmax = float(np.hypot(*wind_velocity(X, Y, 0.0)).max())
    field = ax.pcolormesh(X, Y, speed, cmap="Blues", shading="auto", vmin=0.0, vmax=vmax)
    bar = fig.colorbar(field, ax=ax, fraction=0.046, pad=0.04)
    bar.set_label("predkosc")
    quiver = ax.quiver(
        X, Y, bx, by, color="#1a1a1a", angles="xy", scale_units="xy", scale=5.0
    )
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("equal")
    ax.set_xlabel("x (wschod)")
    ax.set_ylabel("y (polnoc)")
    ax.plot(82, 62, "o", color="#c0392b", ms=5)
    ax.plot(48, 52, "o", color="#d68910", ms=5)
    ax.text(83, 66, "Pulga", color="#c0392b", fontsize=8)
    ax.text(49, 56, "Paradise", color="#d68910", fontsize=8)

    for t in times:
        bx, by = wind_velocity(X, Y, float(t))
        speed = np.hypot(bx, by)
        field.set_array(speed.ravel())
        quiver.set_UVC(bx, by)
        ax.set_title(f"wiatr Jarbo Gap,  t = {t:.2f}")
        fig.tight_layout()
        shot = figure_image(fig, dpi)
        images.append(shot)
        shot.save(png_dir / f"wind_{t:04.2f}.png")
    plt.close(fig)
    save_gif(images, out_dir / "wind.gif", fps)


def main():
    parser = argparse.ArgumentParser(description="GIF temperatury, paliwa i wiatru")
    parser.add_argument("--data", default="/tmp/wildfire", help="katalog z out_*.data i fuel_*.data")
    parser.add_argument("--docker", default="", help="nazwa kontenera; puste = katalog lokalny")
    parser.add_argument("--out", type=Path, default=Path("anim"), help="katalog wyjsciowy")
    parser.add_argument("--every", type=int, default=0, help="co ktory zapis brac; 0 = dobierz tak, by bylo okolo 40 klatek")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--dpi", type=int, default=90)
    parser.add_argument("--wind-frames", type=int, default=40)
    args = parser.parse_args()

    source = DataSource(args.data, args.docker or None)
    steps = source.list_steps("out")
    if not steps:
        raise SystemExit(f"brak out_*.data w {args.data}")

    every = args.every
    if every <= 0:
        every = max(1, len(steps) // 40)

    where = f"kontener {args.docker}:{args.data}" if args.docker else args.data
    print(f"czytam {where}, co {every} plik")
    temp_frames, temp_skipped = finite_frames(source, "out", every)
    fuel_frames, fuel_skipped = finite_frames(source, "fuel", every)
    if len(temp_frames) < 15:
        print(
            f"temperatura: {len(temp_frames)} dobrych klatek. "
            "Ten bieg od kroku 70 jest NaN, wiec GIF pozaru obejmuje tylko start. "
            "Po przebudowaniu skasuj stare *.data i odpal symulacje jeszcze raz."
        )

    args.out.mkdir(parents=True, exist_ok=True)
    if temp_frames:
        animate_scalar(
            temp_frames,
            args.out,
            "fire",
            "temperatura [K]",
            "inferno",
            vmin=300.0,
            vmax=1600.0,
            fps=args.fps,
            dpi=args.dpi,
        )
    else:
        print("brak skonczonych klatek temperatury")

    if fuel_frames:
        animate_scalar(
            fuel_frames,
            args.out,
            "fuel",
            "paliwo",
            "YlOrBr",
            vmin=0.0,
            vmax=1.0,
            fps=args.fps,
            dpi=args.dpi,
        )

    animate_wind(args.out, args.wind_frames, args.fps, args.dpi)


if __name__ == "__main__":
    main()
