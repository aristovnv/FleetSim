#!/usr/bin/env python3
"""Simulation task runners and conflict-rule helpers."""
import sys, os, json, math, copy, random, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from core.enums import Granularity
from core.models import SimConfig
from config.schemas import (
    load_regions, load_companies, load_ship_types, load_nodes,
    load_edges, load_constraints, load_orderbook,
    load_vessel_groups, load_vessel_group_members,
)
from core.engine import SimulationRunner

from .shared import (
    STATE, DATA_DIR, _clean, safe_json,
    get_table, rows_to_df, df_to_rows,
)

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

def build_owner_supply_routes(route_index: dict) -> dict:
    """
    {owner: [route_key, ...]} — routes that START from that owner's supply regions.
    Derived from companies.supply_regions vs route_index[key]['from'].
    Falls back to all routes if no match found.
    """
    # company → supply regions
    company_supply: dict = {}
    for r in get_table("companies"):
        name = str(r.get("name") or "").strip()
        srs  = [x.strip() for x in str(r.get("supply_regions") or "").split(",") if x.strip()]
        if name and srs:
            company_supply[name] = set(srs)

    # owner (from fleet) → supply regions (via companies table)
    owner_supply: dict = {}
    for r in get_table("fleet"):
        owner = str(r.get("owner") or "").strip()
        if owner and owner in company_supply:
            owner_supply.setdefault(owner, set()).update(company_supply[owner])

    # build route lists per owner
    all_keys = list(route_index.keys())
    result: dict = {}
    for owner, supply_regions in owner_supply.items():
        keys = [k for k, v in route_index.items() if v.get("from") in supply_regions]
        result[owner] = keys if keys else all_keys
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
        owner_routes = build_owner_supply_routes(route_index)
        rng = random.Random(int(run_cfg.get("seed", 42)))

        # v3 engine uses vessels_{vessel_id} columns
        type_cols = [c for c in df.columns
                     if c.startswith("vessels_")]
        # Fall back to v2 active_ columns if vessels_ not present
        if not type_cols:
            type_cols = [c for c in df.columns
                         if c.startswith("active_") and c != "active_constraints"]
        col_prefix = "vessels_" if type_cols and type_cols[0].startswith("vessels_") else "active_"

        def pick_route(owner: str, vid: int) -> str:
            """Pick a route for this vessel based on owner's supply regions."""
            keys = owner_routes.get(owner) or route_keys
            if not keys:
                return ""
            return keys[vid % len(keys)]

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
                    route_key=pick_route(owner, vid),
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
                            route_key=pick_route(owner, vid),
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

        # Build per-step flow counts: {from→to: {group: count, dwt_kt: total}}
        # We have vessel list at each step - aggregate by route from/to
        ship_type_dwt = {}
        for r in get_table("ship_types"):
            if r.get("name"):
                ship_type_dwt[r["name"]] = float(r.get("dwt_mean") or 0) / 1000  # in kt

        steps = []
        region_names = list(region_coords.keys())
        node_names   = list(node_coords.keys())

        for step_i, (_, row) in enumerate(df.iterrows()):
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

            # Flows: count active vessels per (from_region, to_region) pair
            flows = {}
            if step_i < len(frames):
                frame_ids = {v["id"] for v in frames[step_i]}
                for v in vessels:
                    if v["id"] not in frame_ids:
                        continue
                    rt = route_index.get(v["route_key"], {})
                    fr = rt.get("from", ""); to = rt.get("to", "")
                    if fr and to:
                        key = f"{fr}→{to}"
                        if key not in flows:
                            flows[key] = {"count": 0, "dwt_kt": 0, "groups": {}}
                        flows[key]["count"] += 1
                        flows[key]["dwt_kt"] = round(
                            flows[key]["dwt_kt"] + ship_type_dwt.get(v["type"], 0), 0)
                        g = v["group"]
                        flows[key]["groups"][g] = flows[key]["groups"].get(g, 0) + 1

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
                route_throughput = round(float(row.get("route_throughput_factor", 1.0)), 4),
                constraints   = str(row.get("active_constraints") or ""),
                fleet         = fleet_bd,
                regions       = regions_data,
                nodes         = nodes_data,
                flows         = flows,
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



