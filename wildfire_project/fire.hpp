// SPDX-FileCopyrightText: 2015 - 2024 Marcin Łoś <marcin.los.91@gmail.com>
// SPDX-License-Identifier: MIT

#ifndef FIRE_FIRE_HPP
#define FIRE_FIRE_HPP

#include <algorithm>
#include <cmath>

#include "ads/executor/galois.hpp"
#include "ads/output_manager.hpp"
#include "ads/simulation.hpp"
#include "ads/util.hpp"

// Schematic of the 2018 Camp Fire on the model square [0, 100]^2.
// x grows east, y grows north. Not a georeferenced map.
//   Pulga (ignition)     (82, 62)
//   Concow               (68, 64)
//   Paradise             (48, 52)
//   Magalia              (50, 70)
//   Lake Oroville        southwest of Paradise
//   Feather River        canyon axis from the NE rim into the lake

inline double falloff(double r, double R, double t) {
    if (t < r)
        return 1.0;
    if (t > R)
        return 0.0;
    double h = (t - r) / (R - r);
    return std::pow((h - 1) * (h + 1), 2);
}

inline double smoothstep(double edge0, double edge1, double x) {
    if (x <= edge0)
        return 0.0;
    if (x >= edge1)
        return 1.0;
    double s = (x - edge0) / (edge1 - edge0);
    return s * s * (3.0 - 2.0 * s);
}

// 1 inside the ellipse, 0 outside, with a soft edge.
inline double ellipse_mask(double x, double y, double cx, double cy, double rx, double ry) {
    double n = std::pow((x - cx) / rx, 2) + std::pow((y - cy) / ry, 2);
    return 1.0 - smoothstep(0.55, 1.15, n);
}

// Distance to the Feather River / Jarbo Gap axis (Pulga rim -> Lake Oroville).
inline double canyon_distance(double x, double y) {
    const double ax = 90.0;
    const double ay = 80.0;
    const double bx = 40.0;
    const double by = 16.0;
    double dx = bx - ax;
    double dy = by - ay;
    double L2 = dx * dx + dy * dy;
    double t = ((x - ax) * dx + (y - ay) * dy) / L2;
    t = std::max(0.0, std::min(1.0, t));
    return std::hypot(x - (ax + t * dx), y - (ay + t * dy));
}

namespace ads::problems {

class fire : public simulation_2d {
private:
    using Base = simulation_2d;
    vector_type u, u_prev;

    vector_type fuel, fuel_prev;

    double ch = 1.0;
    double Ar = 5.7e-5;
    double rho = 1.293;
    double cp = 1.0;
    double cw = 0.5;
    double kappa = 0.3;
    double xi = 2e-2;
    double sigma = 5.67e-8;
    double eps = 0.05; // "percentage error"
    double delta_x = 3.5e-2 / eps;
    double delta_z = 1.5 * eps;
    double T0 = 300;
    double Tcomb = 1200;
    double Tig = 800;
    double Ta = 300; // ???

    double M = 2;
    double M1 = 1;

    galois_executor executor;
    output_manager<2> output;

public:
    explicit fire(const config_2d& config, int threads)
    : Base{config}
    , u{shape()}
    , u_prev{shape()}
    , fuel{shape()}
    , fuel_prev{shape()}
    , executor{threads}
    , output{x.B, y.B, 300} { }

    // Point ignition under the Pulga transmission line, morning of 8 Nov 2018.
    // Hot core is a few model units across; the rest of the domain stays at T0.
    double init_state(double x, double y) {
        const double x0 = 82.0;
        const double y0 = 62.0;
        double d = std::hypot(x - x0, y - y0);
        return T0 + Tcomb * falloff(2.5, 7.0, d);
    }

    // 1 = continuous dry wildland fuel, 0 = water (nothing to burn).
    // Towns stay flammable: the real fire burned through the WUI.
    double fuel_map(double x, double y) const {
        double easting = (0.45 * x + 0.55 * y) / 100.0;
        double fuel = 0.75 + 0.23 * easting;

        fuel += (1.00 - fuel) * ellipse_mask(x, y, 68.0, 64.0, 8.0, 6.0);  // Concow
        fuel += (0.62 - fuel) * ellipse_mask(x, y, 48.0, 52.0, 11.0, 8.0); // Paradise
        fuel += (0.72 - fuel) * ellipse_mask(x, y, 50.0, 70.0, 8.0, 6.0);  // Magalia

        double lake = ellipse_mask(x, y, 28.0, 26.0, 24.0, 16.0);
        double river = 1.0 - smoothstep(2.2, 3.8, canyon_distance(x, y));
        double water = std::max(lake, river);
        fuel *= (1.0 - water);

        return std::max(0.0, std::min(1.0, fuel));
    }

    // Jarbo Gap wind. Velocity points mostly west, a little south (from the NE).
    // t = 0 is sunrise on 8 Nov (peak), the lull is midday, a second pulse is the evening.
    // The run t in [0, 10] stands in for that first day. Peak speed is 12 in the
    // model's wind units; the explicit step is unstable near the old value of 40.
    void wind_velocity(double x, double y, double t, double& bx, double& by) const {
        double morning = std::exp(-std::pow(t / 2.2, 2));
        double evening = std::exp(-std::pow((t - 7.0) / 1.8, 2));
        double strength = 0.25 + 0.75 * morning + 0.40 * evening;

        double channel = std::exp(-std::pow(canyon_distance(x, y) / 22.0, 2));
        // Peak 12, not 40: the explicit step goes negative and then NaN at the higher value.
        double speed = 12.0 * strength * (0.62 + 0.38 * channel);

        double turn = 1.0 - morning; // evening flow spreads more to the south
        double dirx = -0.96 + 0.16 * turn;
        double diry = -0.28 - 0.32 * turn;
        double norm = std::hypot(dirx, diry);
        bx = speed * dirx / norm;
        by = speed * diry / norm;
    }

private:
    void before() override {
        prepare_matrices();

        auto init = [this](double x, double y) { return init_state(x, y); };
        projection(u, init);
        solve(u);
        output.to_file(u, "out_0.data");

        auto fuel_init = [this](double x, double y) { return fuel_map(x, y); };
        projection(fuel, fuel_init);
        solve(fuel);
        output.to_file(fuel, "fuel_0.data");
    }

    void before_step(int /*iter*/, double /*t*/) override {
        using std::swap;
        swap(u, u_prev);
        swap(fuel, fuel_prev);
    }

    void step(int /*iter*/, double t) override {
        compute_rhs(t);
        solve(u);
        solve(fuel);
    }

    void compute_rhs(double t) {
        auto& rhs = u;
        auto& rhs_fuel = fuel;

        zero(rhs);
        zero(rhs_fuel);
        executor.for_each(elements(), [&](index_type e) {
            auto U = element_rhs();
            auto F = element_rhs();

            double J = jacobian(e);
            for (auto q : quad_points()) {
                double w = weight(q);
                auto p = point(e, q);
                double x = p[0];
                double y = p[1];
                double bx, by;
                wind_velocity(x, y, t, bx, by);

                value_type u = eval_fun(u_prev, e, q);
                value_type fuel = eval_fun(fuel_prev, e, q);

                for (auto a : dofs_on_element(e)) {
                    auto aa = dof_global_to_local(e, a);
                    value_type v = eval_basis(e, q, a);
                    double inv = 1.0 / (rho * cp);

                    // Spline ringing near the ignition can drive T below 0. pow() and
                    // exp(-Ta/T) then overflow, and 0*inf becomes NaN for the whole field.
                    double T = std::max(u.val, 0.0);
                    double delta = T > Tig && fuel.val > 0.2 ? 1.0 : 0.0;
                    double hc = -70; // enthalpy
                    double r = 0.0;
                    if (delta > 0.0)
                        r = Ar * T * std::exp(-Ta / T);
                    double Rc = - 1e4 * rho * ch * hc * M / M1 * r;
                    double Qw = - rho * cw * (bx * u.dx + by * u.dy);
                    double qc = - kappa * grad_dot(u, v);
                    double qd = 0.0; // omitted
                    double qr = -4 * sigma * eps * delta_x * std::pow(T, 3) * grad_dot(u, v);
                    double Qconv = xi * (T0 - T);
                    double Qrz = sigma * eps / delta_z * (std::pow(T0, 4) - std::pow(T, 4));

                    double val = (Rc + Qw + Qconv + Qrz) * v.val + qc + qd + qr;
                    U(aa[0], aa[1]) += (u.val * v.val + steps.dt * inv * val) * w * J;

                    double fval = - delta * 3e2 * r * fuel.val * v.val;
                    F(aa[0], aa[1]) += (fuel.val * v.val + steps.dt * fval) * w * J;
                }
            }
            executor.synchronized([&] { update_global_rhs(rhs, U, e); });
            executor.synchronized([&] { update_global_rhs(rhs_fuel, F, e); });
        });
    }

    void after_step(int iter, double /*t*/) override {
        auto i = iter  +1;
        if (i % 10 == 0) {
            std::cout << "Step " << i << std::endl;
            output.to_file(u, "out_%d.data", i);
            output.to_file(fuel, "fuel_%d.data", i);
        }
    }

    // double forcing(point_type x, double /*t*/) const {
    //     return 0;
    // }
};

}  // namespace ads::problems

#endif  // FIRE_FIRE_HPP
