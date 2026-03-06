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
