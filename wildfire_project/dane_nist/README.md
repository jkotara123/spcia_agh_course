# Dane o Camp Fire (8–9 XI 2018)

Skąd są dane i jak je pobrać. Opis całego projektu: [README w głównym katalogu](../../README.md).
Po zmianie któregoś pliku przelicz dane do modelu: `just dane`, potem `just rebuild` (z `wildfire_project`).

Wszystko uruchamiamy z tego katalogu (`wildfire_project/dane_nist`), Pythonem z condy
(ma pandas, matplotlib, openpyxl):

```bash
PY=/opt/homebrew/Caskroom/miniconda/base/bin/python3
```

## 1. Przebieg pożaru – NIST

Plik `NIST TN 2135 Appendix F Fire Spread Data.xlsx` z https://data.nist.gov/od/id/mds2-2954
(2836 obserwacji ognia z czasem i GPS).

```bash
$PY nist_viz.py "NIST TN 2135 Appendix F Fire Spread Data.xlsx" --out wyniki --woda osm_woda.json
```

## 2. Rzeki i jezioro – OpenStreetMap

```bash
curl -sS -A "camp-fire-agh-student/1.0" -H "Accept: application/json" --data-urlencode "data@woda.overpassql" https://overpass-api.de/api/interpreter -o osm_woda.json
```

Bez `-A` serwer odpowiada błędem 406. Zapasowy serwer: `https://overpass.kumi.systems/api/interpreter`.

## 3. Wiatr – stacja RAWS Jarbo Gap (JBGC1)

Stacja przy miejscu zapłonu (39.736 N, 121.489 W). Dane z archiwum IEM (Iowa State), czas w pliku w UTC,
zakres 7–10 XI 2018:

```bash
curl -sS -A "camp-fire-agh-student/1.0" "https://mesonet.agron.iastate.edu/cgi-bin/request/hads.py?network=CA_DCP&stations=JBGC1&year1=2018&month1=11&day1=7&hour1=8&minute1=0&year2=2018&month2=11&day2=10&hour2=8&minute2=0&what=txt&delim=comma" -o jarbo_gap.csv
```

```bash
$PY wiatr_jarbo.py jarbo_gap.csv --out wyniki
```

Wynik: `wyniki/wiatr_jarbo.png` (prędkość, porywy, kierunek, wilgotność) i `wyniki/wiatr_jarbo_8xi.csv`
(godzinowo z 8 XI, w m/s, ze składowymi `bx` na wschód i `by` na północ).

## 4. Paliwo – LANDFIRE FBFM40 (wersja 2016, sprzed pożaru)

Usługa LFPS udostępnia tylko najnowszą wersję (po pożarze), więc bierzemy pełny plik dla USA (ok. 3,1 GB)
ze strony https://www.landfire.gov/data → Full Extent Downloads → CONUS → LF 2016 Remap → FBFM40.
Plik zostaw w `~/Downloads`, nie w repo.

```bash
curl -L -o ~/Downloads/LF2016_FBFM40_CONUS.zip https://www.landfire.gov/data-downloads/CONUS_LF2016/LF2016_FBFM40_CONUS.zip
```

Biblioteka do map rastrowych (raz):

```bash
/opt/homebrew/Caskroom/miniconda/base/bin/conda install -c conda-forge rasterio
```

Wycięcie obszaru pożaru:

```bash
$PY landfire_clip.py ~/Downloads/LF2016_FBFM40_CONUS.zip --out wyniki
```

Wynik: `wyniki/landfire_paliwo.png` (mapa grup paliwa), `wyniki/landfire_fbfm40_campfire.tif` (wycinek 30 m)
i `wyniki/landfire_fbfm40_campfire.npz` (kody na siatce lat/lon, do przeliczenia na `fuel_map`).

## 5. Animacja wiatru na mapie (rzeki, miejscowości, ogień z NIST)

```bash
$PY wiatr_anim.py jarbo_gap.csv --woda osm_woda.json --nist "NIST TN 2135 Appendix F Fire Spread Data.xlsx" --out wyniki
```

Wynik: `wyniki/wiatr_anim.gif` (8 XI, 4:00–22:00 co 10 min) i `wyniki/klatki_wiatr/wiatr_XXh.png` (co 2 h).
Jedna stacja, więc wiatr jest taki sam w całym obszarze (interpolowany między pomiarami co godzinę).
Opcje: `--start 6 --end 14` (zakres godzin), `--step 5` (krok w minutach), bez `--nist` - sam wiatr.
