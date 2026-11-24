#!/usr/bin/env python3
"""Analiza przebiegów do raportu: działko, powstawanie chmury, miary, bilans masy.

    python3 analiza.py --docker iga-ads-dev --out raport/latex/img \\
        bez=run_A emisja=run_B wznoszenie=run_C po=run_D

Pierwszy przebieg (bez działka) jest odniesieniem. Tworzy w --out:
    cannon_przestrzen.png  cannon(x, y) w szczycie impulsu i profil prędkości unoszenia
    cannon_czas.png        harmonogram strzałów każdego wariantu (czas i numer kroku)
    wznoszenie.png         wysokość chmury w czasie (bez działka)
    miary.png              ilość pod inwersją i średnie stężenie przy ziemi w czasie
    masa_calkowita.png     całkowita ilość zanieczyszczeń w czasie
    bilans.png             całkowita ilość a bilans z członów równania (bez działka)
    roznica.png            różnica stężeń: z działkiem minus bez, po strzałach
i wypisuje liczby do raportu (także do wyniki.json).
"""

import argparse
import csv
import io
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
DT = 1e-5
INV = 0.8      # wysokość inwersji
LIFT = 5.2     # -dT/dy pod inwersją
KY = 0.1
GROUND = 0.1   # warstwa przy ziemi do miary stężenia


def read_grid(container, path):
    raw = subprocess.check_output(["docker", "exec", container, "cat", path]) if container else Path(path).read_bytes()
    d = np.loadtxt(io.BytesIO(raw))
    x, y, u = d[:, 0], d[:, 1], d[:, 2]
    jumps = np.where(np.diff(x) != 0)[0]
    ny = int(jumps[0] + 1)
    nx = len(x) // ny
    return u.reshape(nx, ny).T, np.unique(y)  # grid[j, i] = u(x_i, y_j)


def steps_of(container, data_dir):
    names = subprocess.check_output(["docker", "exec", container, "ls", data_dir], text=True).split()
    return sorted(int(n[4:-5]) for n in names if n.startswith("out_") and n.endswith(".data"))


def params_of(container, data_dir):
    text = subprocess.check_output(["docker", "exec", container, "cat", f"{data_dir}/params.csv"], text=True)
    head, vals = text.split()[:2]
    return {k: float(v) for k, v in zip(head.split(","), vals.split(","))}


def source_s(it):
    """s z before_step w pollution.hpp."""
    d, c = 0.7, 10000
    return max((np.cos(it * np.pi / c) - d) / (1 - d), 0.0)


def pulse(t, par):
    t0, P, tau, n = par["cannon_t"], par["cannon_period"], par["cannon_duration"], par["cannon_shots"]
    t = np.asarray(t, dtype=float)
    on = (t >= t0) & (t - t0 < n * P) & (par["cannon_amp"] != 0)
    ph = np.mod(t - t0, P)
    return np.where(on & (ph < tau), np.sin(np.pi * ph / tau), 0.0)


def analyse(container, data_dir, every):
    st = steps_of(container, data_dir)
    st = st[::every] + ([st[-1]] if st[-1] not in st[::every] else [])
    out = {"step": [], "t": [], "total": [], "under": [], "ground": [], "centroid": [], "top": [],
           "u_inv": [], "dudy0": []}
    grids = {}
    for s in st:
        g, ys = read_grid(container, f"{data_dir}/out_{s}.data")
        prof = g.mean(axis=1)                      # średnia po x, funkcja y
        dy = ys[1] - ys[0]
        total = np.trapezoid(prof, ys)
        under = np.trapezoid(np.where(ys < INV, prof, 0), ys)
        ground = prof[ys <= GROUND].mean()
        cen = np.trapezoid(prof * ys, ys) / total if total > 0 else 0
        top = ys[np.where(prof > 0.5 * prof.max())[0][-1]] if prof.max() > 0 else 0
        out["step"].append(s)
        out["t"].append(s * DT)
        out["total"].append(total)
        out["under"].append(under)
        out["ground"].append(ground)
        out["centroid"].append(cen)
        out["top"].append(top)
        out["u_inv"].append(np.interp(INV, ys, prof))
        out["dudy0"].append((prof[1] - prof[0]) / dy)
        grids[s] = g
    return {k: np.array(v) for k, v in out.items()}, grids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="etykieta=run_... (pierwszy: bez działka)")
    ap.add_argument("--docker", default="iga-ads-dev")
    ap.add_argument("--data", default="/tmp/pollution")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--out", type=Path, default=HERE / "przebiegi" / "analiza")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    names = {"bez": "bez działka", "emisja": "start w czasie emisji", "wznoszenie": "start w trakcie wznoszenia",
             "po": "start po uformowaniu"}
    runs = []
    for item in args.runs:
        label, run = item.split("=")
        d = f"{args.data}/{run}"
        par = params_of(args.docker, d)
        res, grids = analyse(args.docker, d, args.every)
        runs.append((label, names.get(label, label), run, par, res, grids))
        print(f"{label}: {run}, cannon_t={par['cannon_t']}, amp={par['cannon_amp']}")

    result = {}
    base = runs[0][4]

    # --- działko: przestrzeń ---
    par = next(r[3] for r in runs if r[3]["cannon_amp"] != 0)
    A, w, L, xc = par["cannon_amp"], par["cannon_width"], par["cannon_reach"], par["cannon_x"]
    X, Y = np.meshgrid(np.linspace(0, 1, 201), np.linspace(0, 1, 201))
    C = -A * np.exp(-((X - xc) / w) ** 2) * np.exp(-Y / L)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.3))
    im = ax[0].imshow(C, origin="lower", extent=[0, 1, 0, 1], cmap="Blues_r")
    fig.colorbar(im, ax=ax[0], label="cannon(x, y) w szczycie impulsu")
    ax[0].axhline(INV, color="k", ls="--", lw=1, label="inwersja")
    ax[0].plot(xc, 0, "^", color="red", ms=11, mec="k", clip_on=False, label="działko")
    ax[0].set_xlabel("x")
    ax[0].set_ylabel("y (wysokość)")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[0].set_title("rozkład przestrzenny (sin = 1)")
    yy = np.linspace(0, 1, 401)
    dTy = np.where(yy < INV, -LIFT, 0.0)
    ax[1].plot(-dTy, yy, label="bez działka: $-\\partial T/\\partial y$")
    ax[1].plot(-(dTy - A * np.exp(-yy / L)), yy, label="nad działkiem, szczyt impulsu")
    ax[1].axhline(INV, color="k", ls="--", lw=1)
    ax[1].set_xlabel("prędkość unoszenia $-(\\partial T/\\partial y + \\mathrm{cannon})$")
    ax[1].set_ylabel("y")
    ax[1].legend(fontsize=8)
    ax[1].set_title(f"profil w x = {xc}")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out / "cannon_przestrzen.png", dpi=120)
    plt.close(fig)

    # --- działko: czas ---
    tt = np.linspace(0, 0.3, 3001)
    shooters = [r for r in runs if r[3]["cannon_amp"] != 0]
    fig, axs = plt.subplots(len(shooters), 1, figsize=(10, 1.5 + 1.1 * len(shooters)), sharex=True)
    axs = np.atleast_1d(axs)
    for a, (lab, name, run, p, *_r) in zip(axs, shooters):
        a.fill_between(tt, pulse(tt, p), color="tab:red", alpha=0.6)
        a.set_ylabel("impuls", fontsize=8)
        a.set_ylim(0, 1.1)
        a.set_title(f"{name}: start t = {p['cannon_t']:g} (krok {round(p['cannon_t'] / DT)})", fontsize=9, loc="left")
        a.axvspan(0, 0.0253, color="gray", alpha=0.15)
        a.axvspan(0.1747, 0.2253, color="gray", alpha=0.15)
        a.grid(alpha=0.3)
    axs[-1].set_xlabel("t (szare: emisja przy ziemi)")
    sec = axs[0].secondary_xaxis("top", functions=(lambda t: t / DT, lambda k: k * DT))
    sec.set_xlabel("numer kroku")
    fig.tight_layout()
    fig.savefig(args.out / "cannon_czas.png", dpi=120)
    plt.close(fig)

    # --- powstawanie chmury (bez działka) ---
    t, cen, top = base["t"], base["centroid"], base["top"]
    first = t < 0.17
    win = (t >= 0.03) & (t <= 0.10)
    v_cen = np.polyfit(t[win], cen[win], 1)[0]
    v_top = np.polyfit(t[win], top[win], 1)[0]
    vel = np.gradient(cen, t)
    formed_idx = np.where(first & (t > 0.05) & (np.abs(vel) < 0.5 * LIFT))[0]
    t_formed = float(t[formed_idx[0]]) if len(formed_idx) else float("nan")
    reach_idx = np.where(first & (top >= INV - 0.02))[0]
    t_reach = float(t[reach_idx[0]]) if len(reach_idx) else float("nan")
    result["wznoszenie"] = {"v_srodek": v_cen, "v_czolo": v_top, "t_czolo_pod_inwersja": t_reach,
                            "t_uformowana": t_formed}
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(t, cen, label="środek masy chmury")
    ax.plot(t, top, label="górna krawędź (50% maksimum)")
    ax.plot(t[win], cen[win][0] + LIFT * (t[win] - t[win][0]), "k:", label="nachylenie 5,2 (kod)")
    ax.axhline(INV, color="k", ls="--", lw=1, label="inwersja")
    ax.axvline(t_formed, color="tab:green", lw=1, label=f"uformowana, t = {t_formed:.3f}")
    ax.axvspan(0, 0.0253, color="gray", alpha=0.15, label="emisja")
    ax.axvspan(0.1747, 0.2253, color="gray", alpha=0.15)
    ax.set_xlabel("t")
    ax.set_ylabel("y")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title("Wznoszenie chmury bez działka")
    fig.tight_layout()
    fig.savefig(args.out / "wznoszenie.png", dpi=120)
    plt.close(fig)

    # --- miary i masa ---
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    table = []
    for lab, name, run, p, r, _g in runs:
        for a in ax:
            pass
        ax[0].plot(r["t"], r["under"], label=name)
        ax[1].plot(r["t"], r["ground"], label=name)
        ax2.plot(r["t"], r["total"], label=name)
        row = {"wariant": name, "run": run, "start_t": p["cannon_t"] if p["cannon_amp"] else None,
               "pod_koniec": float(r["under"][-1]), "pod_srednia": float(np.trapezoid(r["under"], r["t"]) / (r["t"][-1] - r["t"][0])),
               "pod_t017": float(np.interp(0.17, r["t"], r["under"])), "ziemia_srednia": float(np.trapezoid(r["ground"], r["t"]) / (r["t"][-1] - r["t"][0])),
               "ziemia_max": float(r["ground"].max()), "calkowita_koniec": float(r["total"][-1]),
               "nad_koniec": float(r["total"][-1] - r["under"][-1])}
        table.append(row)
    for a, title in zip(ax, ["ilość pod inwersją $\\int_{y<0,8} u$", f"średnie stężenie przy ziemi (y < {GROUND})"]):
        a.set_title(title)
        a.set_xlabel("t")
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(args.out / "miary.png", dpi=120)
    ax2.set_title("całkowita ilość zanieczyszczeń $\\int_\\Omega u$")
    ax2.set_xlabel("t")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8)
    fig2.tight_layout()
    fig2.savefig(args.out / "masa_calkowita.png", dpi=120)
    plt.close("all")
    result["miary"] = table

    # --- bilans masy bez działka: dM/dt = ∫f - 5,2 ū(0,8) - K_y ū_y(0) ---
    t, M = base["t"], base["total"]
    src = np.array([9.375 * source_s(round(tt_ / DT)) for tt_ in t])
    inv_loss = LIFT * base["u_inv"]
    gnd_loss = KY * base["dudy0"]
    def integ(f):
        return np.concatenate([[0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(t))])
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(t, M, "k", lw=2, label="$\\int u$ z symulacji")
    ax.plot(t, integ(src - inv_loss - gnd_loss), "--", label="bilans: źródło − inwersja − ziemia")
    ax.plot(t, integ(src), ":", label="samo źródło $\\int f$")
    ax.plot(t, integ(inv_loss), label="ubytek na inwersji $5{,}2\\,\\bar u(0{,}8)$")
    ax.plot(t, integ(gnd_loss), label="ubytek do ziemi $K_y \\bar u_y(0)$")
    ax.set_xlabel("t")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title("Bilans masy bez działka")
    fig.tight_layout()
    fig.savefig(args.out / "bilans.png", dpi=120)
    plt.close(fig)
    result["bilans"] = {"zrodlo": float(integ(src)[-1]), "inwersja": float(integ(inv_loss)[-1]),
                        "ziemia": float(integ(gnd_loss)[-1]), "M_koniec": float(M[-1]),
                        "M_bilans": float(integ(src - inv_loss - gnd_loss)[-1])}

    # --- gdzie działko przenosi zanieczyszczenia: różnica po strzałach ---
    po = next((r for r in runs if r[0] == "po"), runs[-1])
    p = po[3]
    t_end_shots = p["cannon_t"] + (p["cannon_shots"] - 1) * p["cannon_period"] + p["cannon_duration"]
    common = sorted(set(runs[0][5]) & set(po[5]))
    s_pick = min(common, key=lambda s: abs(s * DT - t_end_shots))
    diff = po[5][s_pick] - runs[0][5][s_pick]
    lim = np.abs(diff).max()
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(diff, origin="lower", extent=[0, 1, 0, 1], cmap="RdBu_r", vmin=-lim, vmax=lim)
    fig.colorbar(im, ax=ax, label="u (z działkiem) − u (bez działka)")
    ax.axhline(INV, color="k", ls="--", lw=1)
    ax.plot(p["cannon_x"], 0, "^", color="red", ms=11, mec="k", clip_on=False)
    ax.set_title(f"{po[1]}: krok {s_pick}, t = {s_pick * DT:.3f}")
    ax.set_xlabel("x")
    ax.set_ylabel("y (wysokość)")
    fig.tight_layout()
    fig.savefig(args.out / "roznica.png", dpi=120)
    plt.close(fig)
    result["roznica"] = {"krok": s_pick, "t": s_pick * DT}

    (args.out / "wyniki.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=float))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
