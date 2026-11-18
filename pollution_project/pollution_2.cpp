// SPDX-FileCopyrightText: 2015 - 2023 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <string>

#include "pollution.hpp"

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: pollution_spcia <N> <p> <threads> [nazwa=wartość ...]" << std::endl;
        std::exit(1);
    }
    int n = std::atoi(argv[1]);
    int p = std::atoi(argv[2]);
    int threads = std::atoi(argv[3]);

    // Parametry do strojenia (opis w pollution.hpp, struct pollution_params), np. wind_speed=8 diff=40
    ads::pollution_params par;
    std::map<std::string, double*> real{
        {"dt", &par.dt},           {"t_end", &par.t_end}, {"wind_speed", &par.wind_speed},
        {"diff", &par.diff},       {"ambient", &par.ambient},
        {"src_x", &par.src_x},     {"src_y", &par.src_y}, {"src_r", &par.src_r},
    };
    std::map<std::string, int*> whole{{"out_every", &par.out_every}};
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

    ads::dim_config dim{p, n, 0.0, 5000.0};
    int nsteps = static_cast<int>(std::lround(par.t_end / par.dt));
    ads::timesteps_config steps{nsteps, par.dt};
    int ders = 1;

    ads::config_2d c{dim, dim, steps, ders};
    ads::pollution sim{c, par, threads};
    sim.run();
}
