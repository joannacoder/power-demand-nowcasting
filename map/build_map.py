"""Build an interactive grid map of Northern Virginia (Dominion zone, PJM).

Layers
------
* Power plants: EIA-860M monthly generator inventory (operating + planned),
  aggregated to plant level. Public domain (US government work).
* Transmission lines: HIFLD "Electric Power Transmission Lines" (ArcGIS
  FeatureServer, last edited Sep 2023). Public domain.
* Substations (INFERRED): HIFLD's public substation layer is no longer open,
  so substations are approximated by clustering transmission line endpoints.
  Names come from the lines' SUB_1/SUB_2 fields when two or more lines agree.
* Data centers: OpenStreetMap (ODbL) via Overpass, when the file is
  available. OSM coverage of data centers is incomplete; see map/README.md.

Usage
-----
    python map/build_map.py            # download (if needed) and build
    python map/build_map.py --offline  # use cached files only

Output: map/nova_grid_map.html (self-contained apart from CDN JS/CSS and tiles).
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import folium
import pandas as pd
import requests
from folium.plugins import MiniMap

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "map"
OUT = ROOT / "map" / "nova_grid_map.html"

# Study area: Loudoun, Prince William, Fairfax, Fauquier, Arlington and
# surroundings. (south, west, north, east)
BBOX = (38.30, -78.30, 39.45, -76.90)

EIA860M_URL = "https://www.eia.gov/electricity/data/eia860m/xls/{month}_generator{year}.xlsx"
EIA860M_FILE = RAW / "eia860m_september_generator2026.xlsx"
EIA860M_VINTAGE = "September 2026"

HIFLD_LINES_URL = (
    "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
    "Electric_Power_Transmission_Lines/FeatureServer/0/query"
)
HIFLD_LINES_FILE = RAW / "hifld_transmission_lines_nova.geojson"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_DC_FILE = ROOT / "map" / "osm_datacenters_nova.json"  # fetched by GitHub Action

FUEL_GROUPS = {
    "Natural Gas Fired Combined Cycle": "Gas (combined cycle)",
    "Natural Gas Fired Combustion Turbine": "Gas (peaker)",
    "Natural Gas Internal Combustion Engine": "Gas (peaker)",
    "Natural Gas Steam Turbine": "Gas (peaker)",
    "Petroleum Liquids": "Oil",
    "Solar Photovoltaic": "Solar",
    "Batteries": "Battery storage",
    "Conventional Hydroelectric": "Hydro",
    "Hydroelectric Pumped Storage": "Hydro",
    "Nuclear": "Nuclear",
    "Conventional Steam Coal": "Coal",
    "Onshore Wind Turbine": "Wind",
}
FUEL_COLORS = {
    "Gas (combined cycle)": "#e8590c",
    "Gas (peaker)": "#f59f00",
    "Oil": "#862e9c",
    "Coal": "#495057",
    "Nuclear": "#c2255c",
    "Solar": "#f8d417",
    "Wind": "#15aabf",
    "Hydro": "#1c7ed6",
    "Battery storage": "#2f9e44",
    "Waste / biomass": "#8d6e63",
    "Other": "#868e96",
}
VOLT_STYLE = {  # VOLT_CLASS -> (color, weight, label)
    "500": ("#c92a2a", 4.0, "500 kV"),
    "220-287": ("#5f3dc4", 2.6, "230 kV"),
    "100-161": ("#1971c2", 1.6, "115-138 kV"),
}


def in_bbox(lat: float, lon: float) -> bool:
    s, w, n, e = BBOX
    return s <= lat <= n and w <= lon <= e


# --------------------------------------------------------------------- data
def fetch(offline: bool) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    if offline:
        return
    if not EIA860M_FILE.exists():
        r = requests.get(EIA860M_URL.format(month="september", year=2026), timeout=120)
        r.raise_for_status()
        EIA860M_FILE.write_bytes(r.content)
    if not HIFLD_LINES_FILE.exists():
        s, w, n, e = BBOX
        params = dict(where="1=1", geometry=f"{w},{s},{e},{n}",
                      geometryType="esriGeometryEnvelope", inSR=4326,
                      spatialRel="esriSpatialRelIntersects", outFields="*",
                      outSR=4326, f="geojson")
        r = requests.get(HIFLD_LINES_URL, params=params, timeout=120)
        r.raise_for_status()
        HIFLD_LINES_FILE.write_bytes(r.content)
    if not OSM_DC_FILE.exists():
        s, w, n, e = BBOX
        q = (f'[out:json][timeout:90];(nwr["telecom"="data_center"]({s},{w},{n},{e});'
             f'nwr["building"="data_center"]({s},{w},{n},{e}););out center tags;')
        try:
            r = requests.post(OVERPASS_URL, data={"data": q}, timeout=180)
            r.raise_for_status()
            OSM_DC_FILE.write_bytes(r.content)
        except requests.RequestException as exc:  # map still builds without it
            print(f"[warn] OSM data centers not downloaded: {exc}")


def load_plants() -> pd.DataFrame:
    xl = pd.ExcelFile(EIA860M_FILE)
    frames = []
    for sheet, status in [("Operating", "Operating"), ("Planned", "Planned")]:
        d = pd.read_excel(xl, sheet, header=2)
        d = d[pd.to_numeric(d["Latitude"], errors="coerce").notna()]
        d["status_group"] = status
        frames.append(d)
    g = pd.concat(frames, ignore_index=True)
    g = g[[in_bbox(a, b) for a, b in zip(g["Latitude"], g["Longitude"])]]
    g["fuel"] = g["Technology"].map(FUEL_GROUPS)
    waste = g["Technology"].str.contains("Waste|Landfill|Wood|Biomass", na=False)
    g.loc[waste, "fuel"] = "Waste / biomass"
    g["fuel"] = g["fuel"].fillna("Other")
    g["mw"] = pd.to_numeric(g["Nameplate Capacity (MW)"], errors="coerce").fillna(0)

    rows = []
    for (pid, status), d in g.groupby(["Plant ID", "status_group"]):
        by_fuel = d.groupby("fuel")["mw"].sum().sort_values(ascending=False)
        years = pd.to_numeric(d["Operating Year"], errors="coerce")
        rows.append(dict(
            plant_id=int(pid), status=status, name=d["Plant Name"].iloc[0],
            operator=d["Entity Name"].iloc[0], county=d["County"].iloc[0],
            state=d["Plant State"].iloc[0], lat=d["Latitude"].iloc[0],
            lon=d["Longitude"].iloc[0], mw=d["mw"].sum(), fuel=by_fuel.index[0],
            fuel_mix=", ".join(f"{k} {v:,.0f} MW" for k, v in by_fuel.items()),
            n_units=len(d), first_year=years.min(), last_year=years.max(),
            ba=d["Balancing Authority Code"].iloc[0],
        ))
    return pd.DataFrame(rows).sort_values("mw", ascending=False)


def load_lines() -> list[dict]:
    gj = json.loads(HIFLD_LINES_FILE.read_text())
    feats = [f for f in gj["features"] if f.get("geometry")]
    for f in feats:
        geom = f["geometry"]
        f["_parts"] = (geom["coordinates"] if geom["type"] == "MultiLineString"
                       else [geom["coordinates"]])
    return feats


def infer_substations(lines: list[dict], grid: float = 0.004) -> list[dict]:
    """Cluster line endpoints (~400 m grid) into approximate substations."""
    clusters: dict[tuple, dict] = defaultdict(lambda: dict(pts=[], names=Counter(),
                                                          kv=0, lines=0))
    for f in lines:
        p = f["properties"]
        names = [s for s in (p.get("SUB_1"), p.get("SUB_2"))
                 if s and not s.upper().startswith(("UNKNOWN", "NOT AVAILABLE", "TAP"))]
        kv = p.get("VOLTAGE") or 0
        for part in f["_parts"]:
            for lon, lat in (part[0], part[-1]):
                key = (round(lat / grid), round(lon / grid))
                c = clusters[key]
                c["pts"].append((lat, lon))
                c["names"].update(names)
                c["kv"] = max(c["kv"], kv if kv > 0 else 0)
                c["lines"] += 1
    subs = []
    for c in clusters.values():
        if c["lines"] < 2:  # a lone endpoint is more likely a tap or clip edge
            continue
        lat = sum(p[0] for p in c["pts"]) / len(c["pts"])
        lon = sum(p[1] for p in c["pts"]) / len(c["pts"])
        if not in_bbox(lat, lon):
            continue
        top = c["names"].most_common(1)
        name = top[0][0].title() if top and top[0][1] >= 2 else "Unnamed (inferred)"
        subs.append(dict(lat=lat, lon=lon, name=name, kv=c["kv"], lines=c["lines"]))
    return subs


def load_datacenters() -> list[dict]:
    if not OSM_DC_FILE.exists():
        return []
    els = json.loads(OSM_DC_FILE.read_text()).get("elements", [])
    out, seen = [], set()
    for e in els:
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None:
            continue
        t = e.get("tags", {})
        key = (t.get("name"), round(lat, 3), round(lon, 3))  # site + building duplicates
        if t.get("name") and key in seen:
            continue
        seen.add(key)
        out.append(dict(lat=lat, lon=lon, name=t.get("name", "Unnamed data center"),
                        operator=t.get("operator", "n/a"),
                        osm=f"https://www.openstreetmap.org/{e['type']}/{e['id']}"))
    return out



# ----------------------------------------------------------- nowcast link
DOM_MONTHLY = ROOT / "map" / "dom_monthly.csv"
DOM_DAILY = ROOT / "map" / "dom_daily.csv"
NON_DISPATCHABLE = ("Solar", "Wind", "Batter")


def zone_capacity() -> dict:
    """Approximate Dominion-zone capacity: Virginia plants minus AEP/Appalachian Power.

    Approximation: merchant plants in AEP's SW Virginia territory are still
    counted, and Dominion's small NE North Carolina fleet is left out.
    """
    d = pd.read_excel(EIA860M_FILE, "Operating", header=2)
    d = d[(d["Plant State"] == "VA")
          & ~d["Entity Name"].str.contains("Appalachian Power|AEP", na=False)]
    cap = pd.to_numeric(d["Net Summer Capacity (MW)"], errors="coerce").fillna(0)
    nd = d["Technology"].str.contains("|".join(NON_DISPATCHABLE), na=False)
    return dict(total=cap.sum(), dispatchable=cap[~nd].sum(), variable=cap[nd].sum())


def growth_color(g: float) -> str:
    """Diverging blue (below last year) - gray - red (above), clipped at +/-12%."""
    if g != g:
        return "#f0efec"
    t = max(-1.0, min(1.0, g / 0.12))
    lo, mid, hi = (42, 120, 214), (240, 239, 236), (214, 59, 59)
    a, b = (mid, hi) if t >= 0 else (mid, lo)
    t = abs(t)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def growth_svg(mon: pd.DataFrame) -> str:
    """Bar chart of monthly weather-normalized YoY growth, hover shows values."""
    mon = mon.dropna(subset=["wn_yoy"]).tail(36)
    W, H, pad = 300, 110, 18
    vmax = max(0.05, mon["wn_yoy"].abs().max())
    neg = (mon["wn_yoy"] < 0).any()
    span = (H / 2 - pad) if neg else (H - 2 * pad)
    y0 = H / 2 if neg else H - pad
    bw = (W - 2) / len(mon)
    bars = []
    for i, r in enumerate(mon.itertuples()):
        h = abs(r.wn_yoy) / vmax * span
        y = y0 - h if r.wn_yoy >= 0 else y0
        bars.append(
            f"<rect x='{1 + i * bw + 1:.1f}' y='{y:.1f}' width='{max(1, bw - 2):.1f}' "
            f"height='{max(h, 0.5):.1f}' rx='1.5' fill='{growth_color(r.wn_yoy)}'>"
            f"<title>{r.month}: {r.wn_yoy:+.1%} weather-normalized, {r.raw_yoy:+.1%} raw, "
            f"peak {r.peak_mw:,.0f} MW</title></rect>")
    first, last = mon["month"].iloc[0], mon["month"].iloc[-1]
    return (f"<svg viewBox='0 0 {W} {H}' width='100%' role='img' "
            f"aria-label='Monthly weather-normalized demand growth, Dominion zone'>"
            f"<line x1='0' x2='{W}' y1='{y0}' y2='{y0}' stroke='#c3c2b7' stroke-width='1'/>"
            + "".join(bars)
            + f"<text x='0' y='{H - 2}' font-size='9' fill='#52514e'>{first}</text>"
            f"<text x='{W}' y='{H - 2}' font-size='9' fill='#52514e' text-anchor='end'>{last}</text>"
            f"<text x='0' y='9' font-size='9' fill='#52514e'>+{vmax:.0%}</text></svg>")


def nowcast_section(m: folium.Map) -> str:
    if not DOM_MONTHLY.exists():
        return ""
    mon = pd.read_csv(DOM_MONTHLY)
    cap = zone_capacity()
    ok = mon.dropna(subset=["wn_yoy"])
    last = ok.iloc[-1]
    yr = ok[ok["month"].str[:4] == ok["month"].iloc[-1][:4]]
    peak_yr = yr["peak_mw"].max()
    gap = peak_yr - cap["dispatchable"]
    surprise = ""
    if DOM_DAILY.exists():
        dd = pd.read_csv(DOM_DAILY).tail(30)
        surprise = (f"<div>Last 30 days vs nowcast: <b>{dd['surprise_pct'].mean():+.1f}%</b> "
                    f"(through {dd['date'].iloc[-1]})</div>")

    # Zone shading over the study box, recolored by the month slider.
    s_, w_, n_, e_ = BBOX
    rect = folium.Rectangle([[s_, w_], [n_, e_]], color="#868e96", weight=1, dash_array="6",
                            fill=True, fill_color=growth_color(last["wn_yoy"]), fill_opacity=0.15,
                            interactive=False)
    fg = folium.FeatureGroup(name="Demand growth shading (Dominion zone)")
    rect.add_to(fg)
    fg.add_to(m)

    months = ok[["month", "wn_yoy", "raw_yoy", "peak_mw"]].tail(36).to_dict("records")
    for r in months:
        r["color"] = growth_color(r["wn_yoy"])
    js = f"""
    <script>
    (function() {{
      var D = {json.dumps(months)};
      function upd(i) {{
        var r = D[i];
        document.getElementById('nc-month').textContent = r.month;
        document.getElementById('nc-val').textContent =
          (r.wn_yoy >= 0 ? '+' : '') + (100 * r.wn_yoy).toFixed(1) + '% weather-normalized YoY, peak ' +
          Math.round(r.peak_mw).toLocaleString() + ' MW';
        var lyr = window['{rect.get_name()}'];
        if (lyr) lyr.setStyle({{fillColor: r.color}});
      }}
      document.addEventListener('DOMContentLoaded', function() {{
        var s = document.getElementById('nc-slider');
        s.max = D.length - 1; s.value = D.length - 1;
        s.addEventListener('input', function() {{ upd(+s.value); }});
        setTimeout(function() {{ upd(D.length - 1); }}, 300);
      }});
    }})();
    </script>"""
    m.get_root().html.add_child(folium.Element(js))

    return f"""
      <div style="margin-top:8px;padding-top:6px;border-top:1px solid #dee2e6">
        <div style="font-weight:700">Demand nowcast: Dominion zone</div>
        <div><b>{last['wn_yoy']:+.1%}</b> weather-normalized demand growth, {last['month']}
             (raw {last['raw_yoy']:+.1%})</div>
        {surprise}
        <div><b>{peak_yr:,.0f} MW</b> {last['month'][:4]} peak vs about
             <b>{cap['dispatchable']:,.0f} MW</b> dispatchable capacity in the zone
             (+{cap['variable']:,.0f} MW solar/wind/storage)</div>
        <div>Peak-hour gap to cover with solar and imports: <b>~{gap:,.0f} MW</b></div>
        <div style="margin-top:4px">{growth_svg(mon)}</div>
        <div style="color:#52514e">Monthly growth vs same month last year, red = higher.
             Hover bars for values. The slider recolors the study box; the box is
             not the zone boundary.</div>
        <div style="margin-top:4px"><input id="nc-slider" type="range" min="0" step="1"
             style="width:100%" aria-label="Month"></div>
        <div><b id="nc-month"></b> <span id="nc-val"></span></div>
      </div>"""

# ---------------------------------------------------------------------- map
def popup_table(title: str, rows: list[tuple[str, str]]) -> folium.Popup:
    body = "".join(f"<tr><td style='color:#666;padding-right:8px'>{k}</td><td>{v}</td></tr>"
                   for k, v in rows)
    html = f"<b>{title}</b><table style='font-size:12px;margin-top:4px'>{body}</table>"
    return folium.Popup(html, max_width=320)


def build(offline: bool = False) -> Path:
    fetch(offline)
    plants = load_plants()
    lines = load_lines()
    subs = infer_substations(lines)
    dcs = load_datacenters()

    s, w, n, e = BBOX
    m = folium.Map(location=[(s + n) / 2, (w + e) / 2], zoom_start=9,
                   tiles=None, control_scale=True)
    folium.TileLayer(
        "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attr="&copy; OpenStreetMap contributors &copy; CARTO", name="Light basemap",
        subdomains="abcd", max_zoom=19).add_to(m)
    folium.TileLayer("OpenStreetMap", name="Street basemap", show=False).add_to(m)

    # Transmission lines, low voltage first so 500 kV draws on top.
    line_groups = {k: folium.FeatureGroup(name=f"Transmission {v[2]}")
                   for k, v in VOLT_STYLE.items()}
    order = ["100-161", "220-287", "500"]
    for f in sorted(lines, key=lambda f: order.index(f["properties"]["VOLT_CLASS"])
                    if f["properties"]["VOLT_CLASS"] in order else -1):
        p = f["properties"]
        vc = p.get("VOLT_CLASS")
        if vc not in VOLT_STYLE:
            continue
        color, weight, label = VOLT_STYLE[vc]
        kv = p.get("VOLTAGE")
        tip = f"{kv if kv and kv > 0 else label} kV line · {(p.get('OWNER') or 'n/a').title()}"
        pop = popup_table("Transmission line", [
            ("Voltage", f"{kv} kV" if kv and kv > 0 else label),
            ("Owner", (p.get("OWNER") or "n/a").title()),
            ("From / to", f"{(p.get('SUB_1') or '?').title()} / {(p.get('SUB_2') or '?').title()}"),
            ("Type", p.get("TYPE", "n/a")), ("Status", p.get("STATUS", "n/a")),
            ("Source", "HIFLD (edited Sep 2023)")])
        for part in f["_parts"]:
            folium.PolyLine([(lat, lon) for lon, lat in part], color=color, weight=weight,
                            opacity=0.8, tooltip=tip, popup=pop).add_to(line_groups[vc])
    for k in order:
        line_groups[k].add_to(m)

    # Inferred substations
    fg_sub = folium.FeatureGroup(name="Substations (inferred)")
    for sub in subs:
        folium.CircleMarker(
            [sub["lat"], sub["lon"]], radius=3 if sub["kv"] < 300 else 4.5,
            color="#212529", weight=1, fill=True, fill_color="#ffffff", fill_opacity=1,
            tooltip=f"{sub['name']} · up to {sub['kv']:.0f} kV (inferred)",
            popup=popup_table(sub["name"], [
                ("Max line voltage", f"{sub['kv']:.0f} kV"),
                ("Line endpoints", str(sub["lines"])),
                ("Note", "Location inferred from HIFLD line endpoints, not an official "
                         "substation record")]),
        ).add_to(fg_sub)
    fg_sub.add_to(m)

    # Plants
    fg_op = folium.FeatureGroup(name="Power plants (operating)")
    fg_pl = folium.FeatureGroup(name="Power plants (planned)")
    for r in plants.itertuples():
        radius = max(3.0, 1.0 * math.sqrt(r.mw))
        color = FUEL_COLORS.get(r.fuel, FUEL_COLORS["Other"])
        planned = r.status == "Planned"
        years = (f"{r.first_year:.0f}" if r.first_year == r.last_year
                 else f"{r.first_year:.0f}-{r.last_year:.0f}")
        folium.CircleMarker(
            [r.lat, r.lon], radius=radius, color=color if planned else "#343a40",
            weight=2 if planned else 0.8, dash_array="4" if planned else None,
            fill=True, fill_color=color, fill_opacity=0.15 if planned else 0.85,
            tooltip=f"{r.name} · {r.mw:,.0f} MW {r.fuel}{' (planned)' if planned else ''}",
            popup=popup_table(r.name, [
                ("Status", r.status), ("Capacity", f"{r.mw:,.1f} MW nameplate"),
                ("Fuel mix", r.fuel_mix), ("Operator", r.operator),
                ("County", f"{r.county}, {r.state}"), ("Units", str(r.n_units)),
                ("Online" if not planned else "Planned online", years),
                ("EIA plant ID", str(r.plant_id)),
                ("Source", f"EIA-860M, {EIA860M_VINTAGE}")]),
        ).add_to(fg_pl if planned else fg_op)
    fg_op.add_to(m)
    fg_pl.add_to(m)

    # Data centers
    fg_dc = folium.FeatureGroup(name="Data centers (OpenStreetMap)")
    for dc in dcs:
        folium.CircleMarker(
            [dc["lat"], dc["lon"]], radius=3.5,
            color="#0b7285", fill=True, fill_color="#22b8cf", fill_opacity=0.9, weight=1,
            tooltip=f"{dc['name']} · {dc['operator']}",
            popup=popup_table(dc["name"], [("Operator", dc["operator"]),
                                           ("Source", f"<a href='{dc['osm']}' target='_blank'>OSM</a>")]),
        ).add_to(fg_dc)
    fg_dc.add_to(m)

    # Approximate area labels (context, not facility locations)
    fg_ctx = folium.FeatureGroup(name="Area labels (approximate)")
    for label, lat, lon in [("Data Center Alley (Ashburn)", 39.03, -77.48),
                            ("Manassas / Gainesville cluster", 38.79, -77.58)]:
        folium.Marker([lat, lon], icon=folium.DivIcon(
            html=f"<div style='font:600 11px sans-serif;color:#0b7285;white-space:nowrap;"
                 f"text-shadow:0 0 3px #fff,0 0 3px #fff'>{label}</div>")).add_to(fg_ctx)
    fg_ctx.add_to(m)

    nc_html = nowcast_section(m)
    folium.LayerControl(collapsed=False).add_to(m)
    MiniMap(toggle_display=True, position="bottomleft").add_to(m)
    m.fit_bounds([[s, w], [n, e]])

    op = plants[plants.status == "Operating"]
    pl = plants[plants.status == "Planned"]
    legend_fuels = [f for f in FUEL_COLORS if f in set(plants.fuel)]
    fuel_rows = "".join(
        f"<div><span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
        f"background:{FUEL_COLORS[f]};margin-right:6px'></span>{f}</div>" for f in legend_fuels)
    volt_rows = "".join(
        f"<div><span style='display:inline-block;width:18px;height:{max(2, int(v[1]))}px;"
        f"background:{v[0]};margin-right:6px;vertical-align:middle'></span>{v[2]}</div>"
        for k, v in sorted(VOLT_STYLE.items(), key=lambda kv: -kv[1][1]))
    dc_note = (f"<b>{len(dcs)}</b> data center buildings/sites from OpenStreetMap (coverage incomplete)." if dcs else
               "<b>Data center layer pending:</b> source not loaded yet.")
    panel = f"""
    <div style="position:fixed;top:12px;left:56px;z-index:9999;max-width:330px;max-height:calc(100vh - 24px);overflow-y:auto;
                background:rgba(255,255,255,.94);padding:10px 12px;border-radius:8px;
                box-shadow:0 1px 6px rgba(0,0,0,.25);font:12px/1.4 sans-serif;color:#212529">
      <div style="font-weight:700;font-size:14px">Northern Virginia grid map</div>
      <div style="color:#495057;margin-bottom:6px">Dominion zone, PJM · study area box</div>
      <div><b>{op.mw.sum():,.0f} MW</b> operating generation at {len(op)} plants</div>
      <div><b>{pl.mw.sum():,.0f} MW</b> planned at {len(pl)} plants (dashed)</div>
      <div><b>{len(lines)}</b> transmission line segments · <b>{len(subs)}</b> inferred substations</div>
      <div style="margin-top:6px">{dc_note}</div>
      {nc_html}
      <details style="margin-top:6px"><summary style="cursor:pointer">Legend</summary>
        <div style="margin-top:4px">{fuel_rows}</div>
        <div style="margin-top:6px">{volt_rows}</div>
        <div style="margin-top:6px">○ substation (inferred) · <span style='color:#22b8cf'>●</span> data center</div>
        <div style="color:#495057">Circle area ∝ nameplate MW</div>
      </details>
      <details style="margin-top:4px"><summary style="cursor:pointer">Sources and caveats</summary>
        <div style="margin-top:4px">Plants: EIA-860M ({EIA860M_VINTAGE}), public domain.<br>
        Lines: HIFLD Electric Power Transmission Lines (last edited Sep 2023), public domain.
        Lines built since 2023 may be missing.<br>
        Substations: inferred by clustering line endpoints; names only where 2+ lines agree.<br>
        Data centers: OpenStreetMap contributors (ODbL); many facilities are unmapped.<br>
        Area labels are approximate context, not facility locations.<br>
        Nowcast: EIA-930 hourly demand for PJM's DOM zone, fit with this repo's point-in-time
        weather model (map/dom_nowcast.py). Zone capacity: EIA-860M Virginia plants minus
        AEP/Appalachian Power, net summer MW (approximate).</div>
      </details>
    </div>"""
    m.get_root().html.add_child(folium.Element(panel))
    m.get_root().header.add_child(folium.Element(
        "<title>Northern Virginia Grid Map</title>"
        "<meta name='description' content='Power plants, transmission and data centers "
        "in Northern Virginia (Dominion zone, PJM).'>"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    m.save(OUT)
    plants.to_csv(ROOT / "map" / "nova_plants.csv", index=False)
    print(f"plants op={len(op)} ({op.mw.sum():,.0f} MW) planned={len(pl)} "
          f"lines={len(lines)} subs={len(subs)} dcs={len(dcs)} -> {OUT}")
    return OUT


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    build(ap.parse_args().offline)
