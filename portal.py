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
    load_vessel_groups, load_vessel_group_members,
    ALL_TEMPLATES,
)
from config.portal_schemas import ALL_PORTAL_TEMPLATES
from core.engine import SimulationRunner


# ── Server state ──────────────────────────────────────────────────────────────
STATE = {
    "tables":         {},   # all config tables: sim + portal-visual
    "sim_result":     None,
    "sim_running":    False,
    "sim_progress":   0,
    "sim_error":      None,
    # ── Branching ────────────────────────────────────────────────────────────
    "branches":       {},   # branch_id → {name, cfg, result, fork_from, fork_step, created_at, color}
    "active_branch":  None, # branch_id currently displayed
    "world_snapshots":{},   # step → deepcopy(WorldState) for the LAST completed main run
    "branch_running": None, # branch_id currently computing (or None)
}

DATA_DIR = None        # resolved at startup; can be changed at runtime
TABLE_SOURCES = {}     # name → "csv:<path>" | "template"  (for UI display)



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
def _resolve_data_dir(path: str | None) -> str | None:
    """Expand ~ and env vars; return None if path is falsy."""
    if not path:
        # Auto-discover ./data next to portal.py
        auto = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        return auto if os.path.isdir(auto) else None
    return os.path.expandvars(os.path.expanduser(path))


def load_one_table(name: str, fn, data_dir: str | None) -> tuple:
    """Load a single table: CSV if available, else template. Returns (rows, source_str)."""
    if data_dir:
        csv_path = os.path.join(data_dir, f"{name}.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            return df_to_rows(df), f"csv:{csv_path}"
    return df_to_rows(fn()), "template"


def init_tables(data_dir: str | None = None):
    global DATA_DIR, TABLE_SOURCES
    if data_dir is not None:
        DATA_DIR = data_dir
    all_templates = {**ALL_TEMPLATES, **ALL_PORTAL_TEMPLATES}
    for name, fn in all_templates.items():
        rows, source = load_one_table(name, fn, DATA_DIR)
        STATE["tables"][name] = rows
        TABLE_SOURCES[name] = source
        if source.startswith("csv"):
            print(f"  CSV  : {name} ({len(rows)} rows)  ← {source[4:]}")
    print(f"  {len(STATE['tables'])} tables loaded ({sum(1 for s in TABLE_SOURCES.values() if s.startswith('csv'))} from CSV)")


def reload_table(name: str) -> str:
    """Reload a single table from its current source. Returns source string."""
    all_templates = {**ALL_TEMPLATES, **ALL_PORTAL_TEMPLATES}
    fn = all_templates.get(name)
    if fn is None:
        return "unknown"
    rows, source = load_one_table(name, fn, DATA_DIR)
    STATE["tables"][name] = rows
    TABLE_SOURCES[name] = source
    return source


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
            "is_gateway":   bool(r.get("is_gateway", False)),
            "icon_shape":   str(r.get("icon_shape", "circle")),
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

        # Wire conflict_rules → scrapping_priority on cfg
        _apply_conflict_rules(cfg, tables_snap)

        STATE["sim_progress"] = 20

        vmembers   = load_vessel_group_members(_df("vessel_group_members"))
        runner = SimulationRunner(cfg, regions, companies, ship_types,
                                  fleet_df, orderbook, nodes, edges, constraints,
                                  vessel_group_memberships=vmembers)
        df = runner.run_with_snapshots(snapshot_every=1)
        STATE["world_snapshots"] = runner._world_snapshots
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

        # v3 engine uses vessels_{vessel_id} columns
        type_cols = [c for c in df.columns
                     if c.startswith("vessels_")]
        # Fall back to v2 active_ columns if vessels_ not present
        if not type_cols:
            type_cols = [c for c in df.columns
                         if c.startswith("active_") and c != "active_constraints"]
        col_prefix = "vessels_" if type_cols and type_cols[0].startswith("vessels_") else "active_"

        # Populate initial vessel list
        vessels, vid = [], 0
        for col in type_cols:
            st = col[len(col_prefix):]
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
                st = col[len(col_prefix):]
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
            fleet_bd = {col[len(col_prefix):]: int(row[col]) for col in type_cols}

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


# ── Conflict rules helper ──────────────────────────────────────────────────────

def _apply_conflict_rules(cfg, tables_snap: dict):
    """Read conflict_rules table and wire rule types into SimConfig attributes."""
    rules = tables_snap.get("conflict_rules", [])
    if not rules:
        return
    # Build per-type priority lists sorted by priority_rank
    by_type: dict = {}
    for r in rules:
        rt    = str(r.get("rule_type") or "").strip()
        gid   = str(r.get("group_id") or "").strip()
        rank  = int(r.get("priority_rank") or 99)
        enabled = str(r.get("enabled", "true")).lower() not in ("false", "0", "")
        if not rt or not gid or not enabled:
            continue
        by_type.setdefault(rt, []).append((rank, gid))

    for rt, lst in by_type.items():
        lst.sort(key=lambda x: x[0])
        ordered = [g for _, g in lst]
        if rt == "scrapping":
            cfg.scrapping_priority = ordered          # type: ignore[attr-defined]
        elif rt == "ordering_priority":
            cfg.ordering_group_priority = ordered     # type: ignore[attr-defined]
        elif rt == "storage_preference":
            cfg.storage_group_priority = ordered      # type: ignore[attr-defined]


# ── Branch simulation task ─────────────────────────────────────────────────────

_BRANCH_COLORS = ["#ff6b35","#ffd23f","#39ff14","#f472b6","#818cf8","#34d399","#fb923c"]

def run_branch_task(branch_id: str, fork_step: int, fork_branch_id: str,
                    run_cfg: dict, tables_snap: dict):
    """Fork a simulation from fork_step with new run_cfg overrides.
    Stores result in STATE['branches'][branch_id].
    """
    import traceback, time
    try:
        STATE["branch_running"] = branch_id
        branch = STATE["branches"][branch_id]
        branch["status"] = "running"
        branch["progress"] = 5

        # Get the world snapshot at fork_step from the source branch or main run
        if fork_branch_id and fork_branch_id != "main":
            src_result = STATE["branches"].get(fork_branch_id, {}).get("result")
            world_snaps = STATE["branches"].get(fork_branch_id, {}).get("world_snapshots", {})
        else:
            src_result = STATE["sim_result"]
            world_snaps = STATE["world_snapshots"]

        if not world_snaps:
            branch["status"] = "error"
            branch["error"] = "No snapshots available — run main simulation first"
            return

        # Find closest available snapshot at or before fork_step
        available = sorted(k for k in world_snaps if k <= fork_step)
        if not available:
            branch["status"] = "error"
            branch["error"] = f"No snapshot at or before step {fork_step}"
            return
        snap_step = available[-1]
        snapshot  = world_snaps[snap_step]

        branch["progress"] = 15

        # Build new SimConfig with overrides
        gran = Granularity(str(run_cfg.get("granularity", "month")))
        import inspect
        sig = inspect.signature(SimConfig.__init__)
        FIELD_MAP = {
            "n_periods":"n_periods","seed":"random_seed",
            "base_spot_rate":"base_spot_rate_usd_day","spot_volatility":"spot_rate_volatility",
            "wti_price":"wti_price_usd_bbl","fuel_vlsfo":"vlsfo_price_usd_t",
            "fuel_hfo":"hfo_price_usd_t","ordering_sensitivity":"ordering_sensitivity",
            "scrapping_threshold":"scrapping_threshold_usd_day",
            "storage_sd_threshold":"storage_conversion_sd_ratio",
        }
        sim_kwargs = {}
        for pk, sf in FIELD_MAP.items():
            if pk in run_cfg and sf in sig.parameters:
                try:
                    v = run_cfg[pk]
                    sim_kwargs[sf] = float(v) if "." in str(v) else int(v)
                except (ValueError, TypeError):
                    pass

        # Ensure n_periods covers the full range
        if "n_periods" not in sim_kwargs:
            base_n = (src_result or {}).get("n_periods", 48)
            sim_kwargs["n_periods"] = int(run_cfg.get("n_periods", base_n))

        cfg = SimConfig(granularity=gran, **sim_kwargs)
        _apply_conflict_rules(cfg, tables_snap)

        # Rebuild engine objects from tables
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
        vmembers   = load_vessel_group_members(_df("vessel_group_members"))

        branch["progress"] = 30

        runner = SimulationRunner(cfg, regions, companies, ship_types,
                                  fleet_df, orderbook, nodes, edges, constraints,
                                  vessel_group_memberships=vmembers)

        # Merge pre-fork history from the source branch/run
        pre_fork_steps = []
        if src_result:
            pre_fork_steps = [s for s in src_result.get("steps", [])
                              if int(s.get("step", 0)) < snap_step]

        # Resume from snapshot
        post_df = runner.resume_from_snapshot(snapshot, cfg, snap_step)
        branch["progress"] = 80

        # Convert post-fork DataFrame rows to dicts (same as main run_simulation_task)
        post_steps = _df_to_steps(post_df, runner)

        # Prepend pre-fork history
        all_steps = pre_fork_steps + post_steps

        # Build a minimal sim_result compatible with the main display
        branch["result"] = _clean(dict(
            steps       = all_steps,
            routes      = (src_result or {}).get("routes", {}),
            regions     = (src_result or {}).get("regions", {}),
            nodes       = (src_result or {}).get("nodes", {}),
            frames      = (src_result or {}).get("frames", []),  # reuse main frames for vessels
            n_periods   = cfg.n_periods,
            fork_step   = fork_step,
            fork_from   = fork_branch_id,
        ))
        branch["world_snapshots"] = runner._world_snapshots if hasattr(runner, "_world_snapshots") else {}
        branch["status"]   = "done"
        branch["progress"] = 100

    except Exception as e:
        import traceback
        err = str(e) + "\n" + traceback.format_exc()
        STATE["branches"][branch_id]["status"] = "error"
        STATE["branches"][branch_id]["error"]  = err
        print(f"BRANCH ERROR [{branch_id}]:", err[:600])
    finally:
        STATE["branch_running"] = None


def _df_to_steps(df: "pd.DataFrame", runner) -> list:
    """Convert a post-fork sim DataFrame back into the steps list format."""
    if df is None or len(df) == 0:
        return []
    steps = []
    region_names = list(runner.regions.keys())
    node_names   = list(runner.nodes.keys())
    for _, row in df.iterrows():
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
            step      = int(row.get("step", 0)),
            date      = str(row.get("date_label", "")),
            spot_rate = round(float(row.get("spot_rate", 0)), 0),
            wti       = round(float(row.get("wti_usd_bbl", 0)), 2),
            vlsfo     = round(float(row.get("vlsfo_usd_t", 0)), 1),
            hfo       = round(float(row.get("hfo_usd_t",   0)), 1),
            load_factor=round(float(row.get("load_factor", 0)), 4),
            fleet_active=int(row.get("fleet_active", 0)),
            orderbook = int(row.get("orderbook", 0)),
            sd_ratio  = round(float(row.get("sd_ratio", 1)), 4),
            regions   = regions_data,
            nodes     = nodes_data,
        )))
    return steps



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
                            error=STATE["sim_error"], has_result=STATE["sim_result"] is not None,
                            active_branch=STATE["active_branch"],
                            branch_running=STATE["branch_running"]))
        elif path == "/api/result":
            # Return active branch result if set, otherwise main
            ab = STATE["active_branch"]
            if ab and ab in STATE["branches"] and STATE["branches"][ab].get("result"):
                self._json(STATE["branches"][ab]["result"])
            elif STATE["sim_result"]:
                self._json(STATE["sim_result"])
            else:
                self._json({"error": "no result"}, 404)
        elif path == "/api/branches":
            # Summary of all branches (no heavy result payloads)
            summary = []
            for bid, b in STATE["branches"].items():
                summary.append({
                    "id": bid, "name": b["name"], "status": b["status"],
                    "fork_from": b["fork_from"], "fork_step": b["fork_step"],
                    "color": b["color"], "progress": b.get("progress", 0),
                    "error": b.get("error"),
                    "created_at": b.get("created_at", 0),
                })
            self._json({"branches": summary, "active": STATE["active_branch"]})
        elif path == "/api/export_csv":
            self._export_csv()
        elif path.startswith("/api/download_table/"):
            tname = path.split("/api/download_table/", 1)[1]
            self._download_table(tname)
        elif path == "/api/data_config":
            all_templates = {**ALL_TEMPLATES, **ALL_PORTAL_TEMPLATES}
            self._json({
                "data_dir": DATA_DIR or "",
                "tables": [
                    {
                        "name":    name,
                        "source":  TABLE_SOURCES.get(name, "template"),
                        "rows":    len(STATE["tables"].get(name, [])),
                        "has_template": name in all_templates,
                    }
                    for name in sorted(STATE["tables"].keys())
                ],
            })
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
        elif path == "/api/set_data_dir":
            body = self._body()
            new_dir = body.get("data_dir", "").strip()
            resolved = _resolve_data_dir(new_dir or None) if new_dir else None
            if new_dir and not resolved:
                self._json({"error": f"Directory not found: {new_dir}"}, 400); return
            init_tables(data_dir=resolved)
            self._json({"status": "ok", "data_dir": DATA_DIR or "",
                        "loaded": len(STATE["tables"])})
        elif path == "/api/upload_csv":
            self._upload_csv()
        elif path == "/api/reset_table":
            body = self._body()
            tname = body.get("name", "")
            src_str = reload_table(tname)
            self._json({"status": "ok", "source": src_str, "rows": len(STATE["tables"].get(tname, []))})
        elif path == "/api/save_table_csv":
            body = self._body()
            tname = body.get("name", "")
            if not tname or tname not in STATE["tables"]:
                self._json({"error": "unknown table"}, 400); return
            save_dir = DATA_DIR or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(save_dir, exist_ok=True)
            csv_path = os.path.join(save_dir, f"{tname}.csv")
            df = rows_to_df(STATE["tables"][tname])
            df.to_csv(csv_path, index=False)
            TABLE_SOURCES[tname] = f"csv:{csv_path}"
            self._json({"status": "ok", "path": csv_path})
        # ── Branch endpoints ──────────────────────────────────────────────────
        elif path == "/api/branch/create":
            body = self._body()
            if not STATE["sim_result"]:
                self._json({"error": "Run main simulation first"}, 400); return
            if STATE["branch_running"]:
                self._json({"error": "A branch is already running"}, 409); return
            fork_step      = int(body.get("fork_step", 0))
            fork_branch_id = str(body.get("fork_branch_id", "main"))
            override_cfg   = body.get("config", {})
            branch_name    = str(body.get("name", f"Branch @step{fork_step}"))
            import time
            bid = f"b{int(time.time()*1000) % 1_000_000}"
            color_idx = len(STATE["branches"]) % len(_BRANCH_COLORS)
            STATE["branches"][bid] = {
                "id": bid, "name": branch_name, "status": "pending",
                "fork_from": fork_branch_id, "fork_step": fork_step,
                "cfg": override_cfg, "color": _BRANCH_COLORS[color_idx],
                "created_at": int(time.time()), "progress": 0,
                "result": None, "error": None,
            }
            snap = copy.deepcopy(STATE["tables"])
            cfg  = build_portal_params_defaults()
            cfg.update(override_cfg)
            threading.Thread(
                target=run_branch_task,
                args=(bid, fork_step, fork_branch_id, cfg, snap),
                daemon=True).start()
            self._json({"status": "started", "branch_id": bid})
        elif path == "/api/branch/activate":
            body = self._body()
            bid  = body.get("branch_id")
            if bid == "main" or bid is None:
                STATE["active_branch"] = None
                self._json({"status": "ok", "active": "main"})
            elif bid in STATE["branches"]:
                STATE["active_branch"] = bid
                self._json({"status": "ok", "active": bid})
            else:
                self._json({"error": "unknown branch"}, 404)
        elif path == "/api/branch/delete":
            body = self._body()
            bid  = body.get("branch_id")
            if bid in STATE["branches"]:
                del STATE["branches"][bid]
                if STATE["active_branch"] == bid:
                    STATE["active_branch"] = None
                self._json({"status": "ok"})
            else:
                self._json({"error": "unknown branch"}, 404)
        else:
            self.send_response(404); self.end_headers()

    def _upload_csv(self):
        """Multipart CSV upload: ?table=name + file body."""
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        tname = (qs.get("table") or [""])[0]
        if not tname:
            self._json({"error": "?table= required"}, 400); return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            df = pd.read_csv(io.StringIO(raw))
        except Exception as e:
            self._json({"error": f"CSV parse error: {e}"}, 400); return
        rows = df_to_rows(df)
        STATE["tables"][tname] = rows
        TABLE_SOURCES[tname] = "upload"
        # Optionally persist to data dir
        if DATA_DIR:
            os.makedirs(DATA_DIR, exist_ok=True)
            df.to_csv(os.path.join(DATA_DIR, f"{tname}.csv"), index=False)
            TABLE_SOURCES[tname] = f"csv:{os.path.join(DATA_DIR, tname + '.csv')}"
        self._json({"status": "ok", "rows": len(rows), "columns": list(df.columns)})

    def _download_table(self, tname: str):
        rows = STATE["tables"].get(tname)
        if rows is None:
            self.send_response(404); self.end_headers(); return
        df = rows_to_df(rows)
        body = df.to_csv(index=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", f"attachment; filename={tname}.csv")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

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
/* SETTINGS TAB */
#panel-settings{flex-direction:column;padding:16px;gap:14px;overflow-y:auto}
.st-card{background:var(--bg2);border:1px solid var(--b1);border-radius:4px;padding:14px;max-width:900px}
.st-card h3{font-family:var(--mono);font-size:.72rem;color:var(--cy);margin-bottom:10px;letter-spacing:.1em}
.st-card p{font-size:.68rem;color:var(--t2);margin-bottom:10px;line-height:1.6}
.dir-row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.dir-input{flex:1;background:var(--bg3);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:.72rem;padding:5px 9px;border-radius:3px;outline:none}
.dir-input:focus{border-color:var(--cy2)}
.st-btn{background:var(--bg3);border:1px solid var(--b1);color:var(--t2);font-family:var(--mono);font-size:.62rem;padding:5px 11px;border-radius:3px;cursor:pointer;transition:all .12s;white-space:nowrap}
.st-btn:hover{border-color:var(--cy2);color:var(--cy)}
.st-btn.warn{border-color:#5a2010;color:var(--or)}
.st-btn.warn:hover{border-color:var(--or)}
.table-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-top:8px}
.tbl-card{background:var(--bg3);border:1px solid var(--b1);border-radius:3px;padding:8px 10px}
.tbl-name{font-family:var(--mono);font-size:.65rem;color:var(--cy);margin-bottom:3px}
.tbl-src{font-size:.58rem;margin-bottom:6px;font-family:var(--mono)}
.tbl-src.csv{color:var(--gn)}.tbl-src.template{color:var(--t3)}.tbl-src.upload{color:var(--am)}
.tbl-rows{font-size:.56rem;color:var(--t3);margin-bottom:5px}
.tbl-actions{display:flex;gap:4px;flex-wrap:wrap}
.tbl-btn{font-family:var(--mono);font-size:.55rem;padding:2px 7px;border-radius:2px;cursor:pointer;border:1px solid var(--b1);color:var(--t2);background:transparent;transition:all .1s}
.tbl-btn:hover{border-color:var(--cy2);color:var(--cy)}
.tbl-btn.green:hover{border-color:var(--gn);color:var(--gn)}
.tbl-btn.red:hover{border-color:var(--rd);color:var(--rd)}
.upload-zone{border:1px dashed var(--b2);border-radius:3px;padding:8px 12px;text-align:center;font-size:.62rem;color:var(--t3);cursor:pointer;margin-top:6px;transition:all .12s}
.upload-zone:hover{border-color:var(--cy2);color:var(--t2)}
.kv-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.kv-row{display:contents}
.kv-key{font-family:var(--mono);font-size:.62rem;color:var(--t2);padding:4px 6px;background:var(--bg3);border-radius:2px;align-self:center}
.kv-val{background:var(--bg3);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:.65rem;padding:3px 7px;border-radius:2px;outline:none}
.kv-val:focus{border-color:var(--cy2)}
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

/* Pinned region popup panels */
.rpin{position:absolute;background:rgba(5,12,24,.97);border:1px solid var(--cy2);border-radius:5px;min-width:200px;max-width:260px;box-shadow:0 4px 24px rgba(0,229,255,.18);cursor:default;backdrop-filter:blur(10px)}
.rpin-hdr{display:flex;align-items:center;gap:6px;padding:7px 10px;border-bottom:1px solid var(--b1);cursor:move;user-select:none}
.rpin-title{font-family:var(--mono);font-size:.72rem;color:var(--cy);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpin-sub{font-family:var(--mono);font-size:.55rem;color:var(--t3)}
.rpin-x{background:none;border:none;color:var(--t3);cursor:pointer;font-size:.8rem;padding:0 2px;line-height:1;flex-shrink:0;transition:color .1s}
.rpin-x:hover{color:var(--rd)}
.rpin-body{padding:7px 10px 4px}
.rprow{display:flex;justify-content:space-between;gap:8px;margin-bottom:3px;font-size:.65rem}
.rpk{color:var(--t2)}
.rpv{font-family:var(--mono);color:var(--t1)}
.rpin-spark{width:100%;display:block;border-top:1px solid var(--b1);padding:4px 0}

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
      <div class="tab" data-tab="settings">⚙ SETTINGS</div>
    </div>
    <div id="run-area">
      <span id="run-txt">no result yet</span>
      <div id="run-prog"><div id="run-prog-bar"></div></div>
      <button id="run-btn" onclick="startRun()">INIT</button>
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
        <button class="tb fork-btn" id="tb-fork" onclick="openForkDialog()" title="Fork simulation from current step">⑂ Fork</button>
        <div id="branch-sel-wrap" style="display:none">
          <select id="branch-sel" onchange="activateBranch(this.value)" style="background:#142540;color:#00e5ff;border:1px solid #1e3a5f;border-radius:3px;font-size:.6rem;padding:2px 4px;font-family:var(--mono)">
            <option value="main">● main</option>
          </select>
        </div>
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
    <div class="panel" id="panel-settings"></div>
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
  if(t.dataset.tab==='settings') renderSettings();
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
    toast('Ready — press INIT to build simulation frames');
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
  // autoplay disabled — use Play button
  if(document.querySelector('#panel-dash.active'))buildDashboard();
}

// ── Leaflet map ───────────────────────────────────────────────────────────────
let lmap,vlayer,rmarks={},nmarks={},vmarks={};

function initMap(){
  if(lmap)return;
  const s=uiSettings();
  lmap=L.map('map',{center:[+(s.map_center_lat||20),+(s.map_center_lon||20)],
    zoom:+(s.map_zoom||2),zoomControl:true,attributionControl:false,minZoom:2,maxZoom:6,
    worldCopyJump:true});
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
      const gateLbl = (c.is_gateway?'⬦ ':'◦ ') + (c.label||name);
      nmarks[name]=L.marker([c.lat,c.lon],{icon:nodeIcon(c,true)})
        .bindTooltip(gateLbl,{className:'leaflet-tooltip',sticky:false})
        .addTo(lmap);
    });
  // Region pins: hover for tooltip, click to pin popup panel
  if(s.show_region_pins!=='false')
    Object.entries(SIM.regions).forEach(([name,c])=>{
      const m=L.marker([c.lat,c.lon],{icon:regionIcon(name,SIM.steps[0],c)}).addTo(lmap);
      m.on('mouseover',e=>showHoverTip(name,e,c));
      m.on('mouseout',()=>{$('rpop').style.display='none'});
      m.on('click',e=>pinRegionPanel(name,c));
      rmarks[name]=m;
    });
}

function nodeIcon(c,open){
  const col=open?(c.color_open||'#ffd23f'):(c.color_closed||'#ff3860');
  const isGate=c.is_gateway||c.icon_shape==='diamond';
  if(isGate){
    // Diamond shape for gateways — rotate a square 45deg
    const sz=open?14:12; const shadow=open?`0 0 10px ${col}99`:`0 0 6px ${col}`;
    return L.divIcon({className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2],
      html:`<div style="width:${sz}px;height:${sz}px;transform:rotate(45deg);border:2px solid ${col};background:${col}${open?'22':'55'};box-shadow:${shadow}"></div>`});
  }
  // Circle for secondary chokepoints
  return L.divIcon({className:'',iconSize:[9,9],iconAnchor:[4,4],
    html:`<div style="width:9px;height:9px;border-radius:50%;border:1.5px solid ${col};background:${col}18;box-shadow:0 0 5px ${col}66"></div>`});
}

function regionIcon(name,sd,coords){
  const rd=(sd.regions||{})[name]||{};
  const ratio=rd.supply>0?rd.demand/rd.supply:0;
  // Colour pulse: green=balanced, amber=tight, red=shortage
  const col=ratio>1.1?'#ff3860':ratio>0.85?'#39ff14':'#ffd23f';
  const r=6;
  return L.divIcon({className:'',iconSize:[r*2,r*2],iconAnchor:[r,r],
    html:`<div title="${coords.label||name}" style="width:${r*2}px;height:${r*2}px;border-radius:50%;
      border:1.5px solid ${col};background:${col}28;
      box-shadow:0 0 6px ${col}88;cursor:pointer;transition:box-shadow .2s"
      onmouseenter="this.style.boxShadow='0 0 12px ${col}'"
      onmouseleave="this.style.boxShadow='0 0 6px ${col}88'"></div>`});
}

function showHoverTip(name,e,coords){
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
  updateFleet(sd);updateSD(sd);updateSpark(step);updateAllPinnedPanels();
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

// ═══════════════════════════════════════════════════════════════════════════
// SETTINGS TAB
// ═══════════════════════════════════════════════════════════════════════════
let dataCfg=null;

async function renderSettings(){
  const panel=document.getElementById('panel-settings');
  panel.innerHTML='<div style="padding:20px;font-family:var(--mono);font-size:.7rem;color:var(--t2)">Loading…</div>';
  try{ dataCfg=await fetch('/api/data_config').then(r=>r.json()); }
  catch(e){ panel.innerHTML='<div style="padding:20px;color:var(--rd)">Error: '+e.message+'</div>'; return; }

  panel.innerHTML=`
    <div class="st-card">
      <h3>📁 DATA DIRECTORY</h3>
      <p>CSV files in this folder override built-in templates. Leave blank to auto-discover <code style="color:var(--cy)">./data/</code> next to portal.py. Apply reloads all tables.</p>
      <div class="dir-row">
        <input class="dir-input" id="dir-input" placeholder="/path/to/your/data  or  ./data" value="${dataCfg.data_dir||''}">
        <button class="st-btn" onclick="applyDataDir()">Apply &amp; Reload All</button>
        <button class="st-btn" onclick="exportAllCSV()">⬇ Export all CSVs</button>
      </div>
      <div id="dir-status" style="font-family:var(--mono);font-size:.6rem;color:var(--t3)">
        ${dataCfg.data_dir?'✓ Using: '+dataCfg.data_dir:'Using built-in templates — no data dir configured'}
      </div>
    </div>
    <div class="st-card">
      <h3>📊 TABLE SOURCES  <span style="color:var(--t3);font-size:.62rem">${dataCfg.tables.length} tables</span></h3>
      <p>Download any table as CSV, upload your own CSV to replace it, save the current in-browser edits to a file, or reset to the built-in template.</p>
      <div style="margin-bottom:8px;font-family:var(--mono);font-size:.58rem">
        <span style="color:var(--gn)">■</span> from CSV &nbsp; <span style="color:var(--t3)">■</span> built-in template &nbsp; <span style="color:var(--am)">■</span> uploaded
      </div>
      <div class="table-grid" id="table-grid"></div>
    </div>
    <div class="st-card">
      <h3>🎨 UI SETTINGS  <span style="color:var(--t3);font-size:.62rem">portal_settings table</span></h3>
      <p>These control map center, animation speed, accent colour etc. Saved to the portal_settings table and take effect on next reload.</p>
      <div class="kv-grid" id="settings-kv"></div>
      <button class="st-btn" style="margin-top:10px" onclick="savePortalSettings()">💾 Save</button>
    </div>`;
  renderTableGrid(); renderSettingsKV();
}

function renderTableGrid(){
  if(!dataCfg) return;
  const grid=document.getElementById('table-grid');
  if(!grid) return;
  grid.innerHTML=dataCfg.tables.map(t=>{
    const st=t.source.startsWith('csv')?'csv':t.source==='upload'?'upload':'template';
    const sl=st==='csv'?'📄 '+t.source.replace('csv:',''):st==='upload'?'⬆ uploaded this session':'⬡ built-in template';
    return `<div class="tbl-card" id="tc-${t.name}">
      <div class="tbl-name">${t.name}</div>
      <div class="tbl-src ${st}">${sl}</div>
      <div class="tbl-rows">${t.rows} rows</div>
      <div class="tbl-actions">
        <button class="tbl-btn" onclick="downloadTable('${t.name}')">⬇ CSV</button>
        <button class="tbl-btn" onclick="uploadTable('${t.name}')">⬆ Upload</button>
        <button class="tbl-btn" onclick="saveTableToFile('${t.name}')">💾 Save to file</button>
        ${t.has_template?`<button class="tbl-btn red" onclick="resetTable('${t.name}')">↺ Reset</button>`:''}
      </div>
      <div class="upload-zone" onclick="triggerUpload('${t.name}')"
           ondragover="event.preventDefault()" ondrop="handleDrop(event,'${t.name}')">
        drop CSV here or click
      </div>
      <input type="file" accept=".csv" style="display:none" id="fi-${t.name}" onchange="handleFileInput(this,'${t.name}')">
    </div>`;
  }).join('');
}

function renderSettingsKV(){
  const rows=tables.portal_settings||[];
  const kv=document.getElementById('settings-kv');
  if(!kv) return;
  kv.innerHTML=rows.map((r,i)=>`
    <div class="kv-key" title="${r.description||''}">${r.key}<span style="display:block;font-size:.52rem;color:var(--t3)">${r.group||''}</span></div>
    <input class="kv-val" id="kv-${i}" value="${r.value!=null?r.value:''}" placeholder="${r.description||''}">
  `).join('');
}

async function savePortalSettings(){
  const rows=tables.portal_settings||[];
  rows.forEach((r,i)=>{const el=document.getElementById('kv-'+i);if(el)r.value=el.value;});
  tables.portal_settings=rows;
  await fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'portal_settings',rows})});
  toast('✓ UI settings saved');
}

async function applyDataDir(){
  const val=document.getElementById('dir-input').value.trim();
  const ds=document.getElementById('dir-status');
  ds.textContent='Applying…'; ds.style.color='var(--t3)';
  const r=await fetch('/api/set_data_dir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data_dir:val})}).then(r=>r.json()).catch(e=>({error:e.message}));
  if(r.error){ds.textContent='✗ '+r.error;ds.style.color='var(--rd)';return;}
  tables=await fetch('/api/tables').then(r=>r.json());
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  ds.textContent='✓ Loaded '+r.loaded+' tables from: '+(r.data_dir||'built-in templates');
  ds.style.color='var(--gn)';
  renderTableGrid(); buildConfigNav();
  toast('✓ '+r.loaded+' tables reloaded');
}

function downloadTable(name){window.location.href='/api/download_table/'+name;}

async function saveTableToFile(name){
  const r=await fetch('/api/save_table_csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).then(r=>r.json());
  if(r.error){toast('✗ '+r.error);return;}
  toast('✓ Saved → '+r.path);
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  renderTableGrid();
}

async function resetTable(name){
  if(!confirm('Reset "'+name+'" to built-in template? Unsaved changes lost.'))return;
  const r=await fetch('/api/reset_table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).then(r=>r.json());
  tables=await fetch('/api/tables').then(r=>r.json());
  dataCfg=await fetch('/api/data_config').then(r=>r.json());
  renderTableGrid();
  toast('↺ '+name+' reset ('+r.rows+' rows)');
}

function uploadTable(name){document.getElementById('fi-'+name)?.click();}
function triggerUpload(name){document.getElementById('fi-'+name)?.click();}

function handleFileInput(input,name){
  const f=input.files[0]; if(!f)return;
  uploadCSVFile(name,f); input.value='';
}
function handleDrop(e,name){
  e.preventDefault(); const f=e.dataTransfer.files[0]; if(f)uploadCSVFile(name,f);
}

async function uploadCSVFile(name,file){
  const text=await file.text();
  try{
    const r=await fetch('/api/upload_csv?table='+encodeURIComponent(name),{
      method:'POST',headers:{'Content-Type':'text/plain'},body:text
    }).then(r=>r.json());
    if(r.error){toast('✗ '+r.error);return;}
    tables=await fetch('/api/tables').then(r=>r.json());
    dataCfg=await fetch('/api/data_config').then(r=>r.json());
    renderTableGrid(); buildConfigNav();
    toast('✓ '+name+': '+r.rows+' rows loaded from file');
  }catch(e){toast('✗ Upload failed: '+e.message);}
}

async function exportAllCSV(){
  const names=(dataCfg?.tables||[]).map(t=>t.name);
  for(const n of names){
    const a=document.createElement('a');a.href='/api/download_table/'+n;a.download=n+'.csv';a.click();
    await new Promise(r=>setTimeout(r,200));
  }
  toast('⬇ Downloading '+names.length+' CSV files…');
}


// ── Pinned region popup panels ────────────────────────────────────────────
const pinnedPanels = {};

function pinRegionPanel(name, coords) {
  if (pinnedPanels[name]) {
    // Already open — bring to front
    pinnedPanels[name].style.zIndex = nextZ();
    return;
  }
  if (!SIM) return;
  const el = document.createElement('div');
  el.className = 'rpin';
  el.id = 'rpin-'+name;
  el.style.cssText = `position:absolute;z-index:${nextZ()};left:${80+Object.keys(pinnedPanels).length*24}px;top:${60+Object.keys(pinnedPanels).length*24}px`;
  el.innerHTML = buildPinContent(name, coords, SIM.steps[step]);
  // Make draggable
  makeDraggable(el);
  $('map').parentElement.style.position='relative';
  $('map').parentElement.appendChild(el);
  pinnedPanels[name] = el;
  updatePinnedPanel(name);
}

let _zCounter = 2100;
function nextZ(){ return ++_zCounter; }

function buildPinContent(name, coords, sd) {
  const rd = (sd.regions||{})[name]||{};
  const fields = (coords.popup_fields||'supply,demand,storage').split(',');
  const dsRatio = rd.supply>0 ? (rd.demand/rd.supply).toFixed(3) : '—';
  const bal = rd.supply - rd.demand;
  const balCol = bal>=0?'#39ff14':'#ff3860';
  const rows = fields.map(f=>
    `<div class="rprow"><span class="rpk">${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`
  ).join('');
  return `
    <div class="rpin-hdr">
      <span class="rpin-title">${coords.label||name}</span>
      <span class="rpin-sub">${name}</span>
      <button class="rpin-x" onclick="closePin('${name}')">✕</button>
    </div>
    <div class="rpin-body" id="rpinb-${name}">
      ${rows}
      <div class="rprow"><span class="rpk">D/S ratio</span><span class="rpv">${dsRatio}</span></div>
      <div class="rprow"><span class="rpk">Balance</span><span class="rpv" style="color:${balCol}">${bal>=0?'+':''}${bal.toFixed(2)} MMT</span></div>
    </div>
    <canvas class="rpin-spark" id="rpinspark-${name}" height="40"></canvas>`;
}

function updatePinnedPanel(name) {
  if (!SIM || !pinnedPanels[name]) return;
  const coords = SIM.regions[name]; if(!coords) return;
  const sd = SIM.steps[step];
  const rd = (sd.regions||{})[name]||{};
  const fields = (coords.popup_fields||'supply,demand,storage').split(',');
  const dsRatio = rd.supply>0 ? (rd.demand/rd.supply).toFixed(3) : '—';
  const bal = rd.supply - rd.demand;
  const balCol = bal>=0?'#39ff14':'#ff3860';
  const rows = fields.map(f=>
    `<div class="rprow"><span class="rpk">${f}</span><span class="rpv">${(rd[f]||0).toFixed(2)} MMT</span></div>`
  ).join('');
  const bodyEl = document.getElementById('rpinb-'+name);
  if(bodyEl) bodyEl.innerHTML = rows +
    `<div class="rprow"><span class="rpk">D/S ratio</span><span class="rpv">${dsRatio}</span></div>
     <div class="rprow"><span class="rpk">Balance</span><span class="rpv" style="color:${balCol}">${bal>=0?'+':''}${bal.toFixed(2)} MMT</span></div>`;
  // Spark — supply history for this region
  const cvs = document.getElementById('rpinspark-'+name);
  if(cvs) {
    const ctx=cvs.getContext('2d'), dpr=devicePixelRatio||1;
    cvs.width=cvs.offsetWidth*dpr; cvs.height=40*dpr; ctx.scale(dpr,dpr);
    const W=cvs.offsetWidth, H=40;
    const vals = SIM.steps.slice(0,step+1).map(s=>(s.regions||{})[name]?.supply||0);
    const mn=Math.min(...vals),mx=Math.max(...vals),rng=mx-mn||1;
    ctx.clearRect(0,0,W,H);
    // Supply line (green)
    ctx.strokeStyle='#39ff14'; ctx.lineWidth=1.2; ctx.beginPath();
    vals.forEach((v,i)=>{const x=(i/(vals.length-1||1))*W,y=H-((v-mn)/rng)*(H-4)-2;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
    // Demand line (amber)
    const dvals = SIM.steps.slice(0,step+1).map(s=>(s.regions||{})[name]?.demand||0);
    ctx.strokeStyle='#ffd23f'; ctx.lineWidth=1; ctx.beginPath();
    dvals.forEach((v,i)=>{const x=(i/(dvals.length-1||1))*W,y=H-((v-mn)/rng)*(H-4)-2;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
  }
}

function updateAllPinnedPanels() {
  Object.keys(pinnedPanels).forEach(name=>updatePinnedPanel(name));
}

function closePin(name) {
  if(pinnedPanels[name]) {
    pinnedPanels[name].remove();
    delete pinnedPanels[name];
  }
}

function makeDraggable(el) {
  let ox,oy,mx,my,dragging=false;
  el.querySelector('.rpin-hdr').addEventListener('mousedown',e=>{
    if(e.target.classList.contains('rpin-x')) return;
    dragging=true; ox=el.offsetLeft; oy=el.offsetTop; mx=e.clientX; my=e.clientY;
    el.style.zIndex=nextZ();
    e.preventDefault();
  });
  document.addEventListener('mousemove',e=>{
    if(!dragging) return;
    el.style.left=(ox+e.clientX-mx)+'px';
    el.style.top=(oy+e.clientY-my)+'px';
  });
  document.addEventListener('mouseup',()=>{dragging=false;});
}

init();

// ── Fork / Branch system ──────────────────────────────────────────────────────

/* CSS injected inline */
(function(){
  const s=document.createElement('style');
  s.textContent=`
  #fork-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:4000;align-items:center;justify-content:center}
  #fork-modal.open{display:flex}
  #fork-box{background:#050c18;border:1px solid #1e3a5f;border-radius:6px;padding:20px 24px;min-width:340px;max-width:480px;font-family:var(--mono);color:var(--t1)}
  #fork-box h3{margin:0 0 14px;color:#00e5ff;font-size:.85rem;letter-spacing:.05em}
  .fp{margin-bottom:10px}
  .fp label{display:block;font-size:.6rem;color:#7a9abb;margin-bottom:3px}
  .fp input,.fp select{width:100%;background:#0a1628;border:1px solid #1e3a5f;color:var(--t1);
    border-radius:3px;padding:5px 8px;font-family:var(--mono);font-size:.7rem;box-sizing:border-box}
  .fp .fp-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  #fork-actions{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
  #fork-actions button{padding:6px 14px;border-radius:3px;font-family:var(--mono);font-size:.68rem;cursor:pointer;border:none}
  #fork-go{background:#00e5ff;color:#050c18;font-weight:700}
  #fork-cancel{background:#142540;color:#7a9abb;border:1px solid #1e3a5f}
  #branch-panel{position:fixed;right:12px;top:50%;transform:translateY(-50%);
    background:#050c18;border:1px solid #1e3a5f;border-radius:5px;z-index:1200;
    min-width:200px;max-width:240px;display:none;font-family:var(--mono)}
  #branch-panel.open{display:block}
  #branch-panel-hdr{padding:7px 10px;color:#00e5ff;font-size:.65rem;letter-spacing:.05em;
    border-bottom:1px solid #1e3a5f;display:flex;justify-content:space-between;align-items:center}
  .br-item{padding:6px 10px;border-bottom:1px solid #0d1f3a;cursor:pointer;transition:background .15s}
  .br-item:hover{background:#0a1628}
  .br-item.active{background:#0a1f3a;border-left:3px solid #00e5ff}
  .br-name{font-size:.65rem;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .br-meta{font-size:.55rem;color:#7a9abb;margin-top:2px}
  .br-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;flex-shrink:0}
  .br-row{display:flex;align-items:center}
  .br-del{margin-left:auto;padding:1px 5px;background:transparent;border:none;color:#ff3860;
    cursor:pointer;font-size:.7rem;opacity:.5;transition:opacity .15s}
  .br-del:hover{opacity:1}
  .fork-btn{background:#1e3a5f!important;color:#00e5ff!important;font-size:.6rem!important;padding:3px 8px!important}
  #branch-toggle{padding:3px 8px;background:#1e3a5f;color:#00e5ff;border:1px solid #2a4a7f;
    border-radius:3px;font-family:var(--mono);font-size:.58rem;cursor:pointer;margin-left:6px}
  .br-prog{height:2px;background:#142540;margin-top:3px;border-radius:1px;overflow:hidden}
  .br-prog-fill{height:100%;background:#00e5ff;transition:width .3s}
  `;
  document.head.appendChild(s);
})();

// Fork dialog
let forkOverrides = {};

function openForkDialog(){
  if(!SIM){toast('Run simulation first');return;}
  $('fork-step-val').value = step;
  $('fork-name').value = 'Branch @step '+step;
  // Reset overrides
  ['fork-spot','fork-wti','fork-vlsfo','fork-scrapping'].forEach(id=>{
    const el=$B(id); if(el) el.value='';
  });
  $('fork-modal').classList.add('open');
}
function closeForkDialog(){$('fork-modal').classList.remove('open');}

async function submitFork(){
  const forkStep = parseInt($('fork-step-val').value)||step;
  const name     = $('fork-name').value || ('Branch @'+forkStep);
  const cfg = {};
  const spot = parseFloat($('fork-spot').value);    if(!isNaN(spot))   cfg.base_spot_rate=spot;
  const wti  = parseFloat($('fork-wti').value);     if(!isNaN(wti))    cfg.wti_price=wti;
  const vlsfo= parseFloat($('fork-vlsfo').value);   if(!isNaN(vlsfo))  cfg.fuel_vlsfo=vlsfo;
  const scrap= parseFloat($('fork-scrapping').value);if(!isNaN(scrap)) cfg.scrapping_threshold=scrap;
  const n    = parseInt($('fork-nperiods').value);   if(!isNaN(n))      cfg.n_periods=n;
  closeForkDialog();
  toast('Forking simulation from step '+forkStep+'…');
  const r = await fetch('/api/branch/create',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({fork_step:forkStep, fork_branch_id:'main', name, config:cfg})});
  const d = await r.json();
  if(d.error){toast('Fork error: '+d.error);return;}
  $('branch-sel-wrap').style.display='';
  $('branch-panel').classList.add('open');
  pollBranches();
}

async function activateBranch(bid){
  await fetch('/api/branch/activate',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({branch_id:bid})});
  SIM=null; step=0;
  const r=await fetch('/api/result'); if(!r.ok)return;
  SIM=await r.json();
  if(SIM&&SIM.steps){
    $('scrubber').max=SIM.steps.length-1;
    renderStep(step);
    renderInitMap();
  }
  toast(bid==='main'?'Showing main run':'Showing '+bid);
}

async function deleteBranch(bid){
  if(!confirm('Delete branch '+bid+'?'))return;
  await fetch('/api/branch/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({branch_id:bid})});
  refreshBranchPanel();
  if($('branch-sel').value===bid) activateBranch('main');
}

let _branchPoll=null;
function pollBranches(){
  if(_branchPoll)clearInterval(_branchPoll);
  _branchPoll=setInterval(async()=>{
    await refreshBranchPanel();
    const any=Object.values(await (await fetch('/api/branches')).json().then(d=>d.branches||[])).some(b=>b.status==='running');
    if(!any){clearInterval(_branchPoll);_branchPoll=null;}
  },1200);
}

async function refreshBranchPanel(){
  const resp=await fetch('/api/branches');
  const data=await resp.json();
  const branches=data.branches||[];
  const active=data.active||'main';

  // Update selector
  const sel=$('branch-sel');
  const prevVal=sel.value;
  sel.innerHTML='<option value="main">● main</option>';
  branches.forEach(b=>{
    const o=document.createElement('option');
    o.value=b.id;
    o.textContent=(b.status==='running'?'⟳ ':b.status==='error'?'✗ ':'⑂ ')+b.name;
    sel.appendChild(o);
  });
  sel.value=active||'main';

  // Update panel
  const list=$('branch-list');
  list.innerHTML='';
  if(branches.length===0){
    list.innerHTML='<div style="padding:8px 10px;font-size:.58rem;color:#7a9abb">No branches yet.<br>Click ⑂ Fork to create one.</div>';
    return;
  }
  branches.forEach(b=>{
    const isActive=(b.id===active);
    const div=document.createElement('div');
    div.className='br-item'+(isActive?' active':'');
    const progHtml=b.status==='running'?
      `<div class="br-prog"><div class="br-prog-fill" style="width:${b.progress}%"></div></div>`:'';
    div.innerHTML=`<div class="br-row">
      <span class="br-dot" style="background:${b.color}"></span>
      <span class="br-name">${b.name}</span>
      <button class="br-del" onclick="deleteBranch('${b.id}')" title="Delete">✕</button>
    </div>
    <div class="br-meta">⑂ step ${b.fork_step} · ${b.status}${b.status==='running'?' '+b.progress+'%':''}</div>
    ${progHtml}`;
    div.onclick=e=>{if(e.target.classList.contains('br-del'))return;activateBranch(b.id);};
    list.appendChild(div);
  });
  if(branches.length>0) $('branch-sel-wrap').style.display='';
}

function $B(id){return document.getElementById(id);}

// Chart overlay: draw fork marker
const _origDrawChart=drawChart;
function drawChart(cfg,steps,canvasId){
  _origDrawChart(cfg,steps,canvasId);
  // Draw fork lines for all branches
  fetch('/api/branches').then(r=>r.json()).then(data=>{
    const branches=data.branches||[];
    branches.forEach(b=>{
      const canvas=$B(canvasId);
      if(!canvas)return;
      const ctx=canvas.getContext('2d');
      const n=steps.length;
      if(n<2)return;
      const x=Math.round((b.fork_step/Math.max(n-1,1))*canvas.width);
      ctx.save();
      ctx.strokeStyle=b.color;ctx.lineWidth=1;ctx.setLineDash([3,3]);
      ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle=b.color;ctx.font='9px monospace';
      ctx.fillText('⑂',x+2,12);
      ctx.restore();
    });
  }).catch(()=>{});
}
</script>

<!-- Fork dialog modal -->
<div id="fork-modal">
  <div id="fork-box">
    <h3>⑂ Fork Simulation</h3>
    <div class="fp">
      <label>Branch name</label>
      <input id="fork-name" type="text" placeholder="Branch @step N">
    </div>
    <div class="fp">
      <label>Fork from step</label>
      <input id="fork-step-val" type="number" min="0">
    </div>
    <div class="fp"><label>Parameter overrides (leave blank to inherit)</label>
      <div class="fp-row">
        <div><label>Spot rate ($/day)</label><input id="fork-spot" type="number" placeholder="inherit"></div>
        <div><label>WTI price ($/bbl)</label><input id="fork-wti" type="number" placeholder="inherit"></div>
        <div><label>VLSFO ($/t)</label><input id="fork-vlsfo" type="number" placeholder="inherit"></div>
        <div><label>Scrapping threshold</label><input id="fork-scrapping" type="number" placeholder="inherit"></div>
        <div><label>n_periods (total)</label><input id="fork-nperiods" type="number" placeholder="inherit"></div>
      </div>
    </div>
    <div id="fork-actions">
      <button id="fork-cancel" onclick="closeForkDialog()">Cancel</button>
      <button id="fork-go" onclick="submitFork()">Run Fork →</button>
    </div>
  </div>
</div>

<!-- Branch panel (right side) -->
<div id="branch-panel">
  <div id="branch-panel-hdr">
    <span>⑂ BRANCHES</span>
    <button onclick="$('branch-panel').classList.remove('open')" style="background:none;border:none;color:#7a9abb;cursor:pointer;font-size:.8rem">✕</button>
  </div>
  <div id="branch-list"></div>
</div>

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
    resolved = _resolve_data_dir(args.data)

    print(f"\n{'═'*56}\n  ⬡  Maritime Fleet Simulation Portal  v3\n{'═'*56}")
    print(f"  Loading tables...")
    init_tables(data_dir=resolved)
    print(f"  http://{args.host}:{args.port}\n{'═'*56}\n")
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
