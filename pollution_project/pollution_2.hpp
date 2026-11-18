// SPDX-FileCopyrightText: 2015 - 2023 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#ifndef POLLUTION_POLLUTION_HPP
#define POLLUTION_POLLUTION_HPP

#include <cmath>
#include <iomanip>
#include <iostream>

#include "ads/executor/galois.hpp"
#include "ads/output_manager.hpp"
#include "ads/simulation.hpp"

// Punkt startowy: przykład pollution_2d z IGA-ADS (gałąź spciaa). Obszar [0, 5000]^2 m,
// komin w (3000, 400), wiatr 5 m/s o kierunku zmiennym w czasie, schemat ADI.

namespace ads {

// Parametry do strojenia, nadpisywane z linii poleceń: pollution <N> <p> <wątki> [nazwa=wartość ...]
struct pollution_params {
    double dt = 10;           // krok czasu [s]
    double t_end = 6000;      // koniec symulacji [s]
    double wind_speed = 5;    // [m/s]
    double diff = 20;         // dyfuzja w x i y [m^2/s]
    double ambient = 1e-6;    // stężenie tła [g/m^3]
    double src_x = 3000;      // komin [m]
    double src_y = 400;
    double src_r = 25;        // promień źródła [m]
    int out_every = 10;       // zapis .data co tyle kroków
};

class pollution : public simulation_2d {
private:
    using Base = simulation_2d;
    vector_type u, u_prev;

    pollution_params par;

    output_manager<2> output;
    galois_executor executor;

    lin::band_matrix Kx, Ky;
    lin::solver_ctx Kx_ctx, Ky_ctx;

    double ambient;
    double Vd = 0.1;
    point_type c_diff;  // m/s^2

    double wind_angle = 2 * M_PI / 4;
    double wind_speed;

    point_type wind;

    double absorbed = 0.0;

public:
    pollution(const config_2d& config, const pollution_params& params, int threads)
    : Base{config}
    , u{shape()}
    , u_prev{shape()}
    , par{params}
    , output{x.B, y.B, 400}
    , executor{threads}
    , Kx{x.p, x.p, x.B.dofs()}
    , Ky{y.p, y.p, y.B.dofs()}
    , Kx_ctx{Kx}
    , Ky_ctx{Ky}
    , ambient{params.ambient}
    , c_diff{{params.diff, params.diff}}
    , wind_speed{params.wind_speed}
    , wind{{wind_speed * cos(wind_angle), wind_speed * sin(wind_angle)}} {
        matrix(Kx, x.basis, steps.dt / 2, c_diff[0], wind[0]);
        matrix(Ky, y.basis, steps.dt / 2, c_diff[1], wind[1]);
    }

private:
    void diffusion_matrix(lin::band_matrix& M, const basis_data& d, double h, double diffusion) {
        for (element_id e = 0; e < d.elements; ++e) {
            for (int q = 0; q < d.quad_order; ++q) {
                int first = d.first_dof(e);
                int last = d.last_dof(e);
                for (int a = 0; a + first <= last; ++a) {
                    for (int b = 0; b + first <= last; ++b) {
                        int ia = a + first;
                        int ib = b + first;
                        auto da = d.b[e][q][1][a];
                        auto db = d.b[e][q][1][b];
                        auto diff = diffusion * h * da * db;
                        M(ia, ib) += diff * d.w[q] * d.J[e];
                    }
                }
            }
        }
    }

    void advection_matrix(lin::band_matrix& M, const basis_data& d, double h, double advection) {
        for (element_id e = 0; e < d.elements; ++e) {
            for (int q = 0; q < d.quad_order; ++q) {
                int first = d.first_dof(e);
                int last = d.last_dof(e);
                for (int a = 0; a + first <= last; ++a) {
                    for (int b = 0; b + first <= last; ++b) {
                        int ia = a + first;
                        int ib = b + first;
                        auto va = d.b[e][q][0][a];
                        auto db = d.b[e][q][1][b];
                        auto adv = advection * h * va * db;

                        M(ia, ib) += adv * d.w[q] * d.J[e];
                    }
                }
            }
        }
    }

    void matrix(lin::band_matrix& K, const basis_data& d, double h, double diffusion,
                double advection) {
        gram_matrix_1d(K, d);
        diffusion_matrix(K, d, h, diffusion);
        advection_matrix(K, d, h, advection);
    }

    double emission(double x, double y) const {
        double dx = (x - par.src_x) / par.src_r;
        double dy = (y - par.src_y) / par.src_r;
        double r2 = std::min((dx * dx + dy * dy), 1.0);
        return (r2 - 1) * (r2 - 1) * (r2 + 1) * (r2 + 1);  // g/m^3
    }

    void prepare_implicit_matrices() {
        Kx.zero();
        Ky.zero();
        matrix(Kx, x.basis, steps.dt / 2, c_diff[0], wind[0]);
        matrix(Ky, y.basis, steps.dt / 2, c_diff[1], wind[1]);

        lin::factorize(Kx, Kx_ctx);
        lin::factorize(Ky, Ky_ctx);
    }

    void prepare_matrices() {
        Base::prepare_matrices();
        prepare_implicit_matrices();
    }

    void before() override {
        prepare_matrices();

        auto init = [this](double /*x*/, double /*y*/) { return ambient; };

        projection(u, init);
        solve(u);

        output.to_file(u, "out_0.data");
    }

    void before_step(int /*iter*/, double /*t*/) override {
        using std::swap;
        swap(u, u_prev);
    }

    void step(int /*iter*/, double /*t*/) override {
        compute_rhs_x();
        ads_solve(u, buffer, dim_data{Kx, Kx_ctx}, y.data());

        using std::swap;
        swap(u, u_prev);

        compute_rhs_y();
        ads_solve(u, buffer, x.data(), dim_data{Ky, Ky_ctx});
    }

    void after_step(int iter, double t) override {
        int i = iter + 1;
        if (i % par.out_every == 0) {
            output.to_file(u, "out_%d.data", i);
            analyze(i, t + 0.5 * steps.dt);
        }

        auto s = t / 150;
        auto phase = sin(s) + 0.5 * sin(2.3 * s);
        wind_angle = M_PI / 3 * phase + 1.5 * M_PI / 4;

        wind = {wind_speed * cos(wind_angle), wind_speed * sin(wind_angle)};
        prepare_implicit_matrices();
    }

    double grad_dot(point_type a, value_type u) const { return a[0] * u.dx + a[1] * u.dy; }

    point_type local_wind(double /*x*/, double /*y*/) const { return {}; }

    void compute_rhs_x() {
        auto& rhs = u;

        zero(rhs);

        executor.for_each(elements(), [&](index_type e) {
            auto U = element_rhs();
            auto h = 0.5 * steps.dt;

            double J = jacobian(e);
            for (auto q : quad_points()) {
                double w = weight(q);
                auto x = point(e, q);
                value_type u = eval_fun(u_prev, e, q);

                for (auto a : dofs_on_element(e)) {
                    auto aa = dof_global_to_local(e, a);
                    value_type v = eval_basis(e, q, a);

                    auto wind_loc = local_wind(x[0], x[1]);
                    double conv_term = (wind[1] * u.dy + grad_dot(wind_loc, u)) * v.val;

                    double gradient_prod = u.dy * v.dy;
                    double e = emission(x[0], x[1]) * v.val;
                    double val = u.val * v.val + h * (-conv_term - c_diff[1] * gradient_prod + e);

                    U(aa[0], aa[1]) += val * w * J;
                }
            }

            executor.synchronized([&]() { update_global_rhs(rhs, U, e); });
        });
    }

    void compute_rhs_y() {
        auto& rhs = u;

        zero(rhs);

        executor.for_each(elements(), [&](index_type e) {
            auto U = element_rhs();
            auto h = 0.5 * steps.dt;

            double J = jacobian(e);
            for (auto q : quad_points()) {
                double w = weight(q);
                auto x = point(e, q);
                value_type u = eval_fun(u_prev, e, q);

                for (auto a : dofs_on_element(e)) {
                    auto aa = dof_global_to_local(e, a);
                    value_type v = eval_basis(e, q, a);

                    auto wind_loc = local_wind(x[0], x[1]);
                    double conv_term = (wind[0] * u.dx + grad_dot(wind_loc, u)) * v.val;

                    double gradient_prod = u.dx * v.dx;
                    double e = emission(x[0], x[1]) * v.val;
                    double val = u.val * v.val + h * (-conv_term - c_diff[0] * gradient_prod + e);
                    U(aa[0], aa[1]) += val * w * J;
                }
            }

            executor.synchronized([&] { update_global_rhs(rhs, U, e); });
        });
    }

    void analyze(int step, double t) {
        double total = 0.0;
        double emission_rate = 0.0;
        for (auto e : elements()) {
            double J = jacobian(e);
            for (auto q : quad_points()) {
                double w = weight(q);
                auto x = point(e, q);
                value_type u = eval_fun(u_prev, e, q);

                total += u.val * w * J;
                emission_rate += emission(x[0], x[1]) * w * J;
            }
        }

        using std::setw, std::setprecision;

        total /= 1000;          // g -> kg
        emission_rate /= 1000;  // g -> kg

        auto emitted = t * emission_rate;      // kg
        auto area = 5000.0 * 5000.0;           // m^2
        auto initial = area * ambient / 1000;  // kg
        auto absorbed_kg = absorbed / 1000;
        auto loss = initial + emitted - total - absorbed_kg;
        auto loss_percent = 100 * loss / emitted;

        std::cout << "Step " << step << ":"
                  << "  total " << setw(8) << setprecision(5) << total << " kg "
                  << "  absorbed " << setw(8) << setprecision(5) << absorbed_kg << " kg "
                  << "  (loss " << setw(6) << loss << " kg,  " << setw(5) << loss_percent << "%)"
                  << std::endl;
    }
};

}  // namespace ads

#endif  // POLLUTION_POLLUTION_HPP
