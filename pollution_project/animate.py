#!/usr/bin/env python3
"""GIF-y i klatki PNG z wynikow symulacji pollution.

Czyta <prefiks>_<krok>.data (format gnuplot z output_manager: kolumny x, y, wartosc).
Domyslnie jedno pole: out = stezenie zanieczyszczen. Kolejne pola dopisuje sie opcja --field,
np. gdy kod zapisuje tez temperature do temp_<krok>.data:

    python3 animate.py --docker iga-ads-dev --data /tmp/pollution/latest --out anim \
        --field out:stezenie:viridis --field temp:temperatura:inferno

Dane zostaja w kontenerze, skrypt sciaga tylko klatki, ktore rysuje.
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
from matplotlib.colors import LogNorm, Normalize
from PIL import Image


class DataSource:
    """Katalog z plikami .data, lokalny albo w kontenerze Dockera."""

    def __init__(self, data_dir, container=None):
        self.data_dir = str(data_dir).rstrip("/")
        self.container = container

    def _read(self, path, binary=False):
        if self.container:
            return subprocess.check_output(["docker", "exec", self.container, "cat", path],
                                           text=not binary, stderr=subprocess.DEVNULL)
        return Path(path).read_bytes() if binary else Path(path).read_text()

    def list_steps(self, prefix):
        if self.container:
            names = subprocess.check_output(["docker", "exec", self.container, "ls", self.data_dir],
                                            text=True).split()
        else:
            names = [path.name for path in Path(self.data_dir).glob(f"{prefix}_*.data")]
        steps = []
        for name in names:
            match = re.fullmatch(rf"{prefix}_(\d+)\.data", name)
            if match:
                steps.append(int(match.group(1)))
        return sorted(steps)

    def read_params(self):
        """params.csv z programu (naglowek + wiersz wartosci); pusty slownik, gdy go nie ma."""
        try:
            lines = self._read(f"{self.data_dir}/params.csv").split()
        except (subprocess.CalledProcessError, OSError):
            return {}
        return dict(zip(lines[0].split(","), lines[1].split(","))) if len(lines) >= 2 else {}

    def read_frame(self, prefix, step):
        name = f"{prefix}_{step}.data"
        try:
            raw = self._read(f"{self.data_dir}/{name}", binary=True)
            if len(raw) < 20:
                return None
            grid, extent = grid_from_table(np.loadtxt(io.BytesIO(raw)), name)
        except Exception as exc:
            print(f"pomijam {name}: {exc}")
            return None
        if not np.isfinite(grid).all():
            print(f"pomijam {name}: NaN/inf")
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


def read_frames(source, prefix, frames_n):
    steps = source.list_steps(prefix)
    if not steps:
        return []
    every = max(1, len(steps) // frames_n)
    chosen = steps[::every]
    if chosen[-1] != steps[-1]:
        chosen.append(steps[-1])
    print(f"{prefix}: {len(steps)} plikow, czytam {len(chosen)}")
    frames = []
    for step in chosen:
        loaded = source.read_frame(prefix, step)
        if loaded is not None:
            frames.append((step, *loaded))
    return frames


def color_norm(frames, log, vmin, vmax):
    values = np.concatenate([grid.ravel() for _step, grid, _extent in frames])
    if vmax is None:
        vmax = float(np.percentile(values, 99.5))
    if log:
        if vmin is None:
            positive = values[values > 0]
            vmin = max(float(positive.min()) if positive.size else 1e-12, vmax * 1e-6)
        return LogNorm(vmin=vmin, vmax=vmax)
    if vmin is None:
        vmin = float(values.min())
    return Normalize(vmin=vmin, vmax=vmax)


def figure_image(fig, buf, dpi):
    buf.seek(0)
    buf.truncate()
    fig.savefig(buf, format="png", dpi=dpi)
    buf.seek(0)
    image = Image.open(buf).convert("RGB")
    image.load()
    return image.copy()


def save_gif(images, path: Path, fps: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(path, save_all=True, append_images=images[1:], duration=int(round(1000 / fps)),
                   loop=0, disposal=2)
    print(f"{path}  ({len(images)} klatek, {fps} fps)")


def is_firing(t, params):
    """Czy działko strzela w chwili t (ten sam harmonogram co cannon() w pollution.hpp)."""
    t0 = float(params.get("cannon_t", 0))
    period = float(params.get("cannon_period", 0.06))
    duration = float(params.get("cannon_duration", 0.03))
    shots = int(float(params.get("cannon_shots", 10**9)))
    if t < t0 or t - t0 >= shots * period:
        return False
    return (t - t0) % period < duration


def animate_field(frames, out_dir: Path, name, title, cmap, norm, dt, params, fps, dpi):
    png_dir = out_dir / "png" / name
    png_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    step0, grid0, extent = frames[0]
    image = ax.imshow(grid0, origin="lower", extent=extent, cmap=cmap, norm=norm,
                      interpolation="nearest", aspect="equal")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label=f"{title} u")
    if "src_x" in params and "src_y" in params:
        ax.plot(float(params["src_x"]), float(params["src_y"]), "^", color="red", ms=8, mec="k")
    if "inversion_y" in params:
        ax.axhline(float(params["inversion_y"]), color="white", ls="--", lw=1.0, alpha=0.9,
                   label="inwersja")
    cannon_on = "cannon_x" in params and float(params.get("cannon_amp", "1")) != 0.0
    if cannon_on:
        n = int(float(params.get("cannon_n", 1)))
        dx = float(params.get("cannon_dx", 0.3))
        xs = [float(params["cannon_x"]) + (k - (n - 1) / 2) * dx for k in range(n)]
        ax.plot(xs, [0.0] * n, "^", color="red", ms=11, mec="k", clip_on=False, zorder=5,
                label="działko")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.8)
    ax.set_xlabel("x")
    ax.set_ylabel("y (wysokość)")

    images = []
    for step, grid, _extent in frames:
        image.set_data(grid)
        t = step * dt
        when = f"t = {t:.4f}" if dt < 1 else f"t = {t:.0f} s ({t / 60:.1f} min)"
        firing = cannon_on and is_firing(t, params)
        ax.set_title(f"{title},  krok {step},  {when}" + ("  STRZAŁ" if firing else ""),
                     color="red" if firing else "black")
        fig.tight_layout()
        shot = figure_image(fig, buf, dpi)
        images.append(shot)
        shot.save(png_dir / f"{name}_{step:05d}.png")
    plt.close(fig)
    save_gif(images, out_dir / f"{name}.gif", fps)


def parse_field(text):
    parts = text.split(":")
    prefix = parts[0]
    title = parts[1] if len(parts) > 1 else prefix
    cmap = parts[2] if len(parts) > 2 else "viridis"
    return prefix, title, cmap


def main():
    parser = argparse.ArgumentParser(description="GIF i klatki PNG z plikow .data")
    parser.add_argument("--data", default="/tmp/pollution/latest", help="katalog z *_<krok>.data")
    parser.add_argument("--docker", default="", help="nazwa kontenera; puste = katalog lokalny")
    parser.add_argument("--out", type=Path, default=Path("anim"), help="katalog wyjsciowy")
    parser.add_argument("--field", action="append", default=[],
                        help="prefiks[:tytul[:colormap]], mozna wiele razy; domyslnie out:stezenie [g/m^3]:viridis")
    parser.add_argument("--frames", type=int, default=40, help="ile klatek w GIF-ie (w przyblizeniu)")
    parser.add_argument("--log", action="store_true", help="skala logarytmiczna kolorow")
    parser.add_argument("--vmin", type=float, default=None)
    parser.add_argument("--vmax", type=float, default=None, help="domyslnie 99,5 percentyl ze wszystkich klatek")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--dpi", type=int, default=90)
    args = parser.parse_args()

    source = DataSource(args.data, args.docker or None)
    params = source.read_params()
    dt = float(params.get("dt", 1.0))
    fields = [parse_field(f) for f in args.field] or [("out", "stężenie", "viridis")]

    where = f"kontener {args.docker}:{args.data}" if args.docker else args.data
    print(f"czytam {where}")
    args.out.mkdir(parents=True, exist_ok=True)
    drawn = 0
    for prefix, title, cmap in fields:
        frames = read_frames(source, prefix, args.frames)
        if not frames:
            print(f"brak klatek {prefix}_*.data")
            continue
        norm = color_norm(frames, args.log, args.vmin, args.vmax)
        name = "pollution" if prefix == "out" else prefix
        animate_field(frames, args.out, name, title, cmap, norm, dt, params, args.fps, args.dpi)
        drawn += 1
    if not drawn:
        raise SystemExit(f"nic do narysowania w {args.data}")


if __name__ == "__main__":
    main()
