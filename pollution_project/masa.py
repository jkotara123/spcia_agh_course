#!/usr/bin/env python3
"""Ilość zanieczyszczenia (całka z u) w warstwach w czasie, dla kilku przebiegów naraz.

Czyta out_<krok>.data z kontenera (/tmp/pollution/<run>) i liczy:
    ziemia  - y < 0.3
    pod     - y < 0.8 (pod inwersją)
    nad     - y >= 0.8

    python3 masa.py --docker iga-ads-dev run_A run_B ... --out przebiegi/masa

Tworzy masa.png (ziemia i pod inwersją w czasie) i masa.csv (wartości na końcu przebiegu).
Opis przebiegu w legendzie bierze się z kolumny "argumenty" w przebiegi.csv.
"""

import argparse
import csv
import io
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
DT = 1e-5
INVERSION = 0.8
GROUND = 0.3


def read(container, path):
    if container:
        raw = subprocess.check_output(["docker", "exec", container, "cat", path])
        return np.loadtxt(io.BytesIO(raw))
    return np.loadtxt(path)


def steps(container, data_dir):
    if container:
        names = subprocess.check_output(["docker", "exec", container, "ls", data_dir], text=True).split()
    else:
        names = [p.name for p in Path(data_dir).iterdir()]
    return sorted(int(n[4:-5]) for n in names if n.startswith("out_") and n.endswith(".data"))


def labels():
    index = HERE / "przebiegi" / "przebiegi.csv"
    if not index.exists():
        return {}
    with open(index) as f:
        return {row["run"]: row.get("argumenty", "") for row in csv.DictReader(f)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+", help="nazwy przebiegów run_...")
    p.add_argument("--docker", default="")
    p.add_argument("--data", default="/tmp/pollution")
    p.add_argument("--every", type=int, default=5, help="co który plik out_*.data czytać")
    p.add_argument("--out", type=Path, default=HERE / "przebiegi" / "masa")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names = labels()

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    rows = []
    for run in args.runs:
        data_dir = f"{args.data}/{run}"
        all_steps = steps(args.docker, data_dir)
        chosen = all_steps[::args.every] + ([all_steps[-1]] if all_steps[-1] not in all_steps[::args.every] else [])
        t, ground, under, above = [], [], [], []
        for s in chosen:
            d = read(args.docker, f"{data_dir}/out_{s}.data")
            y, u = d[:, 1], d[:, 2]
            area = 1.0 / len(u)
            t.append(s * DT)
            ground.append((u * (y < GROUND)).sum() * area)
            under.append((u * (y < INVERSION)).sum() * area)
            above.append((u * (y >= INVERSION)).sum() * area)
        label = names.get(run, "") or run
        label = "domyślne" if label == "-" else label
        ax[0].plot(t, ground, label=label)
        ax[1].plot(t, under, label=label)
        rows.append({"run": run, "argumenty": label, "ziemia_max": round(max(ground), 4),
                     "ziemia_koniec": round(ground[-1], 4), "pod_koniec": round(under[-1], 4),
                     "nad_koniec": round(above[-1], 4)})
        print(f"{run} ({label}): pod inwersją na końcu {under[-1]:.4f}, nad {above[-1]:.4f}, "
              f"przy ziemi max {max(ground):.4f}")

    ax[0].set_title(f"przy ziemi (y < {GROUND})")
    ax[1].set_title(f"pod inwersją (y < {INVERSION})")
    for a in ax:
        a.set_xlabel("t")
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out / "masa.png", dpi=120)
    with open(args.out / "masa.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"gotowe: {args.out / 'masa.png'}, {args.out / 'masa.csv'}")


if __name__ == "__main__":
    main()
