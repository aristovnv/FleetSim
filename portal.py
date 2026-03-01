#!/usr/bin/env python3
"""
Maritime Fleet Simulation — Unified Portal  v3
===============================================
All data-driven. No hardcoded constants.

Run from maritime_sim_v2/:

    python portal.py [--port 8765] [--data ./data]

If ./data/{table}.csv exists, it is loaded instead of the built-in template.
This means you can customise every table just by editing CSVs.

Architecture:
  - Python HTTP server (stdlib only, no Flask/Streamlit) at /api/*
  - All config: 15 simulation tables + 9 portal-visual tables, all editable in browser
  - Simulation runs server-side in a background thread (POST /api/run)
  - Map animation, charts, forms all rendered browser-side from JSON APIs
  - Adding a new SimConfig param: add a row to portal_params table only (no code edit)
  - Rearranging/hiding a dashboard chart: edit dashboard_charts table
  - Changing company colours, vessel sizes, map coordinates: edit viz_* tables
"""

import sys, os, json, math, random, copy, io, csv, threading, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import numpy as np
import pandas as pd


# ── JSON safety ───────────────────────────────────────────────────────────────
def _clean(obj):
    """NaN / Inf / numpy scalars -> JSON-safe Python types."""
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
    return json.dumps(_clean(obj), separators=(',', ':'))


# ── Simulation imports ────────────────────────────────────────────────────────
from core.enums import Granularity
from core.models import SimConfig
from config.schemas import (
    load_regions, load_companies, load_ship_types, load_nodes,
    load_edges, load_constraints, load_orderbook,
    ALL_TEMPLATES,
)
from config.portal_schemas import ALL_PORTAL_TEMPLATES
from core.engine import SimulationRunner


# ── Server state ──────────────────────────────────────────────────────────────
STATE = {
    "tables":       {},   # all config tables: sim + portal-visual
    "sim_result":   None,
    "sim_running":  False,
    "sim_progress": 0,
    "sim_error":    None,
}

DATA_DIR = None   # set by CLI arg


# ── Table helpers ─────────────────────────────────────────────────────────────
def df_to_rows(df: pd.DataFrame) -> list:
    return _clean(df.where(df.notna(), other=None).to_dict(orient="records"))

def rows_to_df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def get_table(name) -> list:
    return STATE["tables"].get(name, [])

def get_df(name) -> pd.DataFrame:
    return rows_to_df(get_table(name))


# ── Init: load all templates (or CSVs from --data dir) ───────────────────────
def init_tables():
    all_templates = {**ALL_TEMPLATES, **ALL_PORTAL_TEMPLATES}
    for name, fn in all_templates.items():
        csv_path = os.path.join(DATA_DIR, f"{name}.csv") if DATA_DIR else None
        if csv_path and os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            print(f"  CSV: {name} ({len(df)} rows)")
        else:
            df = fn()
        STATE["tables"][name] = df_to_rows(df)
    print(f"  {len(STATE['tables'])} tables loaded")


# ── Derive display maps from config tables ────────────────────────────────────
def build_company_color_map() -> dict:
    return {r["name"]: r["color"] for r in get_table("viz_companies") if r.get("name")}

def build_group_radius_map() -> dict:
    return {r["group"]: int(r["map_radius"]) for r in get_table("viz_ship_groups") if r.get("group")}

def build_region_coords() -> dict:
    return {
        r["region"]: {
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "label": r.get("label") or r["region"],
            "popup_fields": r.get("popup_fields") or "supply,demand,storage",
        }
        for r in get_table("viz_regions")
        if r.get("region") and str(r.get("enabled", "true")).lower() not in ("false", "0", "")
    }

def build_node_coords() -> dict:
    return {
        r["node"]: {
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "label": r.get("label") or r["node"],
            "color_open":   r.get("color_open")   or "#ffd23f",
            "color_closed": r.get("color_closed") or "#ff3860",
        }
        for r in get_table("viz_nodes")
        if r.get("node") and str(r.get("enabled", "true")).lower() not in ("false", "0", "")
    }

def build_route_index() -> dict:
    """Reassemble route waypoints from the flat viz_routes table."""
    raw = [
        r for r in get_table("viz_routes")
        if r.get("route_id") and str(r.get("enabled", "true")).lower() not in ("false", "0", "")
    ]
    routes = {}
    for r in sorted(raw, key=lambda x: (str(x["route_id"]), int(x.get("seq") or 0))):
        rid = r["route_id"]
        if rid not in routes:
            via = r.get("via_nodes") or ""
            routes[rid] = {
                "from":      r.get("from_region", ""),
                "to":        r.get("to_region", ""),
                "nodes":     [n.strip() for n in via.split(";") if n.strip()],
                "waypoints": [],
            }
        routes[rid]["waypoints"].append([float(r["lat"]), float(r["lon"])])
    return routes

def build_portal_params_defaults() -> dict:
    """Build run_config dict from portal_params table defaults."""
    result = {}
    for r in get_table("portal_params"):
        if not r.get("key"):
            continue
        raw = r.get("default_val") or ""
        ptype = r.get("param_type") or "text"
        try:
            if ptype == "number":
                result[r["key"]] = float(raw) if "." in str(raw) else int(raw)
            elif ptype == "bool":
                result[r["key"]] = str(raw).lower() in ("true", "1", "yes")
            else:
                result[r["key"]] = raw
        except (ValueError, TypeError):
            result[r["key"]] = raw
    return result

def build_type_owner_map() -> dict:
    """
    {ship_type_name: owner} derived from the fleet table's owner column.
    This is the authoritative link — no string-pattern hacking.
    Fallback: viz_companies.owner_patterns for types not in any fleet row.
    """
    result = {}
    # Primary: fleet table has (ship_type, owner) directly
    for r in get_table("fleet"):
        st = str(r.get("ship_type") or "").strip()
        ow = str(r.get("owner") or "").strip()
        if st and ow:
            result.setdefault(st, ow)   # first occurrence wins

    # Fallback: pattern matching from viz_companies
    for r in get_table("viz_companies"):
        name = str(r.get("name") or "").strip()
        patterns = [
            p.strip() for p in str(r.get("owner_patterns") or "").split(",")
            if p.strip()
        ]
        for pat in patterns:
            result.setdefault(f"__pat__{pat}", name)
    return result

def type_to_owner(st_name: str, tmap: dict) -> str:
    if st_name in tmap:
        return tmap[st_name]
    for key, owner in tmap.items():
        if key.startswith("__pat__") and key[7:] in st_name:
            return owner
    return "Independent"

def type_to_group(st_name: str, grad_map: dict) -> str:
    for g in grad_map:
        if g.lower() in st_name.lower():
            return g
    return list(grad_map.keys())[-1] if grad_map else "MR"


# ── Simulation runner ─────────────────────────────────────────────────────────
def run_simulation_task(run_cfg: dict, tables_snap: dict):
    try:
        STATE["sim_running"] = True
        STATE["sim_error"]   = None
        STATE["sim_progress"] = 5

        gran = Granularity(str(run_cfg.get("granularity", "month")))

        # Map portal_params keys to SimConfig field names
        import inspect
        sig = inspect.signature(SimConfig.__init__)
        FIELD_MAP = {
            "n_periods":              "n_periods",
            "seed":                   "random_seed",
            "base_spot_rate":         "base_spot_rate_usd_day",
            "spot_volatility":        "spot_rate_volatility",
            "wti_price":              "wti_price_usd_bbl",
            "fuel_vlsfo":             "vlsfo_price_usd_t",
            "fuel_hfo":               "hfo_price_usd_t",
            "vlsfo_price":            "vlsfo_price_usd_t",
            "hfo_price":              "hfo_price_usd_t",
            "ordering_sensitivity":   "ordering_sensitivity",
            "scrapping_threshold":    "scrapping_threshold_usd_day",
            "storage_sd_threshold":   "storage_conversion_sd_ratio",
        }
        sim_kwargs = {}
        for portal_key, sim_field in FIELD_MAP.items():
            if portal_key in run_cfg and sim_field in sig.parameters:
                try:
                    v = run_cfg[portal_key]
                    sim_kwargs[sim_field] = float(v) if "." in str(v) else int(v)
                except (ValueError, TypeError):
                    pass

        cfg = SimConfig(granularity=gran, **sim_kwargs)

        def _df(name): return rows_to_df(tables_snap.get(name, []))

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

        # Build display maps from config tables (not hardcoded)
        company_colors = build_company_color_map()
        group_radius   = build_group_radius_map()
        region_coords  = build_region_coords()
        node_coords    = build_node_coords()
        route_index    = build_route_index()
        type_owner_map = build_type_owner_map()

        route_keys = list(route_index.keys())
        rng = random.Random(int(run_cfg.get("seed", 42)))

        type_cols = [c for c in df.columns
                     if c.startswith("active_") and c != "active_constraints"]

        # Populate initial vessel list
        vessels, vid = [], 0
        for col in type_cols:
            st = col[len("active_"):]
            count  = int(df.iloc[0][col])
            group  = type_to_group(st, group_radius)
            owner  = type_to_owner(st, type_owner_map)
            color  = company_colors.get(owner, "#94a3b8")
            radius = group_radius.get(group, 4)
            for _ in range(count):
                vessels.append(dict(
                    id=vid, type=st, group=group, owner=owner, color=color, radius=radius,
                    route_key=route_keys[vid % len(route_keys)] if route_keys else "",
                    progress=rng.uniform(0, 1), speed=rng.uniform(0.025, 0.055), status="active",
                ))
                vid += 1

        frames = []
        for _, row in df.iterrows():
            # Sync fleet counts
            for col in type_cols:
                st = col[len("active_"):]
                new_n = int(row[col])
                cur_n = sum(1 for v in vessels if v["type"] == st and v["status"] == "active")
                diff  = new_n - cur_n
                if diff > 0:
                    group  = type_to_group(st, group_radius)
                    owner  = type_to_owner(st, type_owner_map)
                    color  = company_colors.get(owner, "#94a3b8")
                    radius = group_radius.get(group, 4)
                    for _ in range(diff):
                        vessels.append(dict(
                            id=vid, type=st, group=group, owner=owner, color=color, radius=radius,
                            route_key=route_keys[vid % len(route_keys)] if route_keys else "",
                            progress=rng.uniform(0, 1), speed=rng.uniform(0.025, 0.055), status="active",
                        ))
                        vid += 1
                elif diff < 0:
                    removed = 0
                    for v in reversed(vessels):
                        if v["type"] == st and v["status"] == "active":
                            v["status"] = "scrapped"; removed += 1
                            if removed >= abs(diff): break

            fv = []
            for v in vessels:
                if v["status"] != "active": continue
                v["progress"] = (v["progress"] + v["speed"]) % 1.0
                rt   = route_index.get(v["route_key"], {})
                wpts = rt.get("waypoints", [])
                if not wpts: continue
                frac = v["progress"] * (len(wpts) - 1)
                i0 = int(frac); i1 = min(i0+1, len(wpts)-1); t = frac - i0
                lat = wpts[i0][0] + t*(wpts[i1][0]-wpts[i0][0])
                lon = wpts[i0][1] + t*(wpts[i1][1]-wpts[i0][1])
                fv.append(dict(id=v["id"], lat=round(lat,4), lon=round(lon,4),
                               color=v["color"], radius=v["radius"],
                               type=v["type"], owner=v["owner"], group=v["group"]))
            frames.append(fv)

        STATE["sim_progress"] = 90

        steps = []
        region_names = list(region_coords.keys())
        node_names   = list(node_coords.keys())

        for _, row in df.iterrows():
            fleet_bd = {col[len("active_"):]: int(row[col]) for col in type_cols}

            regions_data = {}
            for rn in region_names:
                regions_data[rn] = {
                    "demand":  round(float(row.get(f"demand_{rn}",  0) or 0), 3),
                    "supply":  round(float(row.get(f"supply_{rn}",  0) or 0), 3),
                    "storage": round(float(row.get(f"storage_inv_{rn}", 0) or 0), 3),
                }

            nodes_data = {}
            for nn in node_names:
                nk = "node_" + nn.replace(" ", "_").replace(".", "")
                nodes_data[nn] = bool(int(row.get(nk, 1) or 1))

            steps.append(_clean(dict(
                date          = str(row["date_label"]),
                spot_rate     = round(float(row["spot_rate"]), 0),
                wti           = round(float(row["wti_usd_bbl"]), 2),
                vlsfo         = round(float(row["vlsfo_usd_t"]), 1),
                hfo           = round(float(row["hfo_usd_t"]), 1),
                fleet_active  = int(row["fleet_active"]),
                fleet_storage = int(row["fleet_storage"]),
                orderbook     = int(row["orderbook"]),
                sd_ratio      = round(float(row["sd_ratio"]), 4),
                load_factor   = round(float(row["load_factor"]), 4),
                constraints   = str(row.get("active_constraints") or ""),
                fleet         = fleet_bd,
                regions       = regions_data,
                nodes         = nodes_data,
            )))

        STATE["sim_result"] = _clean(dict(
            meta           = dict(granularity=run_cfg.get("granularity", "month"),
                                  n_periods=len(steps), seed=int(run_cfg.get("seed", 42))),
            regions        = region_coords,
            nodes          = node_coords,
            routes         = route_index,
            company_colors = company_colors,
            group_radius   = group_radius,
            steps          = steps,
            frames         = frames,
        ))
        STATE["sim_progress"] = 100
        n_v = max((len(f) for f in frames), default=0)
        print(f"  Done: {len(steps)} steps, {n_v} vessels/frame")

    except Exception as e:
        import traceback
        STATE["sim_error"] = str(e) + "\n" + traceback.format_exc()
        print("SIM ERROR:", STATE["sim_error"][:600])
    finally:
        STATE["sim_running"] = False


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def _json(self, data, status=200):
        body = safe_json(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._html(PORTAL_HTML)
        elif path == "/api/tables":
            self._json(STATE["tables"])
        elif path == "/api/status":
            self._json(dict(running=STATE["sim_running"], progress=STATE["sim_progress"],
                            error=STATE["sim_error"], has_result=STATE["sim_result"] is not None))
        elif path == "/api/result":
            if STATE["sim_result"]:
                self._json(STATE["sim_result"])
            else:
                self._json({"error": "no result"}, 404)
        elif path == "/api/export_csv":
            self._export_csv()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/run":
            body = self._body()
            if STATE["sim_running"]:
                self._json({"error": "already running"}, 409); return
            cfg  = build_portal_params_defaults()
            cfg.update(body.get("config", {}))
            snap = copy.deepcopy(STATE["tables"])
            threading.Thread(target=run_simulation_task, args=(cfg, snap), daemon=True).start()
            self._json({"status": "started"})
        elif path == "/api/table":
            body = self._body()
            name, rows = body.get("name"), body.get("rows")
            if name and rows is not None:
                STATE["tables"][name] = _clean(rows)
                self._json({"status": "ok", "rows": len(rows)})
            else:
                self._json({"error": "bad request"}, 400)
        else:
            self.send_response(404); self.end_headers()

    def _export_csv(self):
        if not STATE["sim_result"]:
            self._json({"error": "no result"}, 404); return
        steps = STATE["sim_result"]["steps"]
        buf = io.StringIO()
        if steps:
            w = csv.DictWriter(buf, fieldnames=list(steps[0].keys()))
            w.writeheader()
            for s in steps:
                w.writerow({k: (safe_json(v) if isinstance(v, dict) else v) for k, v in s.items()})
        body = buf.getvalue().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=maritime_sim.csv")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


# ── Portal HTML ───────────────────────────────────────────────────────────────
PORTAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maritime Fleet Portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{
  --bg:#050c18;--bg2:#0a1628;--bg3:#0f2040;--bg4:#162a4a;
  --b1:#1e3a5a;--b2:#254870;
  --cy:#00e5ff;--cy2:#0099b5;--cy3:rgba(0,229,255,.12);
  --am:#ffd23f;--gn:#39ff14;--rd:#ff3860;--or:#ff6b35;
  --t1:#c8daf0;--t2:#7a9abb;--t3:#3d5a78;
  --mono:'Share Tech Mono',monospace;--sans:'Exo 2',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;overflow:hidden;background:var(--bg);color:var(--t1);font-family:var(--sans);font-size:13px}
#shell{display:flex;flex-direction:column;height:100vh}
/* topbar */
#topbar{display:flex;align-items:center;background:var(--bg2);border-bottom:1px solid var(--b1);flex-shrink:0;height:42px}
#logo{padding:0 18px;font-family:var(--mono);font-size:.88rem;color:var(--cy);letter-spacing:.2em;border-right:1px solid var(--b1);height:100%;display:flex;align-items:center;white-space:nowrap}
#logo span{color:var(--t2);font-size:.58rem;margin-left:8px}
#tabs{display:flex;height:100%;border-right:1px solid var(--b1)}
.tab{padding:0 15px;cursor:pointer;font-family:var(--mono);font-size:.67rem;letter-spacing:.1em;color:var(--t2);border-right:1px solid var(--b1);display:flex;align-items:center;gap:5px;transition:all .12s;height:100%;border-bottom:2px solid transparent}
.tab:hover{color:var(--t1);background:var(--bg3)}.tab.active{color:var(--cy);border-bottom-color:var(--cy);background:var(--bg3)}
#run-area{margin-left:auto;display:flex;align-items:center;gap:8px;padding:0 14px}
#run-btn{background:rgba(0,229,255,.08);border:1px solid var(--cy2);color:var(--cy);font-family:var(--mono);font-size:.67rem;padding:4px 13px;border-radius:3px;cursor:pointer;letter-spacing:.1em;transition:all .15s}
#run-btn:hover{background:var(--cy3)}#run-btn:disabled{opacity:.4;cursor:not-allowed}
#run-prog{display:none;width:100px;height:3px;background:var(--bg4);border-radius:2px;overflow:hidden}
#run-prog-bar{height:100%;background:var(--cy);width:0;transition:width .3s;border-radius:2px}
#run-txt{font-family:var(--mono);font-size:.6rem;color:var(--t2)}
/* panels */
#content{flex:1;overflow:hidden;position:relative}
.panel{position:absolute;inset:0;display:none;overflow:auto}.panel.active{display:flex}
/* MAP */
#panel-map{flex-direction:column;overflow:hidden}
#tbar{display:flex;align-items:center;gap:6px;background:var(--bg2);border-bottom:1px solid var(--b1);padding:4px 12px;flex-shrink:0;flex-wrap:wrap}
#date-bd{font-family:var(--mono);font-size:1.1rem;color:var(--am);letter-spacing:.06em;min-width:74px}
#step-bd{font-family:var(--mono);font-size:.6rem;color:var(--t3);min-width:60px}
.tb{background:transparent;border:1px solid var(--b1);color:var(--t2);width:27px;height:27px;border-radius:3px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.82rem;transition:all .12s;flex-shrink:0}
.tb:hover{border-color:var(--cy);color:var(--cy)}.tb.active{background:var(--cy3);border-color:var(--cy);color:var(--cy)}
#spd-ind{font-family:var(--mono);font-size:.62rem;color:var(--t3);min-width:20px}
#scrub-wrap{flex:1;min-width:80px}
#scrubber{-webkit-appearance:none;width:100%;height:3px;background:var(--bg4);border-radius:2px;outline:none;cursor:pointer}
#scrubber::-webkit-slider-thumb{-webkit-appearance:none;width:11px;height:11px;background:var(--cy);border-radius:50%;cursor:pointer}
.tg{display:flex;gap:11px;border-left:1px solid var(--b1);padding-left:11px}
.tk{display:flex;flex-direction:column;align-items:flex-end;line-height:1.1}
.tkl{font-size:.5rem;color:var(--t3);text-transform:uppercase;letter-spacing:.07em}
.tkv{font-family:var(--mono);font-size:.78rem;color:var(--cy)}
.tkv.up{color:var(--gn)}.tkv.dn{color:var(--rd)}
#cst-strip{display:flex;gap:3px;padding-left:8px;flex-wrap:wrap}
.cb{font-family:var(--mono);font-size:.5rem;padding:2px 5px;border:1px solid var(--or);color:var(--or);background:rgba(255,107,53,.07);border-radius:2px;white-space:nowrap}
.cb.closed{border-color:var(--rd);color:var(--rd);background:rgba(255,56,96,.07)}
#map-body{display:flex;flex:1;overflow:hidden}
#map{flex:1;background:var(--bg)}
.leaflet-tile{filter:brightness(.28) saturate(.3) hue-rotate(190deg)}.leaflet-container{background:#010608}
.leaflet-control-zoom a{background:var(--bg2)!important;color:var(--t2)!important;border-color:var(--b1)!important}
.leaflet-tooltip{background:rgba(5,12,24,.93)!important;color:var(--t1)!important;border:1px solid var(--b1)!important;font-family:var(--mono)!important;font-size:.63rem!important;padding:3px 6px!important;border-radius:2px!important}
#scanlines{position:absolute;inset:0;pointer-events:none;z-index:999;background:repeating-linear-gradient(to bottom,transparent 0,transparent 3px,rgba(0,0,0,.04) 3px,rgba(0,0,0,.04) 4px)}
#rpop{position:absolute;z-index:2000;background:rgba(5,12,24,.95);border:1px solid var(--cy2);border-radius:4px;padding:9px 12px;min-width:156px;pointer-events:none;display:none;backdrop-filter:blur(8px)}
#rpop h4{font-family:var(--mono);color:var(--cy);font-size:.74rem;margin-bottom:5px}
.rpr{display:flex;justify-content:space-between;gap:10px;font-size:.66rem;color:var(--t2);margin-bottom:2px}
.rpv{font-family:var(--mono);color:var(--t1)}
#side{width:240px;background:rgba(5,12,24,.94);border-left:1px solid var(--b1);display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
.sec{padding:8px 11px;border-bottom:1px solid var(--b1)}
.sec-t{font-family:var(--mono);font-size:.56rem;letter-spacing:.13em;color:var(--t3);text-transform:uppercase;margin-bottom:5px}
.fr{display:flex;align-items:center;gap:4px;margin-bottom:3px}
.fd{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.fn{font-size:.59rem;color:var(--t2);flex:1;overflow:hidden;white-space:nowrap}
.fbw{width:64px;height:3px;background:var(--bg4);border-radius:2px;overflow:hidden}
.fbf{height:100%;border-radius:2px;transition:width .3s}
.fn2{font-family:var(--mono);font-size:.6rem;color:var(--t1);min-width:16px;text-align:right}
.sdb{margin-top:4px}.sdg{width:100%;height:4px;background:var(--bg4);border-radius:2px;position:relative}
.sdf{height:100%;border-radius:2px;transition:width .35s,background .35s}
.sdm{position:absolute;top:-2px;left:50%;width:1.5px;height:8px;background:var(--t3);transform:translateX(-50%)}
.sdv{font-family:var(--mono);font-size:.68rem;margin-top:2px}
#spark{width:100%;height:60px;display:block}
.li{display:flex;align-items:center;gap:5px;margin-bottom:2px}
.ld{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.ll{font-size:.62rem;color:var(--t2)}
.sr{display:flex;align-items:center;gap:4px;margin-bottom:2px}
.sg{border-radius:50%;border:1.5px solid var(--t3);flex-shrink:0}
/* CONFIG */
#panel-config{flex-direction:row;overflow:hidden}
#cnav{width:152px;background:var(--bg2);border-right:1px solid var(--b1);flex-shrink:0;overflow-y:auto;padding:6px 0}
.cng{padding:9px 13px 2px;font-family:var(--mono);font-size:.54rem;color:var(--t3);letter-spacing:.1em;text-transform:uppercase}
.cni{padding:5px 13px;cursor:pointer;font-size:.68rem;color:var(--t2);border-left:2px solid transparent;transition:all .12s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cni:hover{color:var(--t1);background:var(--bg3)}.cni.active{color:var(--cy);border-left-color:var(--cy);background:var(--bg3)}
#cfg-main{flex:1;overflow:auto;padding:13px}
#cfg-title{font-family:var(--mono);font-size:.78rem;color:var(--cy);margin-bottom:7px}
#cfg-actions{display:none;gap:6px;margin-bottom:9px;align-items:center}
.ab{background:transparent;border:1px solid var(--b1);color:var(--t2);font-family:var(--mono);font-size:.6rem;padding:3px 9px;border-radius:3px;cursor:pointer;letter-spacing:.07em;transition:all .12s}
.ab:hover{border-color:var(--cy2);color:var(--cy)}
#add-row{background:rgba(0,229,255,.04);border:1px dashed var(--b2);color:var(--t3);font-size:.6rem;padding:3px 8px;border-radius:2px;cursor:pointer;font-family:var(--mono);transition:all .12s}
#add-row:hover{color:var(--cy);border-color:var(--cy2)}
.ctw{overflow-x:auto}
.ct{border-collapse:collapse;width:100%;font-size:.66rem}
.ct th{padding:4px 8px;text-align:left;background:var(--bg3);border-bottom:1px solid var(--b1);font-family:var(--mono);font-size:.56rem;color:var(--t2);letter-spacing:.07em;text-transform:uppercase;white-space:nowrap;position:sticky;top:0;z-index:1}
.ct td{padding:2px 1px;border-bottom:1px solid var(--b1);vertical-align:middle}
.ct tr:hover td{background:var(--bg3)}
.ci{background:transparent;border:none;color:var(--t1);font-family:var(--mono);font-size:.66rem;padding:2px 6px;width:100%;min-width:50px;border-radius:2px;outline:none}
.ci:focus{background:var(--bg3);outline:1px solid var(--b2)}.ci.ch{color:var(--am)}
.dr{background:transparent;border:none;color:var(--t3);cursor:pointer;font-size:.82rem;padding:0 3px}
.dr:hover{color:var(--rd)}
/* DASHBOARD */
#panel-dash{flex-wrap:wrap;padding:12px;gap:10px;align-content:flex-start;overflow-y:auto}
.cc{background:var(--bg2);border:1px solid var(--b1);border-radius:4px;padding:11px;flex-shrink:0}
.cc.wide{width:calc(66% - 5px);min-width:360px}.cc.half{width:calc(50% - 5px);min-width:260px}.cc.third{width:calc(33.3% - 7px);min-width:210px}
.cct{font-family:var(--mono);font-size:.6rem;color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px}
canvas.ch{width:100%;display:block}
/* SCENARIO */
#panel-scenario{flex-direction:column;padding:13px;gap:12px;overflow-y:auto}
.sc-sec{background:var(--bg2);border:1px solid var(--b1);border-radius:4px;padding:12px}
.sc-t{font-family:var(--mono);font-size:.68rem;color:var(--cy);letter-spacing:.1em;margin-bottom:9px}
.pg{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:9px}
.pr{display:flex;flex-direction:column;gap:2px}
.pl{font-size:.61rem;color:var(--t2)}
.pi{background:var(--bg3);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:.7rem;padding:4px 7px;border-radius:3px;outline:none;width:100%}
.pi:focus{border-color:var(--cy2)}select.pi option{background:var(--bg2)}
.pi-d{font-size:.55rem;color:var(--t3);margin-top:1px}
.pg-lbl{font-family:var(--mono);font-size:.54rem;color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-top:5px;margin-bottom:3px;grid-column:1/-1;padding-top:4px;border-top:1px solid var(--b1)}
.pg-lbl:first-child{border-top:none;margin-top:0}
.prst-grid{display:flex;gap:7px;flex-wrap:wrap}
.prst{background:var(--bg3);border:1px solid var(--b1);color:var(--t2);font-family:var(--mono);font-size:.61rem;padding:5px 11px;border-radius:3px;cursor:pointer;letter-spacing:.07em;transition:all .12s}
.prst:hover{border-color:var(--am);color:var(--am);background:rgba(255,210,63,.05)}
/* EXPORT */
#panel-export{flex-direction:column;padding:18px;gap:13px;overflow-y:auto}
.xc{background:var(--bg2);border:1px solid var(--b1);border-radius:4px;padding:13px;max-width:560px}
.xc h3{font-family:var(--mono);font-size:.7rem;color:var(--cy);margin-bottom:5px}
.xc p{font-size:.68rem;color:var(--t2);line-height:1.6;margin-bottom:9px}
.xb{display:inline-block;background:var(--bg3);border:1px solid var(--b2);color:var(--t1);font-family:var(--mono);font-size:.63rem;padding:5px 12px;border-radius:3px;cursor:pointer;letter-spacing:.07em;transition:all .12s;margin-right:6px;text-decoration:none}
.xb:hover{border-color:var(--cy2);color:var(--cy)}
/* toast */
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--bg3);border:1px solid var(--b2);color:var(--t1);font-family:var(--mono);font-size:.66rem;padding:6px 16px;border-radius:3px;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none}
#toast.show{opacity:1}
::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:2px}
</style>
</head>
<body>
<div id="shell">
  <div id="topbar">
    <div id="logo">⬡ MARITIME SIM <span>v3 · all data-driven</span></div>
    <div id="tabs">
      <div class="tab active" data-tab="map">🗺 MAP</div>
      <div class="tab" data-tab="config">⚙ CONFIG</div>
      <div class="tab" data-tab="dash">📊 DASHBOARD</div>
      <div class="tab" data-tab="scenario">🎯 SCENARIO</div>
      <div class="tab" data-tab="export">💾 EXPORT</div>
    </div>
    <div id="run-area">
      <span id="run-txt">no result yet</span>
      <div id="run-prog"><div id="run-prog-bar"></div></div>
      <button id="run-btn" onclick="startRun()">▶ RUN</button>
    </div>
  </div>

  <div id="content">
    <!-- MAP TAB -->
    <div class="panel active" id="panel-map">
      <div id="tbar">
        <div id="date-bd">----</div><div id="step-bd">—</div>
        <button class="tb" id="tb-prev">◀</button>
        <button class="tb" id="tb-play">▶</button>
        <button class="tb" id="tb-next">▷</button>
        <button class="tb" id="tb-stop">■</button>
        <button class="tb" id="tb-sl">−</button>
        <span id="spd-ind">1×</span>
        <button class="tb" id="tb-fa">+</button>
        <div id="scrub-wrap"><input type="range" id="scrubber" min="0" value="0"></div>
        <div class="tg">
          <div class="tk"><span class="tkl">Spot</span><span class="tkv" id="tv-spot">—</span></div>
          <div class="tk"><span class="tkl">WTI</span><span class="tkv" id="tv-wti">—</span></div>
          <div class="tk"><span class="tkl">VLSFO</span><span class="tkv" id="tv-vlsfo">—</span></div>
          <div class="tk"><span class="tkl">Fleet</span><span class="tkv" id="tv-fleet">—</span></div>
          <div class="tk"><span class="tkl">S/D</span><span class="tkv" id="tv-sd">—</span></div>
        </div>
        <div id="cst-strip"></div>
      </div>
      <div id="map-body">
        <div id="map"><div id="scanlines"></div><div id="rpop"></div></div>
        <div id="side">
          <div class="sec"><div class="sec-t">Fleet by Type</div><div id="fleet-bd"></div></div>
          <div class="sec"><div class="sec-t">S/D Balance</div>
            <div class="sdb"><div class="sdg"><div class="sdf" id="sd-fill"></div><div class="sdm"></div></div>
            <div class="sdv" id="sd-val">—</div></div></div>
          <div class="sec" style="flex:1"><div class="sec-t">Spot Rate History</div><canvas id="spark"></canvas></div>
          <div class="sec"><div class="sec-t">Owners</div><div id="leg-owners"></div></div>
          <div class="sec" style="padding-bottom:10px"><div class="sec-t">Vessel size</div><div id="leg-groups"></div></div>
        </div>
      </div>
    </div>

    <!-- CONFIG TAB -->
    <div class="panel" id="panel-config">
      <div id="cnav"></div>
      <div id="cfg-main">
        <div id="cfg-title">Select a table →</div>
        <div id="cfg-actions">
          <button class="ab" onclick="saveTable()">💾 Save</button>
          <button class="ab" onclick="resetTable()">↺ Reset to default</button>
          <button id="add-row" onclick="addRow()">+ Add row</button>
        </div>
        <div class="ctw"><table class="ct"><thead id="ct-head"></thead><tbody id="ct-body"></tbody></table></div>
      </div>
    </div>

    <!-- DASHBOARD TAB -->
    <div class="panel" id="panel-dash"></div>

    <!-- SCENARIO TAB -->
    <div class="panel" id="panel-scenario">
      <div class="sc-sec"><div class="sc-t">⚙ SIMULATION PARAMETERS</div><div class="pg" id="param-grid"></div></div>
      <div class="sc-sec"><div class="sc-t">🎯 PRESETS</div><div class="prst-grid" id="prst-grid"></div></div>
      <div class="sc-sec">
        <div class="sc-t">⚡ QUICK EVENT</div>
        <div class="pg">
          <div class="pr"><label class="pl">Event type</label>
            <select class="pi" id="qe-type">
              <option value="node_closure">Node Closure</option>
              <option value="demand_shock">Demand Shock</option>
              <option value="sanction_ship_flag">Sanction (flag/company)</option>
              <option value="supply_shock">Supply Shock</option>
            </select></div>
          <div class="pr"><label class="pl">Target (node/region/company)</label>
            <input class="pi" id="qe-target" value="Strait of Hormuz"></div>
          <div class="pr"><label class="pl">Apply on day</label>
            <input class="pi" type="number" id="qe-day" value="30"></div>
          <div class="pr"><label class="pl">End on day (blank = permanent)</label>
            <input class="pi" type="number" id="qe-end" placeholder="blank=permanent"></div>
          <div class="pr"><label class="pl">Multiplier (0=block, 1=no change)</label>
            <input class="pi" type="number" id="qe-mult" value="0" step="0.05"></div>
        </div>
        <button class="ab" style="margin-top:9px" onclick="addEvent()">+ Add event &amp; re-run</button>
      </div>
    </div>

    <!-- EXPORT TAB -->
    <div class="panel" id="panel-export">
      <div class="xc"><h3>📄 Results CSV</h3><p>All time steps, market metrics, fleet counts, regional stats.</p>
        <button class="xb" onclick="window.location='/api/export_csv'">⬇ Download CSV</button></div>
      <div class="xc"><h3>🗂 Config Tables (JSON)</h3>
        <p>All editable tables as a single JSON. Edit tables here, download, put CSVs in data/ folder for persistent overrides.</p>
        <button class="xb" onclick="downloadTables()">⬇ Config JSON</button></div>
      <div class="xc"><h3>🗺 Standalone Map HTML</h3>
        <p>Self-contained animated map HTML file for sharing.</p>
        <button class="xb" onclick="exportMap()">⬇ Export Map HTML</button></div>
      <div class="xc" id="x-summary" style="display:none">
        <h3>📊 Last Run Summary</h3>
        <div id="x-sum-body" style="font-family:var(--mono);font-size:.66rem;color:var(--t2);line-height:2"></div>
      </div>
    </div>
  </div>
</div>
<div id="toast"></div>

<script>
// ── Global state ──────────────────────────────────────────────────────────────
let SIM=null, tables={}, runCfg={};
let step=0, playing=false, timer=null, spdIdx=0;
const SPDS=[1,2,4,8];
let prevSpot=null, curTable=null;

const $=id=>document.getElementById(id);
function toast(m,d=2400){const e=$('toast');e.textContent=m;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),d)}

// ── Derived maps from config tables ──────────────────────────────────────────
// These are recalculated from tables each time they're needed — if you edit
// viz_companies in the Config tab and re-run, the new colours take effect.
function companyColors(){return Object.fromEntries((tables.viz_companies||[]).map(r=>[r.name,r.color]))}
function groupRadius(){return Object.fromEntries((tables.viz_ship_groups||[]).map(r=>[r.group,+r.map_radius]))}
function uiSettings(){return Object.fromEntries((tables.portal_settings||[]).map(r=>[r.key,r.value]))}

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('panel-'+t.dataset.tab).classList.add('active');
  if(t.dataset.tab==='dash'&&SIM) buildDashboard();
  if(t.dataset.tab==='export'&&SIM) buildExportSummary();
}));

// ── Init ──────────────────────────────────────────────────────────────────────
async function init(){
  try{
    tables=await fetch('/api/tables').then(r=>r.json());
    runCfg=buildRunCfg();
    buildConfigNav();
    buildScenarioParams();
    buildLegend();
    initMap();
    const st=await fetch('/api/status').then(r=>r.json());
    if(st.has_result){SIM=await fetch('/api/result').then(r=>r.json());onSimLoaded();}
    toast('Ready — press ▶ RUN to simulate');
  }catch(e){toast('Server error: '+e.message,5000);console.error(e);}
}

function buildRunCfg(){
  const cfg={};
  (tables.portal_params||[]).forEach(p=>{
    if(!p.key)return;
    const raw=String(p.default_val??'');
    if(p.param_type==='number')cfg[p.key]=raw.includes('.')?parseFloat(raw):parseInt(raw);
    else if(p.param_type==='bool')cfg[p.key]=raw.toLowerCase()==='true';
    else cfg[p.key]=raw;
  });
  return cfg;
}

// ── Run ───────────────────────────────────────────────────────────────────────
async function startRun(){
  const btn=$('run-btn');btn.disabled=true;
  $('run-prog').style.display='block';$('run-txt').textContent='starting…';
  await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:runCfg})});
  const poll=setInterval(async()=>{
    const st=await fetch('/api/status').then(r=>r.json());
    $('run-prog-bar').style.width=st.progress+'%';
    $('run-txt').textContent=st.running?`running ${st.progress}%`:st.error?'error':'done';
    if(!st.running){
      clearInterval(poll);btn.disabled=false;$('run-prog').style.display='none';
      if(st.error){toast('Sim error — see console',5000);console.error(st.error);return;}
      SIM=await fetch('/api/result').then(r=>r.json());
      onSimLoaded();toast(`✓ Done — ${SIM.steps.length} steps`);
    }
  },400);
}

function onSimLoaded(){
  $('scrubber').max=SIM.steps.length-1;
  initMapLayers();render(0);
  const s=uiSettings();
  if(s.autoplay_on_load!=='false')setTimeout(()=>setPlay(true),500);
  if(document.querySelector('#panel-dash.active'))buildDashboard();
}

// ── Leaflet map ───────────────────────────────────────────────────────────────
let lmap,vlayer,rmarks={},nmarks={},vmarks={};

function initMap(){
  if(lmap)return;
  const s=uiSettings();
  lmap=L.map('map',{center:[+(s.map_center_lat||20),+(s.map_center_lon||20)],
    zoom:+(s.map_zoom||2),zoomControl:true,attributionControl:false,minZoom:2,maxZoom:6});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:6}).addTo(lmap);
  vlayer=L.layerGroup().addTo(lmap);
}

function initMapLayers(){
  if(!SIM||!lmap)return;
  Object.values(rmarks).forEach(m=>lmap.removeLayer(m));rmarks={};
  Object.values(nmarks).forEach(m=>lmap.removeLayer(m));nmarks={};
  vlayer.clearLayers();vmarks={};
  const s=uiSettings();
  // Routes (from SIM.routes — assembled server-side from viz_routes table)
  if(s.show_route_lines!=='false'){
    const op=parseFloat(s.route_opacity||0.08);
    Object.values(SIM.routes).forEach(rt=>
      L.polyline(rt.waypoints,{color:'#00e5ff',opacity:op,weight:1.5,dashArray:'4 6'}).addTo(lmap));
  }
  // Node pins (config from viz_nodes table via SIM.nodes)
  if(s.show_node_pins!=='false')
    Object.entries(SIM.nodes).forEach(([name,c])=>{
      nmarks[name]=L.marker([c.lat,c.lon],{icon:nodeIcon(c,true)})
        .bindTooltip(c.label||name).addTo(lmap);
    });
  // Region pins (config from viz_regions table via SIM.regions)
  if(s.show_region_pins!=='false')
    Object.entries(SIM.regions).forEach(([name,c])=>{
      const m=L.marker([c.lat,c.lon],{icon:regionIcon(name,SIM.steps[0],c)}).addTo(lmap);
      m.on('mouseover',e=>showPop(name,e,c));
      m.on('mouseout',()=>$('rpop').style.display='none');
      rmarks[name]=m;
    });
}

function nodeIcon(c,open){
  const col=open?(c.color_open||'#ffd23f'):(c.color_closed||'#ff3860');
  return L.divIcon({className:'',iconSize:[10,10],iconAnchor:[5,5],
    html:`<div style="width:10px;height:10px;border-radius:50%;border:2px solid ${col};background:${col}22;box-shadow:0 0 8px ${col}88"></div>`});
}

function regionIcon(name,sd,coords){
  const rd=(sd.regions||{})[name]||{};
  const ratio=rd.supply>0?rd.demand/rd.supply:0;
  const w=Math.min(100,Math.round(ratio*55));
  const bc=ratio>1.1?'#ff3860':ratio>0.9?'#39ff14':'#ffd23f';
  const lbl=(coords.label||name).substring(0,11);
  return L.divIcon({className:'',iconSize:[84,40],iconAnchor:[42,20],
    html:`<div style="padding:3px 6px;background:rgba(5,12,24,.88);border:1px solid rgba(0,229,255,.3);border-radius:3px;font-family:'Share Tech Mono',monospace;cursor:pointer">
      <div style="color:#00e5ff;font-size:.58rem;margin-bottom:1px">${lbl}</div>
      <div style="display:flex;gap:4px;font-size:.52rem;color:#7a9abb"><span>S:${(rd.supply||0).toFixed(1)}</span><span>D:${(rd.demand||0).toFixed(1)}</span></div>
      <div style="height:2px;background:#142540;margin-top:2px;border-radius:1px;overflow:hidden"><div style="width:${w}%;height:100%;background:${bc}"></div></div>
    </div>`});
}

function showPop(name,e,coords){
  if(!SIM)return;
  const rd=(SIM.steps[step].regions||{})[name]||{};
  const fields=(coords.popup_fields||'supply,demand,storage').split(',');
  const sd=rd.supply>0?(rd.demand/rd.supply).toFixed(3):'—';
  $('rpop').innerHTML=`<h4>${coords.label||name}</h4>
    ${fields.map(f=>`<div class="rpr"><span>${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`).join('')}
    <div class="rpr"><span>D/S ratio</span><span class="rpv">${sd}</span></div>`;
  const mr=$('map').getBoundingClientRect();
  let x=e.originalEvent.clientX-mr.left+12,y=e.originalEvent.clientY-mr.top+12;
  if(x+180>mr.width)x-=190;if(y+110>mr.height)y-=120;
  $('rpop').style.cssText+=`;left:${x}px;top:${y}px;display:block`;
}

// ── Master render ─────────────────────────────────────────────────────────────
function render(s){
  if(!SIM)return;
  step=Math.max(0,Math.min(SIM.steps.length-1,s));
  const sd=SIM.steps[step];
  $('date-bd').textContent=sd.date;
  $('step-bd').textContent=`${step+1}/${SIM.steps.length}`;
  $('scrubber').value=step;
  // Ticker
  const sp=sd.spot_rate,dir=prevSpot===null?'':sp>prevSpot?'up':'dn';
  $('tv-spot').textContent='$'+(sp/1000).toFixed(1)+'k';$('tv-spot').className='tkv '+dir;
  $('tv-wti').textContent='$'+sd.wti.toFixed(1);
  $('tv-vlsfo').textContent='$'+sd.vlsfo.toFixed(0);
  $('tv-fleet').textContent=sd.fleet_active+(sd.fleet_storage>0?'+'+sd.fleet_storage+'⚓':'');
  $('tv-sd').textContent=sd.sd_ratio.toFixed(3);
  prevSpot=sp;
  // Constraint/node badges
  const csts=(sd.constraints||'').split(';').filter(Boolean);
  const closed=Object.entries(sd.nodes||{}).filter(([,v])=>!v).map(([k])=>k);
  $('cst-strip').innerHTML=csts.map(c=>`<span class="cb">${c}</span>`).join('')+
    closed.map(n=>`<span class="cb closed">⛔ ${n}</span>`).join('');
  // Map update
  updateVessels(step);
  Object.entries(nmarks).forEach(([name,m])=>{
    const nc=SIM.nodes[name];if(!nc)return;
    const open=!sd.nodes||sd.nodes[name]!==false;
    m.setIcon(nodeIcon(nc,open));
  });
  Object.entries(rmarks).forEach(([name,m])=>m.setIcon(regionIcon(name,sd,SIM.regions[name]||{})));
  updateFleet(sd);updateSD(sd);updateSpark(step);
}

function updateVessels(s){
  if(!SIM)return;
  const frame=SIM.frames[s]||[];
  const fids=new Set(frame.map(v=>v.id));
  Object.keys(vmarks).forEach(id=>{if(!fids.has(+id)){vlayer.removeLayer(vmarks[id]);delete vmarks[id];}});
  const op=parseFloat(uiSettings().vessel_opacity||0.85);
  frame.forEach(v=>{
    if(!vmarks[v.id]){
      vmarks[v.id]=L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,
        fillOpacity:op,weight:1.2,opacity:.9})
        .bindTooltip(`<b style="color:${v.color}">${v.owner}</b><br>${v.type}`,{sticky:true})
        .addTo(vlayer);
    }else vmarks[v.id].setLatLng([v.lat,v.lon]);
  });
}

function updateFleet(sd){
  const fleet=sd.fleet||{},total=Object.values(fleet).reduce((a,b)=>a+b,0)||1;
  // Colour each type from the current frame's vessel data
  const typeColors={};
  (SIM.frames[step]||[]).forEach(v=>{typeColors[v.type]=v.color;});
  $('fleet-bd').innerHTML=Object.entries(fleet).map(([t,n])=>{
    const c=typeColors[t]||'#8892b0';
    return `<div class="fr"><div class="fd" style="background:${c}"></div>
      <div class="fn">${t}</div>
      <div class="fbw"><div class="fbf" style="width:${(n/total*100).toFixed(0)}%;background:${c}"></div></div>
      <div class="fn2">${n}</div></div>`;
  }).join('');
}

function updateSD(sd){
  const v=sd.sd_ratio||1,pct=Math.min(100,Math.max(0,(v-.5)/1*100));
  const c=v>1.15?'#ff3860':v>0.95?'#39ff14':'#ffd23f';
  $('sd-fill').style.width=pct+'%';$('sd-fill').style.background=c;
  $('sd-val').textContent='S/D = '+v.toFixed(3);$('sd-val').style.color=c;
}

function updateSpark(upTo){
  if(!SIM)return;
  const cv=$('spark'),ctx=cv.getContext('2d'),dpr=devicePixelRatio||1;
  cv.width=cv.offsetWidth*dpr;cv.height=cv.offsetHeight*dpr;ctx.scale(dpr,dpr);
  const W=cv.offsetWidth,H=cv.offsetHeight;
  const rates=SIM.steps.slice(0,upTo+1).map(s=>s.spot_rate);
  const mn=Math.min(...rates),mx=Math.max(...rates),rng=mx-mn||1;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='#00e5ff';ctx.lineWidth=1.3;ctx.shadowColor='#00e5ff';ctx.shadowBlur=3;
  ctx.beginPath();
  rates.forEach((r,i)=>{const x=(i/(rates.length-1||1))*W,y=H-((r-mn)/rng)*(H-5)-3;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
  ctx.stroke();ctx.shadowBlur=0;
  const lx=(rates.length-1)/(SIM.steps.length-1||1)*W,ly=H-((rates[rates.length-1]-mn)/rng)*(H-5)-3;
  ctx.beginPath();ctx.arc(lx,ly,2.5,0,Math.PI*2);ctx.fillStyle='#00e5ff';ctx.fill();
}

function buildLegend(){
  // Legend is built from viz_companies and viz_ship_groups tables — not hardcoded
  $('leg-owners').innerHTML=(tables.viz_companies||[]).map(r=>
    `<div class="li"><div class="ld" style="background:${r.color}"></div><span class="ll">${r.label||r.name}</span></div>`).join('');
  $('leg-groups').innerHTML=(tables.viz_ship_groups||[]).map(r=>{
    const d=+r.map_radius*2+2;
    return `<div class="sr"><div class="sg" style="width:${d}px;height:${d}px"></div><span class="ll">${r.label||r.group}</span></div>`;
  }).join('');
}

// ── Playback controls ─────────────────────────────────────────────────────────
function setPlay(v){
  playing=v;$('tb-play').textContent=v?'⏸':'▶';$('tb-play').classList.toggle('active',v);
  if(v)timer=setInterval(()=>{
    if(step>=(SIM?.steps.length||1)-1){setPlay(false);return;}
    render(step+SPDS[spdIdx]);
  },parseInt(uiSettings().animation_tick_ms||600));
  else clearInterval(timer);
}
$('tb-play').onclick=()=>{if(SIM)setPlay(!playing)};
$('tb-stop').onclick=()=>{setPlay(false);render(0)};
$('tb-prev').onclick=()=>{setPlay(false);if(SIM)render(step-1)};
$('tb-next').onclick=()=>{setPlay(false);if(SIM)render(step+1)};
$('tb-fa').onclick=()=>{spdIdx=Math.min(spdIdx+1,SPDS.length-1);$('spd-ind').textContent=SPDS[spdIdx]+'×'};
$('tb-sl').onclick=()=>{spdIdx=Math.max(spdIdx-1,0);$('spd-ind').textContent=SPDS[spdIdx]+'×'};
$('scrubber').oninput=function(){setPlay(false);if(SIM)render(+this.value)};

// ── Config nav — driven by table_registry ─────────────────────────────────────
function buildConfigNav(){
  const reg=[...(tables.table_registry||[])].filter(r=>String(r.enabled||'true').toLowerCase()!=='false');
  reg.sort((a,b)=>(+a.sort_order||99)-(+b.sort_order||99));
  const groups={};
  reg.forEach(r=>{const g=r.group||'Other';if(!groups[g])groups[g]=[];groups[g].push(r);});
  const nav=$('cnav');nav.innerHTML='';
  Object.entries(groups).forEach(([g,items])=>{
    const gh=document.createElement('div');gh.className='cng';gh.textContent=g;nav.appendChild(gh);
    items.forEach(r=>{
      if(!tables[r.table_name])return;
      const el=document.createElement('div');el.className='cni';
      el.textContent=r.label||r.table_name;el.id='cni-'+r.table_name;
      el.onclick=()=>loadTable(r.table_name,r.label||r.table_name);
      nav.appendChild(el);
    });
  });
}

// ── Config table editor ───────────────────────────────────────────────────────
function loadTable(name,label){
  curTable=name;
  document.querySelectorAll('.cni').forEach(x=>x.classList.remove('active'));
  const el=$('cni-'+name);if(el)el.classList.add('active');
  $('cfg-title').textContent=label||name;
  $('cfg-actions').style.display='flex';
  const rows=tables[name]||[],cols=rows.length?Object.keys(rows[0]):[];
  $('ct-head').innerHTML='<tr><th style="width:22px"></th>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>';
  $('ct-body').innerHTML=rows.map((row,ri)=>`
    <tr><td><button class="dr" onclick="delRow(${ri})">✕</button></td>
    ${cols.map(c=>`<td><input class="ci" value="${esc(row[c]??'')}" data-col="${c}" data-ri="${ri}" oninput="this.classList.add('ch')"></td>`).join('')}
    </tr>`).join('');
}

function esc(v){return String(v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}

function saveTable(){
  if(!curTable)return;
  const rows=[];
  $('ct-body').querySelectorAll('tr').forEach(tr=>{
    const row={};tr.querySelectorAll('input.ci').forEach(i=>row[i.dataset.col]=i.value);
    if(Object.keys(row).length)rows.push(row);
  });
  tables[curTable]=rows;
  fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:curTable,rows})})
    .then(()=>toast(`✓ ${curTable} saved (${rows.length} rows)`));
  document.querySelectorAll('.ci.ch').forEach(i=>i.classList.remove('ch'));
  // Rebuild legend if visual table was edited
  if(['viz_companies','viz_ship_groups'].includes(curTable))buildLegend();
}

function resetTable(){
  if(!curTable)return;
  fetch('/api/tables').then(r=>r.json()).then(t=>{tables[curTable]=t[curTable];loadTable(curTable);toast(`↺ ${curTable} reset`);});
}
function addRow(){
  if(!curTable)return;
  const rows=tables[curTable]||[];
  tables[curTable].push(rows.length?Object.fromEntries(Object.keys(rows[0]).map(k=>[k,''])):{});
  loadTable(curTable);toast('Row added — fill in and Save');
}
function delRow(ri){if(!curTable)return;tables[curTable].splice(ri,1);loadTable(curTable);toast('Row deleted — Save to apply');}

// ── Scenario params — driven by portal_params table ────────────────────────
function buildScenarioParams(){
  const params=(tables.portal_params||[]).filter(p=>String(p.enabled||'true').toLowerCase()!=='false');
  const groups={};
  params.forEach(p=>{const g=p.group||'General';if(!groups[g])groups[g]=[];groups[g].push(p);});
  const grid=$('param-grid');grid.innerHTML='';
  Object.entries(groups).forEach(([g,ps])=>{
    const lbl=document.createElement('div');lbl.className='pg-lbl';lbl.textContent=g;grid.appendChild(lbl);
    ps.forEach(p=>{
      const wrap=document.createElement('div');wrap.className='pr';
      const lel=document.createElement('label');lel.className='pl';lel.textContent=p.label||p.key;
      wrap.appendChild(lel);
      let inp;
      if(p.param_type==='select'){
        inp=document.createElement('select');inp.className='pi';
        (p.options||'').split(';').filter(Boolean).forEach(o=>{
          const opt=document.createElement('option');opt.value=o;opt.textContent=o;
          if(String(runCfg[p.key])===o)opt.selected=true;
          inp.appendChild(opt);
        });
      }else{
        inp=document.createElement('input');inp.className='pi';
        inp.type=p.param_type==='number'?'number':'text';
        inp.value=runCfg[p.key]??p.default_val??'';
        if(p.min_val!=null&&p.min_val!=='')inp.min=p.min_val;
        if(p.max_val!=null&&p.max_val!=='')inp.max=p.max_val;
        if(p.step!=null&&p.step!=='')inp.step=p.step;
      }
      inp.onchange=()=>{runCfg[p.key]=p.param_type==='number'?+inp.value:inp.value;};
      wrap.appendChild(inp);
      if(p.description){const d=document.createElement('div');d.className='pi-d';d.textContent=p.description;wrap.appendChild(d);}
      grid.appendChild(wrap);
    });
  });

  // Presets loaded from scenario_presets table — not hardcoded
  const presetRows = (tables.scenario_presets || [])
    .filter(p => String(p.enabled) !== 'false' && String(p.enabled) !== '0')
    .sort((a,b) => (+a.sort_order||99) - (+b.sort_order||99));
  window._PRESETS = presetRows;
  $('prst-grid').innerHTML = '';
  presetRows.forEach((p, i) => {
    const b = document.createElement('button');
    b.className = 'prst';
    b.textContent = p.name;
    b.title = p.description || '';
    b.onclick = () => applyPreset(i);
    $('prst-grid').appendChild(b);
  });
}

function applyPreset(i){
  const p = window._PRESETS[i];
  if(!p) return;
  // Apply cfg_overrides (key=value;key=value pairs)
  if(p.cfg_overrides){
    p.cfg_overrides.split(';').forEach(pair => {
      const [k,v] = pair.split('=');
      if(k && v !== undefined){
        const num = parseFloat(v);
        runCfg[k.trim()] = isNaN(num) ? v.trim() : num;
      }
    });
    buildScenarioParams();
  }
  // Add constraint row if preset has a constraint_type
  if(p.constraint_type){
    addConstraintRow({
      type:   p.constraint_type,
      target: p.target_nodes || p.target_companies || p.target_regions || '',
      day:    p.apply_on_day  != null ? +p.apply_on_day  : 0,
      end:    p.end_on_day    != null ? p.end_on_day      : '',
      mult:   p.multiplier    != null ? +p.multiplier     : 1,
      add:    p.additive      != null ? +p.additive       : 0,
    }, p.name);
  }
  toast(`"${p.name}" applied — press RUN`);
}

function addConstraintRow(c,label){
  const row={constraint_id:'EVT_'+Date.now(),constraint_type:c.type,
    apply_on_day:c.day??0,end_on_day:c.end??'',description:label||c.type,
    target_nodes:c.type==='node_closure'?c.target:'',
    target_companies:c.type.includes('sanction')?c.target:'',
    target_countries:'',target_regions:'',target_products:'',
    multiplier:c.mult??1,additive:c.add??0,capacity_vessels:''};
  if(!tables.constraints)tables.constraints=[];
  tables.constraints.push(row);
  fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'constraints',rows:tables.constraints})});
}

function addEvent(){
  const type=$('qe-type').value,target=$('qe-target').value.trim();
  addConstraintRow({type,target,day:+$('qe-day').value,end:$('qe-end').value.trim()||'',mult:+$('qe-mult').value},`Quick: ${type} on ${target}`);
  toast('Event added — triggering re-run…');startRun();
}

// ── Dashboard — driven by dashboard_charts table ──────────────────────────────
function buildDashboard(){
  if(!SIM)return;
  const charts=[...(tables.dashboard_charts||[])].filter(c=>String(c.enabled||'true').toLowerCase()!=='false');
  charts.sort((a,b)=>(+a.sort_order||99)-(+b.sort_order||99));
  const dash=$('panel-dash');dash.innerHTML='';
  charts.forEach(c=>{
    const div=document.createElement('div');div.className='cc '+(c.width_class||'third');
    const h=parseInt(c.height||160);
    div.innerHTML=`<div class="cct">${c.title||c.chart_id}</div><canvas class="ch" id="ch-${c.chart_id}" height="${h}" style="height:${h}px"></canvas>`;
    dash.appendChild(div);
    setTimeout(()=>drawChart(c),20);
  });
}

function drawChart(cfg){
  const canvas=document.getElementById('ch-'+cfg.chart_id);if(!canvas)return;
  const ctx=canvas.getContext('2d'),dpr=devicePixelRatio||1;
  canvas.width=canvas.offsetWidth*dpr;canvas.height=canvas.offsetHeight*dpr;ctx.scale(dpr,dpr);
  const W=canvas.offsetWidth,H=canvas.offsetHeight;
  const P={l:44,r:8,t:10,b:24},CW=W-P.l-P.r,CH=H-P.t-P.b;
  const fields=(cfg.series_fields||'').split(';').filter(Boolean);
  const labels=(cfg.series_labels||'').split(';');
  const colors=(cfg.series_colors||'').split(';');
  const fill=cfg.chart_type==='area';
  const series=fields.map((f,i)=>({data:SIM.steps.map(s=>parseFloat(s[f])||0),label:labels[i]||f,color:colors[i]||'#00e5ff',fill}));
  const all=series.flatMap(s=>s.data).filter(isFinite);
  let mn=Math.min(...all),mx=Math.max(...all);
  const hl=cfg.hline&&cfg.hline!==''?parseFloat(cfg.hline):null;
  if(hl!==null){mn=Math.min(mn,hl*.9);mx=Math.max(mx,hl*1.1);}
  const rng=mx-mn||1;
  const toX=i=>P.l+(i/(SIM.steps.length-1||1))*CW;
  const toY=v=>P.t+CH-((v-mn)/rng)*CH;
  ctx.fillStyle='#060e18';ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#1e3a5a';ctx.lineWidth=.5;
  for(let i=0;i<5;i++){const y=P.t+i*(CH/4);ctx.beginPath();ctx.moveTo(P.l,y);ctx.lineTo(P.l+CW,y);ctx.stroke();
    const v=mx-(i/4)*rng;ctx.fillStyle='#3d5a78';ctx.font='9px Share Tech Mono';
    ctx.fillText(v>9999?(v/1000).toFixed(1)+'k':v.toFixed(2),2,y+3);}
  if(hl!==null){ctx.strokeStyle='rgba(255,210,63,.35)';ctx.setLineDash([4,4]);ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(P.l,toY(hl));ctx.lineTo(P.l+CW,toY(hl));ctx.stroke();ctx.setLineDash([]);}
  series.forEach(s=>{
    if(s.fill){ctx.beginPath();s.data.forEach((v,i)=>i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)));
      ctx.lineTo(toX(s.data.length-1),P.t+CH);ctx.lineTo(toX(0),P.t+CH);ctx.closePath();ctx.fillStyle=s.color+'18';ctx.fill();}
    ctx.beginPath();ctx.strokeStyle=s.color;ctx.lineWidth=1.4;ctx.setLineDash([]);
    s.data.forEach((v,i)=>i?ctx.lineTo(toX(i),toY(v)):ctx.moveTo(toX(i),toY(v)));ctx.stroke();
  });
  const xstep=Math.ceil(SIM.steps.length/8);
  ctx.fillStyle='#3d5a78';ctx.font='9px Share Tech Mono';
  SIM.steps.forEach((_,i)=>{if(i%xstep===0)ctx.fillText(SIM.steps[i].date,toX(i)-12,H-3);});
  let lx=P.l;series.forEach(s=>{ctx.fillStyle=s.color;ctx.fillRect(lx,4,6,4);ctx.fillStyle='#7a9abb';ctx.font='9px Share Tech Mono';
    ctx.fillText(s.label,lx+9,10);lx+=ctx.measureText(s.label).width+18;});
}

// ── Export ────────────────────────────────────────────────────────────────────
function downloadTables(){
  const b=new Blob([JSON.stringify(tables,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='maritime_tables.json';a.click();
}
function exportMap(){
  if(!SIM){toast('Run simulation first');return;}
  const html=`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Maritime Map Export</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"><\/script>
<style>html,body{margin:0;height:100%}#m{height:100vh}.leaflet-tile{filter:brightness(.28) saturate(.3) hue-rotate(190deg)}.leaflet-container{background:#010608}</style>
</head><body><div id="m"></div><script>
const D=${JSON.stringify(SIM)};
const m=L.map('m',{center:[20,20],zoom:2,attributionControl:false});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(m);
Object.values(D.routes).forEach(r=>L.polyline(r.waypoints,{color:'#00e5ff',opacity:.08,weight:1.5,dashArray:'4 6'}).addTo(m));
let s=0;const vl=L.layerGroup().addTo(m),vm={};
setInterval(()=>{
  const fr=D.frames[s]||[],ids=new Set(fr.map(v=>v.id));
  Object.keys(vm).forEach(id=>{if(!ids.has(+id)){vl.removeLayer(vm[id]);delete vm[id];}});
  fr.forEach(v=>{if(!vm[v.id])vm[v.id]=L.circleMarker([v.lat,v.lon],{radius:v.radius,color:v.color,fillColor:v.color,fillOpacity:.85,weight:1}).bindTooltip(v.owner+': '+v.type).addTo(vl);else vm[v.id].setLatLng([v.lat,v.lon]);});
  s=(s+1)%D.steps.length;
},600);
<\/script></body></html>`;
  const b=new Blob([html],{type:'text/html'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='maritime_map.html';a.click();
  toast('Map HTML exported');
}
function buildExportSummary(){
  if(!SIM)return;
  const steps=SIM.steps,f=steps[0],l=steps[steps.length-1];
  $('x-summary').style.display='block';
  $('x-sum-body').innerHTML=[`Granularity: ${SIM.meta.granularity}`,`Periods: ${SIM.meta.n_periods}`,
    `Range: ${f.date} → ${l.date}`,`Spot: $${(f.spot_rate/1000).toFixed(1)}k → $${(l.spot_rate/1000).toFixed(1)}k /day`,
    `Fleet: ${f.fleet_active} → ${l.fleet_active} vessels`,
    `Peak spot: $${(Math.max(...steps.map(s=>s.spot_rate))/1000).toFixed(1)}k/day`,
    `Constraints (final): ${l.constraints||'none'}`].map(t=>`<div>${t}</div>`).join('');
}

window.addEventListener('resize',()=>{if(SIM&&document.querySelector('#panel-dash.active'))buildDashboard();});
init();
</script>
</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global DATA_DIR
    p = argparse.ArgumentParser(description="Maritime Fleet Simulation Portal v3")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="localhost")
    p.add_argument("--data", default=None,
                   help="CSV override directory. Files named {table}.csv override built-in templates.")
    args = p.parse_args()
    DATA_DIR = args.data

    print(f"\n{'═'*56}\n  ⬡  Maritime Fleet Simulation Portal  v3\n{'═'*56}")
    if DATA_DIR:
        print(f"  Data dir: {DATA_DIR}")
    print(f"  Loading tables...")
    init_tables()
    print(f"  http://{args.host}:{args.port}\n{'═'*56}\n")
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
