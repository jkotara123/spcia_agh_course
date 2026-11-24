// SPDX-FileCopyrightText: 2015 - 2021 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#ifndef HEAT_HEAT_2D_HPP
#define HEAT_HEAT_2D_HPP

#include <galois/Timer.h>
#include <cmath>
#include <iostream>

#include "ads/output_manager.hpp"
#include "ads/simulation.hpp"

const int iterations = 30000;
namespace ads::problems {

class heat_2d : public simulation_2d {
private:
    using Base = simulation_2d;
    vector_type u, u_prev;

    output_manager<2> output;

public:
    // Patrz cannon(). cannon_amp = 0 wyłącza działko, cannon_t = 0 strzela od razu.
    // cannon_n działek co cannon_dx, symetrycznie wokół cannon_x (np. cannon_n=3: 0.2, 0.5, 0.8).
    // double cannon_t0 = 0.16;
    double cannon_t0 = 0.07;

    
    double cannon_amp = 80;
    double cannon_x = 0.5;
    int cannon_n = 1;
    double cannon_dx = 0.3;

    explicit heat_2d(const config_2d& config)
    : Base{config}
    , u{shape()}
    , u_prev{shape()}
    , output{x.B, y.B, 200} { }

    double init_state(double x, double y) {
        return 0;
        // double dx = x - 0.5;
        // double dy = y - 0.5;
        // double r2 = std::min(8 * (dx * dx + dy * dy), 1.0);
        // return (r2 - 1) * (r2 - 1) * (r2 + 1) * (r2 + 1);
    };

private:

    // Dół (y = 0): u = 0, bo unoszenie wnosi tędy powietrze do obszaru, a od ziemi napływa
    // czyste powietrze. Bez tego warunku wartość przy ziemi stoi w miejscu i bez końca zasila chmurę.
    // Góra (y = 1) i boki: naturalny warunek grad u . n = 0 jak na slajdach, nic nie znika.
    void prepare_matrices() {
        y.fix_left();
        Base::prepare_matrices();
    }

    void before() override {
        prepare_matrices();

        auto init = [this](double x, double y) { return init_state(x, y); };
        projection(u, init);
        solve(u);

        output.to_file(u, "init.data");
    }

    double s;
    void before_step(int iter, double /*t*/) override {
        using std::swap;
        swap(u, u_prev);
        const double d = 0.7;
        const double c = 10000;
        s = std::max(((cos(iter * 3.14159265358979 / c) - d) * 1 / (1-d)), 0.);
        if (iter % 100 == 0)
            std::cout << iter << "/" << iterations << " (s=" << s << ")" << std::endl;
    }

    void step(int iter, double t) override {
        compute_rhs(iter, t);
        solve(u);
    }

    void after_step(int iter, double /*t*/) override {
        if (iter % 100 == 0) {
            output.to_file(u, "out_%d.data", iter);
        }
    }

    // Źródło przy ziemi; y to wysokość punktu kwadratury (działa dla każdej siatki).
    double f(double y) {
        if (y <= 0.125) return (150 - 1200 * y) * s;
        return 0;
    }

    // Gradient temperatury: unoszenie pod inwersją (y < 0.8), brak nad nią.
    double dTy(double y) {
      if (y >= 0.8) return 0;
      return -5.2;
    }

    // Działko. Wynik jest dodawany do dTy.
    // dTy = -5.2 pod pokrywą inwersji (y < 0.8) i 0 nad nią, więc chmura
    // dochodzi do y = 0.8 i staje. Ujemny impuls w wąskiej kolumnie nad armatą
    // przedłuża ruch w górę przez pokrywę.
    // Strzał dopiero po uformowaniu chmury: źródło gaśnie ok. t = 0.025,
    // a dojście do pokrywy trwa ok. 0.8 / 5.2 ≈ 0.15.
    double cannon_width = 0.08;
    double cannon_reach = 1.0;
    double cannon_duration = 0.03;
    double cannon_period = 0.06;

    double cannon(double x, double y, double t) const {
        if (t < cannon_t0 || cannon_amp == 0.0)
            return 0.0;
        double phase = std::fmod(t - cannon_t0, cannon_period);
        if (phase >= cannon_duration)
            return 0.0;
        const double pi = 3.14159265358979;
        double pulse = std::sin(pi * phase / cannon_duration);
        double column = 0.0;
        for (int k = 0; k < cannon_n; ++k) {
            double xc = cannon_x + (k - (cannon_n - 1) / 2.0) * cannon_dx;
            column += std::exp(-std::pow((x - xc) / cannon_width, 2));
        }
        double reach = std::exp(-y / cannon_reach);
        return -cannon_amp * column * reach * pulse;
    }

    const double k_x = 1.0, k_y = 0.1;
    void compute_rhs(int /*iter*/, double t) {
        auto& rhs = u;

        zero(rhs);
        for (auto e : elements()) {
            double J = jacobian(e);
            for (auto q : quad_points()) {
                double w = weight(q);
                auto p = point(e, q);
                double x = p[0];
                double y = p[1];
                for (auto a : dofs_on_element(e)) {
                    value_type v = eval_basis(e, q, a);
                    value_type u = eval_fun(u_prev, e, q);

                    double gradient_prod = k_x * u.dx * v.dx + k_y * u.dy * v.dy;
                    double val = u.val * v.val - steps.dt * gradient_prod
                        + steps.dt * (dTy(y) + cannon(x, y, t)) * u.dy * v.val
                        + steps.dt * f(y) * v.val;
                    rhs(a[0], a[1]) += val * w * J;
                }
            }
        }
    }

};

}  // namespace ads::problems

#endif  // HEAT_HEAT_2D_HPP