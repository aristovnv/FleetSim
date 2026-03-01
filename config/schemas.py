"""
DataFrame schemas and CSV loaders for Maritime Fleet Simulation v2.

Every configurable entity has:
  1. A SCHEMA dict   - {column_name: (dtype, description, default)}
  2. A load_*()      - reads a CSV / DataFrame and returns the typed entity dict
  3. A template_*()  - returns an empty template DataFrame with columns + types

Usage pattern:
    df = pd.read_csv("regions.csv")
    regions = load_regions(df)
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Any

from core.models import (
    MeanStd, GrowthRate, SeasonalCoeff, Region, CompanyVolume,
    StorageSlot, PortTime, OilCompany, ShipGroupType, ShipType,
    OrderbookEntry, ScenarioConstraint, SimConfig, Product, ProductMix,
    Node, Edge
)
from core.enums import (
    Granularity, ShipCountry, VesselStatus, NodeType,
    ProductType, ConstraintType
)

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _get(row: pd.Series, col: str, default=None):
    """Safe column accessor with default."""
    if col in row.index and pd.notna(row[col]):
        return row[col]
    return default

def _ms(row, mean_col, std_col, default_mean=0.0, default_std=0.0) -> MeanStd:
    return MeanStd(
        mean=float(_get(row, mean_col, default_mean)),
        std=float(_get(row, std_col, default_std)),
    )

def _seasonal(row, prefix="season") -> SeasonalCoeff:
    """Read season_1 .. season_12 columns; default 1.0."""
    return SeasonalCoeff([
        float(_get(row, f"{prefix}_{m}", 1.0)) for m in range(1, 13)
    ])


# ══════════════════════════════════════════════════════════════════════════════
# 1.  PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

PRODUCT_SCHEMA = {
    # col_name          : (dtype,   description,                         default)
    "name"              : (str,    "Unique product identifier (e.g. WTI)",  None),
    "product_type"      : (str,    "ProductType enum name",          "crude_oil"),
    "energy_density"    : (float,  "GJ per metric tonne",                  42.0),
    "api_gravity"       : (float,  "API gravity (crude quality proxy)",     None),
    "sulfur_pct"        : (float,  "Sulfur content %",                      None),
}

def template_products() -> pd.DataFrame:
    rows = [
        dict(name="WTI",   product_type="crude_oil",   energy_density=42.0, api_gravity=39.6, sulfur_pct=0.24),
        dict(name="Brent", product_type="crude_oil",   energy_density=42.0, api_gravity=38.3, sulfur_pct=0.37),
        dict(name="Urals", product_type="crude_oil",   energy_density=41.5, api_gravity=31.0, sulfur_pct=1.30),
        dict(name="Arab Heavy", product_type="crude_oil", energy_density=41.0, api_gravity=27.7, sulfur_pct=2.85),
        dict(name="VLSFO", product_type="fuel_oil",    energy_density=40.5, api_gravity=None, sulfur_pct=0.50),
        dict(name="HFO",   product_type="fuel_oil",    energy_density=40.0, api_gravity=None, sulfur_pct=3.50),
    ]
    return pd.DataFrame(rows)

def load_products(df: pd.DataFrame) -> Dict[str, Product]:
    out = {}
    for _, row in df.iterrows():
        p = Product(
            name=str(row["name"]),
            product_type=ProductType(_get(row, "product_type", "crude_oil")),
            energy_density_gj_per_t=float(_get(row, "energy_density", 42.0)),
            api_gravity=_get(row, "api_gravity"),
            sulfur_pct=_get(row, "sulfur_pct"),
        )
        out[p.name] = p
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2.  REGIONS — demand, supply, storage, port times, seasonality
#     One row = one (region, company, product) triple for demand/supply.
#     We load in long form then pivot into Region objects.
# ══════════════════════════════════════════════════════════════════════════════

REGION_SCHEMA = {
    "region"              : (str,   "Region name",                              None),
    "latitude"            : (float, "Degrees N",                                 0.0),
    "longitude"           : (float, "Degrees E",                                 0.0),
    "spot_price_premium"  : (float, "Regional spot rate multiplier (0.5-8.0)",   1.0),
    "fuel_price_premium"  : (float, "Regional fuel price multiplier",             1.0),
    "max_vessel_dwt"      : (float, "Max draft restriction DWT (blank=none)",     None),
}

REGION_DEMAND_SCHEMA = {
    "region"              : (str,   "Region name",                              None),
    "company"             : (str,   "Company name or __free__ for spot market",  None),
    "product"             : (str,   "Product name",                              None),
    "volume_mean_mmt"     : (float, "Mean demand volume MMT per sim period",      0.0),
    "volume_std_mmt"      : (float, "Std dev of demand volume",                   0.0),
    "price_mean_usd_t"    : (float, "Mean demand price USD/MT",                   0.0),
    "price_std_usd_t"     : (float, "Std dev of price",                            0.0),
    "growth_rate_annual"  : (float, "Annual growth rate (0.02 = 2%)",              0.0),
    # Seasonality: columns season_1 .. season_12 (optional, default 1.0)
    "season_1"  : (float,"Jan multiplier",1.0), "season_2"  : (float,"Feb",1.0),
    "season_3"  : (float,"Mar",1.0),            "season_4"  : (float,"Apr",1.0),
    "season_5"  : (float,"May",1.0),            "season_6"  : (float,"Jun",1.0),
    "season_7"  : (float,"Jul",1.0),            "season_8"  : (float,"Aug",1.0),
    "season_9"  : (float,"Sep",1.0),            "season_10" : (float,"Oct",1.0),
    "season_11" : (float,"Nov",1.0),            "season_12" : (float,"Dec",1.0),
}

REGION_SUPPLY_SCHEMA = {k: v for k, v in REGION_DEMAND_SCHEMA.items()}  # same shape

REGION_STORAGE_SCHEMA = {
    "region"          : (str,   "Region name",              None),
    "company"         : (str,   "Company or __free__",       None),
    "total_mmt"       : (float, "Total storage capacity MMT", 0.0),
    "available_mmt"   : (float, "Currently available MMT",    0.0),
}

PORT_TIME_SCHEMA = {
    "region"            : (str,   "Region name",                 None),
    "ship_type"         : (str,   "ShipType name or __default__", None),
    "load_mean_days"    : (float, "Mean loading time days",        1.0),
    "load_std_days"     : (float, "Std dev",                       0.2),
    "unload_mean_days"  : (float, "Mean unloading time days",      1.0),
    "unload_std_days"   : (float, "Std dev",                       0.2),
    "bunker_mean_days"  : (float, "Mean bunkering time days",      0.5),
    "bunker_std_days"   : (float, "Std dev",                       0.1),
}


def template_regions() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region="USGulf",         latitude=29.5, longitude=-90.5, spot_price_premium=1.0, fuel_price_premium=0.9, max_vessel_dwt=None),
        dict(region="North Sea",      latitude=57.0, longitude=2.0,   spot_price_premium=1.0, fuel_price_premium=1.0),
        dict(region="Baltic",         latitude=59.0, longitude=22.0,  spot_price_premium=1.1, fuel_price_premium=1.0),
        dict(region="Mediterranean",  latitude=38.0, longitude=18.0,  spot_price_premium=1.0, fuel_price_premium=1.0),
        dict(region="Persian Gulf",   latitude=26.0, longitude=54.0,  spot_price_premium=0.9, fuel_price_premium=0.8),
        dict(region="West Africa",    latitude=4.0,  longitude=3.0,   spot_price_premium=1.2, fuel_price_premium=1.3),
        dict(region="Southeast Asia", latitude=5.0,  longitude=110.0, spot_price_premium=1.1, fuel_price_premium=1.0),
        dict(region="Alaska",         latitude=61.0, longitude=-150.0,spot_price_premium=1.5, fuel_price_premium=1.4),
        dict(region="Caribbean",      latitude=15.0, longitude=-75.0, spot_price_premium=1.0, fuel_price_premium=1.0),
    ])


def template_region_demand() -> pd.DataFrame:
    """Template: one row per (region, company, product)."""
    rows = [
        # Persian Gulf — Saudi Aramco supplies Arab Heavy
        dict(region="Persian Gulf", company="Saudi Aramco", product="Arab Heavy",
             volume_mean_mmt=80.0, volume_std_mmt=4.0,
             price_mean_usd_t=380.0, price_std_usd_t=20.0,
             growth_rate_annual=0.02),
        # North Sea — Shell, Brent
        dict(region="North Sea", company="Shell", product="Brent",
             volume_mean_mmt=30.0, volume_std_mmt=3.0,
             price_mean_usd_t=390.0, price_std_usd_t=18.0,
             growth_rate_annual=0.01),
        # Baltic — Rosneft, Urals
        dict(region="Baltic", company="Rosneft", product="Urals",
             volume_mean_mmt=25.0, volume_std_mmt=4.0,
             price_mean_usd_t=360.0, price_std_usd_t=25.0,
             growth_rate_annual=0.01),
        # USGulf — ExxonMobil, WTI
        dict(region="USGulf", company="ExxonMobil", product="WTI",
             volume_mean_mmt=35.0, volume_std_mmt=3.5,
             price_mean_usd_t=400.0, price_std_usd_t=22.0,
             growth_rate_annual=0.01),
        # Free/spot demand in Southeast Asia
        dict(region="Southeast Asia", company="__free__", product="Arab Heavy",
             volume_mean_mmt=45.0, volume_std_mmt=5.0,
             price_mean_usd_t=375.0, price_std_usd_t=30.0,
             growth_rate_annual=0.04),
    ]
    return pd.DataFrame(rows)


def template_region_supply() -> pd.DataFrame:
    """Supply side: same schema as demand."""
    return template_region_demand().rename(columns={})  # identical structure


def template_region_storage() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region="USGulf",         company="ExxonMobil",   total_mmt=40.0, available_mmt=35.0),
        dict(region="USGulf",         company="__free__",      total_mmt=20.0, available_mmt=18.0),
        dict(region="Persian Gulf",   company="Saudi Aramco", total_mmt=80.0, available_mmt=70.0),
        dict(region="North Sea",      company="Shell",         total_mmt=30.0, available_mmt=25.0),
        dict(region="Southeast Asia", company="__free__",      total_mmt=25.0, available_mmt=22.0),
    ])


def template_port_times() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region="Persian Gulf", ship_type="__default__",
             load_mean_days=1.5, load_std_days=0.3,
             unload_mean_days=1.5, unload_std_days=0.3,
             bunker_mean_days=0.5, bunker_std_days=0.1),
        dict(region="Persian Gulf", ship_type="VLCC",
             load_mean_days=2.0, load_std_days=0.4,
             unload_mean_days=2.0, unload_std_days=0.4,
             bunker_mean_days=0.7, bunker_std_days=0.15),
        dict(region="USGulf", ship_type="__default__",
             load_mean_days=1.2, load_std_days=0.2,
             unload_mean_days=1.2, unload_std_days=0.2,
             bunker_mean_days=0.4, bunker_std_days=0.1),
        dict(region="Alaska", ship_type="__default__",
             load_mean_days=3.0, load_std_days=0.8,
             unload_mean_days=2.5, unload_std_days=0.6,
             bunker_mean_days=1.0, bunker_std_days=0.3),
    ])


def load_regions(
    df_regions:  pd.DataFrame,
    df_demand:   pd.DataFrame,
    df_supply:   pd.DataFrame,
    df_storage:  pd.DataFrame,
    df_port_times: pd.DataFrame,
) -> Dict[str, Region]:
    """Build Region objects from the four long-form DataFrames."""

    regions: Dict[str, Region] = {}

    # Base properties
    for _, row in df_regions.iterrows():
        name = str(row["region"])
        regions[name] = Region(
            name=name,
            latitude=float(_get(row, "latitude", 0.0)),
            longitude=float(_get(row, "longitude", 0.0)),
            spot_price_premium=float(_get(row, "spot_price_premium", 1.0)),
            fuel_price_premium=float(_get(row, "fuel_price_premium", 1.0)),
            max_vessel_dwt=_get(row, "max_vessel_dwt"),
        )

    # Demand volumes
    for _, row in df_demand.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        cv = CompanyVolume(
            product=str(row["product"]),
            volume=_ms(row, "volume_mean_mmt", "volume_std_mmt"),
            price=_ms(row, "price_mean_usd_t", "price_std_usd_t"),
        )
        company_key = str(row["company"])
        r.demand[company_key] = cv
        # Growth rate
        gr = r.demand_growth.by_entity
        gr[company_key] = float(_get(row, "growth_rate_annual", 0.0))
        # Seasonality stored on cv — attach directly
        cv._seasonal = _seasonal(row, "season")

    # Supply volumes (same structure)
    for _, row in df_supply.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        cv = CompanyVolume(
            product=str(row["product"]),
            volume=_ms(row, "volume_mean_mmt", "volume_std_mmt"),
            price=_ms(row, "price_mean_usd_t", "price_std_usd_t"),
        )
        company_key = str(row["company"])
        r.supply[company_key] = cv
        gr = r.supply_growth.by_entity
        gr[company_key] = float(_get(row, "growth_rate_annual", 0.0))
        cv._seasonal = _seasonal(row, "season")

    # Storage
    for _, row in df_storage.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        r.storage[str(row["company"])] = StorageSlot(
            total_mmt=float(_get(row, "total_mmt", 0.0)),
            available_mmt=float(_get(row, "available_mmt", 0.0)),
        )

    # Port times
    for _, row in df_port_times.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        r.port_times[str(row["ship_type"])] = PortTime(
            load_days=_ms(row, "load_mean_days", "load_std_days", 1.0, 0.2),
            unload_days=_ms(row, "unload_mean_days", "unload_std_days", 1.0, 0.2),
            bunker_days=_ms(row, "bunker_mean_days", "bunker_std_days", 0.5, 0.1),
        )

    return regions


# ══════════════════════════════════════════════════════════════════════════════
# 3.  NETWORK NODES & EDGES
# ══════════════════════════════════════════════════════════════════════════════

NODE_SCHEMA = {
    "node_id"                : (str,   "Unique node ID",                         None),
    "node_type"              : (str,   "NodeType enum: port/canal/strait/...",   "port"),
    "region_name"            : (str,   "Linked Region name (for port nodes)",     None),
    "max_vessels_per_period" : (int,   "Capacity cap; blank=unlimited",           None),
    "transit_time_mean_days" : (float, "Mean transit/wait days",                  0.5),
    "transit_time_std_days"  : (float, "Std dev",                                 0.1),
    "max_vessel_dwt"         : (float, "Max DWT allowed; blank=unlimited",         None),
    "is_open"                : (bool,  "False if currently closed by scenario",    True),
}

EDGE_SCHEMA = {
    "from_node"                     : (str,   "Origin node ID",                    None),
    "to_node"                       : (str,   "Destination node ID",               None),
    "distance_nm"                   : (float, "Great-circle distance nautical mi",  0.0),
    "base_transit_mean_days"        : (float, "Base transit time days",             5.0),
    "base_transit_std_days"         : (float, "Std dev",                            0.5),
    "available_for"                 : (str,   "Comma-sep ship types; blank=all",    ""),
    "requires_nodes"                : (str,   "Comma-sep intermediate nodes",       ""),
    "fuel_consumption_multiplier"   : (float, "Weather/current adj factor",         1.0),
}


def template_nodes() -> pd.DataFrame:
    return pd.DataFrame([
        dict(node_id="USGulf",         node_type="port",   region_name="USGulf",         transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="North Sea",      node_type="port",   region_name="North Sea",      transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Baltic",         node_type="port",   region_name="Baltic",         transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Mediterranean",  node_type="port",   region_name="Mediterranean",  transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Persian Gulf",   node_type="port",   region_name="Persian Gulf",   transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="West Africa",    node_type="port",   region_name="West Africa",    transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Southeast Asia", node_type="port",   region_name="Southeast Asia", transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Alaska",         node_type="port",   region_name="Alaska",         transit_time_mean_days=0.5,  is_open=True),
        dict(node_id="Caribbean",      node_type="port",   region_name="Caribbean",      transit_time_mean_days=0.5,  is_open=True),
        # Chokepoints
        dict(node_id="Suez Canal",     node_type="canal",  region_name=None,
             max_vessels_per_period=450, transit_time_mean_days=1.0, transit_time_std_days=0.3,
             max_vessel_dwt=240_000, is_open=True),
        dict(node_id="Strait of Hormuz", node_type="strait", region_name=None,
             max_vessels_per_period=None, transit_time_mean_days=0.5, transit_time_std_days=0.1,
             max_vessel_dwt=None, is_open=True),
        dict(node_id="Strait of Malacca", node_type="strait", region_name=None,
             max_vessels_per_period=None, transit_time_mean_days=0.75, transit_time_std_days=0.2,
             max_vessel_dwt=300_000, is_open=True),
        dict(node_id="Danish Straits",  node_type="strait", region_name=None,
             max_vessels_per_period=None, transit_time_mean_days=0.25, transit_time_std_days=0.1,
             max_vessel_dwt=150_000, is_open=True),
        dict(node_id="Panama Canal",   node_type="canal",  region_name=None,
             max_vessels_per_period=200, transit_time_mean_days=1.0, transit_time_std_days=0.4,
             max_vessel_dwt=120_000, is_open=True),
        dict(node_id="Cape of Good Hope", node_type="open_sea", region_name=None,
             transit_time_mean_days=0.0, is_open=True),
    ])


def template_edges() -> pd.DataFrame:
    """
    Representative routes.  distances are approximate great-circle NM.
    Each edge is ONE-WAY; add reverse if needed.
    """
    rows = [
        # Persian Gulf → Mediterranean (via Suez)
        dict(from_node="Persian Gulf", to_node="Mediterranean",
             distance_nm=6500, base_transit_mean_days=16, base_transit_std_days=1.5,
             requires_nodes="Strait of Hormuz,Suez Canal"),
        # Persian Gulf → Mediterranean (via Cape — used when Suez blocked)
        dict(from_node="Persian Gulf", to_node="Mediterranean",
             distance_nm=14000, base_transit_mean_days=35, base_transit_std_days=3.0,
             requires_nodes="Strait of Hormuz,Cape of Good Hope"),
        # Persian Gulf → Southeast Asia (via Malacca)
        dict(from_node="Persian Gulf", to_node="Southeast Asia",
             distance_nm=5500, base_transit_mean_days=13, base_transit_std_days=1.5,
             requires_nodes="Strait of Hormuz,Strait of Malacca"),
        # Persian Gulf → USGulf (via Cape)
        dict(from_node="Persian Gulf", to_node="USGulf",
             distance_nm=17000, base_transit_mean_days=42, base_transit_std_days=4.0,
             requires_nodes="Strait of Hormuz,Cape of Good Hope"),
        # Baltic → Mediterranean (via Danish Straits)
        dict(from_node="Baltic", to_node="Mediterranean",
             distance_nm=4500, base_transit_mean_days=11, base_transit_std_days=1.0,
             requires_nodes="Danish Straits"),
        # North Sea → Mediterranean
        dict(from_node="North Sea", to_node="Mediterranean",
             distance_nm=3800, base_transit_mean_days=9, base_transit_std_days=1.0,
             requires_nodes=""),
        # West Africa → USGulf
        dict(from_node="West Africa", to_node="USGulf",
             distance_nm=5200, base_transit_mean_days=13, base_transit_std_days=1.5,
             requires_nodes=""),
        # West Africa → Mediterranean
        dict(from_node="West Africa", to_node="Mediterranean",
             distance_nm=3500, base_transit_mean_days=9, base_transit_std_days=1.0,
             requires_nodes=""),
        # USGulf → Caribbean
        dict(from_node="USGulf", to_node="Caribbean",
             distance_nm=1500, base_transit_mean_days=4, base_transit_std_days=0.5,
             requires_nodes=""),
        # Alaska → USGulf
        dict(from_node="Alaska", to_node="USGulf",
             distance_nm=8500, base_transit_mean_days=21, base_transit_std_days=2.0,
             requires_nodes=""),
        # Southeast Asia → North Sea (via Malacca + Suez)
        dict(from_node="Southeast Asia", to_node="North Sea",
             distance_nm=13000, base_transit_mean_days=32, base_transit_std_days=3.0,
             requires_nodes="Strait of Malacca,Suez Canal"),
    ]
    return pd.DataFrame(rows)


def load_nodes(df: pd.DataFrame) -> Dict[str, Node]:
    out = {}
    for _, row in df.iterrows():
        nid = str(row["node_id"])
        out[nid] = Node(
            node_id=nid,
            node_type=NodeType(_get(row, "node_type", "port")),
            region_name=_get(row, "region_name"),
            max_vessels_per_period=_get(row, "max_vessels_per_period"),
            transit_time_days=_ms(row, "transit_time_mean_days", "transit_time_std_days", 0.5, 0.1),
            max_vessel_dwt=_get(row, "max_vessel_dwt"),
            is_open=bool(_get(row, "is_open", True)),
        )
    return out


def load_edges(df: pd.DataFrame) -> list:
    out = []
    for _, row in df.iterrows():
        avail_raw = _get(row, "available_for", "")
        req_raw   = _get(row, "requires_nodes", "")
        out.append(Edge(
            from_node=str(row["from_node"]),
            to_node=str(row["to_node"]),
            distance_nm=float(_get(row, "distance_nm", 0.0)),
            base_transit_days=_ms(row, "base_transit_mean_days", "base_transit_std_days", 5.0, 0.5),
            available_for=[x.strip() for x in str(avail_raw).split(",") if x.strip()] if avail_raw else [],
            requires_nodes=[x.strip() for x in str(req_raw).split(",") if x.strip()] if req_raw else [],
            fuel_consumption_multiplier=float(_get(row, "fuel_consumption_multiplier", 1.0)),
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 4.  OIL COMPANIES
# ══════════════════════════════════════════════════════════════════════════════

COMPANY_SCHEMA = {
    "name"                : (str,   "Company name",                      None),
    "supply_regions"      : (str,   "Comma-separated supply region names", ""),
    "demand_regions"      : (str,   "Comma-separated demand region names", ""),
    "supply_growth_default" : (float,"Default annual supply growth rate", 0.02),
    "demand_growth_default" : (float,"Default annual demand growth rate", 0.02),
    "supply_volatility"   : (float, "Fractional supply std dev",          0.05),
    "demand_volatility"   : (float, "Fractional demand std dev",          0.05),
    "wtp_spot"            : (float, "Max willingness to pay spot ($/day)",30000),
    "contract_fraction"   : (float, "Fraction of volume under contract",  0.60),
    "is_sanctioned"       : (bool,  "True if currently sanctioned",       False),
    "associated_countries": (str,   "Comma-sep ShipCountry enum names",   ""),
}


def template_companies() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="Saudi Aramco", supply_regions="Persian Gulf",
             demand_regions="Mediterranean,Southeast Asia,USGulf",
             supply_growth_default=0.02, demand_growth_default=0.02,
             supply_volatility=0.05, demand_volatility=0.05,
             wtp_spot=32000, contract_fraction=0.70,
             is_sanctioned=False, associated_countries="uae"),
        dict(name="Shell", supply_regions="North Sea,West Africa",
             demand_regions="North Sea,Mediterranean,USGulf",
             supply_growth_default=0.01, demand_growth_default=0.01,
             supply_volatility=0.08, demand_volatility=0.08,
             wtp_spot=30000, contract_fraction=0.60,
             is_sanctioned=False, associated_countries="other_western"),
        dict(name="ExxonMobil", supply_regions="USGulf,Alaska",
             demand_regions="USGulf,Caribbean,Mediterranean",
             supply_growth_default=0.01, demand_growth_default=0.01,
             supply_volatility=0.08, demand_volatility=0.08,
             wtp_spot=29000, contract_fraction=0.65,
             is_sanctioned=False, associated_countries="usa"),
        dict(name="BP", supply_regions="North Sea,Caribbean",
             demand_regions="North Sea,Mediterranean",
             supply_growth_default=0.01, demand_growth_default=0.01,
             supply_volatility=0.10, demand_volatility=0.10,
             wtp_spot=28000, contract_fraction=0.60,
             is_sanctioned=False, associated_countries="other_western"),
        dict(name="Rosneft", supply_regions="Baltic",
             demand_regions="Mediterranean,Southeast Asia",
             supply_growth_default=0.02, demand_growth_default=0.02,
             supply_volatility=0.12, demand_volatility=0.12,
             wtp_spot=25000, contract_fraction=0.50,
             is_sanctioned=False, associated_countries="russia"),
        dict(name="CNOOC", supply_regions="Southeast Asia",
             demand_regions="Southeast Asia,USGulf",
             supply_growth_default=0.04, demand_growth_default=0.04,
             supply_volatility=0.08, demand_volatility=0.08,
             wtp_spot=28000, contract_fraction=0.55,
             is_sanctioned=False, associated_countries="china"),
        dict(name="Independent", supply_regions="",
             demand_regions="",
             supply_growth_default=0.02, demand_growth_default=0.02,
             supply_volatility=0.20, demand_volatility=0.20,
             wtp_spot=35000, contract_fraction=0.20,
             is_sanctioned=False, associated_countries=""),
    ])


def load_companies(df: pd.DataFrame) -> Dict[str, OilCompany]:
    out = {}
    for _, row in df.iterrows():
        name = str(row["name"])

        def _split(col): 
            v = _get(row, col, "")
            return [x.strip() for x in str(v).split(",") if x.strip()] if v else []

        countries_raw = _split("associated_countries")
        countries = []
        for c in countries_raw:
            try: countries.append(ShipCountry(c))
            except ValueError: pass

        out[name] = OilCompany(
            name=name,
            supply_regions=_split("supply_regions"),
            demand_regions=_split("demand_regions"),
            supply_growth=GrowthRate(default=float(_get(row, "supply_growth_default", 0.02))),
            demand_growth=GrowthRate(default=float(_get(row, "demand_growth_default", 0.02))),
            supply_volatility=float(_get(row, "supply_volatility", 0.05)),
            demand_volatility=float(_get(row, "demand_volatility", 0.05)),
            wtp_spot=float(_get(row, "wtp_spot", 30000)),
            contract_fraction=float(_get(row, "contract_fraction", 0.60)),
            is_sanctioned=bool(_get(row, "is_sanctioned", False)),
            associated_countries=countries,
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5.  SHIP TYPES & INITIAL FLEET
# ══════════════════════════════════════════════════════════════════════════════

SHIP_GROUP_SCHEMA = {
    "name"          : (str,   "Group name e.g. VLCC",             None),
    "dwt_min"       : (float, "Min DWT for this class",           0.0),
    "dwt_max"       : (float, "Max DWT for this class",           999999.0),
    "description"   : (str,   "Free text",                        ""),
}

SHIP_TYPE_SCHEMA = {
    "name"                      : (str,   "Unique type name e.g. VLCC_scrubber_KR",  None),
    "group"                     : (str,   "ShipGroupType name",                      None),
    "dwt_mean"                  : (float, "Mean DWT",                              300000),
    "dwt_std"                   : (float, "Std dev DWT",                             5000),
    "speed_mean_kn"             : (float, "Mean speed knots",                         15.5),
    "speed_std_kn"              : (float, "Std dev",                                   0.5),
    "daily_opex_mean"           : (float, "Mean daily opex USD",                      8500),
    "daily_opex_std"            : (float, "Std dev",                                   500),
    "fuel_cons_t_day"           : (float, "Fuel consumption t/day at design speed",    90.0),
    "fuel_ballast_factor"       : (float, "Fraction of fuel when in ballast",           0.75),
    "scrubber_fitted"           : (bool,  "True if fitted with exhaust scrubber",      False),
    "build_cost_musd"           : (float, "Newbuild cost USD million",                120.0),
    "scrap_value_musd"          : (float, "Scrap value USD million",                   30.0),
    "build_time_years"          : (float, "Mean build time years",                      2.5),
    "build_time_std_years"      : (float, "Std dev",                                    0.25),
    "economic_life_years"       : (float, "Expected service life years",               25.0),
    "can_be_storage"            : (bool,  "Can convert to FSO",                        True),
    "country"                   : (str,   "ShipCountry enum name",              "other_western"),
    "compatible_products"       : (str,   "Comma-sep product names; blank=all crude",  ""),
    "max_beam_m"                : (float, "Max beam for canal/strait access",           None),
    "max_draft_m"               : (float, "Max draft",                                  None),
}

FLEET_SCHEMA = {
    "ship_type"   : (str, "ShipType name",         None),
    "owner"       : (str, "Company name",           None),
    "count"       : (int, "Number of active vessels", 0),
    "count_storage": (int,"Number in FSO/storage",   0),
    "avg_age_years": (float,"Average fleet age years", 5.0),
}

ORDERBOOK_SCHEMA = {
    "ship_type"      : (str,   "ShipType name",                None),
    "owner"          : (str,   "Ordering company",             None),
    "delivery_year"  : (int,   "Expected delivery year",       None),
    "delivery_month" : (int,   "Expected delivery month 1-12", 1),
    "count"          : (int,   "Number of orders",             1),
    "build_cost_musd": (float, "Build cost USD million",       120.0),
    "shipyard_country": (str,  "ShipCountry enum name",        "south_korea"),
}


def template_ship_groups() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="VLCC",    dwt_min=200_000, dwt_max=320_000, description="Very Large Crude Carrier"),
        dict(name="Suezmax", dwt_min=120_000, dwt_max=200_000, description="Suezmax tanker"),
        dict(name="Aframax", dwt_min=80_000,  dwt_max=120_000, description="Aframax tanker"),
        dict(name="Panamax", dwt_min=55_000,  dwt_max=80_000,  description="Panamax tanker"),
        dict(name="MR",      dwt_min=25_000,  dwt_max=55_000,  description="Medium Range product tanker"),
    ])


def template_ship_types() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="VLCC_KR",          group="VLCC",    dwt_mean=300_000, dwt_std=5000,
             speed_mean_kn=15.5, speed_std_kn=0.5,
             daily_opex_mean=8500,  daily_opex_std=500,
             fuel_cons_t_day=90.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=120.0, scrap_value_musd=30.0,
             build_time_years=2.5, build_time_std_years=0.25, economic_life_years=25.0,
             can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="VLCC_scrubber_KR", group="VLCC",    dwt_mean=300_000, dwt_std=5000,
             speed_mean_kn=15.5, speed_std_kn=0.5,
             daily_opex_mean=9200,  daily_opex_std=500,
             fuel_cons_t_day=90.0, fuel_ballast_factor=0.75,
             scrubber_fitted=True,  build_cost_musd=125.0, scrap_value_musd=30.0,
             build_time_years=2.5,  build_time_std_years=0.25, economic_life_years=25.0,
             can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="VLCC_CN",          group="VLCC",    dwt_mean=298_000, dwt_std=6000,
             speed_mean_kn=15.2, speed_std_kn=0.6,
             daily_opex_mean=7800,  daily_opex_std=600,
             fuel_cons_t_day=92.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=105.0, scrap_value_musd=28.0,
             build_time_years=2.0, build_time_std_years=0.20, economic_life_years=22.0,
             can_be_storage=True, country="china", compatible_products=""),
        dict(name="Suezmax_KR",       group="Suezmax", dwt_mean=158_000, dwt_std=3000,
             speed_mean_kn=15.0, speed_std_kn=0.4,
             daily_opex_mean=6500, daily_opex_std=400,
             fuel_cons_t_day=58.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=78.0, scrap_value_musd=18.0,
             build_time_years=2.0, build_time_std_years=0.20, economic_life_years=25.0,
             can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="Aframax_GR",       group="Aframax", dwt_mean=105_000, dwt_std=2000,
             speed_mean_kn=14.5, speed_std_kn=0.4,
             daily_opex_mean=5200, daily_opex_std=350,
             fuel_cons_t_day=44.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=56.0, scrap_value_musd=12.0,
             build_time_years=1.8, build_time_std_years=0.20, economic_life_years=25.0,
             can_be_storage=False, country="greece", compatible_products=""),
        dict(name="Aframax_RU",       group="Aframax", dwt_mean=100_000, dwt_std=3000,
             speed_mean_kn=14.2, speed_std_kn=0.5,
             daily_opex_mean=4800, daily_opex_std=400,
             fuel_cons_t_day=46.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=48.0, scrap_value_musd=10.0,
             build_time_years=2.2, build_time_std_years=0.30, economic_life_years=20.0,
             can_be_storage=False, country="russia", compatible_products="Urals"),
        dict(name="MR_NO",            group="MR",      dwt_mean=47_000,  dwt_std=1500,
             speed_mean_kn=14.0, speed_std_kn=0.3,
             daily_opex_mean=3500, daily_opex_std=300,
             fuel_cons_t_day=30.0, fuel_ballast_factor=0.75,
             scrubber_fitted=False, build_cost_musd=38.0, scrap_value_musd=7.0,
             build_time_years=1.5, build_time_std_years=0.20, economic_life_years=25.0,
             can_be_storage=False, country="norway", compatible_products=""),
    ])


def template_fleet() -> pd.DataFrame:
    return pd.DataFrame([
        dict(ship_type="VLCC_KR",          owner="Saudi Aramco", count=6,  count_storage=0, avg_age_years=6.0),
        dict(ship_type="VLCC_scrubber_KR", owner="Saudi Aramco", count=3,  count_storage=0, avg_age_years=3.0),
        dict(ship_type="VLCC_CN",          owner="CNOOC",        count=5,  count_storage=0, avg_age_years=4.0),
        dict(ship_type="VLCC_KR",          owner="Independent",  count=8,  count_storage=0, avg_age_years=10.0),
        dict(ship_type="Suezmax_KR",       owner="Shell",        count=6,  count_storage=0, avg_age_years=8.0),
        dict(ship_type="Suezmax_KR",       owner="BP",           count=4,  count_storage=0, avg_age_years=7.0),
        dict(ship_type="Suezmax_KR",       owner="Independent",  count=10, count_storage=0, avg_age_years=12.0),
        dict(ship_type="Aframax_GR",       owner="BP",           count=5,  count_storage=0, avg_age_years=9.0),
        dict(ship_type="Aframax_GR",       owner="ExxonMobil",   count=4,  count_storage=0, avg_age_years=8.0),
        dict(ship_type="Aframax_RU",       owner="Rosneft",      count=8,  count_storage=0, avg_age_years=7.0),
        dict(ship_type="Aframax_GR",       owner="Independent",  count=12, count_storage=0, avg_age_years=14.0),
        dict(ship_type="MR_NO",            owner="Shell",        count=4,  count_storage=0, avg_age_years=6.0),
        dict(ship_type="MR_NO",            owner="Independent",  count=9,  count_storage=0, avg_age_years=11.0),
    ])


def template_orderbook() -> pd.DataFrame:
    return pd.DataFrame([
        dict(ship_type="VLCC_KR",          owner="Saudi Aramco", delivery_year=2026, delivery_month=3, count=2, build_cost_musd=120.0, shipyard_country="south_korea"),
        dict(ship_type="VLCC_CN",          owner="CNOOC",        delivery_year=2026, delivery_month=6, count=3, build_cost_musd=106.0, shipyard_country="china"),
        dict(ship_type="Suezmax_KR",       owner="Independent",  delivery_year=2026, delivery_month=9, count=2, build_cost_musd=78.0,  shipyard_country="south_korea"),
        dict(ship_type="Aframax_GR",       owner="BP",           delivery_year=2025, delivery_month=12,count=1, build_cost_musd=56.0,  shipyard_country="south_korea"),
        dict(ship_type="VLCC_scrubber_KR", owner="Saudi Aramco", delivery_year=2027, delivery_month=1, count=2, build_cost_musd=125.0, shipyard_country="south_korea"),
    ])


def load_ship_types(df: pd.DataFrame) -> Dict[str, ShipType]:
    out = {}
    for _, row in df.iterrows():
        name = str(row["name"])
        prods_raw = _get(row, "compatible_products", "")
        prods = [x.strip() for x in str(prods_raw).split(",") if x.strip()] if prods_raw else []
        try:
            country = ShipCountry(_get(row, "country", "other_western"))
        except ValueError:
            country = ShipCountry.OTHER_WESTERN

        out[name] = ShipType(
            name=name,
            group=str(_get(row, "group", "")),
            dwt=_ms(row, "dwt_mean", "dwt_std", 300_000, 5_000),
            speed_knots=_ms(row, "speed_mean_kn", "speed_std_kn", 15.0, 0.5),
            daily_opex=_ms(row, "daily_opex_mean", "daily_opex_std", 8_000, 500),
            fuel_consumption_tons_day=float(_get(row, "fuel_cons_t_day", 60.0)),
            fuel_consumption_ballast_factor=float(_get(row, "fuel_ballast_factor", 0.75)),
            scrubber_fitted=bool(_get(row, "scrubber_fitted", False)),
            build_cost_musd=float(_get(row, "build_cost_musd", 80.0)),
            scrap_value_musd=float(_get(row, "scrap_value_musd", 15.0)),
            build_time_years=float(_get(row, "build_time_years", 2.5)),
            build_time_std_years=float(_get(row, "build_time_std_years", 0.25)),
            economic_life_years=float(_get(row, "economic_life_years", 25.0)),
            can_be_storage=bool(_get(row, "can_be_storage", False)),
            country=country,
            compatible_products=prods,
            max_beam_m=_get(row, "max_beam_m"),
            max_draft_m=_get(row, "max_draft_m"),
        )
    return out


def load_orderbook(df: pd.DataFrame, ship_types: Dict[str, ShipType]) -> list:
    entries = []
    for _, row in df.iterrows():
        ship_type = str(row["ship_type"])
        st = ship_types.get(ship_type)
        if st is None:
            continue
        count = int(_get(row, "count", 1))
        try:
            sc = ShipCountry(_get(row, "shipyard_country", "south_korea"))
        except ValueError:
            sc = ShipCountry.SOUTH_KOREA

        delivery_year  = int(_get(row, "delivery_year", 2026))
        delivery_month = int(_get(row, "delivery_month", 6))
        # Convert to simulation day
        start_year   = 2025
        delivery_day = (delivery_year - start_year) * 365 + (delivery_month - 1) * 30.0

        for _ in range(count):
            entries.append(OrderbookEntry(
                ship_type=ship_type,
                owner=str(row["owner"]),
                ordered_on_day=0.0,
                delivery_day=delivery_day,
                build_cost_musd=float(_get(row, "build_cost_musd", st.build_cost_musd)),
                shipyard_country=sc,
            ))
    return entries


# ══════════════════════════════════════════════════════════════════════════════
# 6.  SCENARIO CONSTRAINTS
# ══════════════════════════════════════════════════════════════════════════════

CONSTRAINT_SCHEMA = {
    "constraint_id"    : (str,   "Unique ID",                         None),
    "constraint_type"  : (str,   "ConstraintType enum name",           None),
    "apply_on_day"     : (float, "Simulation day to activate",          0.0),
    "end_on_day"       : (float, "Simulation day to deactivate (blank=permanent)", None),
    "description"      : (str,   "Human-readable description",          ""),
    "target_nodes"     : (str,   "Comma-sep Node IDs",                  ""),
    "target_companies" : (str,   "Comma-sep company names",             ""),
    "target_countries" : (str,   "Comma-sep ShipCountry enum names",    ""),
    "target_regions"   : (str,   "Comma-sep region names",              ""),
    "target_products"  : (str,   "Comma-sep product names",             ""),
    "multiplier"       : (float, "Volume/capacity multiplier (1.0=no change)", 1.0),
    "additive"         : (float, "Additive cost delta (USD/MT or USD/day)", 0.0),
    "capacity_vessels" : (int,   "New vessel capacity cap for node (blank=unchanged)", None),
}


def template_constraints() -> pd.DataFrame:
    return pd.DataFrame([
        # IMO 2020 — fuel premium on non-scrubber vessels
        dict(constraint_id="IMO2020", constraint_type="fuel_regulation",
             apply_on_day=0.0, end_on_day=None, description="IMO 2020 sulfur cap",
             target_nodes="", target_companies="", target_countries="",
             target_regions="", target_products="HFO",
             multiplier=1.0, additive=150.0, capacity_vessels=None),
        # Russian sanctions — Baltic, Rosneft, Russian-flagged ships
        dict(constraint_id="RU_SANCTION_2022", constraint_type="sanction_ship_flag",
             apply_on_day=365.0, end_on_day=None, description="Western sanctions on Russian fleet",
             target_nodes="", target_companies="Rosneft", target_countries="russia",
             target_regions="Baltic", target_products="Urals",
             multiplier=0.40, additive=0.0, capacity_vessels=None),
        # Hormuz closure (ad-hoc event)
        dict(constraint_id="HORMUZ_CLOSURE", constraint_type="node_closure",
             apply_on_day=9999.0, end_on_day=10007.0, description="Strait of Hormuz temporary closure",
             target_nodes="Strait of Hormuz", target_companies="",
             target_countries="", target_regions="", target_products="",
             multiplier=0.0, additive=0.0, capacity_vessels=0),
        # COVID demand shock
        dict(constraint_id="COVID_SHOCK", constraint_type="demand_shock",
             apply_on_day=9999.0, end_on_day=10547.0, description="Pandemic demand collapse",
             target_nodes="", target_companies="", target_countries="",
             target_regions="", target_products="",
             multiplier=0.75, additive=0.0, capacity_vessels=None),
    ])


def load_constraints(df: pd.DataFrame) -> list:
    out = []
    for _, row in df.iterrows():
        def _split(col):
            v = _get(row, col, "")
            return [x.strip() for x in str(v).split(",") if x.strip()] if v else []

        countries_raw = _split("target_countries")
        countries = []
        for c in countries_raw:
            try: countries.append(ShipCountry(c))
            except ValueError: pass

        try:
            ct = ConstraintType(str(row["constraint_type"]))
        except ValueError:
            continue

        out.append(ScenarioConstraint(
            constraint_id=str(row["constraint_id"]),
            constraint_type=ct,
            apply_on_day=float(_get(row, "apply_on_day", 0.0)),
            end_on_day=_get(row, "end_on_day"),
            description=str(_get(row, "description", "")),
            target_nodes=_split("target_nodes"),
            target_companies=_split("target_companies"),
            target_countries=countries,
            target_regions=_split("target_regions"),
            target_products=_split("target_products"),
            multiplier=float(_get(row, "multiplier", 1.0)),
            additive=float(_get(row, "additive", 0.0)),
            capacity_vessels=_get(row, "capacity_vessels"),
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 7.  SEASONALITY OVERRIDES  (optional separate CSV)
# ══════════════════════════════════════════════════════════════════════════════

SEASONALITY_SCHEMA = {
    "entity_type"  : (str, "region/product/spot",                    None),
    "entity_name"  : (str, "name of the entity",                     None),
    "attribute"    : (str, "demand/supply/price/spot",               None),
    "season_1"     : (float,"Jan multiplier",                         1.0),
    "season_2"     : (float,"Feb",1.0), "season_3"  : (float,"Mar",1.0),
    "season_4"     : (float,"Apr",1.0), "season_5"  : (float,"May",1.0),
    "season_6"     : (float,"Jun",1.0), "season_7"  : (float,"Jul",1.0),
    "season_8"     : (float,"Aug",1.0), "season_9"  : (float,"Sep",1.0),
    "season_10"    : (float,"Oct",1.0), "season_11" : (float,"Nov",1.0),
    "season_12"    : (float,"Dec",1.0),
}


def template_seasonality() -> pd.DataFrame:
    """Example: heating oil demand spikes in NH winter."""
    return pd.DataFrame([
        dict(entity_type="region", entity_name="North Sea", attribute="demand",
             season_1=1.15, season_2=1.12, season_3=1.05,
             season_4=0.95, season_5=0.90, season_6=0.88,
             season_7=0.88, season_8=0.90, season_9=0.95,
             season_10=1.00, season_11=1.10, season_12=1.18),
        dict(entity_type="region", entity_name="USGulf", attribute="demand",
             season_1=1.10, season_2=1.08, season_3=1.02,
             season_4=0.97, season_5=0.95, season_6=0.93,
             season_7=0.93, season_8=0.95, season_9=0.98,
             season_10=1.00, season_11=1.05, season_12=1.12),
        dict(entity_type="spot", entity_name="global", attribute="spot_rate",
             season_1=1.08, season_2=1.05, season_3=1.00,
             season_4=0.95, season_5=0.92, season_6=0.93,
             season_7=0.95, season_8=0.98, season_9=1.02,
             season_10=1.05, season_11=1.08, season_12=1.10),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# 8.  SAVE ALL TEMPLATES  (convenience function)
# ══════════════════════════════════════════════════════════════════════════════

ALL_TEMPLATES = {
    "products":          template_products,
    "regions":           template_regions,
    "region_demand":     template_region_demand,
    "region_supply":     template_region_supply,
    "region_storage":    template_region_storage,
    "port_times":        template_port_times,
    "nodes":             template_nodes,
    "edges":             template_edges,
    "companies":         template_companies,
    "ship_groups":       template_ship_groups,
    "ship_types":        template_ship_types,
    "fleet":             template_fleet,
    "orderbook":         template_orderbook,
    "constraints":       template_constraints,
    "seasonality":       template_seasonality,
}

def save_templates(output_dir: str = "."):
    """Write all template CSVs to output_dir."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    for name, fn in ALL_TEMPLATES.items():
        df = fn()
        df.to_csv(f"{output_dir}/{name}.csv", index=False)
        print(f"  Wrote {output_dir}/{name}.csv  ({len(df)} rows)")
