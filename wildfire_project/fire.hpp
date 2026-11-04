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
#include "camp_fire_data.hpp"

// Camp Fire, 8 XI 2018, na kwadracie modelu [0, 100]^2: x na wschód, y na północ,
// 1 jednostka = 300 m (obszar 30 x 30 km). Dane z prawdziwych pomiarów, przeliczone przez
// przygotuj_model.py do camp_fire_data.hpp:
//   paliwo  - LANDFIRE 2016 FBFM40 (stan przed pożarem) + rzeki z OpenStreetMap
//   wiatr   - stacja RAWS Jarbo Gap (JBGC1), pomiary co godzinę
//   zapłon  - pierwsza obserwacja NIST TN 2135 (linia przesyłowa koło Pulga)
// Czas: t = 0 to zapłon o 6:25, 1 jednostka czasu = 0,5 h, więc t in [0, 10] to 6:25-11:25.

inline double falloff(double r, double R, double t) {
    if (t < r)
        return 1.0;
    if (t > R)
        return 0.0;
    double h = (t - r) / (R - r);
    return std::pow((h - 1) * (h + 1), 2);
}

// Liniowa interpolacja tabeli (xs rosnące); poza zakresem wartość z końca.
inline double interp_table(const double* xs, const double* ys, int n, double x) {
    if (x <= xs[0])
        return ys[0];
    if (x >= xs[n - 1])
        return ys[n - 1];
    int i = 1;
    while (xs[i] < x)
        ++i;
    double h = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
    return (1 - h) * ys[i - 1] + h * ys[i];
}

namespace ads::problems {

// Parametry do strojenia, nadpisywane z linii poleceń: fire <N> <p> <threads> [nazwa=wartość ...]
//
// Front ognia musi być szerszy niż element siatki (100 / N = 1,25), inaczej "zacina się" na liniach
// siatki i gaśnie albo idzie wzdłuż osi. Stąd rad, loss razy 6 i heat, burn przez 6 względem
// wartości ze slajdów (0.035 / 1.5 / 1 / 300): lokalne spalanie trwa 6 razy dłużej, ale progi
// zapłonu i gaśnięcia są te same, a front jest ok. 6 razy szerszy. Wartości dobrane porównaniem
// z obserwacjami NIST (porownaj_nist.py).
struct fire_params {
    double rad = 0.16;      // promieniowanie: delta_x = rad / eps; prędkość frontu rośnie jak sqrt(rad)
    double loss = 9;        // straty ciepła w górę: delta_z = loss * eps (mniej = większe straty)
    double cw = 0.5;        // jak mocno wiatr niesie ciepło
    double Tig = 800;       // temperatura zapłonu
    double fuel_min = 0.2;  // od ilu paliwa komórka się pali
    double heat = 1.0 / 6;  // mnożnik ciepła spalania Rc
    double burn = 50;       // tempo wypalania paliwa
    int fuel_heat = 1;      // 1 = ciepło spalania razy waga klasy paliwa (krzewy grzeją mocniej niż podszyt)
    double dt = 1e-3;
    double t_end = 10;      // 10 = 11:25
    int out_every = 250;    // zapis .data co tyle kroków (250 = ok. 40 klatek do animacji)

    // Wagi paliwa 0..1 dla klas LANDFIRE (mapa klas w camp_fire_data.hpp, podgląd: model_paliwo.png).
    // Pali się tylko paliwo > fuel_min; więcej paliwa = dłużej płonie. Przy fuel_heat = 1 waga
    // klasy mnoży też ciepło spalania Rc.
    // Przy heat = 1/6 ogień sam się utrzymuje od wagi ok. 0.55; niżej gaśnie (chyba że sąsiedzi grzeją).
    double SH = 1.00;     // krzewy (chaparral)
    double GS = 1.00;     // trawy z krzewami
    double GR = 0.80;     // trawy
    double TU = 0.50;     // podszyt leśny: wg NIST ogień go omijał (29% obszaru, 5% obserwacji)
    double TL = 0.90;     // ściółka leśna: sosny na grzbiecie Paradise, 45% obserwacji NIST
    double SB = 1.00;     // pozostałości po wycince
    double urban = 0.90;  // zabudowa: domy w Paradise i Magalia spłonęły
    double agri = 0.15;   // pola uprawne (nawadniane)
    double rock = 0.05;   // skały, piach
    double water = 0.0;   // woda (jezioro Oroville)
    double snow = 0.0;
    double other = 0.50;  // kody spoza listy
    double river = 0.55;  // pas 150 m przy rzece: min(waga klasy, river)

    double fuel_weight(unsigned char code) const {
        double w = other;
        switch (code & ~camp_fire::RIVER) {
        case camp_fire::URBAN: w = urban; break;
        case camp_fire::SNOW: w = snow; break;
        case camp_fire::AGRI: w = agri; break;
        case camp_fire::WATER: w = water; break;
        case camp_fire::ROCK: w = rock; break;
        case camp_fire::GR: w = GR; break;
        case camp_fire::GS: w = GS; break;
        case camp_fire::SH: w = SH; break;
        case camp_fire::TU: w = TU; break;
        case camp_fire::TL: w = TL; break;
        case camp_fire::SB: w = SB; break;
        default: break;
        }
        return code & camp_fire::RIVER ? std::min(w, river) : w;
    }
};

class fire : public simulation_2d {
private:
    using Base = simulation_2d;
    vector_type u, u_prev;

    vector_type fuel, fuel_prev;

    double ch = 1.0;
    double Ar = 5.7e-5;
    double rho = 1.293;
    double cp = 1.0;
    double cw;
    double kappa = 0.3;
    double xi = 2e-2;
    double sigma = 5.67e-8;
    double eps = 0.05; // "percentage error"
    double delta_x;
    double delta_z;
    double T0 = 300;
    double Tcomb = 1200;
    double Tig;
    double Ta = 300; // ???

    double M = 2;
    double M1 = 1;

    fire_params par;

    galois_executor executor;
    output_manager<2> output;

public:
    explicit fire(const config_2d& config, const fire_params& params, int threads)
    : Base{config}
    , u{shape()}
    , u_prev{shape()}
    , fuel{shape()}
    , fuel_prev{shape()}
    , cw{params.cw}
    , delta_x{params.rad / eps}
    , delta_z{params.loss * eps}
    , Tig{params.Tig}
    , par{params}
    , executor{threads}
    , output{x.B, y.B, 300} { }

    // Zapłon w miejscu pierwszej obserwacji NIST (6:25), gorący rdzeń ok. 0,75 km, otoczka do 2 km.
    double init_state(double x, double y) {
        double d = std::hypot(x - camp_fire::IGNITION_X, y - camp_fire::IGNITION_Y);
        return T0 + Tcomb * falloff(2.5, 7.0, d);
    }

    // Paliwo z siatki klas LANDFIRE: waga klasy z fire_params, interpolacja dwuliniowa.
    double fuel_map(double x, double y) const {
        const int n = camp_fire::FUEL_N;
        double gx = std::clamp(x / 100.0 * (n - 1), 0.0, n - 1.0);
        double gy = std::clamp(y / 100.0 * (n - 1), 0.0, n - 1.0);
        int i = std::min(static_cast<int>(gx), n - 2);
        int j = std::min(static_cast<int>(gy), n - 2);
        double hx = gx - i;
        double hy = gy - j;
        auto f = [this, n](int a, int b) { return par.fuel_weight(camp_fire::FUEL_CLASS[b * n + a]); };
        return (1 - hx) * (1 - hy) * f(i, j) + hx * (1 - hy) * f(i + 1, j)
             + (1 - hx) * hy * f(i, j + 1) + hx * hy * f(i + 1, j + 1);
    }

    // Wiatr ze stacji Jarbo Gap: jedna stacja, więc taki sam w całym obszarze.
    // Interpolacja liniowa między pomiarami co godzinę. Wieje z NE (ok. 30-40 st.),
    // czyli pcha ogień na południowy zachód; najsilniej rano, słabiej w południe.
    void wind_velocity(double /*x*/, double /*y*/, double t, double& bx, double& by) const {
        bx = interp_table(camp_fire::WIND_T, camp_fire::WIND_BX, camp_fire::WIND_N, t);
        by = interp_table(camp_fire::WIND_T, camp_fire::WIND_BY, camp_fire::WIND_N, t);
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
                double intensity = par.heat * (par.fuel_heat ? fuel_map(x, y) : 1.0);

                value_type u = eval_fun(u_prev, e, q);
                value_type fuel = eval_fun(fuel_prev, e, q);

                for (auto a : dofs_on_element(e)) {
                    auto aa = dof_global_to_local(e, a);
                    value_type v = eval_basis(e, q, a);
                    double inv = 1.0 / (rho * cp);

                    // Spline ringing near the ignition can drive T below 0. pow() and
                    // exp(-Ta/T) then overflow, and 0*inf becomes NaN for the whole field.
                    double T = std::max(u.val, 0.0);
                    double delta = T > Tig && fuel.val > par.fuel_min ? 1.0 : 0.0;
                    double hc = -70; // enthalpy
                    double r = 0.0;
                    if (delta > 0.0)
                        r = Ar * T * std::exp(-Ta / T);
                    double Rc = - intensity * 1e4 * rho * ch * hc * M / M1 * r;
                    double Qw = - rho * cw * (bx * u.dx + by * u.dy);
                    double qc = - kappa * grad_dot(u, v);
                    double qd = 0.0; // omitted
                    double qr = -4 * sigma * eps * delta_x * std::pow(T, 3) * grad_dot(u, v);
                    double Qconv = xi * (T0 - T);
                    double Qrz = sigma * eps / delta_z * (std::pow(T0, 4) - std::pow(T, 4));

                    double val = (Rc + Qw + Qconv + Qrz) * v.val + qc + qd + qr;
                    U(aa[0], aa[1]) += (u.val * v.val + steps.dt * inv * val) * w * J;

                    double fval = - delta * par.burn * r * fuel.val * v.val;
                    F(aa[0], aa[1]) += (fuel.val * v.val + steps.dt * fval) * w * J;
                }
            }
            executor.synchronized([&] { update_global_rhs(rhs, U, e); });
            executor.synchronized([&] { update_global_rhs(rhs_fuel, F, e); });
        });
    }

    void after_step(int iter, double /*t*/) override {
        auto i = iter  +1;
        if (i % par.out_every == 0) {
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
