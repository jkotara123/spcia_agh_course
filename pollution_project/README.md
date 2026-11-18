# Usuwanie zanieczyszczeń w IGA-ADS

Symulacja chmury zanieczyszczeń w bibliotece [IGA-ADS](https://github.com/marcinlos/iga-ads).
Kod żyje w tym katalogu, a kompilacja i obliczenia idą w tym samym kontenerze `iga-ads-dev`
co [`wildfire_project`](../wildfire_project). Katalogu `iga-ads` nie trzeba ruszać.

**Stan:** `pollution.hpp` i `pollution.cpp` to na razie przykład `pollution_2d` z IGA-ADS
(komin, wiatr o zmiennym kierunku). Dodane są tylko parametry z linii poleceń i `params.csv`.
Kod z zajęć (inwersja termiczna) wstawia się w miejsce tych dwóch plików.

## Instalacja

Potrzebne:
- Docker Desktop (uruchomiony) z włączoną integracją WSL
  (*Settings → Resources → WSL integration*), żeby `docker` działał w WSL,
- [`just`](https://github.com/casey/just),
- Python 3 z `numpy`, `matplotlib` i `pillow`.

**1. Obraz Dockera `iga-ads:latest`** (raz, wspólny z `wildfire_project`). Jeśli `docker images`
już go pokazuje, ten krok pomiń.

```bash
git clone https://github.com/marcinlos/iga-ads.git --branch spciaa ~/iga-ads-spciaa
cd ~/iga-ads-spciaa
sed -i 's/podman/docker/g' justfile
mv Containerfile Dockerfile
sed -i 's/install-dependencies.sh,z/install-dependencies.sh/' Dockerfile
just image
```

**2. Kontener i kompilacja.** Wszystkie komendy uruchamiaj z katalogu `pollution_project`:

```bash
cd pollution_project
just kontener
just rebuild
```

`just kontener` używa istniejącego kontenera `iga-ads-dev`, a jeśli go nie ma, zakłada nowy.
Pierwsze `just rebuild` dopisuje przykład `pollution_spcia` do `examples/CMakeLists.txt`
w kontenerze i kompiluje bibliotekę, więc trwa kilka minut. Każde następne kompiluje tylko ten przykład.

**3. Python.** `just gif` uruchamia `python3`. Inny interpreter wskazujesz zmienną `PYTHON`.

## Szybki start

```bash
just run
just gif
```

`just run` liczy nowy przebieg `run_<data>_<godzina>`, a `just gif` robi z ostatniego
przebiegu `pollution.gif` i klatki PNG w `przebiegi/run_.../`.

Próba z innymi parametrami (bez kompilacji):

```bash
just run wind_speed=8 diff=40
just gif
just przebiegi
```

## Komendy

| Komenda | Co robi |
|---|---|
| `just kontener` | Uruchamia kontener `iga-ads-dev` albo zakłada go z obrazu `iga-ads:latest` i konfiguruje CMake. |
| `just rebuild` | Kopiuje `pollution.cpp` i `pollution.hpp` do `/code/examples/pollution_spcia/` w kontenerze i kompiluje. Potrzebne po każdej zmianie kodu C++. |
| `just run [nazwa=wartość ...]` | Nowy przebieg w kontenerze. Zapisuje `params.csv` i pełny log (`log.txt`) w `przebiegi/run_.../` i dopisuje wiersz do `przebiegi/przebiegi.csv`. |
| `just gif [run] [opcje]` | `pollution.gif` i `png/pollution/*.png` w `przebiegi/<run>/`. Domyślnie ostatni przebieg. Opcje `animate.py`, np. `just gif latest --log`. |
| `just przebiegi` | Tabela wszystkich przebiegów. |
| `just shell` | Powłoka w kontenerze w katalogu ostatniego przebiegu. |
| `just clean` | Usuwa z kontenera wszystkie przebiegi poza ostatnim. |
| `just n=40 run` | Inna siatka (domyślnie `n=80`, `p=2`). |

Opcje `animate.py` (po `just gif <run>`):
- `--log`: logarytmiczna skala kolorów, dobra dla smugi, która szybko rzednie,
- `--vmin`, `--vmax`: stały zakres kolorów (domyślnie 99,5 percentyl ze wszystkich klatek),
- `--frames 60`: liczba klatek,
- `--field temp:temperatura:inferno`: dodatkowe pole z plików `temp_<krok>.data`,
  gdy kod zacznie je zapisywać (można podać kilka razy).

## Przebiegi

```
kontener:  /tmp/pollution/run_20261118_101500/   out_*.data, params.csv
           /tmp/pollution/latest → run_20261118_101500

host:      pollution_project/przebiegi/
           ├── przebiegi.csv                      jeden wiersz na przebieg
           └── run_20261118_101500/
               ├── params.csv  log.txt            (just run)
               └── pollution.gif  png/            (just gif)
```

## Parametry

Są w `struct pollution_params` w `pollution.hpp`. Każdy można nadpisać w `just run nazwa=wartość`.
Nowy parametr dodaje się w strukturze i w mapie `real` (albo `whole` dla liczb całkowitych)
w `pollution.cpp`, potem `just rebuild`.

| Nazwa | Domyślnie | Co robi |
|---|---|---|
| `dt` | 10 | Krok czasu [s]. |
| `t_end` | 6000 | Koniec symulacji [s]. |
| `out_every` | 10 | Co ile kroków zapisywać `out_<krok>.data`. |
| `wind_speed` | 5 | Prędkość wiatru [m/s], kierunek zmienia się w czasie. |
| `diff` | 20 | Dyfuzja w x i y. |
| `ambient` | 1e-6 | Stężenie tła [g/m³]. |
| `src_x`, `src_y`, `src_r` | 3000, 400, 25 | Położenie i promień komina [m]. |

## Struktura plików

```
pollution_project/
├── justfile        komendy (just --list)
├── pollution.hpp   model: pollution_params, równania, zapis wyników
├── pollution.cpp   main: czyta nazwa=wartość, zapisuje params.csv, uruchamia symulację
├── animate.py      .data z kontenera → pollution.gif, png/
└── przebiegi/      wyniki kolejnych przebiegów i przebiegi.csv
```
