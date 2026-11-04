// SPDX-FileCopyrightText: 2015 - 2024 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <string>

#include "fire.hpp"

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: fire <N> <p> <threads> [nazwa=wartość ...]" << std::endl;
        std::exit(1);
    }
    int n = std::atoi(argv[1]);
    int p = std::atoi(argv[2]);
    int threads = std::atoi(argv[3]);

    // Parametry do strojenia (opis w fire.hpp, struct fire_params), np. rad=0.007 cw=1.5 TU=0.4
    ads::problems::fire_params par;
    std::map<std::string, double*> real{
        {"rad", &par.rad},   {"loss", &par.loss},         {"cw", &par.cw},
        {"Tig", &par.Tig},   {"fuel_min", &par.fuel_min}, {"heat", &par.heat},
        {"burn", &par.burn}, {"dt", &par.dt},             {"t_end", &par.t_end},
        // wagi paliwa
        {"SH", &par.SH},       {"GS", &par.GS},       {"GR", &par.GR},     {"TU", &par.TU},
        {"TL", &par.TL},       {"SB", &par.SB},       {"urban", &par.urban}, {"agri", &par.agri},
        {"rock", &par.rock},   {"water", &par.water}, {"snow", &par.snow}, {"other", &par.other},
        {"river", &par.river},
    };
    std::map<std::string, int*> whole{{"fuel_heat", &par.fuel_heat}, {"out_every", &par.out_every}};
    for (int i = 4; i < argc; ++i) {
        std::string arg = argv[i];
        auto eq = arg.find('=');
        std::string key = arg.substr(0, eq);
        if (eq != std::string::npos && real.count(key)) {
            *real[key] = std::atof(arg.c_str() + eq + 1);
        } else if (eq != std::string::npos && whole.count(key)) {
            *whole[key] = std::atoi(arg.c_str() + eq + 1);
        } else {
            std::cerr << "nieznany parametr: " << arg << "\nznane:";
            for (auto& [k, v] : real)
                std::cerr << ' ' << k;
            for (auto& [k, v] : whole)
                std::cerr << ' ' << k;
            std::cerr << std::endl;
            std::exit(1);
        }
    }

    // params.csv obok wyników (nagłówek + jeden wiersz): opis przebiegu, animate.py bierze z niego dt
    std::ofstream info{"params.csv"};
    info << "N,p";
    for (auto& [k, v] : real)
        info << ',' << k;
    for (auto& [k, v] : whole)
        info << ',' << k;
    info << '\n' << n << ',' << p;
    for (auto& [k, v] : real)
        info << ',' << *v;
    for (auto& [k, v] : whole)
        info << ',' << *v;
    info << '\n';

    // Camp Fire: kwadrat [0, 100]^2 = 30 x 30 km (x na wschód, y na północ).
    // t in [0, 10] to 8 XI 2018 6:25-11:25 (1 jednostka czasu = 0,5 h), patrz fire.hpp.
    ads::dim_config dim{p, n, 0.0, 100.0};
    int nsteps = static_cast<int>(std::lround(par.t_end / par.dt));
    ads::timesteps_config steps{nsteps, par.dt};
    int ders = 1;

    ads::config_2d c{dim, dim, steps, ders};
    ads::problems::fire sim{c, par, threads};
    sim.run();
}
