# Northern Virginia grid map

Interactive Leaflet map (built with Folium) of the Northern Virginia part of
Dominion's zone in PJM: where generation sits, how the high-voltage network
runs, and where the data center load is.

```bash
pip install folium pandas openpyxl requests
python map/build_map.py            # downloads raw data into data/raw/map/, then builds
python map/build_map.py --offline  # rebuild from cached files
```

Output: `map/nova_grid_map.html` (open in a browser; needs internet for the
Leaflet CDN and basemap tiles) and `map/nova_plants.csv` (plant-level table).

## Layers and sources

| Layer | Source | License | Vintage |
|---|---|---|---|
| Power plants (operating, planned) | EIA-860M monthly generator inventory, aggregated to plant | Public domain | September 2026 |
| Transmission lines (115-500 kV) | HIFLD Electric Power Transmission Lines (ArcGIS FeatureServer) | Public domain | last edited Sep 2023 |
| Substations | **Inferred** from line endpoints (see below) | derived | - |
| Data centers | OpenStreetMap (`telecom=data_center`, `building=data_center`) via Overpass, fetched by the `fetch-datacenters` GitHub Action into `map/osm_datacenters_nova.json` | ODbL, attribution required | snapshot 2026-11-22 (371 sites/buildings) |

Study area: bounding box 38.30-39.45 N, 78.30-76.90 W (Loudoun, Prince William,
Fairfax, Fauquier, Arlington and edges of MD/WV).

## Caveats (honest gaps)

* **Substations are approximate.** HIFLD's public substation layer is no longer
  open. Substations are placed by clustering transmission line endpoints on a
  ~400 m grid (clusters with 2+ endpoints). A name is shown only when two or more
  lines agree on it; otherwise "Unnamed (inferred)".
* **Transmission data stops in 2023.** Lines energized since then (several
  new 230/500 kV projects for data center load) may be missing.
* **Data center coverage is incomplete, and counts are buildings, not campuses.** A campus often has several buildings, and some may be double-counted where both a site and its building are tagged. OSM is the best open, redistributable
  source, but many facilities are untagged. Commercial trackers (e.g. Data
  Center Map, datacenterHawk) are more complete but not licensed for
  redistribution. County building-permit data is a possible future source.
* **Area labels** ("Data Center Alley", "Manassas / Gainesville cluster") are
  hand-placed context labels, not facility locations.
* Circle area is proportional to nameplate MW, which overstates solar output
  relative to firm capacity.

## What the map shows (first read)

Roughly 5.9 GW of nameplate generation sits inside the box, mostly gas, while
Northern Virginia data center demand is several GW and growing (figure to be
sourced from Dominion/PJM load forecasts before publishing). The
region leans on 500 kV imports from the west and south, which is the physical
story behind the "grid bottleneck" part of this project.

## Link to the demand nowcast (Dominion zone)

`python map/dom_nowcast.py` pulls hourly demand for PJM's **DOM** transmission
zone from the EIA-930 *subregion* files and runs this repo's point-in-time
weather model (`src/pdn/model.py`) on it, with a three-point temperature
(Dulles 45%, Richmond 30%, Norfolk 25%: assumed load weights). It writes:

* `map/dom_monthly.csv`: weather-normalized and raw YoY growth, monthly peak MW,
  out-of-sample error.
* `map/dom_daily.csv`: daily actual vs. out-of-sample expected demand
  ("surprise" %).

The map panel shows the latest growth, last-30-day surprise, the year's peak vs.
approximate dispatchable capacity in the zone, a 36-month growth bar chart, and
a month slider that recolors the study box (blue = below last year, red =
above). Zone capacity is an approximation: EIA-860M Virginia plants minus
AEP/Appalachian Power, net summer MW. The shaded box is the study area, not the
DOM zone boundary.
