#!/usr/bin/env python3
"""
Maritime Fleet Simulation — Unified Portal
==========================================
Self-contained single-file server.  Run from maritime_sim_v2/:

    python portal.py [--port 8765]

Then open http://localhost:8765 in your browser.

Architecture:
  • Python HTTP server handles /api/* endpoints
  • Single HTML page with 5 tabs: Map · Configure · Dashboard · Scenario · Export
  • Simulation runs server-side on POST /api/run
  • Map animation and charts run entirely in the browser
"""

import sys, os, json, math, random, copy, io, csv, threading, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import numpy as np
import pandas as pd

# ── NaN / Inf / numpy → JSON-safe ────────────────────────────────────────────
def _clean(obj):
    """Recursively replace NaN/Inf with None, numpy types with Python types."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    tp = type(obj).__name__
    if tp in ('float32', 'float64', 'float16'):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if tp in ('int8','int16','int32','int64','uint8','uint16','uint32','uint64'):
        return int(obj)
    if tp == 'bool_':
        return bool(obj)
    return obj

def safe_json(obj):
    """json.dumps with NaN→null cleaning (valid JSON, browser-safe)."""
    return json.dumps(_clean(obj), separators=(',', ':'))


# ── Import simulation components ──────────────────────────────────────────────
from core.enums import Granularity, ConstraintType, ShipCountry
from core.models import SimConfig, ScenarioConstraint
from config.schemas import (
    load_regions, load_companies, load_ship_types, load_nodes,
    load_edges, load_constraints, load_orderbook,
    template_regions, template_region_demand, template_region_supply,
    template_region_storage, template_port_times,
    template_companies, template_ship_types, template_fleet,
    template_orderbook, template_nodes, template_edges, template_constraints,
    ALL_TEMPLATES,
)
from core.engine import SimulationRunner

# ── Map constants (shared with frontend) ─────────────────────────────────────
COMPANY_COLORS = {
    "Saudi Aramco": "#00d4ff",
    "Shell":        "#ffd23f",
    "ExxonMobil":   "#ff6b35",
    "BP":           "#4ade80",
    "Rosneft":      "#f472b6",
    "CNOOC":        "#fb923c",
    "Independent":  "#94a3b8",
}
GROUP_RADIUS = {"VLCC": 9, "Suezmax": 7, "Aframax": 5, "Panamax": 4, "MR": 3}

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
    "Strait of Hormuz":   {"lat": 26.6, "lon":  56.4},
    "Suez Canal":         {"lat": 30.7, "lon":  32.3},
    "Strait of Malacca":  {"lat":  3.0, "lon": 101.5},
    "Danish Straits":     {"lat": 57.8, "lon":  10.5},
    "Panama Canal":       {"lat":  9.1, "lon": -79.7},
    "Cape of Good Hope":  {"lat":-34.4, "lon":  18.5},
}
ROUTES = [
    ("Persian Gulf","Mediterranean",   ["Strait of Hormuz","Suez Canal"],
     [[25.5,57],[27,51],[27.5,43],[29.5,38],[30.7,32.3],[31.5,29],[33,25],[35,22],[36.5,18.5],[37.5,18]]),
    ("Persian Gulf","Southeast Asia",  ["Strait of Hormuz","Strait of Malacca"],
     [[25.5,57],[15,65],[8,77],[4,82],[3,95],[3,101.5],[4,107],[4.5,110.5]]),
    ("Persian Gulf","USGulf",          ["Strait of Hormuz","Cape of Good Hope"],
     [[25.5,57],[15,52],[5,45],[-5,38],[-15,30],[-25,22],[-34.4,18.5],[-35,5],[-25,-15],[-10,-30],[5,-40],[15,-55],[22,-72],[28.5,-90]]),
    ("Baltic","Mediterranean",         ["Danish Straits"],
     [[59.5,22],[58.5,15],[57.8,10.5],[56,8],[54,7],[52,4],[50,2],[46,3],[43,6],[40,12],[37.5,18]]),
    ("North Sea","Mediterranean",      [],
     [[57.5,2.5],[55,1],[52,3],[49,2],[46,3],[44,8],[40,12],[37.5,18]]),
    ("West Africa","USGulf",           [],
     [[3.5,3.5],[5,-5],[8,-20],[12,-35],[18,-55],[22,-72],[28.5,-90]]),
    ("West Africa","Mediterranean",    [],
     [[3.5,3.5],[10,0],[20,-5],[28,-2],[33,5],[36,10],[37.5,18]]),
    ("USGulf","Caribbean",             [],
     [[28.5,-90],[25,-84],[22,-80],[18,-77],[14.5,-75]]),
    ("Alaska","USGulf",                [],
     [[60.5,-149.5],[55,-140],[50,-130],[45,-125],[38,-123],[30,-115],[28.5,-90]]),
    ("Southeast Asia","North Sea",     ["Strait of Malacca","Suez Canal"],
     [[4.5,110.5],[3,101.5],[3,90],[8,77],[15,60],[25,45],[28,38],[30.7,32.3],[32,29],[35,25],[37,22],[39,16],[42,10],[46,5],[50,2],[54,5],[57.5,2.5]]),
    ("Mediterranean","Persian Gulf",   ["Suez Canal","Strait of Hormuz"],
     [[37.5,18],[35,22],[33,25],[31.5,29],[30.7,32.3],[29.5,38],[27.5,43],[27,51],[25.5,57],[26,54]]),
]

def build_route_index():
    idx = {}
    for i, (fr, to, nodes, wpts) in enumerate(ROUTES):
        key = f"route_{i}"
        idx[key] = {"from": fr, "to": to, "nodes": nodes, "waypoints": wpts}
    return idx

def type_to_group(name):
    for g in GROUP_RADIUS:
        if g.lower() in name.lower():
            return g
    return "MR"

def type_to_owner(st_name):
    if "CN" in st_name:  return "CNOOC"
    if "RU" in st_name:  return "Rosneft"
    if "NO" in st_name:  return "Shell"
    if "GR" in st_name:  return "BP"
    if "scrubber" in st_name.lower(): return "Saudi Aramco"
    if "VLCC_KR" in st_name: return "Saudi Aramco"
    return "Independent"

# ── SERVER STATE (shared, thread-safe via GIL for dicts) ─────────────────────
STATE = {
    "tables": {},          # name → list-of-dicts (editable config tables)
    "sim_result": None,    # last simulation result JSON
    "sim_running": False,
    "sim_progress": 0,
    "sim_error": None,
    "run_config": {        # current run configuration
        "granularity": "month",
        "n_periods": 48,
        "seed": 42,
        "base_spot_rate": 25000,
        "spot_volatility": 0.25,
        "fuel_vlsfo": 600,
        "fuel_hfo": 450,
        "wti_price": 75,
        "ordering_sensitivity": 0.30,
        "scrapping_threshold": 8000,
        "storage_sd_threshold": 1.4,
    },
}

# ── Load all templates into STATE.tables on startup ───────────────────────────
def init_tables():
    for name, fn in ALL_TEMPLATES.items():
        df = fn()
        # pandas None/NaN → None (JSON null) to avoid browser JSON parse failures
        rows = df.where(df.notna(), other=None).to_dict(orient="records")
        STATE["tables"][name] = _clean(rows)
    print(f"  Loaded {len(STATE['tables'])} config tables")

# ── Simulation runner (called in background thread) ───────────────────────────
def run_simulation_task(run_cfg, tables):
    try:
        STATE["sim_running"] = True
        STATE["sim_error"]   = None
        STATE["sim_progress"] = 5

        gran = Granularity(run_cfg["granularity"])
        cfg  = SimConfig(
            granularity=gran,
            n_periods=int(run_cfg["n_periods"]),
            random_seed=int(run_cfg["seed"]),
            base_spot_rate_usd_day=float(run_cfg["base_spot_rate"]),
            spot_rate_volatility=float(run_cfg["spot_volatility"]),
            vlsfo_price_usd_t=float(run_cfg["fuel_vlsfo"]),
            hfo_price_usd_t=float(run_cfg["fuel_hfo"]),
            wti_price_usd_bbl=float(run_cfg["wti_price"]),
            ordering_sensitivity=float(run_cfg["ordering_sensitivity"]),
            scrapping_threshold_usd_day=float(run_cfg["scrapping_threshold"]),
            storage_conversion_sd_ratio=float(run_cfg["storage_sd_threshold"]),
        )

        def _df(name): return pd.DataFrame(tables.get(name, []))

        regions    = load_regions(_df("regions"), _df("region_demand"),
                                   _df("region_supply"), _df("region_storage"),
                                   _df("port_times"))
        companies  = load_companies(_df("companies"))
        ship_types = load_ship_types(_df("ship_types"))
        nodes      = load_nodes(_df("nodes"))
        edges      = load_edges(_df("edges"))
        constraints= load_constraints(_df("constraints"))
        orderbook  = load_orderbook(_df("orderbook"), ship_types)
        fleet_df   = _df("fleet")

        STATE["sim_progress"] = 20

        runner = SimulationRunner(cfg, regions, companies, ship_types,
                                   fleet_df, orderbook, nodes, edges, constraints)
        df = runner.run()
        STATE["sim_progress"] = 70

        # Build vessel animation frames
        route_index = build_route_index()
        route_keys  = list(route_index.keys())
        rng = random.Random(int(run_cfg["seed"]))

        vessels = []
        vid = 0
        type_cols = [c for c in df.columns if c.startswith("active_") and c != "active_constraints"]

        first = df.iloc[0]
        for col in type_cols:
            st_name = col[len("active_"):]
            count = int(first[col])
            group = type_to_group(st_name)
            owner = type_to_owner(st_name)
            for _ in range(count):
                rk = route_keys[vid % len(route_keys)]
                vessels.append({
                    "id": vid, "type": st_name, "group": group,
                    "owner": owner,
                    "color": COMPANY_COLORS.get(owner, "#94a3b8"),
                    "radius": GROUP_RADIUS.get(group, 4),
                    "route_key": rk,
                    "progress": rng.uniform(0, 1),
                    "speed": rng.uniform(0.025, 0.055),
                    "status": "active",
                })
                vid += 1

        frames = []
        for step_idx, row in df.iterrows():
            # Sync counts
            for col in type_cols:
                st_name = col[len("active_"):]
                new_count = int(row[col])
                current = sum(1 for v in vessels if v["type"] == st_name and v["status"] == "active")
                diff = new_count - current
                if diff > 0:
                    group = type_to_group(st_name)
                    owner = type_to_owner(st_name)
                    for _ in range(diff):
                        rk = route_keys[vid % len(route_keys)]
                        vessels.append({
                            "id": vid, "type": st_name, "group": group,
                            "owner": owner,
                            "color": COMPANY_COLORS.get(owner, "#94a3b8"),
                            "radius": GROUP_RADIUS.get(group, 4),
                            "route_key": rk,
                            "progress": rng.uniform(0, 1),
                            "speed": rng.uniform(0.025, 0.055),
                            "status": "active",
                        })
                        vid += 1
                elif diff < 0:
                    removed = 0
                    for v in reversed(vessels):
                        if v["type"] == st_name and v["status"] == "active":
                            v["status"] = "scrapped"
                            removed += 1
                            if removed >= abs(diff): break

            fv = []
            for v in vessels:
                if v["status"] != "active": continue
                v["progress"] = (v["progress"] + v["speed"]) % 1.0
                route = route_index[v["route_key"]]
                wpts  = route["waypoints"]
                frac  = v["progress"] * (len(wpts) - 1)
                i0 = int(frac); i1 = min(i0+1, len(wpts)-1); t = frac - i0
                lat = wpts[i0][0] + t*(wpts[i1][0]-wpts[i0][0])
                lon = wpts[i0][1] + t*(wpts[i1][1]-wpts[i0][1])
                fv.append({"id": v["id"], "lat": round(lat,4), "lon": round(lon,4),
                            "color": v["color"], "radius": v["radius"],
                            "type": v["type"], "owner": v["owner"], "group": v["group"]})
            frames.append(fv)

        STATE["sim_progress"] = 90

        # Build compact steps array
        steps = []
        region_names = list(REGION_COORDS.keys())
        node_names   = list(NODE_COORDS.keys())
        for idx, row in df.iterrows():
            fleet_bd = {}
            for col in type_cols:
                fleet_bd[col[len("active_"):]] = int(row[col])

            regions_data = {}
            for rname in region_names:
                regions_data[rname] = {
                    "demand":  round(float(row.get(f"demand_{rname}", 0)), 3),
                    "supply":  round(float(row.get(f"supply_{rname}", 0)), 3),
                    "storage": round(float(row.get(f"storage_inv_{rname}", 0)), 3),
                }

            nodes_data = {}
            for nname in node_names:
                nk = "node_" + nname.replace(" ","_").replace(".","")
                nodes_data[nname] = bool(int(row.get(nk, 1)))

            steps.append({
                "date":          str(row["date_label"]),
                "spot_rate":     round(float(row["spot_rate"]), 0),
                "wti":           round(float(row["wti_usd_bbl"]), 2),
                "vlsfo":         round(float(row["vlsfo_usd_t"]), 1),
                "hfo":           round(float(row["hfo_usd_t"]), 1),
                "fleet_active":  int(row["fleet_active"]),
                "fleet_storage": int(row["fleet_storage"]),
                "orderbook":     int(row["orderbook"]),
                "sd_ratio":      round(float(row["sd_ratio"]), 4),
                "load_factor":   round(float(row["load_factor"]), 4),
                "constraints":   str(row.get("active_constraints", "")),
                "fleet":         fleet_bd,
                "regions":       regions_data,
                "nodes":         nodes_data,
            })

        result = {
            "meta": {"granularity": run_cfg["granularity"],
                     "n_periods": int(run_cfg["n_periods"]), "seed": int(run_cfg["seed"])},
            "regions":       REGION_COORDS,
            "nodes":         NODE_COORDS,
            "routes":        build_route_index(),
            "company_colors": COMPANY_COLORS,
            "group_radius":   GROUP_RADIUS,
            "steps":         steps,
            "frames":        frames,
        }
        STATE["sim_result"]   = result
        STATE["sim_progress"] = 100
        print(f"  Simulation done: {len(steps)} steps, {max(len(f) for f in frames)} vessels/frame")

    except Exception as e:
        import traceback
        STATE["sim_error"] = str(e) + "\n" + traceback.format_exc()
        print("SIM ERROR:", STATE["sim_error"])
    finally:
        STATE["sim_running"] = False


# ── HTTP REQUEST HANDLER ───────────────────────────────────────────────────────
class PortalHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default logging

    def _send_json(self, data, status=200):
        body = safe_json(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/":
            self._send_html(PORTAL_HTML)
        elif path == "/api/templates":
            self._send_json(STATE["tables"])
        elif path == "/api/run_config":
            self._send_json(STATE["run_config"])
        elif path == "/api/status":
            self._send_json({
                "running":  STATE["sim_running"],
                "progress": STATE["sim_progress"],
                "error":    STATE["sim_error"],
                "has_result": STATE["sim_result"] is not None,
            })
        elif path == "/api/result":
            if STATE["sim_result"]:
                self._send_json(STATE["sim_result"])
            else:
                self._send_json({"error": "no result yet"}, 404)
        elif path == "/api/export_csv":
            # Convert steps to CSV
            if not STATE["sim_result"]:
                self._send_json({"error": "no result"}, 404)
                return
            steps = STATE["sim_result"]["steps"]
            if not steps: self._send_json({"error": "empty"}); return
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(steps[0].keys()))
            w.writeheader()
            for s in steps: w.writerow({k: (safe_json(v) if isinstance(v, dict) else v) for k,v in s.items()})
            body = buf.getvalue().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=maritime_sim.csv")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/api/run":
            body = self._read_body()
            # Update run config
            if "config" in body:
                STATE["run_config"].update(body["config"])
            if STATE["sim_running"]:
                self._send_json({"error": "already running"}, 409)
                return
            tables_snapshot = copy.deepcopy(STATE["tables"])
            cfg_snapshot    = copy.deepcopy(STATE["run_config"])
            t = threading.Thread(target=run_simulation_task,
                                  args=(cfg_snapshot, tables_snapshot), daemon=True)
            t.start()
            self._send_json({"status": "started"})

        elif path == "/api/table":
            body = self._read_body()
            name = body.get("name")
            rows = body.get("rows")
            if name and rows is not None:
                STATE["tables"][name] = rows
                self._send_json({"status": "ok", "rows": len(rows)})
            else:
                self._send_json({"error": "bad request"}, 400)

        elif path == "/api/run_config":
            body = self._read_body()
            STATE["run_config"].update(body)
            self._send_json({"status": "ok"})

        else:
            self.send_response(404); self.end_headers()


# ──────────────────────────────────────────────────────────────────────────────
# PORTAL HTML — the entire frontend
# ──────────────────────────────────────────────────────────────────────────────
PORTAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maritime Fleet Portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {
  --bg:     #050c18; --bg2: #0a1628; --bg3: #0f2040; --bg4: #162a4a;
  --border: #1e3a5a; --border2: #254870;
  --cyan:   #00e5ff; --cyan2: #0099b5; --cyan3: rgba(0,229,255,0.12);
  --amber:  #ffd23f; --green: #39ff14; --red: #ff3860;
  --orange: #ff6b35; --violet: #a78bfa;
  --text:   #c8daf0; --text2: #7a9abb; --text3: #3d5a78;
  --mono:   'Share Tech Mono', monospace;
  --sans:   'Exo 2', sans-serif;
}
* { box-sizing:border-box; margin:0; padding:0; }
html,body { width:100%; height:100%; overflow:hidden; background:var(--bg); color:var(--text); font-family:var(--sans); font-size:13px; }

/* ── SHELL ── */
#shell { display:flex; flex-direction:column; height:100vh; }

/* ── TOPBAR ── */
#topbar {
  display:flex; align-items:center; gap:0;
  background:var(--bg2); border-bottom:1px solid var(--border);
  flex-shrink:0; height:42px;
}
#logo {
  padding:0 20px; font-family:var(--mono); font-size:0.9rem;
  color:var(--cyan); letter-spacing:0.2em; border-right:1px solid var(--border);
  height:100%; display:flex; align-items:center; white-space:nowrap;
}
#logo span { color:var(--text2); font-size:0.65rem; margin-left:10px; letter-spacing:0.1em; }

/* ── TAB BAR ── */
#tabs {
  display:flex; height:100%; border-right:1px solid var(--border);
}
.tab {
  padding:0 18px; cursor:pointer;
  font-family:var(--mono); font-size:0.7rem; letter-spacing:0.12em;
  color:var(--text2); border-right:1px solid var(--border);
  display:flex; align-items:center; gap:7px;
  transition:all 0.15s; white-space:nowrap; height:100%;
  border-bottom:2px solid transparent;
}
.tab:hover  { color:var(--text); background:var(--bg3); }
.tab.active { color:var(--cyan); border-bottom-color:var(--cyan); background:var(--bg3); }
.tab-icon   { font-size:0.9rem; }

/* ── RUN STATUS AREA ── */
#run-area {
  margin-left:auto; display:flex; align-items:center; gap:10px;
  padding:0 16px;
}
#run-btn {
  background:rgba(0,229,255,0.1); border:1px solid var(--cyan2);
  color:var(--cyan); font-family:var(--mono); font-size:0.7rem;
  padding:5px 16px; border-radius:3px; cursor:pointer; letter-spacing:0.1em;
  transition:all 0.15s;
}
#run-btn:hover   { background:rgba(0,229,255,0.2); }
#run-btn:disabled { opacity:0.4; cursor:not-allowed; }
#run-progress {
  display:none; width:120px; height:4px;
  background:var(--bg4); border-radius:2px; overflow:hidden;
}
#run-progress-bar { height:100%; background:var(--cyan); width:0; transition:width 0.3s; border-radius:2px; }
#run-status-text { font-family:var(--mono); font-size:0.65rem; color:var(--text2); }

/* ── CONTENT AREA ── */
#content { flex:1; overflow:hidden; position:relative; }
.panel { position:absolute; inset:0; display:none; overflow:auto; }
.panel.active { display:flex; }

/* ─────────────────────────────────────────────
   MAP TAB
───────────────────────────────────────────── */
#panel-map { flex-direction:column; overflow:hidden; }

/* Transport strip */
#transport-bar {
  display:flex; align-items:center; gap:8px;
  background:var(--bg2); border-bottom:1px solid var(--border);
  padding:5px 14px; flex-shrink:0; flex-wrap:wrap;
}
#date-badge {
  font-family:var(--mono); font-size:1.2rem; color:var(--amber);
  letter-spacing:0.08em; min-width:80px;
}
#step-badge { font-family:var(--mono); font-size:0.65rem; color:var(--text3); min-width:70px; }
.tb-btn {
  background:transparent; border:1px solid var(--border);
  color:var(--text2); width:30px; height:30px; border-radius:3px;
  cursor:pointer; display:flex; align-items:center; justify-content:center;
  font-size:0.9rem; transition:all 0.12s; flex-shrink:0;
}
.tb-btn:hover  { border-color:var(--cyan); color:var(--cyan); }
.tb-btn.active { background:var(--cyan3); border-color:var(--cyan); color:var(--cyan); }
#speed-ind { font-family:var(--mono); font-size:0.68rem; color:var(--text3); min-width:24px; }
#scrubber-wrap { flex:1; min-width:100px; }
#scrubber {
  -webkit-appearance:none; width:100%; height:4px;
  background:var(--bg4); border-radius:2px; outline:none; cursor:pointer;
}
#scrubber::-webkit-slider-thumb {
  -webkit-appearance:none; width:13px; height:13px;
  background:var(--cyan); border-radius:50%; cursor:pointer;
}
.ticker-group { display:flex; gap:14px; border-left:1px solid var(--border); padding-left:14px; }
.tick { display:flex; flex-direction:column; align-items:flex-end; line-height:1.1; }
.tick-l { font-size:0.55rem; color:var(--text3); text-transform:uppercase; letter-spacing:0.08em; }
.tick-v { font-family:var(--mono); font-size:0.82rem; color:var(--cyan); }
.tick-v.up { color:var(--green); } .tick-v.dn { color:var(--red); }
#cst-strip { display:flex; gap:4px; padding-left:10px; flex-wrap:wrap; }
.cst-badge {
  font-family:var(--mono); font-size:0.55rem; padding:2px 6px;
  border:1px solid var(--orange); color:var(--orange);
  background:rgba(255,107,53,0.08); border-radius:2px; white-space:nowrap;
}
.node-closed-badge {
  font-family:var(--mono); font-size:0.55rem; padding:2px 6px;
  border:1px solid var(--red); color:var(--red);
  background:rgba(255,56,96,0.08); border-radius:2px; white-space:nowrap;
}

/* Map body */
#map-body { display:flex; flex:1; overflow:hidden; }
#map { flex:1; background:var(--bg); }
.leaflet-tile { filter:brightness(.3) saturate(.35) hue-rotate(185deg); }
.leaflet-container { background:#020810; }
.leaflet-control-zoom a { background:var(--bg2)!important; color:var(--text2)!important; border-color:var(--border)!important; }
.leaflet-tooltip {
  background:rgba(5,12,24,0.92)!important; color:var(--text)!important;
  border:1px solid var(--border)!important; font-family:var(--mono)!important;
  font-size:0.68rem!important; padding:4px 8px!important;
}
#region-popup {
  position:absolute; z-index:2000; background:rgba(5,12,24,0.95);
  border:1px solid var(--cyan2); border-radius:4px; padding:10px 13px;
  min-width:170px; pointer-events:none; display:none;
  backdrop-filter:blur(10px); font-size:0.72rem;
}
#region-popup h4 { font-family:var(--mono); color:var(--cyan); font-size:0.78rem; margin-bottom:7px; }
.rp-row { display:flex; justify-content:space-between; gap:14px; color:var(--text2); margin-bottom:3px; }
.rp-v   { font-family:var(--mono); color:var(--text); }
/* scan lines */
#scanlines {
  position:absolute; inset:0; pointer-events:none; z-index:999;
  background:repeating-linear-gradient(to bottom,transparent 0,transparent 3px,rgba(0,0,0,.04) 3px,rgba(0,0,0,.04) 4px);
}

/* Side panel */
#map-side {
  width:248px; background:rgba(5,12,24,.95); border-left:1px solid var(--border);
  display:flex; flex-direction:column; overflow:hidden; flex-shrink:0;
}
.mp-section { padding:10px 13px; border-bottom:1px solid var(--border); }
.mp-title { font-family:var(--mono); font-size:0.6rem; letter-spacing:0.15em; color:var(--text3); text-transform:uppercase; margin-bottom:7px; }
.fleet-row { display:flex; align-items:center; gap:5px; margin-bottom:4px; }
.fleet-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }
.fleet-name { font-size:0.68rem; color:var(--text2); flex:1; overflow:hidden; white-space:nowrap; font-size:0.62rem; }
.fleet-bw { width:72px; height:3px; background:var(--bg4); border-radius:2px; overflow:hidden; }
.fleet-bf { height:100%; border-radius:2px; transition:width .3s; }
.fleet-n { font-family:var(--mono); font-size:0.65rem; color:var(--text); min-width:18px; text-align:right; }
.sd-wrap { margin-top:5px; }
.sd-bg { width:100%; height:5px; background:var(--bg4); border-radius:3px; position:relative; }
.sd-fill { height:100%; border-radius:3px; transition:width .35s, background .35s; }
.sd-mark { position:absolute; top:-3px; left:50%; width:2px; height:11px; background:var(--text3); border-radius:1px; transform:translateX(-50%); }
.sd-val { font-family:var(--mono); font-size:0.72rem; margin-top:3px; }
#spark-canvas { width:100%; height:64px; display:block; }
.legend-row { display:flex; align-items:center; gap:6px; margin-bottom:3px; }
.legend-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.legend-lbl { font-size:0.65rem; color:var(--text2); }
.size-row { display:flex; align-items:center; gap:5px; margin-bottom:3px; }
.size-ring { border-radius:50%; border:1.5px solid var(--text3); flex-shrink:0; }

/* ─────────────────────────────────────────────
   CONFIGURE TAB
───────────────────────────────────────────── */
#panel-config { flex-direction:row; overflow:hidden; }
#config-nav {
  width:160px; background:var(--bg2); border-right:1px solid var(--border);
  flex-shrink:0; overflow-y:auto; padding:10px 0;
}
.cnav-item {
  padding:7px 16px; cursor:pointer; font-size:0.72rem; color:var(--text2);
  border-left:2px solid transparent; transition:all 0.12s;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.cnav-item:hover  { color:var(--text); background:var(--bg3); }
.cnav-item.active { color:var(--cyan); border-left-color:var(--cyan); background:var(--bg3); }
.cnav-group { padding:12px 16px 4px; font-family:var(--mono); font-size:0.58rem; color:var(--text3); letter-spacing:0.1em; text-transform:uppercase; }
#config-main { flex:1; overflow:auto; padding:16px; }
.config-table-wrap { overflow-x:auto; }
.cfg-table {
  border-collapse:collapse; width:100%; font-size:0.7rem;
}
.cfg-table th {
  padding:6px 10px; text-align:left; background:var(--bg3);
  border-bottom:1px solid var(--border); font-family:var(--mono);
  font-size:0.6rem; color:var(--text2); letter-spacing:0.08em;
  text-transform:uppercase; white-space:nowrap; position:sticky; top:0; z-index:1;
}
.cfg-table td {
  padding:4px 2px; border-bottom:1px solid var(--border);
  vertical-align:middle;
}
.cfg-table tr:hover td { background:var(--bg3); }
.cfg-input {
  background:transparent; border:none; color:var(--text);
  font-family:var(--mono); font-size:0.7rem; padding:3px 8px;
  width:100%; min-width:60px; border-radius:2px; outline:none;
}
.cfg-input:focus { background:var(--bg3); outline:1px solid var(--border2); }
.cfg-input.changed { color:var(--amber); }
#config-actions { display:flex; gap:8px; margin-bottom:12px; align-items:center; }
.act-btn {
  background:transparent; border:1px solid var(--border);
  color:var(--text2); font-family:var(--mono); font-size:0.65rem;
  padding:5px 12px; border-radius:3px; cursor:pointer; letter-spacing:0.08em;
  transition:all 0.12s;
}
.act-btn:hover  { border-color:var(--cyan2); color:var(--cyan); }
.act-btn.danger { border-color:#5a1020; color:var(--red); }
.act-btn.danger:hover { border-color:var(--red); }
#config-title { font-family:var(--mono); font-size:0.8rem; color:var(--cyan); margin-bottom:8px; }
#add-row-btn { background:rgba(0,229,255,.06); border:1px dashed var(--border2); color:var(--text3); font-size:0.65rem; padding:4px 10px; border-radius:2px; cursor:pointer; transition:all .12s; font-family:var(--mono); }
#add-row-btn:hover { color:var(--cyan); border-color:var(--cyan2); }
.del-row-btn { background:transparent; border:none; color:var(--text3); cursor:pointer; font-size:0.9rem; padding:0 5px; }
.del-row-btn:hover { color:var(--red); }

/* ─────────────────────────────────────────────
   DASHBOARD TAB
───────────────────────────────────────────── */
#panel-dash { flex-wrap:wrap; padding:16px; gap:14px; align-content:flex-start; overflow-y:auto; }
.chart-card {
  background:var(--bg2); border:1px solid var(--border);
  border-radius:4px; padding:14px; flex-shrink:0;
}
.chart-card.wide { width:calc(66% - 7px); min-width:400px; }
.chart-card.half { width:calc(34% - 7px); min-width:240px; }
.chart-card.third { width:calc(33% - 10px); min-width:260px; }
.cc-title { font-family:var(--mono); font-size:0.65rem; color:var(--text3); letter-spacing:0.12em; text-transform:uppercase; margin-bottom:10px; }
canvas.chart { width:100%; height:160px; display:block; }
canvas.chart.tall { height:220px; }

/* ─────────────────────────────────────────────
   SCENARIO TAB
───────────────────────────────────────────── */
#panel-scenario { flex-direction:column; padding:16px; gap:16px; overflow-y:auto; }
.scenario-section { background:var(--bg2); border:1px solid var(--border); border-radius:4px; padding:14px; }
.sc-title { font-family:var(--mono); font-size:0.7rem; color:var(--cyan); letter-spacing:0.12em; margin-bottom:12px; }
.param-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }
.param-row { display:flex; flex-direction:column; gap:4px; }
.param-label { font-size:0.65rem; color:var(--text2); }
.param-input {
  background:var(--bg3); border:1px solid var(--border);
  color:var(--text); font-family:var(--mono); font-size:0.75rem;
  padding:5px 8px; border-radius:3px; outline:none; width:100%;
}
.param-input:focus { border-color:var(--cyan2); }
select.param-input option { background:var(--bg2); }
.preset-grid { display:flex; gap:10px; flex-wrap:wrap; }
.preset-btn {
  background:var(--bg3); border:1px solid var(--border);
  color:var(--text2); font-family:var(--mono); font-size:0.65rem;
  padding:7px 14px; border-radius:3px; cursor:pointer; letter-spacing:0.08em;
  transition:all 0.12s;
}
.preset-btn:hover { border-color:var(--amber); color:var(--amber); background:rgba(255,210,63,.06); }

/* ─────────────────────────────────────────────
   EXPORT TAB
───────────────────────────────────────────── */
#panel-export { flex-direction:column; padding:24px; gap:16px; overflow-y:auto; }
.export-card { background:var(--bg2); border:1px solid var(--border); border-radius:4px; padding:16px; max-width:600px; }
.export-card h3 { font-family:var(--mono); font-size:0.75rem; color:var(--cyan); margin-bottom:8px; }
.export-card p  { font-size:0.72rem; color:var(--text2); line-height:1.6; margin-bottom:12px; }
.export-btn {
  display:inline-block; background:var(--bg3); border:1px solid var(--border2);
  color:var(--text); font-family:var(--mono); font-size:0.68rem;
  padding:7px 16px; border-radius:3px; cursor:pointer; text-decoration:none;
  letter-spacing:0.08em; transition:all .12s; margin-right:8px;
}
.export-btn:hover { border-color:var(--cyan2); color:var(--cyan); }

/* ── TOAST ── */
#toast {
  position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
  background:var(--bg3); border:1px solid var(--border2); color:var(--text);
  font-family:var(--mono); font-size:0.7rem; padding:8px 20px;
  border-radius:4px; z-index:9999; opacity:0; transition:opacity .3s;
  pointer-events:none;
}
#toast.show { opacity:1; }

/* scrollbar */
::-webkit-scrollbar { width:5px; height:5px; }
::-webkit-scrollbar-track { background:var(--bg); }
::-webkit-scrollbar-thumb { background:var(--bg4); border-radius:3px; }
</style>
</head>
<body>
<div id="shell">

  <!-- TOPBAR -->
  <div id="topbar">
    <div id="logo">⬡ MARITIME SIM <span>v2 · FLEET DYNAMICS</span></div>
    <div id="tabs">
      <div class="tab active" data-tab="map">     <span class="tab-icon">🗺</span> MAP</div>
      <div class="tab"        data-tab="config">  <span class="tab-icon">⚙</span> CONFIGURE</div>
      <div class="tab"        data-tab="dash">    <span class="tab-icon">📊</span> DASHBOARD</div>
      <div class="tab"        data-tab="scenario"><span class="tab-icon">🎯</span> SCENARIO</div>
      <div class="tab"        data-tab="export">  <span class="tab-icon">💾</span> EXPORT</div>
    </div>
    <div id="run-area">
      <span id="run-status-text">no simulation yet</span>
      <div id="run-progress"><div id="run-progress-bar"></div></div>
      <button id="run-btn" onclick="startRun()">▶ RUN</button>
    </div>
  </div>

  <!-- CONTENT -->
  <div id="content">

    <!-- MAP TAB -->
    <div class="panel active" id="panel-map">
      <div id="transport-bar">
        <div id="date-badge">----</div>
        <div id="step-badge">—</div>
        <button class="tb-btn" id="tb-prev" title="Step back">◀</button>
        <button class="tb-btn" id="tb-play" title="Play">▶</button>
        <button class="tb-btn" id="tb-next" title="Step fwd">▷</button>
        <button class="tb-btn" id="tb-stop" title="Reset">■</button>
        <button class="tb-btn" id="tb-slower" title="Slower">−</button>
        <span id="speed-ind">1×</span>
        <button class="tb-btn" id="tb-faster" title="Faster">+</button>
        <div id="scrubber-wrap"><input type="range" id="scrubber" min="0" value="0"></div>
        <div class="ticker-group">
          <div class="tick"><span class="tick-l">Spot</span><span class="tick-v" id="tv-spot">—</span></div>
          <div class="tick"><span class="tick-l">WTI</span><span class="tick-v" id="tv-wti">—</span></div>
          <div class="tick"><span class="tick-l">VLSFO</span><span class="tick-v" id="tv-vlsfo">—</span></div>
          <div class="tick"><span class="tick-l">Fleet</span><span class="tick-v" id="tv-fleet">—</span></div>
          <div class="tick"><span class="tick-l">Order</span><span class="tick-v" id="tv-ob">—</span></div>
          <div class="tick"><span class="tick-l">S/D</span><span class="tick-v" id="tv-sd">—</span></div>
        </div>
        <div id="cst-strip"></div>
      </div>
      <div id="map-body">
        <div id="map"><div id="scanlines"></div><div id="region-popup"></div></div>
        <div id="map-side">
          <div class="mp-section">
            <div class="mp-title">Fleet by Type</div>
            <div id="fleet-bd"></div>
          </div>
          <div class="mp-section">
            <div class="mp-title">Oil Supply / Demand</div>
            <div class="sd-wrap">
              <div class="sd-bg"><div class="sd-fill" id="sd-fill"></div><div class="sd-mark"></div></div>
              <div class="sd-val" id="sd-val">—</div>
            </div>
          </div>
          <div class="mp-section" style="flex:1">
            <div class="mp-title">Spot Rate History</div>
            <canvas id="spark-canvas"></canvas>
          </div>
          <div class="mp-section">
            <div class="mp-title">Owners</div>
            <div id="owner-legend"></div>
          </div>
          <div class="mp-section" style="padding-bottom:14px">
            <div class="mp-title">Vessel size</div>
            <div id="size-legend"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- CONFIGURE TAB -->
    <div class="panel" id="panel-config">
      <div id="config-nav" id="cnav"></div>
      <div id="config-main">
        <div id="config-title">Select a table →</div>
        <div id="config-actions" style="display:none">
          <button class="act-btn" onclick="saveCurrentTable()">💾 Save changes</button>
          <button class="act-btn" onclick="resetCurrentTable()">↺ Reset to template</button>
          <button id="add-row-btn" onclick="addRow()">+ Add row</button>
        </div>
        <div class="config-table-wrap">
          <table class="cfg-table" id="cfg-table">
            <thead id="cfg-thead"></thead>
            <tbody id="cfg-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- DASHBOARD TAB -->
    <div class="panel" id="panel-dash">
      <div class="chart-card wide">
        <div class="cc-title">Spot Rate  ($/day)</div>
        <canvas class="chart tall" id="ch-spot"></canvas>
      </div>
      <div class="chart-card half">
        <div class="cc-title">Fleet Active vs Storage</div>
        <canvas class="chart tall" id="ch-fleet"></canvas>
      </div>
      <div class="chart-card third">
        <div class="cc-title">Supply / Demand Ratio</div>
        <canvas class="chart" id="ch-sd"></canvas>
      </div>
      <div class="chart-card third">
        <div class="cc-title">WTI Price  ($/bbl)</div>
        <canvas class="chart" id="ch-wti"></canvas>
      </div>
      <div class="chart-card third">
        <div class="cc-title">Orderbook</div>
        <canvas class="chart" id="ch-ob"></canvas>
      </div>
      <div class="chart-card wide">
        <div class="cc-title">Fleet Composition by Type</div>
        <canvas class="chart" id="ch-fcomp"></canvas>
      </div>
      <div class="chart-card half">
        <div class="cc-title">Load Factor</div>
        <canvas class="chart" id="ch-lf"></canvas>
      </div>
    </div>

    <!-- SCENARIO TAB -->
    <div class="panel" id="panel-scenario">
      <div class="scenario-section">
        <div class="sc-title">⚙ SIMULATION PARAMETERS</div>
        <div class="param-grid" id="sim-params"></div>
      </div>
      <div class="scenario-section">
        <div class="sc-title">🎯 SCENARIO PRESETS</div>
        <p style="font-size:0.7rem;color:var(--text2);margin-bottom:10px">
          Presets apply constraint rows to the Constraints table and trigger a re-run.
        </p>
        <div class="preset-grid" id="preset-grid"></div>
      </div>
      <div class="scenario-section">
        <div class="sc-title">⚡ QUICK EVENT  (applies to constraint table immediately)</div>
        <div class="param-grid">
          <div class="param-row">
            <label class="param-label">Event type</label>
            <select class="param-input" id="qe-type">
              <option value="node_closure">Node Closure (Hormuz, Suez…)</option>
              <option value="demand_shock">Demand Shock</option>
              <option value="sanction_ship_flag">Sanction (country/company)</option>
              <option value="supply_shock">Supply Shock</option>
              <option value="spot_price_shock">Spot Price Shock</option>
            </select>
          </div>
          <div class="param-row">
            <label class="param-label">Target (node / region / company)</label>
            <input class="param-input" id="qe-target" placeholder="e.g. Strait of Hormuz" value="Strait of Hormuz">
          </div>
          <div class="param-row">
            <label class="param-label">Apply on day</label>
            <input class="param-input" type="number" id="qe-day" value="30">
          </div>
          <div class="param-row">
            <label class="param-label">End on day (blank=permanent)</label>
            <input class="param-input" type="number" id="qe-endday" placeholder="blank=permanent">
          </div>
          <div class="param-row">
            <label class="param-label">Multiplier (0=full block, 1=no change)</label>
            <input class="param-input" type="number" id="qe-mult" value="0" step="0.05">
          </div>
        </div>
        <button class="act-btn" style="margin-top:12px" onclick="addQuickEvent()">+ Add event & re-run</button>
      </div>
    </div>

    <!-- EXPORT TAB -->
    <div class="panel" id="panel-export">
      <div class="export-card">
        <h3>📄 RESULTS CSV</h3>
        <p>Download the full simulation output as CSV with all time steps, market metrics, fleet counts, and regional statistics.</p>
        <button class="export-btn" onclick="downloadCSV()">⬇ Download CSV</button>
      </div>
      <div class="export-card">
        <h3>🗂 CONFIGURATION CSVs</h3>
        <p>Download all editable configuration tables as individual CSV files — regions, fleet, ship types, constraints, etc.</p>
        <button class="export-btn" onclick="downloadAllTables()">⬇ Download All Tables (JSON)</button>
      </div>
      <div class="export-card">
        <h3>🗺 STANDALONE MAP HTML</h3>
        <p>Export the current simulation result as a self-contained HTML file that can be opened offline and shared.</p>
        <button class="export-btn" onclick="exportMapHTML()">⬇ Export Map HTML</button>
      </div>
      <div class="export-card" id="export-summary" style="display:none">
        <h3>📊 LAST RUN SUMMARY</h3>
        <div id="export-summary-body" style="font-family:var(--mono);font-size:0.7rem;color:var(--text2);line-height:2"></div>
      </div>
    </div>

  </div><!-- /content -->
</div><!-- /shell -->
<div id="toast"></div>

<script>
// ═══════════════════════════════════════════════════════════════════════════
// GLOBAL STATE
// ═══════════════════════════════════════════════════════════════════════════
const API = '';   // relative — same origin
let SIM = null;   // simulation result loaded from /api/result
let tables = {};  // config tables from /api/templates
let runConfig = {};
let currentStep = 0;
let isPlaying = false;
let playTimer = null;
let speedIdx = 0;
const SPEEDS = [1,2,4,8];
let prevSpot = null;
let currentTableName = null;
let tableEdits = {};   // name → {rowIdx: {col: val}}

// ═══════════════════════════════════════════════════════════════════════════
// TAB NAVIGATION
// ═══════════════════════════════════════════════════════════════════════════
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('panel-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'dash' && SIM) renderDashboard();
    if (t.dataset.tab === 'export' && SIM) renderExportSummary();
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// TOAST
// ═══════════════════════════════════════════════════════════════════════════
function toast(msg, dur=2500) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), dur);
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT — load templates + run config on page load
// ═══════════════════════════════════════════════════════════════════════════
async function init() {
  try {
    const [tablesRes, cfgRes] = await Promise.all([
      fetch(API + '/api/templates').then(r=>r.json()),
      fetch(API + '/api/run_config').then(r=>r.json()),
    ]);
    tables    = tablesRes;
    runConfig = cfgRes;
    buildConfigNav();
    buildSimParams();
    buildLegend();
    toast('Config loaded — press RUN to simulate');

    // Check if there's already a result
    const status = await fetch(API + '/api/status').then(r=>r.json());
    if (status.has_result) {
      const result = await fetch(API + '/api/result').then(r=>r.json());
      SIM = result;
      initMap();
      render(0);
      toast('Previous simulation result loaded');
    } else {
      initMap();
    }
  } catch(e) {
    toast('Could not connect to server: ' + e.message, 5000);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// RUN SIMULATION
// ═══════════════════════════════════════════════════════════════════════════
async function startRun() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  document.getElementById('run-progress').style.display = 'block';
  document.getElementById('run-status-text').textContent = 'starting…';

  // Push current run config
  await fetch(API + '/api/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({config: runConfig})
  });

  // Poll progress
  const poll = setInterval(async () => {
    const st = await fetch(API + '/api/status').then(r=>r.json());
    document.getElementById('run-progress-bar').style.width = st.progress + '%';
    document.getElementById('run-status-text').textContent =
      st.running ? `running ${st.progress}%` : st.error ? 'error' : 'done';

    if (!st.running) {
      clearInterval(poll);
      btn.disabled = false;
      document.getElementById('run-progress').style.display = 'none';
      if (st.error) {
        toast('Simulation error — check console', 5000);
        console.error(st.error);
        return;
      }
      const result = await fetch(API + '/api/result').then(r=>r.json());
      SIM = result;
      render(0);
      if (document.querySelector('.tab[data-tab="dash"]').classList.contains('active')) renderDashboard();
      toast(`✓ Simulation complete — ${SIM.steps.length} steps`);
    }
  }, 400);
}

// ═══════════════════════════════════════════════════════════════════════════
// LEAFLET MAP
// ═══════════════════════════════════════════════════════════════════════════
let leafletMap, vesselLayer, regionMarkers={}, nodeMarkers={}, vesselMarkers={}, routeLines={};

function initMap() {
  if (leafletMap) return;
  leafletMap = L.map('map', {center:[20,20], zoom:2, zoomControl:true, attributionControl:false, minZoom:2, maxZoom:6});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:6}).addTo(leafletMap);
  vesselLayer = L.layerGroup().addTo(leafletMap);

  if (!SIM) return;
  initMapLayers();
}

function initMapLayers() {
  if (!SIM) return;

  // Routes
  Object.entries(SIM.routes).forEach(([key, route]) => {
    const ll = route.waypoints.map(([la,lo])=>[la,lo]);
    routeLines[key] = L.polyline(ll,{color:'#00e5ff',opacity:.08,weight:1.5,dashArray:'4 6'}).addTo(leafletMap);
  });

  // Node markers
  Object.entries(SIM.nodes).forEach(([name,c]) => {
    nodeMarkers[name] = L.marker([c.lat,c.lon], {icon: makeNodeIcon(true)})
      .bindTooltip(name,{className:'leaflet-tooltip'}).addTo(leafletMap);
  });

  // Region markers
  Object.entries(SIM.regions).forEach(([name,c]) => {
    const m = L.marker([c.lat,c.lon], {icon: makeRegionIcon(name, SIM.steps[0])})
      .addTo(leafletMap);
    m.on('mouseover', e => showRegionPopup(name,e));
    m.on('mouseout',  ()  => document.getElementById('region-popup').style.display='none');
    regionMarkers[name] = m;
  });
}

function makeNodeIcon(open) {
  const c = open ? '#ffd23f' : '#ff3860';
  const sh = open ? '0 0 8px rgba(255,210,63,.6)' : '0 0 14px rgba(255,56,96,.8)';
  return L.divIcon({className:'',iconSize:[10,10],iconAnchor:[5,5],
    html:`<div style="width:10px;height:10px;border-radius:50%;border:2px solid ${c};background:${c}33;box-shadow:${sh}"></div>`});
}

function makeRegionIcon(name, stepData) {
  const rd = (stepData.regions||{})[name]||{};
  const sd = rd.supply>0 ? rd.demand/rd.supply : 0;
  const w  = Math.min(100, Math.round(sd*55));
  const bc = sd>1.1?'#ff3860':sd>0.9?'#39ff14':'#ffd23f';
  return L.divIcon({className:'',iconSize:[88,44],iconAnchor:[44,22],
    html:`<div style="padding:4px 8px;background:rgba(5,12,24,.88);border:1px solid rgba(0,229,255,.35);border-radius:3px;font-family:'Share Tech Mono',monospace;cursor:pointer;box-shadow:0 0 10px rgba(0,229,255,.12)">
      <div style="color:#00e5ff;font-size:.62rem;margin-bottom:1px">${name.substring(0,11)}</div>
      <div style="display:flex;gap:5px;font-size:.55rem;color:#7a9abb">
        <span>S:${(rd.supply||0).toFixed(1)}</span><span>D:${(rd.demand||0).toFixed(1)}</span>
      </div>
      <div style="height:3px;background:#142540;margin-top:3px;border-radius:2px;overflow:hidden">
        <div style="width:${w}%;height:100%;background:${bc};border-radius:2px"></div>
      </div>
    </div>`});
}

function showRegionPopup(name,e) {
  if (!SIM) return;
  const rd = (SIM.steps[currentStep].regions||{})[name]||{};
  const sd = rd.supply>0?(rd.demand/rd.supply).toFixed(3):'—';
  const p = document.getElementById('region-popup');
  p.innerHTML=`<h4>${name}</h4>
    <div class="rp-row"><span>Supply</span><span class="rp-v">${(rd.supply||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>Demand</span><span class="rp-v">${(rd.demand||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>Storage</span><span class="rp-v">${(rd.storage||0).toFixed(2)} MMT</span></div>
    <div class="rp-row"><span>D/S</span><span class="rp-v">${sd}</span></div>`;
  const mr = document.getElementById('map').getBoundingClientRect();
  let x=e.originalEvent.clientX-mr.left+12, y=e.originalEvent.clientY-mr.top+12;
  if(x+190>mr.width)x-=200; if(y+120>mr.height)y-=130;
  p.style.left=x+'px'; p.style.top=y+'px'; p.style.display='block';
}

function updateVessels(step) {
  if(!SIM) return;
  const frame = SIM.frames[step]||[];
  const fids = new Set(frame.map(v=>v.id));
  Object.keys(vesselMarkers).forEach(id=>{
    if(!fids.has(+id)){vesselLayer.removeLayer(vesselMarkers[id]);delete vesselMarkers[id];}
  });
  frame.forEach(v=>{
    if(!vesselMarkers[v.id]){
      const m = L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,fillOpacity:.85,weight:1.2,opacity:.9});
      m.bindTooltip(`<b style="color:${v.color}">${v.owner}</b><br>${v.type}`,{sticky:true});
      m.addTo(vesselLayer);
      vesselMarkers[v.id]=m;
    } else {
      vesselMarkers[v.id].setLatLng([v.lat,v.lon]);
    }
  });
}

function updateNodes(stepData) {
  Object.entries(nodeMarkers).forEach(([name,m])=>{
    const open = stepData.nodes[name]!==false;
    m.setIcon(makeNodeIcon(open));
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// MAP SIDE PANEL
// ═══════════════════════════════════════════════════════════════════════════
const FTYPE_COLORS = {
  'VLCC_KR':'#00d4ff','VLCC_scrubber_KR':'#38bdf8','VLCC_CN':'#fb923c',
  'Suezmax_KR':'#4ade80','Aframax_GR':'#a78bfa','Aframax_RU':'#f472b6','MR_NO':'#fbbf24'
};

function updateFleetBD(stepData) {
  const fleet = stepData.fleet||{};
  const total = Object.values(fleet).reduce((a,b)=>a+b,0)||1;
  document.getElementById('fleet-bd').innerHTML = Object.entries(fleet).map(([t,n])=>{
    const c = FTYPE_COLORS[t]||'#94a3b8';
    return `<div class="fleet-row">
      <div class="fleet-dot" style="background:${c}"></div>
      <div class="fleet-name">${t}</div>
      <div class="fleet-bw"><div class="fleet-bf" style="width:${(n/total*100).toFixed(0)}%;background:${c}"></div></div>
      <div class="fleet-n">${n}</div>
    </div>`;
  }).join('');
}

function updateSDPanel(stepData) {
  const sd = stepData.sd_ratio||1;
  const pct = Math.min(100,Math.max(0,(sd-.5)/1*100));
  const c = sd>1.15?'#ff3860':sd>0.95?'#39ff14':'#ffd23f';
  document.getElementById('sd-fill').style.width=pct+'%';
  document.getElementById('sd-fill').style.background=c;
  document.getElementById('sd-val').textContent=`S/D = ${sd.toFixed(3)}`;
  document.getElementById('sd-val').style.color=c;
}

function updateSparkline(upTo) {
  if(!SIM) return;
  const canvas=document.getElementById('spark-canvas');
  const ctx=canvas.getContext('2d');
  const dpr=window.devicePixelRatio||1;
  canvas.width=canvas.offsetWidth*dpr; canvas.height=canvas.offsetHeight*dpr;
  ctx.scale(dpr,dpr);
  const W=canvas.offsetWidth, H=canvas.offsetHeight;
  const rates=SIM.steps.slice(0,upTo+1).map(s=>s.spot_rate);
  const mn=Math.min(...rates), mx=Math.max(...rates), rng=mx-mn||1;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='#00e5ff'; ctx.lineWidth=1.5;
  ctx.shadowColor='#00e5ff'; ctx.shadowBlur=4;
  ctx.beginPath();
  rates.forEach((r,i)=>{
    const x=(i/(rates.length-1||1))*W, y=H-((r-mn)/rng)*(H-6)-3;
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  });
  ctx.stroke();
  ctx.shadowBlur=0;
  const lx=(rates.length-1)/(SIM.steps.length-1||1)*W;
  const ly=H-((rates[rates.length-1]-mn)/rng)*(H-6)-3;
  ctx.beginPath(); ctx.arc(lx,ly,3,0,Math.PI*2);
  ctx.fillStyle='#00e5ff'; ctx.fill();
}

function buildLegend() {
  const COMPANY_COLORS={'Saudi Aramco':'#00d4ff','Shell':'#ffd23f','ExxonMobil':'#ff6b35','BP':'#4ade80','Rosneft':'#f472b6','CNOOC':'#fb923c','Independent':'#94a3b8'};
  const GROUP_RADIUS={'VLCC':9,'Suezmax':7,'Aframax':5,'Panamax':4,'MR':3};
  document.getElementById('owner-legend').innerHTML=Object.entries(COMPANY_COLORS).map(([n,c])=>
    `<div class="legend-row"><div class="legend-dot" style="background:${c}"></div><span class="legend-lbl">${n}</span></div>`
  ).join('');
  document.getElementById('size-legend').innerHTML=Object.entries(GROUP_RADIUS).map(([n,r])=>
    `<div class="size-row"><div class="size-ring" style="width:${r*2+2}px;height:${r*2+2}px"></div><span class="legend-lbl">${n}</span></div>`
  ).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// MASTER RENDER
// ═══════════════════════════════════════════════════════════════════════════
function render(step) {
  if(!SIM) return;
  currentStep = Math.max(0, Math.min(SIM.steps.length-1, step));
  const s = SIM.steps[currentStep];

  // Init map layers if not done
  if (Object.keys(regionMarkers).length === 0) initMapLayers();

  // Transport bar
  document.getElementById('date-badge').textContent = s.date;
  document.getElementById('step-badge').textContent = `step ${currentStep+1} / ${SIM.steps.length}`;
  document.getElementById('scrubber').value = currentStep;

  // Ticker
  const spot = s.spot_rate;
  const dir = prevSpot===null?'':spot>prevSpot?'up':'dn';
  document.getElementById('tv-spot').textContent  = '$'+(spot/1000).toFixed(1)+'k';
  document.getElementById('tv-spot').className    = 'tick-v '+dir;
  document.getElementById('tv-wti').textContent   = '$'+s.wti.toFixed(1);
  document.getElementById('tv-vlsfo').textContent = '$'+s.vlsfo.toFixed(0);
  document.getElementById('tv-fleet').textContent = s.fleet_active+(s.fleet_storage>0?'+'+s.fleet_storage+'⚓':'');
  document.getElementById('tv-ob').textContent    = s.orderbook;
  document.getElementById('tv-sd').textContent    = s.sd_ratio.toFixed(3);
  prevSpot = spot;

  // Constraints
  const csts = (s.constraints||'').split(';').filter(Boolean);
  const closedNodes = Object.entries(s.nodes||{}).filter(([,v])=>!v).map(([k])=>k);
  document.getElementById('cst-strip').innerHTML =
    csts.map(c=>`<span class="cst-badge">${c}</span>`).join('') +
    closedNodes.map(n=>`<span class="node-closed-badge">⛔ ${n}</span>`).join('');

  // Map
  updateVessels(currentStep);
  updateNodes(s);
  Object.keys(SIM.regions).forEach(name => regionMarkers[name].setIcon(makeRegionIcon(name,s)));

  // Side panel
  updateFleetBD(s);
  updateSDPanel(s);
  updateSparkline(currentStep);
}

// ═══════════════════════════════════════════════════════════════════════════
// PLAYBACK CONTROLS
// ═══════════════════════════════════════════════════════════════════════════
function setPlay(val) {
  isPlaying=val;
  document.getElementById('tb-play').textContent=val?'⏸':'▶';
  document.getElementById('tb-play').classList.toggle('active',val);
  if(val){
    playTimer=setInterval(()=>{
      if(currentStep>=((SIM?.steps.length||1)-1)){setPlay(false);return;}
      render(currentStep+SPEEDS[speedIdx]);
    }, 600);
  } else { clearInterval(playTimer); }
}

document.getElementById('tb-play').onclick   = ()=>{ if(SIM)setPlay(!isPlaying); };
document.getElementById('tb-stop').onclick   = ()=>{ setPlay(false); render(0); };
document.getElementById('tb-prev').onclick   = ()=>{ setPlay(false); if(SIM)render(currentStep-1); };
document.getElementById('tb-next').onclick   = ()=>{ setPlay(false); if(SIM)render(currentStep+1); };
document.getElementById('tb-faster').onclick = ()=>{
  speedIdx=Math.min(speedIdx+1,SPEEDS.length-1);
  document.getElementById('speed-ind').textContent=SPEEDS[speedIdx]+'×';
};
document.getElementById('tb-slower').onclick = ()=>{
  speedIdx=Math.max(speedIdx-1,0);
  document.getElementById('speed-ind').textContent=SPEEDS[speedIdx]+'×';
};
document.getElementById('scrubber').oninput = function(){
  setPlay(false); if(SIM)render(+this.value);
};
document.getElementById('scrubber').max = 0;

// ═══════════════════════════════════════════════════════════════════════════
// CONFIGURE TAB
// ═══════════════════════════════════════════════════════════════════════════
const TABLE_LABELS = {
  products:'Products', regions:'Regions', region_demand:'Region Demand',
  region_supply:'Region Supply', region_storage:'Storage', port_times:'Port Times',
  nodes:'Nodes', edges:'Edges', companies:'Companies',
  ship_groups:'Ship Groups', ship_types:'Ship Types',
  fleet:'Initial Fleet', orderbook:'Orderbook', constraints:'Constraints',
  seasonality:'Seasonality',
};
const TABLE_GROUPS = {
  'Market':  ['products','regions','region_demand','region_supply','region_storage','seasonality'],
  'Network': ['nodes','edges','port_times'],
  'Actors':  ['companies'],
  'Fleet':   ['ship_groups','ship_types','fleet','orderbook'],
  'Scenario':['constraints'],
};

function buildConfigNav() {
  const nav = document.getElementById('config-nav');
  nav.innerHTML = '';
  Object.entries(TABLE_GROUPS).forEach(([group, names]) => {
    const gh = document.createElement('div');
    gh.className='cnav-group'; gh.textContent=group;
    nav.appendChild(gh);
    names.forEach(name => {
      if(!tables[name]) return;
      const el = document.createElement('div');
      el.className='cnav-item';
      el.textContent = TABLE_LABELS[name]||name;
      el.onclick = () => loadTable(name);
      el.id = 'cnav-'+name;
      nav.appendChild(el);
    });
  });
}

function loadTable(name) {
  currentTableName = name;
  document.querySelectorAll('.cnav-item').forEach(x=>x.classList.remove('active'));
  const nav = document.getElementById('cnav-'+name);
  if(nav) nav.classList.add('active');
  document.getElementById('config-title').textContent = TABLE_LABELS[name]||name;
  document.getElementById('config-actions').style.display='flex';
  const rows = tables[name]||[];
  const cols = rows.length>0 ? Object.keys(rows[0]) : [];
  const thead = document.getElementById('cfg-thead');
  const tbody = document.getElementById('cfg-tbody');
  thead.innerHTML = '<tr><th style="width:28px"></th>' +
    cols.map(c=>`<th>${c}</th>`).join('') + '</tr>';
  tbody.innerHTML = rows.map((row,ri)=>`
    <tr data-ri="${ri}">
      <td><button class="del-row-btn" onclick="deleteRow(${ri})">✕</button></td>
      ${cols.map(c=>`<td><input class="cfg-input" value="${escHtml(row[c]??'')}" data-col="${c}" data-ri="${ri}" oninput="markChanged(this,'${name}',${ri},'${c}')"></td>`).join('')}
    </tr>`).join('');
}

function escHtml(v) { return String(v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

function markChanged(input, tableName, ri, col) {
  input.classList.add('changed');
  if(!tableEdits[tableName]) tableEdits[tableName]={};
  if(!tableEdits[tableName][ri]) tableEdits[tableName][ri]={};
  tableEdits[tableName][ri][col] = input.value;
}

function saveCurrentTable() {
  if(!currentTableName) return;
  // Collect all input values from DOM
  const tbody = document.getElementById('cfg-tbody');
  const rows = [];
  tbody.querySelectorAll('tr').forEach(tr => {
    const row = {};
    tr.querySelectorAll('input.cfg-input').forEach(inp => {
      row[inp.dataset.col] = inp.value;
    });
    if(Object.keys(row).length>0) rows.push(row);
  });
  tables[currentTableName] = rows;
  fetch(API+'/api/table',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:currentTableName,rows})})
    .then(()=> toast(`✓ ${TABLE_LABELS[currentTableName]} saved (${rows.length} rows)`));
  // Clear changed highlights
  document.querySelectorAll('.cfg-input.changed').forEach(i=>i.classList.remove('changed'));
}

function resetCurrentTable() {
  if(!currentTableName) return;
  // Reload from API (original templates)
  fetch(API+'/api/templates').then(r=>r.json()).then(t=>{
    tables[currentTableName] = t[currentTableName];
    loadTable(currentTableName);
    toast(`↺ ${TABLE_LABELS[currentTableName]} reset`);
  });
}

function addRow() {
  if(!currentTableName) return;
  const rows = tables[currentTableName]||[];
  const template = rows.length>0 ? Object.fromEntries(Object.keys(rows[0]).map(k=>[k,''])) : {};
  tables[currentTableName].push(template);
  loadTable(currentTableName);
}

function deleteRow(ri) {
  if(!currentTableName) return;
  tables[currentTableName].splice(ri,1);
  loadTable(currentTableName);
  toast('Row deleted — click Save to apply');
}

// ═══════════════════════════════════════════════════════════════════════════
// SCENARIO TAB
// ═══════════════════════════════════════════════════════════════════════════
const PARAM_DEFS = [
  {key:'granularity',  label:'Granularity',         type:'select', opts:['week','month','quarter','year']},
  {key:'n_periods',    label:'Periods',              type:'number', min:5,  max:240},
  {key:'seed',         label:'Random seed',          type:'number', min:0,  max:9999},
  {key:'base_spot_rate',label:'Base spot ($/day)',   type:'number', min:5000, max:100000, step:500},
  {key:'spot_volatility',label:'Spot volatility',   type:'number', min:.01,max:.8,step:.01},
  {key:'wti_price',    label:'WTI ($/bbl)',          type:'number', min:10, max:200},
  {key:'fuel_vlsfo',   label:'VLSFO ($/t)',          type:'number', min:100,max:1500, step:10},
  {key:'fuel_hfo',     label:'HFO ($/t)',            type:'number', min:100,max:1000, step:10},
  {key:'ordering_sensitivity',label:'Ordering sensitivity',type:'number',min:.01,max:1,step:.01},
  {key:'scrapping_threshold',label:'Scrapping threshold ($/day)',type:'number',min:1000,max:30000,step:500},
  {key:'storage_sd_threshold',label:'Storage S/D trigger',type:'number',min:1.0,max:2.5,step:.05},
];

function buildSimParams() {
  const grid = document.getElementById('sim-params');
  grid.innerHTML = PARAM_DEFS.map(p => {
    const val = runConfig[p.key]??'';
    if(p.type==='select') {
      return `<div class="param-row">
        <label class="param-label">${p.label}</label>
        <select class="param-input" id="sp-${p.key}" onchange="runConfig['${p.key}']=this.value">
          ${p.opts.map(o=>`<option value="${o}" ${o===val?'selected':''}>${o}</option>`).join('')}
        </select></div>`;
    }
    return `<div class="param-row">
      <label class="param-label">${p.label}</label>
      <input class="param-input" type="number" id="sp-${p.key}"
        value="${val}" min="${p.min??''}" max="${p.max??''}" step="${p.step??1}"
        onchange="runConfig['${p.key}']=+this.value">
    </div>`;
  }).join('');

  // Presets
  const PRESETS = [
    {name:'Baseline (2025-30)',  cfg:{granularity:'month',n_periods:60,seed:42}},
    {name:'Hormuz Crisis',       constraints:[{id:'HORMUZ',type:'node_closure',day:30,end:90,nodes:'Strait of Hormuz',mult:0}]},
    {name:'Russian Sanctions',   constraints:[{id:'RU_2022',type:'sanction_ship_flag',day:0,companies:'Rosneft',countries:'russia',regions:'Baltic',mult:.35}]},
    {name:'COVID Demand Shock',  constraints:[{id:'COVID',type:'demand_shock',day:60,end:600,mult:.72}]},
    {name:'IMO2020 Fuel Rules',  constraints:[{id:'IMO2020X',type:'fuel_regulation',day:0,add:150}]},
    {name:'5-Year Quarterly',    cfg:{granularity:'quarter',n_periods:20}},
    {name:'10-Year Annual',      cfg:{granularity:'year',n_periods:10}},
  ];
  document.getElementById('preset-grid').innerHTML = PRESETS.map((p,i)=>
    `<button class="preset-btn" onclick="applyPreset(${i})">${p.name}</button>`
  ).join('');
  window._PRESETS = PRESETS;
}

function applyPreset(i) {
  const p = window._PRESETS[i];
  if(p.cfg) {
    Object.assign(runConfig, p.cfg);
    PARAM_DEFS.forEach(pd => {
      const el = document.getElementById('sp-'+pd.key);
      if(el && runConfig[pd.key]!==undefined) el.value = runConfig[pd.key];
    });
  }
  if(p.constraints) {
    p.constraints.forEach(c => {
      const row = {
        constraint_id: c.id||'PRESET_'+Date.now(),
        constraint_type: c.type,
        apply_on_day: c.day??0,
        end_on_day: c.end??'',
        description: p.name,
        target_nodes: c.nodes||'',
        target_companies: c.companies||'',
        target_countries: c.countries||'',
        target_regions: c.regions||'',
        target_products: '',
        multiplier: c.mult??1,
        additive: c.add??0,
        capacity_vessels: '',
      };
      if(!tables.constraints) tables.constraints=[];
      tables.constraints.push(row);
      fetch(API+'/api/table',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'constraints',rows:tables.constraints})});
    });
  }
  toast(`Preset "${p.name}" applied — press RUN`);
}

function addQuickEvent() {
  const type    = document.getElementById('qe-type').value;
  const target  = document.getElementById('qe-target').value.trim();
  const day     = +document.getElementById('qe-day').value;
  const endDay  = document.getElementById('qe-endday').value.trim();
  const mult    = +document.getElementById('qe-mult').value;

  const isNode    = ['node_closure','node_capacity_change'].includes(type);
  const isCompany = ['sanction_company','sanction_ship_flag'].includes(type);

  const row = {
    constraint_id: 'QUICK_'+Date.now(),
    constraint_type: type,
    apply_on_day: day,
    end_on_day: endDay||'',
    description: `Quick event: ${type} on ${target}`,
    target_nodes:     isNode    ? target : '',
    target_companies: isCompany ? target : '',
    target_countries: '',
    target_regions:   (!isNode && !isCompany) ? target : '',
    target_products: '',
    multiplier: mult,
    additive: 0,
    capacity_vessels: '',
  };
  if(!tables.constraints) tables.constraints=[];
  tables.constraints.push(row);

  fetch(API+'/api/table',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:'constraints',rows:tables.constraints})})
    .then(()=>{ toast('Event added — triggering re-run…'); startRun(); });
}

// ═══════════════════════════════════════════════════════════════════════════
// DASHBOARD CHARTS (canvas 2D — no external library needed)
// ═══════════════════════════════════════════════════════════════════════════
function renderDashboard() {
  if(!SIM) return;
  const steps = SIM.steps;
  const dates = steps.map(s=>s.date);

  drawLineChart('ch-spot', dates, [{
    data: steps.map(s=>s.spot_rate), color:'#00e5ff', fill:true, label:'Spot Rate'
  }], {yLabel:'$/day', regimes:getRegimeBands(steps)});

  drawLineChart('ch-fleet', dates, [
    {data: steps.map(s=>s.fleet_active),  color:'#4ade80', fill:false, label:'Active'},
    {data: steps.map(s=>s.fleet_storage), color:'#a78bfa', fill:true,  label:'Storage FSO'},
    {data: steps.map(s=>s.orderbook),     color:'#ffd23f', fill:false, label:'Orderbook', dashed:true},
  ], {yLabel:'vessels'});

  drawLineChart('ch-sd', dates, [{
    data: steps.map(s=>s.sd_ratio), color:'#ffd23f', fill:true, label:'S/D ratio'
  }], {yLabel:'ratio', hline:1.0});

  drawLineChart('ch-wti', dates, [{
    data: steps.map(s=>s.wti), color:'#ff6b35', fill:true, label:'WTI'
  }], {yLabel:'$/bbl'});

  drawLineChart('ch-ob', dates, [{
    data: steps.map(s=>s.orderbook), color:'#f472b6', fill:true, label:'Orderbook'
  }], {yLabel:'ships'});

  // Fleet composition stacked area
  const typeKeys = Object.keys(steps[0].fleet||{});
  const COLORS = ['#00d4ff','#38bdf8','#fb923c','#4ade80','#a78bfa','#f472b6','#fbbf24'];
  drawLineChart('ch-fcomp', dates,
    typeKeys.map((k,i)=>({data:steps.map(s=>(s.fleet||{})[k]||0), color:COLORS[i%COLORS.length], fill:false, label:k})),
    {yLabel:'vessels'});

  drawLineChart('ch-lf', dates, [{
    data: steps.map(s=>s.load_factor), color:'#39ff14', fill:true, label:'Load Factor'
  }], {yLabel:'fraction', hline:0.85});
}

function getRegimeBands(steps) {
  // Mark bands where constraints changed
  const bands=[];
  let start=null, prev='';
  steps.forEach((s,i)=>{
    const c=s.constraints||'';
    if(c!==prev && c){
      if(start!==null) bands.push({from:start,to:i,label:prev});
      start=i;
    } else if(!c && start!==null){
      bands.push({from:start,to:i,label:prev});
      start=null;
    }
    prev=c;
  });
  if(start!==null) bands.push({from:start,to:steps.length-1,label:prev});
  return bands;
}

function drawLineChart(canvasId, labels, series, opts={}) {
  const canvas = document.getElementById(canvasId);
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio||1;
  canvas.width  = canvas.offsetWidth  * dpr;
  canvas.height = canvas.offsetHeight * dpr;
  ctx.scale(dpr,dpr);
  const W=canvas.offsetWidth, H=canvas.offsetHeight;
  const PAD={l:48,r:12,t:12,b:28};
  const CW=W-PAD.l-PAD.r, CH=H-PAD.t-PAD.b;

  ctx.fillStyle='#060e18';
  ctx.fillRect(0,0,W,H);

  const allVals = series.flatMap(s=>s.data).filter(v=>isFinite(v));
  let mn=Math.min(...allVals), mx=Math.max(...allVals);
  if(opts.hline!==undefined){mn=Math.min(mn,opts.hline*.9);mx=Math.max(mx,opts.hline*1.1);}
  const rng=mx-mn||1;
  const toX = i => PAD.l + (i/(labels.length-1||1))*CW;
  const toY = v => PAD.t + CH - ((v-mn)/rng)*CH;

  // Grid
  ctx.strokeStyle='#1e3a5a'; ctx.lineWidth=.5;
  for(let i=0;i<5;i++){
    const y=PAD.t+i*(CH/4);
    ctx.beginPath(); ctx.moveTo(PAD.l,y); ctx.lineTo(PAD.l+CW,y); ctx.stroke();
    const val=mx-(i/4)*rng;
    ctx.fillStyle='#3d5a78'; ctx.font=`${9*dpr/dpr}px Share Tech Mono`;
    ctx.fillText(val>9999?(val/1000).toFixed(0)+'k':val.toFixed(2), 2, y+3);
  }

  // Regime bands
  if(opts.regimes) opts.regimes.forEach(b=>{
    if(!b.label) return;
    ctx.fillStyle='rgba(255,107,53,.07)';
    ctx.fillRect(toX(b.from),PAD.t, toX(b.to)-toX(b.from), CH);
  });

  // Hline
  if(opts.hline!==undefined){
    ctx.strokeStyle='rgba(255,210,63,.4)'; ctx.setLineDash([4,4]); ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(PAD.l,toY(opts.hline)); ctx.lineTo(PAD.l+CW,toY(opts.hline)); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Series
  series.forEach(s=>{
    if(s.fill){
      ctx.beginPath();
      s.data.forEach((v,i)=>{ i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)); });
      ctx.lineTo(toX(s.data.length-1),PAD.t+CH); ctx.lineTo(toX(0),PAD.t+CH); ctx.closePath();
      ctx.fillStyle=s.color+'18'; ctx.fill();
    }
    ctx.beginPath(); ctx.strokeStyle=s.color; ctx.lineWidth=1.5;
    if(s.dashed) ctx.setLineDash([5,4]); else ctx.setLineDash([]);
    s.data.forEach((v,i)=>{ i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)); });
    ctx.stroke();
    ctx.setLineDash([]);
  });

  // X-axis labels (sparse)
  ctx.fillStyle='#3d5a78'; ctx.font=`${9*dpr/dpr}px Share Tech Mono`;
  const step=Math.ceil(labels.length/8);
  labels.forEach((l,i)=>{ if(i%step===0) ctx.fillText(l, toX(i)-14, H-5); });

  // Legend
  let lx=PAD.l;
  series.forEach(s=>{
    ctx.fillStyle=s.color; ctx.fillRect(lx,5,8,5);
    ctx.fillStyle='#7a9abb'; ctx.font=`${9*dpr/dpr}px Share Tech Mono`;
    ctx.fillText(s.label, lx+11, 11); lx+=ctx.measureText(s.label).width+22;
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════════════════
function downloadCSV() {
  window.location.href = API+'/api/export_csv';
}

function downloadAllTables() {
  const blob=new Blob([JSON.stringify(tables,null,2)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='maritime_config_tables.json'; a.click();
}

function exportMapHTML() {
  if(!SIM){toast('Run simulation first');return;}
  toast('Building standalone HTML…');
  // Same map HTML structure but with SIM data embedded
  const simJson = JSON.stringify(SIM,null,0);
  // Minimal standalone viewer
  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Maritime Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"><\/script>
<style>html,body{margin:0;height:100%;background:#050c18}#m{height:100vh}.leaflet-tile{filter:brightness(.3) saturate(.4) hue-rotate(185deg)}.leaflet-container{background:#020810}</style>
</head><body><div id="m"></div>
<script>
const SIM=${simJson};
const map=L.map('m',{center:[20,20],zoom:2,attributionControl:false});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
Object.entries(SIM.routes).forEach(([k,r])=>L.polyline(r.waypoints,{color:'#00e5ff',opacity:.1,weight:1.5,dashArray:'4 6'}).addTo(map));
let step=0,timer=null;
const vl=L.layerGroup().addTo(map);
const vm={};
function render(){
  const fr=SIM.frames[step]||[];
  const ids=new Set(fr.map(v=>v.id));
  Object.keys(vm).forEach(id=>{if(!ids.has(+id)){vl.removeLayer(vm[id]);delete vm[id];}});
  fr.forEach(v=>{if(!vm[v.id]){vm[v.id]=L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,fillOpacity:.85,weight:1}).bindTooltip(v.owner+' '+v.type).addTo(vl);}else vm[v.id].setLatLng([v.lat,v.lon]);});
  step=(step+1)%SIM.steps.length;
}
setInterval(render,600);
<\/script></body></html>`;
  const blob=new Blob([html],{type:'text/html'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='maritime_map_export.html'; a.click();
  toast('Map HTML exported');
}

function renderExportSummary() {
  if(!SIM) return;
  const steps=SIM.steps, first=steps[0], last=steps[steps.length-1];
  const el=document.getElementById('export-summary');
  el.style.display='block';
  document.getElementById('export-summary-body').innerHTML = [
    `Granularity: ${SIM.meta.granularity}`,
    `Periods: ${SIM.meta.n_periods}`,
    `Date range: ${first.date} → ${last.date}`,
    `Spot rate: $${(first.spot_rate/1000).toFixed(1)}k → $${(last.spot_rate/1000).toFixed(1)}k /day`,
    `Fleet: ${first.fleet_active} → ${last.fleet_active} vessels`,
    `Peak spot: $${(Math.max(...steps.map(s=>s.spot_rate))/1000).toFixed(1)}k/day`,
    `Active constraints (final): ${last.constraints||'none'}`,
  ].map(l=>`<div>${l}</div>`).join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// BOOT
// ═══════════════════════════════════════════════════════════════════════════
window.addEventListener('resize', ()=>{
  if(SIM && document.getElementById('panel-dash').classList.contains('active')) renderDashboard();
});
init();
</script>
</body></html>"""


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Maritime Fleet Simulation Portal")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="localhost")
    args = p.parse_args()

    print(f"\n{'═'*56}")
    print(f"  ⬡  Maritime Fleet Simulation Portal")
    print(f"{'═'*56}")
    print(f"  Loading config tables...")
    init_tables()
    print(f"  Starting server on http://{args.host}:{args.port}")
    print(f"{'─'*56}")
    print(f"  Open http://{args.host}:{args.port} in your browser")
    print(f"  Press Ctrl+C to stop")
    print(f"{'═'*56}\n")

    server = HTTPServer((args.host, args.port), PortalHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")

if __name__ == "__main__":
    main()
