#!/usr/bin/env python3
"""
generate_map_data.py

Runs the maritime simulation and produces a self-contained JSON snapshot
that the HTML map viewer embeds and animates.

Usage:
    cd maritime_sim_v2
    python generate_map_data.py [--periods N] [--granularity month] [--out ../maritime_map.html]
"""

import sys, os, json, math, argparse, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.enums import Granularity, ConstraintType
from core.models import SimConfig, ScenarioConstraint
from config.schemas import *
from core.engine import SimulationRunner

# ── Company colours (hex) ────────────────────────────────────────────────────
COMPANY_COLORS = {
    "Saudi Aramco": "#00d4ff",
    "Shell":        "#ffd23f",
    "ExxonMobil":   "#ff6b35",
    "BP":           "#4ade80",
    "Rosneft":      "#f472b6",
    "CNOOC":        "#fb923c",
    "Independent":  "#94a3b8",
}

# ── Ship group → size bucket for map circle radius ───────────────────────────
GROUP_RADIUS = {
    "VLCC":    9,
    "Suezmax": 7,
    "Aframax": 5,
    "Panamax": 4,
    "MR":      3,
}

# Map ship_type name to group
def type_to_group(name):
    for g in GROUP_RADIUS:
        if g.lower() in name.lower():
            return g
    return "MR"

def type_to_owner(name, owner_field):
    return owner_field

# ── Region coordinates (lon, lat for Leaflet) ────────────────────────────────
REGION_COORDS = {
    "USGulf":         {"lat": 28.5,  "lon": -90.0},
    "North Sea":      {"lat": 57.5,  "lon":   2.5},
    "Baltic":         {"lat": 59.5,  "lon":  22.0},
    "Mediterranean":  {"lat": 37.5,  "lon":  18.0},
    "Persian Gulf":   {"lat": 26.0,  "lon":  54.0},
    "West Africa":    {"lat":  3.5,  "lon":   3.5},
    "Southeast Asia": {"lat":  4.5,  "lon": 110.5},
    "Alaska":         {"lat": 60.5,  "lon":-149.5},
    "Caribbean":      {"lat": 14.5,  "lon": -75.0},
}

NODE_COORDS = {
    "Strait of Hormuz":   {"lat": 26.6,  "lon":  56.4},
    "Suez Canal":         {"lat": 30.7,  "lon":  32.3},
    "Strait of Malacca":  {"lat":  3.0,  "lon": 101.5},
    "Danish Straits":     {"lat": 57.8,  "lon":  10.5},
    "Panama Canal":       {"lat":  9.1,  "lon": -79.7},
    "Cape of Good Hope":  {"lat":-34.4,  "lon":  18.5},
}

# ── Route definitions for vessel movement animations ─────────────────────────
# (from_region, to_region, via_nodes, waypoints_latlon)
ROUTES = [
    ("Persian Gulf", "Mediterranean",    ["Strait of Hormuz", "Suez Canal"],
     [[25.5,57.0],[27.0,51.0],[27.5,43.0],[29.5,38.0],[30.7,32.3],[31.5,29.0],[33.0,25.0],[35.0,22.0],[36.5,18.5],[37.5,18.0]]),
    ("Persian Gulf", "Southeast Asia",   ["Strait of Hormuz", "Strait of Malacca"],
     [[25.5,57.0],[15.0,65.0],[8.0,77.0],[4.0,82.0],[3.0,95.0],[3.0,101.5],[4.0,107.0],[4.5,110.5]]),
    ("Persian Gulf", "USGulf",           ["Strait of Hormuz", "Cape of Good Hope"],
     [[25.5,57.0],[15.0,52.0],[5.0,45.0],[-5.0,38.0],[-15.0,30.0],[-25.0,22.0],[-34.4,18.5],[-35.0,5.0],[-25.0,-15.0],[-10.0,-30.0],[5.0,-40.0],[15.0,-55.0],[22.0,-72.0],[28.5,-90.0]]),
    ("Baltic",       "Mediterranean",    ["Danish Straits"],
     [[59.5,22.0],[58.5,15.0],[57.8,10.5],[56.0,8.0],[54.0,7.0],[52.0,4.0],[50.0,2.0],[46.0,3.0],[43.0,6.0],[40.0,12.0],[37.5,18.0]]),
    ("North Sea",    "Mediterranean",    [],
     [[57.5,2.5],[55.0,1.0],[52.0,3.0],[49.0,2.0],[46.0,3.0],[44.0,8.0],[40.0,12.0],[37.5,18.0]]),
    ("West Africa",  "USGulf",           [],
     [[3.5,3.5],[5.0,-5.0],[8.0,-20.0],[12.0,-35.0],[18.0,-55.0],[22.0,-72.0],[28.5,-90.0]]),
    ("West Africa",  "Mediterranean",    [],
     [[3.5,3.5],[10.0,0.0],[20.0,-5.0],[28.0,-2.0],[33.0,5.0],[36.0,10.0],[37.5,18.0]]),
    ("USGulf",       "Caribbean",        [],
     [[28.5,-90.0],[25.0,-84.0],[22.0,-80.0],[18.0,-77.0],[14.5,-75.0]]),
    ("Alaska",       "USGulf",           [],
     [[60.5,-149.5],[55.0,-140.0],[50.0,-130.0],[45.0,-125.0],[38.0,-123.0],[30.0,-115.0],[28.5,-90.0]]),
    ("Southeast Asia","North Sea",       ["Strait of Malacca","Suez Canal"],
     [[4.5,110.5],[3.0,101.5],[3.0,90.0],[8.0,77.0],[15.0,60.0],[25.0,45.0],[28.0,38.0],[30.7,32.3],[32.0,29.0],[35.0,25.0],[37.0,22.0],[39.0,16.0],[42.0,10.0],[46.0,5.0],[50.0,2.0],[54.0,5.0],[57.5,2.5]]),
]

def build_route_index():
    idx = {}
    for (fr, to, nodes, wpts) in ROUTES:
        key = f"{fr}→{to}"
        idx[key] = {"from": fr, "to": to, "nodes": nodes, "waypoints": wpts}
    return idx


def run_simulation(granularity: str, n_periods: int, seed: int):
    gran = Granularity(granularity)
    cfg  = SimConfig(granularity=gran, n_periods=n_periods, random_seed=seed)

    df_regions    = template_regions()
    df_demand     = template_region_demand()
    df_supply     = template_region_supply()
    df_storage    = template_region_storage()
    df_port_times = template_port_times()
    df_companies  = template_companies()
    df_ship_types = template_ship_types()
    df_fleet      = template_fleet()
    df_orderbook  = template_orderbook()
    df_nodes      = template_nodes()
    df_edges      = template_edges()
    df_constraints= template_constraints()

    regions    = load_regions(df_regions, df_demand, df_supply, df_storage, df_port_times)
    companies  = load_companies(df_companies)
    ship_types = load_ship_types(df_ship_types)
    nodes      = load_nodes(df_nodes)
    edges      = load_edges(df_edges)
    constraints= load_constraints(df_constraints)
    orderbook  = load_orderbook(df_orderbook, ship_types)

    runner = SimulationRunner(cfg, regions, companies, ship_types, df_fleet,
                               orderbook, nodes, edges, constraints)
    df = runner.run()
    return df, ship_types, regions


def assign_vessels_to_routes(df, ship_types_dict, rng):
    """
    For each simulation step, generate a list of vessel positions on routes.
    Each vessel gets assigned a route and a progress fraction that advances
    each step. Vessels are created/destroyed as fleet counts change.
    Returns a list of per-step vessel arrays.
    """
    route_index = build_route_index()
    route_keys  = list(route_index.keys())

    # Build deterministic vessel registry from first row
    vessels = []
    vessel_id = 0

    # Owner → colour
    company_col = {}
    for _, row in template_companies().iterrows():
        company_col[row["name"]] = COMPANY_COLORS.get(row["name"], "#94a3b8")

    # Initial vessel population from first row
    first = df.iloc[0]
    type_cols = [c for c in df.columns if c.startswith("active_") and c != "active_constraints"]

    for col in type_cols:
        st_name = col[len("active_"):]
        count = int(first[col])
        st = ship_types_dict.get(st_name)
        group = type_to_group(st_name)
        # Assign owner heuristically from name
        owner = "Independent"
        for cname in COMPANY_COLORS:
            if any(k in st_name for k in ["KR","GR","NO","CN","RU"]):
                if "CN" in st_name: owner = "CNOOC"
                elif "RU" in st_name: owner = "Rosneft"
                elif "NO" in st_name: owner = "Shell"
                elif "GR" in st_name: owner = "BP"
                else: owner = "Saudi Aramco"
            break

        for i in range(count):
            route_key = route_keys[vessel_id % len(route_keys)]
            route = route_index[route_key]
            vessels.append({
                "id": vessel_id,
                "type": st_name,
                "group": group,
                "owner": owner,
                "color": COMPANY_COLORS.get(owner, "#94a3b8"),
                "radius": GROUP_RADIUS.get(group, 4),
                "route_key": route_key,
                "progress": rng.uniform(0, 1),   # where on route 0→1
                "speed": rng.uniform(0.025, 0.055),  # fraction of route per step
                "status": "active",
            })
            vessel_id += 1

    # Generate frame data
    frames = []
    prev_totals = {}
    for type_cols_c in type_cols:
        st_name = type_cols_c[len("active_"):]
        prev_totals[st_name] = int(df.iloc[0][type_cols_c])

    for step_idx, row in df.iterrows():
        # Update vessel counts (add/remove vessels)
        for col in type_cols:
            st_name = col[len("active_"):]
            new_count = int(row[col])
            current = sum(1 for v in vessels if v["type"] == st_name and v["status"] == "active")
            diff = new_count - current
            if diff > 0:
                group = type_to_group(st_name)
                for _ in range(diff):
                    owner = "Independent"
                    if "CN" in st_name: owner = "CNOOC"
                    elif "RU" in st_name: owner = "Rosneft"
                    elif "NO" in st_name: owner = "Shell"
                    elif "GR" in st_name: owner = "BP"
                    elif "scrubber" in st_name: owner = "Saudi Aramco"
                    elif "VLCC_KR" in st_name: owner = "Saudi Aramco"

                    route_key = route_keys[vessel_id % len(route_keys)]
                    vessels.append({
                        "id": vessel_id,
                        "type": st_name,
                        "group": group,
                        "owner": owner,
                        "color": COMPANY_COLORS.get(owner, "#94a3b8"),
                        "radius": GROUP_RADIUS.get(group, 4),
                        "route_key": route_key,
                        "progress": rng.uniform(0, 1),
                        "speed": rng.uniform(0.025, 0.055),
                        "status": "active",
                    })
                    vessel_id += 1
            elif diff < 0:
                # Remove oldest independent vessels first
                removed = 0
                for v in reversed(vessels):
                    if v["type"] == st_name and v["status"] == "active":
                        v["status"] = "scrapped"
                        removed += 1
                        if removed >= abs(diff):
                            break

        # Advance vessel positions
        frame_vessels = []
        for v in vessels:
            if v["status"] != "active":
                continue
            v["progress"] = (v["progress"] + v["speed"]) % 1.0
            route = route_index[v["route_key"]]
            wpts  = route["waypoints"]
            # Interpolate position along waypoints
            frac  = v["progress"] * (len(wpts) - 1)
            i0    = int(frac)
            i1    = min(i0 + 1, len(wpts) - 1)
            t     = frac - i0
            lat   = wpts[i0][0] + t * (wpts[i1][0] - wpts[i0][0])
            lon   = wpts[i0][1] + t * (wpts[i1][1] - wpts[i0][1])

            # Check route nodes open
            is_blocked = False
            active_constraints_str = str(row.get("active_constraints", ""))
            for node in route["nodes"]:
                node_key = f"node_{node.replace(' ','_').replace('.','')}"
                if node_key in row and int(row[node_key]) == 0:
                    is_blocked = True
                    break
            if is_blocked:
                v["route_key"] = route_keys[(v["id"] + 1) % len(route_keys)]

            frame_vessels.append({
                "id":     v["id"],
                "lat":    round(lat, 4),
                "lon":    round(lon, 4),
                "color":  v["color"],
                "radius": v["radius"],
                "type":   v["type"],
                "owner":  v["owner"],
                "group":  v["group"],
            })

        frames.append(frame_vessels)

    return frames


def build_sim_json(granularity="month", n_periods=48, seed=42):
    print(f"Running simulation: {granularity} × {n_periods} periods...")
    rng = random.Random(seed)
    np_rng = __import__("numpy").random.default_rng(seed)

    df, ship_types_dict, regions_dict = run_simulation(granularity, n_periods, seed)
    print(f"  → {len(df)} steps, {len(df.columns)} columns")

    print("Building vessel animations...")
    frames = assign_vessels_to_routes(df, ship_types_dict, rng)
    print(f"  → {len(frames)} frames, {max(len(f) for f in frames)} max vessels/frame")

    # Build region stats per step
    region_names = list(REGION_COORDS.keys())
    step_stats = []
    for idx, row in df.iterrows():
        rs = {}
        for rname in region_names:
            safe = rname.replace(" ", "_")
            rs[rname] = {
                "demand": round(float(row.get(f"demand_{rname}", 0)), 2),
                "supply": round(float(row.get(f"supply_{rname}", 0)), 2),
                "storage": round(float(row.get(f"storage_inv_{rname}", 0)), 2),
            }
        step_stats.append(rs)

    # Build per-step summary
    steps = []
    type_cols = [c for c in df.columns if c.startswith("active_") and c != "active_constraints"]
    for idx, row in df.iterrows():
        fleet_breakdown = {}
        for col in type_cols:
            st_name = col[len("active_"):]
            fleet_breakdown[st_name] = int(row[col])

        steps.append({
            "date":          str(row["date_label"]),
            "spot_rate":     round(float(row["spot_rate"]), 0),
            "wti":           round(float(row["wti_usd_bbl"]), 2),
            "vlsfo":         round(float(row["vlsfo_usd_t"]), 1),
            "fleet_active":  int(row["fleet_active"]),
            "fleet_storage": int(row["fleet_storage"]),
            "orderbook":     int(row["orderbook"]),
            "sd_ratio":      round(float(row["sd_ratio"]), 4),
            "load_factor":   round(float(row["load_factor"]), 4),
            "constraints":   str(row.get("active_constraints", "")),
            "fleet":         fleet_breakdown,
            "regions":       step_stats[idx],
        })

    # Node states per step
    node_names = list(NODE_COORDS.keys())
    for i, (idx, row) in enumerate(df.iterrows()):
        steps[i]["nodes"] = {}
        for nname in node_names:
            nkey = f"node_{nname.replace(' ','_').replace('.','')}"
            steps[i]["nodes"][nname] = bool(int(row.get(nkey, 1)))

    data = {
        "meta": {
            "granularity": granularity,
            "n_periods":   n_periods,
            "seed":        seed,
            "n_steps":     len(steps),
        },
        "regions":  REGION_COORDS,
        "nodes":    NODE_COORDS,
        "routes":   build_route_index(),
        "company_colors": COMPANY_COLORS,
        "group_radius":   GROUP_RADIUS,
        "steps":    steps,
        "frames":   frames,
    }
    return data


def generate_html(data: dict, output_path: str):
    data_json = json.dumps(data, separators=(',', ':'))

    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maritime Fleet Simulation</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {
  --navy:    #060e1f;
  --navy2:   #0c1a30;
  --navy3:   #142540;
  --cyan:    #00e5ff;
  --cyan2:   #00a8c0;
  --orange:  #ff6b35;
  --green:   #39ff14;
  --yellow:  #ffd23f;
  --red:     #ff3860;
  --muted:   #4a6080;
  --text:    #c8daf0;
  --text2:   #8baac8;
  --panel:   rgba(6,14,31,0.92);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; overflow: hidden; background: var(--navy); font-family: 'Exo 2', sans-serif; }

#app { display: flex; flex-direction: column; height: 100vh; }

/* ── HEADER ── */
#header {
  display: flex; align-items: center; gap: 20px;
  padding: 8px 20px;
  background: var(--navy2);
  border-bottom: 1px solid var(--navy3);
  z-index: 1000;
  flex-shrink: 0;
}
#header h1 {
  font-family: 'Share Tech Mono', monospace;
  font-size: 1.1rem;
  color: var(--cyan);
  letter-spacing: 0.2em;
  white-space: nowrap;
}
#date-display {
  font-family: 'Share Tech Mono', monospace;
  font-size: 1.4rem;
  color: var(--yellow);
  letter-spacing: 0.1em;
  min-width: 90px;
}
#step-counter {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.75rem;
  color: var(--muted);
}

/* ── TRANSPORT BAR ── */
#transport {
  display: flex; align-items: center; gap: 8px;
  padding: 0 12px;
}
.tb-btn {
  background: transparent;
  border: 1px solid var(--navy3);
  color: var(--text2);
  font-size: 1rem;
  width: 34px; height: 34px;
  border-radius: 4px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.tb-btn:hover { border-color: var(--cyan); color: var(--cyan); }
.tb-btn.active { background: rgba(0,229,255,0.12); border-color: var(--cyan); color: var(--cyan); }
#speed-label {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.7rem;
  color: var(--muted);
  padding: 0 4px;
}

/* ── TIMELINE SCRUBBER ── */
#scrubber-wrap {
  flex: 1;
  display: flex; align-items: center; gap: 8px;
  padding: 0 8px;
}
#scrubber {
  -webkit-appearance: none;
  width: 100%; height: 4px;
  background: var(--navy3);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
}
#scrubber::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px; height: 14px;
  background: var(--cyan);
  border-radius: 50%;
  cursor: pointer;
}

/* ── MARKET TICKER ── */
#ticker {
  display: flex; gap: 16px; align-items: center;
  padding: 0 12px;
  border-left: 1px solid var(--navy3);
}
.tick-item {
  display: flex; flex-direction: column; align-items: flex-end;
  line-height: 1.2;
}
.tick-label { font-size: 0.6rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
.tick-value { font-family: 'Share Tech Mono', monospace; font-size: 0.85rem; color: var(--cyan); }
.tick-value.up   { color: var(--green); }
.tick-value.down { color: var(--red); }

/* ── CONSTRAINTS BADGE STRIP ── */
#constraint-strip {
  padding: 0 4px;
  display: flex; align-items: center; gap: 4px;
  min-width: 120px;
}
.cst-badge {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.6rem;
  padding: 2px 6px;
  border-radius: 2px;
  border: 1px solid var(--orange);
  color: var(--orange);
  background: rgba(255,107,53,0.08);
  white-space: nowrap;
}

/* ── MAIN AREA ── */
#main { display: flex; flex: 1; overflow: hidden; }

/* ── MAP ── */
#map {
  flex: 1;
  position: relative;
  background: var(--navy);
}

/* Custom Leaflet tile darkness */
.leaflet-tile { filter: brightness(0.35) saturate(0.4) hue-rotate(180deg); }
.leaflet-container { background: #020810; }
.leaflet-control-zoom a { background: var(--navy2) !important; color: var(--text2) !important; border-color: var(--navy3) !important; }

/* ── SIDE PANEL ── */
#side-panel {
  width: 260px;
  background: var(--panel);
  border-left: 1px solid var(--navy3);
  display: flex; flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}
.panel-section {
  padding: 12px 14px;
  border-bottom: 1px solid var(--navy3);
}
.panel-title {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  color: var(--muted);
  text-transform: uppercase;
  margin-bottom: 8px;
}

/* Fleet breakdown bars */
.fleet-row {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 5px;
}
.fleet-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.fleet-name {
  font-size: 0.72rem;
  color: var(--text2);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
}
.fleet-bar-wrap {
  width: 80px;
  height: 4px;
  background: var(--navy3);
  border-radius: 2px;
  overflow: hidden;
}
.fleet-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.fleet-count {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.68rem;
  color: var(--text);
  min-width: 20px;
  text-align: right;
}

/* Region popup card */
#region-popup {
  position: absolute;
  z-index: 2000;
  background: var(--panel);
  border: 1px solid var(--cyan2);
  border-radius: 4px;
  padding: 12px 14px;
  min-width: 180px;
  pointer-events: none;
  display: none;
  backdrop-filter: blur(8px);
}
#region-popup h4 {
  font-family: 'Share Tech Mono', monospace;
  color: var(--cyan);
  font-size: 0.8rem;
  margin-bottom: 8px;
}
.rp-row {
  display: flex; justify-content: space-between; gap: 12px;
  font-size: 0.72rem;
  color: var(--text2);
  margin-bottom: 3px;
}
.rp-val { font-family: 'Share Tech Mono', monospace; color: var(--text); }

/* ── MINI SPARKLINE CHART ── */
#sparkline-canvas {
  width: 100%;
  height: 70px;
  display: block;
}
.spark-label {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.6rem;
  color: var(--muted);
  margin-bottom: 2px;
}

/* ── ROUTE LINES on map (SVG overlay) ── */
.route-line {
  stroke-opacity: 0.15;
  stroke-width: 1;
  fill: none;
}

/* ── Vessel SVG circles ── */
.vessel-circle {
  opacity: 0.9;
  transition: opacity 0.1s;
}

/* Scan line overlay */
#scanlines {
  position: absolute; inset: 0;
  pointer-events: none;
  z-index: 1500;
  background: repeating-linear-gradient(
    to bottom,
    transparent 0px,
    transparent 3px,
    rgba(0,0,0,0.04) 3px,
    rgba(0,0,0,0.04) 4px
  );
}

/* ── S/D RATIO BAR ── */
.sd-bar-wrap { margin-top: 6px; }
.sd-bar-bg { width: 100%; height: 6px; background: var(--navy3); border-radius: 3px; overflow: visible; position: relative; }
.sd-bar-fill { height: 100%; border-radius: 3px; transition: width 0.4s, background 0.4s; }
.sd-marker { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--text2); border-radius: 1px; }
.sd-value { font-family: 'Share Tech Mono', monospace; font-size: 0.75rem; margin-top: 2px; }

/* Legend */
.legend-item { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.legend-dot { border-radius: 50%; flex-shrink: 0; }
.legend-label { font-size: 0.68rem; color: var(--text2); }
.legend-group { display: flex; align-items: center; gap: 4px; margin-bottom: 3px; }
.legend-ring { border-radius: 50%; border: 2px solid var(--text2); flex-shrink: 0; }
</style>
</head>
<body>
<div id="app">

<!-- HEADER / TRANSPORT BAR -->
<div id="header">
  <h1>⬡ MARITIME SIM</h1>
  <div id="date-display">----</div>
  <div id="step-counter">step 0 / 0</div>

  <div id="transport">
    <button class="tb-btn" id="btn-prev" title="Step back">◀</button>
    <button class="tb-btn" id="btn-play" title="Play / Pause">▶</button>
    <button class="tb-btn" id="btn-next" title="Step forward">▶▶</button>
    <button class="tb-btn" id="btn-stop" title="Reset">■</button>
    <span id="speed-label">1×</span>
    <button class="tb-btn" id="btn-slower" title="Slower">−</button>
    <button class="tb-btn" id="btn-faster" title="Faster">+</button>
  </div>

  <div id="scrubber-wrap">
    <input type="range" id="scrubber" min="0" value="0">
  </div>

  <div id="ticker">
    <div class="tick-item">
      <span class="tick-label">Spot $/d</span>
      <span class="tick-value" id="t-spot">—</span>
    </div>
    <div class="tick-item">
      <span class="tick-label">WTI $/bbl</span>
      <span class="tick-value" id="t-wti">—</span>
    </div>
    <div class="tick-item">
      <span class="tick-label">VLSFO $/t</span>
      <span class="tick-value" id="t-vlsfo">—</span>
    </div>
    <div class="tick-item">
      <span class="tick-label">Fleet</span>
      <span class="tick-value" id="t-fleet">—</span>
    </div>
    <div class="tick-item">
      <span class="tick-label">Orderbook</span>
      <span class="tick-value" id="t-ob">—</span>
    </div>
  </div>

  <div id="constraint-strip"></div>
</div>

<!-- MAIN -->
<div id="main">
  <div id="map">
    <div id="scanlines"></div>
    <div id="region-popup"></div>
  </div>

  <div id="side-panel">
    <!-- Fleet breakdown -->
    <div class="panel-section">
      <div class="panel-title">Fleet Composition</div>
      <div id="fleet-breakdown"></div>
    </div>

    <!-- S/D balance -->
    <div class="panel-section">
      <div class="panel-title">Oil S/D Balance</div>
      <div class="sd-bar-wrap">
        <div class="sd-bar-bg">
          <div class="sd-bar-fill" id="sd-bar"></div>
          <div class="sd-marker" id="sd-marker" style="left:50%"></div>
        </div>
        <div class="sd-value" id="sd-value">—</div>
      </div>
    </div>

    <!-- Spot rate sparkline -->
    <div class="panel-section" style="flex:1">
      <div class="panel-title">Spot Rate History</div>
      <div class="spark-label" id="spark-label"></div>
      <canvas id="sparkline-canvas"></canvas>
    </div>

    <!-- Legend -->
    <div class="panel-section">
      <div class="panel-title">Legend</div>
      <div style="margin-bottom:6px;font-size:0.65rem;color:var(--muted)">Owner colour</div>
      <div id="owner-legend"></div>
      <div style="margin:6px 0;font-size:0.65rem;color:var(--muted)">Size = vessel class</div>
      <div id="size-legend"></div>
    </div>
  </div>
</div>
</div>

<script>
// ── INJECT SIMULATION DATA ───────────────────────────────────────────────────
const SIM = """ + data_json + r""";

// ── CONSTANTS ────────────────────────────────────────────────────────────────
const TOTAL_STEPS = SIM.steps.length;
const COMPANY_COLORS = SIM.company_colors;
const GROUP_RADIUS   = SIM.group_radius;

// ── STATE ────────────────────────────────────────────────────────────────────
let currentStep  = 0;
let isPlaying    = false;
let playInterval = null;
let playSpeed    = 1; // steps per tick
let tickMs       = 600;
let prevSpotRate = null;
let hoveredRegion = null;

// ── LEAFLET MAP SETUP ────────────────────────────────────────────────────────
const map = L.map('map', {
  center: [20, 20],
  zoom: 2,
  zoomControl: true,
  attributionControl: false,
  minZoom: 2, maxZoom: 6,
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '',
  maxZoom: 6,
}).addTo(map);

// ── ROUTE POLYLINES (static) ─────────────────────────────────────────────────
const routeLines = {};
Object.entries(SIM.routes).forEach(([key, route]) => {
  const latlngs = route.waypoints.map(([la, lo]) => [la, lo]);
  const line = L.polyline(latlngs, {
    color: '#00e5ff', opacity: 0.08, weight: 1.5,
    dashArray: '4 6',
  }).addTo(map);
  routeLines[key] = line;
});

// ── NODE MARKERS (chokepoints) ────────────────────────────────────────────────
const nodeMarkers = {};
Object.entries(SIM.nodes).forEach(([name, coords]) => {
  const el = L.divIcon({
    className: '',
    html: `<div style="
      width:10px;height:10px;
      border-radius:50%;
      border:2px solid #ffd23f;
      background:rgba(255,210,63,0.15);
      box-shadow:0 0 8px rgba(255,210,63,0.5)
    "></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
  });
  const marker = L.marker([coords.lat, coords.lon], { icon: el })
    .bindTooltip(name, { permanent: false, className: 'leaflet-tooltip-dark' })
    .addTo(map);
  nodeMarkers[name] = marker;
});

// ── REGION MARKERS ───────────────────────────────────────────────────────────
const regionMarkers = {};

function makeRegionIcon(name, stepData) {
  const rdata = stepData.regions[name] || {};
  const sd = rdata.supply > 0 ? rdata.demand / rdata.supply : 0;
  const barW = Math.min(100, Math.round(sd * 50));
  const barColor = sd > 1.1 ? '#ff3860' : sd > 0.9 ? '#39ff14' : '#ffd23f';
  return L.divIcon({
    className: '',
    html: `<div class="region-marker" data-region="${name}" style="
      position:relative;
      padding:4px 8px;
      background:rgba(6,14,31,0.82);
      border:1px solid rgba(0,229,255,0.4);
      border-radius:3px;
      font-family:'Share Tech Mono',monospace;
      font-size:0.58rem;
      color:#c8daf0;
      cursor:pointer;
      white-space:nowrap;
      min-width:70px;
      box-shadow:0 0 12px rgba(0,229,255,0.15);
    ">
      <div style="color:#00e5ff;font-size:0.65rem;margin-bottom:2px">${name.substring(0,10)}</div>
      <div style="display:flex;gap:6px;font-size:0.55rem;color:#8baac8">
        <span>S:${(rdata.supply||0).toFixed(1)}</span>
        <span>D:${(rdata.demand||0).toFixed(1)}</span>
      </div>
      <div style="height:3px;background:#142540;margin-top:3px;border-radius:2px;overflow:hidden">
        <div style="width:${barW}%;height:100%;background:${barColor};border-radius:2px"></div>
      </div>
    </div>`,
    iconSize: [90, 44],
    iconAnchor: [45, 22],
  });
}

Object.entries(SIM.regions).forEach(([name, coords]) => {
  const step0 = SIM.steps[0];
  const icon  = makeRegionIcon(name, step0);
  const marker = L.marker([coords.lat, coords.lon], { icon })
    .addTo(map);
  marker.on('mouseover', (e) => showRegionPopup(name, e));
  marker.on('mouseout',  ()  => hideRegionPopup());
  regionMarkers[name] = marker;
});

// ── VESSEL LAYER (SVG overlay) ───────────────────────────────────────────────
const vesselLayer = L.layerGroup().addTo(map);
const vesselMarkers = {};  // id → leaflet circleMarker

function ensureVessel(v) {
  if (vesselMarkers[v.id]) return vesselMarkers[v.id];
  const m = L.circleMarker([v.lat, v.lon], {
    radius: v.radius,
    color: v.color,
    fillColor: v.color,
    fillOpacity: 0.85,
    weight: 1.2,
    opacity: 0.9,
  });
  m.bindTooltip(
    `<b style="color:${v.color}">${v.owner}</b><br>${v.type}<br>${v.group}`,
    { sticky: true, className: 'vessel-tip' }
  );
  m.addTo(vesselLayer);
  vesselMarkers[v.id] = m;
  return m;
}

function updateVessels(step) {
  const frame = SIM.frames[step] || [];
  const frameIds = new Set(frame.map(v => v.id));

  // Remove old
  Object.keys(vesselMarkers).forEach(id => {
    if (!frameIds.has(parseInt(id))) {
      vesselLayer.removeLayer(vesselMarkers[id]);
      delete vesselMarkers[id];
    }
  });

  // Update / create
  frame.forEach(v => {
    const m = ensureVessel(v);
    m.setLatLng([v.lat, v.lon]);
  });
}

// ── REGION POPUP ─────────────────────────────────────────────────────────────
function showRegionPopup(name, e) {
  const popup = document.getElementById('region-popup');
  const stepData = SIM.steps[currentStep];
  const rdata = stepData.regions[name] || {};
  const sd = rdata.supply > 0 ? (rdata.demand / rdata.supply).toFixed(3) : '—';
  popup.innerHTML = `
    <h4>${name}</h4>
    <div class="rp-row"><span>Supply</span><span class="rp-val">${(rdata.supply||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>Demand</span><span class="rp-val">${(rdata.demand||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>Storage</span><span class="rp-val">${(rdata.storage||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>D/S ratio</span><span class="rp-val">${sd}</span></div>
  `;
  // Position near cursor but within map
  const mapEl = document.getElementById('map');
  const rect  = mapEl.getBoundingClientRect();
  let x = e.originalEvent.clientX - rect.left + 12;
  let y = e.originalEvent.clientY - rect.top  + 12;
  if (x + 200 > rect.width)  x -= 210;
  if (y + 120 > rect.height) y -= 130;
  popup.style.left = x + 'px';
  popup.style.top  = y + 'px';
  popup.style.display = 'block';
}

function hideRegionPopup() {
  document.getElementById('region-popup').style.display = 'none';
}

// ── UPDATE NODE COLOURS (open/closed) ────────────────────────────────────────
function updateNodes(stepData) {
  Object.entries(nodeMarkers).forEach(([name, marker]) => {
    const open  = stepData.nodes[name] !== false;
    const color = open ? '#ffd23f' : '#ff3860';
    const bg    = open ? 'rgba(255,210,63,0.15)' : 'rgba(255,56,96,0.25)';
    const shadow = open ? '0 0 8px rgba(255,210,63,0.5)' : '0 0 14px rgba(255,56,96,0.7)';
    marker.setIcon(L.divIcon({
      className: '',
      html: `<div style="width:10px;height:10px;border-radius:50%;border:2px solid ${color};background:${bg};box-shadow:${shadow}"></div>`,
      iconSize: [10, 10], iconAnchor: [5, 5],
    }));
  });
}

// ── SIDE PANEL UPDATES ───────────────────────────────────────────────────────
const FLEET_TYPE_COLORS = {
  'VLCC_KR':          '#00d4ff',
  'VLCC_scrubber_KR': '#38bdf8',
  'VLCC_CN':          '#fb923c',
  'Suezmax_KR':       '#4ade80',
  'Aframax_GR':       '#a78bfa',
  'Aframax_RU':       '#f472b6',
  'MR_NO':            '#fbbf24',
};

function updateFleetPanel(stepData) {
  const fleet = stepData.fleet;
  const total = Object.values(fleet).reduce((a, b) => a + b, 0);
  const el = document.getElementById('fleet-breakdown');
  el.innerHTML = Object.entries(fleet).map(([type, count]) => {
    const pct = total > 0 ? (count / total * 100).toFixed(0) : 0;
    const color = FLEET_TYPE_COLORS[type] || '#8892b0';
    return `<div class="fleet-row">
      <div class="fleet-dot" style="background:${color}"></div>
      <div class="fleet-name">${type}</div>
      <div class="fleet-bar-wrap"><div class="fleet-bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="fleet-count">${count}</div>
    </div>`;
  }).join('');
}

function updateSDBar(stepData) {
  const sd = stepData.sd_ratio;
  // Bar: 0 = 0.5 ratio, 100% = 1.5 ratio
  const pct  = Math.min(100, Math.max(0, (sd - 0.5) / 1.0 * 100));
  const color = sd > 1.15 ? '#ff3860' : sd > 0.95 ? '#39ff14' : '#ffd23f';
  document.getElementById('sd-bar').style.width = pct + '%';
  document.getElementById('sd-bar').style.background = color;
  // Marker at equilibrium (sd=1.0 → 50%)
  document.getElementById('sd-marker').style.left = '50%';
  document.getElementById('sd-value').textContent = `S/D = ${sd.toFixed(3)}`;
  document.getElementById('sd-value').style.color = color;
}

function updateSparkline(upTo) {
  const canvas = document.getElementById('sparkline-canvas');
  const ctx    = canvas.getContext('2d');
  canvas.width  = canvas.offsetWidth  * window.devicePixelRatio;
  canvas.height = canvas.offsetHeight * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  const W = canvas.offsetWidth, H = canvas.offsetHeight;

  const rates = SIM.steps.slice(0, upTo + 1).map(s => s.spot_rate);
  const mn    = Math.min(...rates);
  const mx    = Math.max(...rates);
  const range = mx - mn || 1;

  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#00e5ff';
  ctx.lineWidth   = 1.5;
  ctx.shadowColor = '#00e5ff';
  ctx.shadowBlur  = 4;
  ctx.beginPath();
  rates.forEach((r, i) => {
    const x = (i / (rates.length - 1 || 1)) * W;
    const y = H - ((r - mn) / range) * (H - 6) - 3;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Fill under
  ctx.shadowBlur = 0;
  ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = 'rgba(0,229,255,0.06)';
  ctx.fill();

  // Current point
  if (rates.length > 0) {
    const last = rates[rates.length - 1];
    const x = ((rates.length - 1) / (SIM.steps.length - 1)) * W;
    const y = H - ((last - mn) / range) * (H - 6) - 3;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#00e5ff';
    ctx.fill();
  }

  document.getElementById('spark-label').textContent =
    `$${(SIM.steps[upTo].spot_rate / 1000).toFixed(1)}k/day`;
}

function updateTicker(stepData) {
  const spot = stepData.spot_rate;
  const dir  = prevSpotRate === null ? '' : spot > prevSpotRate ? 'up' : spot < prevSpotRate ? 'down' : '';
  document.getElementById('t-spot').textContent  = '$' + (spot/1000).toFixed(1) + 'k';
  document.getElementById('t-spot').className    = 'tick-value ' + dir;
  document.getElementById('t-wti').textContent   = '$' + stepData.wti.toFixed(1);
  document.getElementById('t-vlsfo').textContent = '$' + stepData.vlsfo.toFixed(0);
  document.getElementById('t-fleet').textContent = stepData.fleet_active
    + (stepData.fleet_storage > 0 ? '+' + stepData.fleet_storage + '⚓' : '');
  document.getElementById('t-ob').textContent    = stepData.orderbook;
  prevSpotRate = spot;
}

function updateConstraints(stepData) {
  const strip = document.getElementById('constraint-strip');
  const parts = stepData.constraints.split(';').filter(Boolean);
  strip.innerHTML = parts.map(c => `<span class="cst-badge">${c}</span>`).join('');
}

// ── LEGEND INIT ──────────────────────────────────────────────────────────────
function buildLegend() {
  const ol = document.getElementById('owner-legend');
  ol.innerHTML = Object.entries(COMPANY_COLORS).map(([owner, color]) =>
    `<div class="legend-item">
       <div class="legend-dot" style="width:8px;height:8px;background:${color}"></div>
       <span class="legend-label">${owner}</span>
     </div>`
  ).join('');

  const sl = document.getElementById('size-legend');
  sl.innerHTML = Object.entries(GROUP_RADIUS).map(([group, r]) =>
    `<div class="legend-group">
       <div class="legend-ring" style="width:${r*2+2}px;height:${r*2+2}px;border-color:#8baac8"></div>
       <span class="legend-label" style="font-size:0.65rem">${group}</span>
     </div>`
  ).join('');
}

// ── MASTER RENDER ─────────────────────────────────────────────────────────────
function render(step) {
  currentStep = Math.max(0, Math.min(TOTAL_STEPS - 1, step));
  const stepData = SIM.steps[currentStep];

  // Header
  document.getElementById('date-display').textContent = stepData.date;
  document.getElementById('step-counter').textContent =
    `step ${currentStep + 1} / ${TOTAL_STEPS}`;
  document.getElementById('scrubber').value = currentStep;

  // Map elements
  updateVessels(currentStep);
  updateNodes(stepData);
  Object.keys(SIM.regions).forEach(name => {
    regionMarkers[name].setIcon(makeRegionIcon(name, stepData));
  });

  // Side panel
  updateFleetPanel(stepData);
  updateSDBar(stepData);
  updateSparkline(currentStep);
  updateTicker(stepData);
  updateConstraints(stepData);
}

// ── PLAYBACK CONTROLS ────────────────────────────────────────────────────────
const SPEED_STEPS = [1, 2, 4, 8];
let speedIdx = 0;

function setPlaying(val) {
  isPlaying = val;
  document.getElementById('btn-play').textContent = isPlaying ? '⏸' : '▶';
  document.getElementById('btn-play').classList.toggle('active', isPlaying);
  if (isPlaying) {
    playInterval = setInterval(() => {
      const next = currentStep + SPEED_STEPS[speedIdx];
      if (next >= TOTAL_STEPS) {
        setPlaying(false);
        return;
      }
      render(next);
    }, tickMs);
  } else {
    clearInterval(playInterval);
  }
}

document.getElementById('btn-play').addEventListener('click', () => setPlaying(!isPlaying));
document.getElementById('btn-stop').addEventListener('click', () => { setPlaying(false); render(0); });
document.getElementById('btn-prev').addEventListener('click', () => { setPlaying(false); render(currentStep - 1); });
document.getElementById('btn-next').addEventListener('click', () => { setPlaying(false); render(currentStep + 1); });
document.getElementById('btn-faster').addEventListener('click', () => {
  speedIdx = Math.min(speedIdx + 1, SPEED_STEPS.length - 1);
  document.getElementById('speed-label').textContent = SPEED_STEPS[speedIdx] + '×';
});
document.getElementById('btn-slower').addEventListener('click', () => {
  speedIdx = Math.max(speedIdx - 1, 0);
  document.getElementById('speed-label').textContent = SPEED_STEPS[speedIdx] + '×';
});
document.getElementById('scrubber').addEventListener('input', function() {
  setPlaying(false);
  render(parseInt(this.value));
});

// ── INIT ──────────────────────────────────────────────────────────────────────
document.getElementById('scrubber').max = TOTAL_STEPS - 1;
buildLegend();
render(0);
// Brief pause then auto-play
setTimeout(() => setPlaying(true), 800);
</script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  → Wrote {output_path}  ({os.path.getsize(output_path)//1024} KB)")


def main():
    p = argparse.ArgumentParser(description="Generate maritime simulation map viewer")
    p.add_argument("--granularity", choices=["week","month","quarter","year"], default="month")
    p.add_argument("--periods", type=int, default=48)
    p.add_argument("--seed",    type=int, default=42)
    p.add_argument("--out",     default="maritime_map.html")
    args = p.parse_args()

    data = build_sim_json(args.granularity, args.periods, args.seed)
    generate_html(data, args.out)
    print(f"\nDone. Open {args.out} in a browser.")
    print("Requires internet for Leaflet tiles (openstreetmap.org)")


if __name__ == "__main__":
    main()
