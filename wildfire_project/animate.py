#!/usr/bin/env python3
"""GIF-y z wynikow symulacji Camp Fire.

Czyta out_<krok>.data (temperatura) i fuel_<krok>.data (paliwo).
Wiatr nie jest zapisywany przez program: klatki sa liczone z tej samej tabeli
(stacja Jarbo Gap) co wind_velocity w fire.hpp, zapisanej w model_data.json.
Na wszystkich animacjach: rzeki i jezioro (OSM), miejscowosci i zapalon (NIST).

Dane zostaja w kontenerze, skrypt sciaga tylko klatki, ktore rysuje:

    python3 animate.py --docker iga-ads-dev --data /tmp/wildfire --out anim
"""

import argparse
import io
import json
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

DT = 1e-3  # krok czasu; nadpisywany z params.txt zapisanego przez fire
T_END = 10.0


MODEL = {}  # model_data.json z przygotuj_model.py


def load_model(path):
    MODEL.update(json.loads(Path(path).read_text()))


def wind_velocity(x, y, t):
    """Ta sama interpolacja co fire::wind_velocity: tabela ze stacji Jarbo Gap, jednorodnie w przestrzeni."""
    w = MODEL["wind"]
    bx = np.interp(t, w["t"], w["bx"])
    by = np.interp(t, w["t"], w["by"])
    return np.full_like(x, bx, dtype=float), np.full_like(y, by, dtype=float)


def clock(t):
    """Godzina 8 XI 2018 odpowiadajaca czasowi modelu t."""
    h = MODEL["t0_hour"] + t * MODEL["hours_per_unit"]
    return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"


def draw_overlay(ax):
    """Rzeki, jezioro (OSM), miejscowosci i zapalon - tak jak na mapach NIST."""
    for _name, xs, ys in MODEL.get("lakes", []):
        ax.plot(xs, ys, color="#4fa3e0", lw=0.6, alpha=0.9)
    for _name, xs, ys in MODEL.get("rivers", []):
        ax.plot(xs, ys, color="#4fa3e0", lw=1.2, alpha=0.9)
    for name, (x, y) in MODEL.get("towns", {}).items():
        ax.plot(x, y, "+", color="white", ms=9, mew=2.5)
        ax.plot(x, y, "k+", ms=8, mew=1.2)
        ax.annotate(name, (x, y), xytext=(3, 3), textcoords="offset points", fontsize=8, weight="bold",
                    bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))
    if "ignition" in MODEL:
        ax.plot(*MODEL["ignition"], "*", color="red", ms=12, mec="k")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)


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

    def read_params(self):
        """params.txt z fire (nazwa=wartość); pusty słownik, gdy go nie ma."""
        path = f"{self.data_dir}/params.txt"
        try:
            if self.container:
                text = subprocess.check_output(["docker", "exec", self.container, "cat", path],
                                               text=True, stderr=subprocess.DEVNULL)
            else:
                text = Path(path).read_text()
        except (subprocess.CalledProcessError, OSError):
            return {}
        return dict(line.split("=", 1) for line in text.split() if "=" in line)

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
    draw_overlay(ax)
    ax.set_xlabel("x (wschod) [1 = 300 m]")
    ax.set_ylabel("y (polnoc)")

    for step, grid, _extent in frames:
        image.set_data(grid)
        ax.set_title(f"{title},  t = {step * DT:.2f}  ({clock(step * DT)})")
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
    xs = np.linspace(2.0, 98.0, 17)
    ys = np.linspace(2.0, 98.0, 17)
    X, Y = np.meshgrid(xs, ys)
    times = np.linspace(0.0, T_END, frames_n)
    images = []
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    fig._anim_buf = io.BytesIO()

    w = MODEL["wind"]
    vmax = float(np.hypot(w["bx"], w["by"]).max())
    bx, by = wind_velocity(X, Y, times[0])
    quiver = ax.quiver(X, Y, bx, by, color="#1f3b73", alpha=0.7, angles="xy", scale_units="xy",
                       scale=vmax / 5.0, width=0.004, zorder=3)
    ax.set_aspect("equal")
    draw_overlay(ax)
    ax.set_xlabel("x (wschod) [1 = 300 m]")
    ax.set_ylabel("y (polnoc)")

    for t in times:
        bx, by = wind_velocity(X, Y, float(t))
        quiver.set_UVC(bx, by)
        ms = float(np.interp(t, w["t"], w["ms"]))
        frm = (np.degrees(np.arctan2(-bx[0, 0], -by[0, 0])) + 360) % 360
        ax.set_title(f"wiatr Jarbo Gap,  t = {t:.2f}  ({clock(t)}),  {ms:.1f} m/s z {frm:.0f}°")
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
    parser.add_argument("--model", type=Path, default=Path(__file__).with_name("model_data.json"),
                        help="model_data.json z przygotuj_model.py (rzeki, miasta, wiatr)")
    args = parser.parse_args()
    load_model(args.model)

    source = DataSource(args.data, args.docker or None)
    global DT, T_END
    params = source.read_params()
    DT = float(params.get("dt", DT))
    T_END = float(params.get("t_end", T_END))
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
