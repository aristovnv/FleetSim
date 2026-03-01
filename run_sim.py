#!/usr/bin/env python3
"""
Maritime Simulation v2 — quick start / smoke test.

Usage:
    python run_sim.py                         # monthly, 5 years, defaults
    python run_sim.py --granularity quarterly # quarterly steps
    python run_sim.py --hormuz               # trigger Hormuz closure at day 30
    python run_sim.py --save-templates        # write all CSVs to ./data/
"""

import sys
import os
# Ensure the sim directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import pandas as pd
import numpy as np

from core.enums import Granularity, ConstraintType
from core.models import SimConfig, ScenarioConstraint
from config.schemas import (
    load_regions, load_companies, load_ship_types, load_nodes,
    load_edges, load_constraints, load_orderbook,
    template_regions, template_region_demand, template_region_supply,
    template_region_storage, template_port_times,
    template_companies, template_ship_types, template_fleet,
    template_orderbook, template_nodes, template_edges, template_constraints,
    save_templates,
)
from core.engine import SimulationRunner


def parse_args():
    p = argparse.ArgumentParser(description="Maritime Fleet Simulation v2")
    p.add_argument("--granularity", choices=["week","month","quarter","year"],
                   default="month")
    p.add_argument("--periods", type=int, default=60,
                   help="Number of simulation steps")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--hormuz", action="store_true",
                   help="Trigger Hormuz closure at day 30 for 14 days")
    p.add_argument("--sanctions", action="store_true",
                   help="Activate Russian sanctions from day 0")
    p.add_argument("--covid", action="store_true",
                   help="Activate COVID demand shock at day 180")
    p.add_argument("--save-templates", action="store_true",
                   help="Write template CSVs to ./data/ and exit")
    p.add_argument("--output", default="results.csv",
                   help="Output CSV filename")
    return p.parse_args()


def build_runner(args) -> SimulationRunner:
    gran = Granularity(args.granularity)
    cfg  = SimConfig(
        granularity=gran,
        n_periods=args.periods,
        random_seed=args.seed,
        start_year=2025,
        start_month=1,
    )

    # --- Load entities from templates (swap for pd.read_csv("...") in production) ---
    data_dir = "./data"
    def _load(template_fn, csv_name):
        path = os.path.join(data_dir, csv_name)
        if os.path.exists(path):
            return pd.read_csv(path)
        return template_fn()

    df_regions     = _load(template_regions,       "regions.csv")
    df_demand      = _load(template_region_demand, "region_demand.csv")
    df_supply      = _load(template_region_supply, "region_supply.csv")
    df_storage     = _load(template_region_storage,"region_storage.csv")
    df_port_times  = _load(template_port_times,    "port_times.csv")
    df_companies   = _load(template_companies,     "companies.csv")
    df_ship_types  = _load(template_ship_types,    "ship_types.csv")
    df_fleet       = _load(template_fleet,         "fleet.csv")
    df_orderbook   = _load(template_orderbook,     "orderbook.csv")
    df_nodes       = _load(template_nodes,         "nodes.csv")
    df_edges       = _load(template_edges,         "edges.csv")
    df_constraints = _load(template_constraints,   "constraints.csv")

    regions    = load_regions(df_regions, df_demand, df_supply, df_storage, df_port_times)
    companies  = load_companies(df_companies)
    ship_types = load_ship_types(df_ship_types)
    nodes      = load_nodes(df_nodes)
    edges      = load_edges(df_edges)
    constraints = load_constraints(df_constraints)
    orderbook  = load_orderbook(df_orderbook, ship_types)

    # --- Scenario overrides from CLI flags ---
    if args.hormuz:
        constraints.append(ScenarioConstraint(
            constraint_id="HORMUZ_CLI",
            constraint_type=ConstraintType.NODE_CLOSURE,
            apply_on_day=30.0,
            end_on_day=44.0,
            description="Hormuz closure triggered from CLI",
            target_nodes=["Strait of Hormuz"],
        ))
        print("⚠  Hormuz closure: day 30 → 44")

    if args.sanctions:
        constraints.append(ScenarioConstraint(
            constraint_id="RU_SANCTION_CLI",
            constraint_type=ConstraintType.SANCTION_SHIP_FLAG,
            apply_on_day=0.0,
            description="Russian sanctions (CLI override, active from day 0)",
            target_companies=["Rosneft"],
            target_regions=["Baltic"],
            multiplier=0.35,
        ))
        print("⚠  Russian sanctions active from day 0")

    if args.covid:
        constraints.append(ScenarioConstraint(
            constraint_id="COVID_CLI",
            constraint_type=ConstraintType.DEMAND_SHOCK,
            apply_on_day=180.0,
            end_on_day=730.0,
            description="COVID demand shock (CLI override)",
            multiplier=0.75,
        ))
        print("⚠  COVID demand shock: day 180 → 730")

    return SimulationRunner(
        config=cfg,
        regions=regions,
        companies=companies,
        ship_types=ship_types,
        fleet_df=df_fleet,
        orderbook_entries=orderbook,
        nodes=nodes,
        edges=edges,
        constraints=constraints,
    )


def print_summary(df: pd.DataFrame, gran: str):
    print(f"\n{'─'*60}")
    print(f"  Simulation complete  |  {gran.upper()}  |  {len(df)} periods")
    print(f"{'─'*60}")
    first, last = df.iloc[0], df.iloc[-1]

    def fmt_delta(col, fmt="{:.0f}"):
        v0, v1 = first[col], last[col]
        delta = v1 - v0
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        return f"{fmt.format(v1)}  {arrow}  ({'+' if delta >= 0 else ''}{fmt.format(delta)})"

    print(f"  Spot rate ($/day)   : {fmt_delta('spot_rate')}")
    print(f"  WTI ($/bbl)         : {fmt_delta('wti_usd_bbl', '{:.2f}')}")
    print(f"  VLSFO ($/t)         : {fmt_delta('vlsfo_usd_t', '{:.1f}')}")
    print(f"  Fleet active        : {fmt_delta('fleet_active', '{:.0f}')}")
    print(f"  Fleet storage (FSO) : {fmt_delta('fleet_storage', '{:.0f}')}")
    print(f"  Orderbook           : {fmt_delta('orderbook', '{:.0f}')}")
    print(f"  S/D ratio           : {fmt_delta('sd_ratio', '{:.3f}')}")
    print(f"  Load factor         : {fmt_delta('load_factor', '{:.3f}')}")
    print(f"{'─'*60}")

    # Spot at min/max
    idx_max = df["spot_rate"].idxmax()
    idx_min = df["spot_rate"].idxmin()
    print(f"  Peak spot  : ${df.loc[idx_max,'spot_rate']:,.0f}/day"
          f"  @ {df.loc[idx_max,'date_label']}")
    print(f"  Trough spot: ${df.loc[idx_min,'spot_rate']:,.0f}/day"
          f"  @ {df.loc[idx_min,'date_label']}")

    # Active constraints in final period
    if df.iloc[-1]["active_constraints"]:
        print(f"  Active constraints (last period):")
        for c in df.iloc[-1]["active_constraints"].split(";"):
            if c: print(f"    · {c}")
    print()


def main():
    args = parse_args()

    if args.save_templates:
        save_templates("./data")
        print("\nTemplate CSVs saved to ./data/")
        print("Edit them then re-run without --save-templates")
        return

    print(f"\nBuilding simulation  [{args.granularity} / {args.periods} periods]")
    runner = build_runner(args)

    print("Running...")
    df = runner.run()

    print_summary(df, args.granularity)

    df.to_csv(args.output, index=False)
    print(f"Results saved → {args.output}  ({len(df)} rows × {len(df.columns)} cols)\n")

    # Show a few key rows
    display_cols = ["date_label","spot_rate","wti_usd_bbl","fleet_active",
                    "fleet_storage","orderbook","sd_ratio","load_factor",
                    "active_constraints"]
    display_cols = [c for c in display_cols if c in df.columns]
    step = max(1, len(df) // 8)
    print(df[display_cols].iloc[::step].to_string(index=False))
    print()


if __name__ == "__main__":
    main()
