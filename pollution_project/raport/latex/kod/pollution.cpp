// SPDX-FileCopyrightText: 2015 - 2021 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include "pollution.hpp"

int main(int argc, char* argv[]) {
    int n = 40;
    int p = 2;
    if (argc >= 3) {
        n = std::atoi(argv[1]);
        p = std::atoi(argv[2]);
    }

    ads::problems::heat_2d sim{ads::config_2d{
        ads::dim_config{p, n}, ads::dim_config{p, n},
        ads::timesteps_config{iterations, 1e-5}, 1}};

    for (int i = 4; i < argc; ++i) {
        std::string arg = argv[i];
        auto eq = arg.find('=');
        if (eq == std::string::npos)
            continue;
        std::string key = arg.substr(0, eq);
        double value = std::atof(arg.c_str() + eq + 1);
        if (key == "cannon_t")
            sim.cannon_t0 = value;
        else if (key == "cannon_amp")
            sim.cannon_amp = value;
        else if (key == "cannon_x")
            sim.cannon_x = value;
        else if (key == "cannon_n")
            sim.cannon_n = static_cast<int>(value);
        else if (key == "cannon_dx")
            sim.cannon_dx = value;
        else if (key == "cannon_shots")
            sim.cannon_shots = static_cast<int>(value);
        else {
            std::cerr << "nieznany parametr: " << arg
                      << "\nznane: cannon_t cannon_amp cannon_x cannon_n cannon_dx cannon_shots" << std::endl;
            std::exit(1);
        }
    }

    std::ofstream info{"params.csv"};
    info << "N,p,dt,t_end,inversion_y,cannon_t,cannon_amp,cannon_x,cannon_n,cannon_dx,"
            "cannon_shots,cannon_period,cannon_duration,cannon_width,cannon_reach\n"
         << n << ',' << p << ",1e-5," << iterations * 1e-5 << ",0.8,"
         << sim.cannon_t0 << ',' << sim.cannon_amp << ',' << sim.cannon_x << ','
         << sim.cannon_n << ',' << sim.cannon_dx << ',' << sim.cannon_shots << ','
         << sim.cannon_period << ',' << sim.cannon_duration << ',' << sim.cannon_width << ','
         << sim.cannon_reach << '\n';

    sim.run();
}
