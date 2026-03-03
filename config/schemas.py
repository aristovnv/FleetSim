"""
DataFrame schemas and CSV loaders for Maritime Fleet Simulation v3.

New in v3:
  - vessel_groups table: defines group dimensions (flag, class, scrubber, sts, trade, age)
  - vessel_group_members table: (vessel_id, group_id, step_from, step_to) many-to-many
  - constraints: step_from/step_to instead of (only) days; target_vessel_groups column
  - nodes: is_gateway flag for Suez/Gibraltar/Panama/Malacca/Singapore
  - edges: alternate_for column (used when gateway closed)
  - products: tags column for product group targeting
  - regions: tags column for region group targeting
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

from core.models import (
    MeanStd, GrowthRate, SeasonalCoeff, Region, CompanyVolume,
    StorageSlot, PortTime, OilCompany, ShipGroupType, ShipType,
    OrderbookEntry, ScenarioConstraint, SimConfig, Product, ProductMix,
    Node, Edge, VesselGroup, VesselGroupMembership
)
from core.enums import (
    Granularity, ShipCountry, VesselStatus, NodeType,
    ProductType, ConstraintType
)


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _get(row: pd.Series, col: str, default=None):
    if col in row.index and pd.notna(row[col]):
        return row[col]
    return default

def _ms(row, mean_col, std_col, default_mean=0.0, default_std=0.0) -> MeanStd:
    return MeanStd(
        mean=float(_get(row, mean_col, default_mean)),
        std=float(_get(row, std_col, default_std)),
    )

def _seasonal(row, prefix="season") -> SeasonalCoeff:
    return SeasonalCoeff([
        float(_get(row, f"{prefix}_{m}", 1.0)) for m in range(1, 13)
    ])

def _split(val, sep=",") -> List[str]:
    if not val or (isinstance(val, float) and np.isnan(val)):
        return []
    return [x.strip() for x in str(val).split(sep) if x.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# 1. PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

def template_products() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="WTI",        product_type="crude_oil",   energy_density=42.0, api_gravity=39.6, sulfur_pct=0.24, tags="light_sweet"),
        dict(name="Brent",      product_type="crude_oil",   energy_density=42.0, api_gravity=38.3, sulfur_pct=0.37, tags="light_sweet"),
        dict(name="Urals",      product_type="crude_oil",   energy_density=41.5, api_gravity=31.0, sulfur_pct=1.30, tags="medium_sour,russian"),
        dict(name="Arab Heavy", product_type="crude_oil",   energy_density=41.0, api_gravity=27.7, sulfur_pct=2.85, tags="heavy_sour,gulf"),
        dict(name="VLSFO",      product_type="fuel_oil",    energy_density=40.5, api_gravity=None, sulfur_pct=0.50, tags="bunker"),
        dict(name="HFO",        product_type="fuel_oil",    energy_density=40.0, api_gravity=None, sulfur_pct=3.50, tags="bunker,high_sulfur"),
    ])

def load_products(df: pd.DataFrame) -> Dict[str, Product]:
    out = {}
    for _, row in df.iterrows():
        p = Product(
            name=str(row["name"]),
            product_type=ProductType(_get(row, "product_type", "crude_oil")),
            energy_density_gj_per_t=float(_get(row, "energy_density", 42.0)),
            api_gravity=_get(row, "api_gravity"),
            sulfur_pct=_get(row, "sulfur_pct"),
            tags=_split(_get(row, "tags", "")),
        )
        out[p.name] = p
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2. REGIONS
# ══════════════════════════════════════════════════════════════════════════════

REGION_SCHEMA = {
    "region":              (str,   "Region code",              None),
    "latitude":            (float, "Centroid latitude",         0.0),
    "longitude":           (float, "Centroid longitude",        0.0),
    "spot_price_premium":  (float, "Spot rate multiplier",      1.0),
    "fuel_price_premium":  (float, "Fuel price multiplier",     1.0),
    "max_vessel_dwt":      (float, "Draft/size limit DWT",      None),
    "tags":                (str,   "Comma-sep tags for constraint targeting", ""),
}

def template_regions() -> pd.DataFrame:
    """43 real-world maritime regions with gateway nodes."""
    return pd.DataFrame([
        dict(region='AG',     latitude=26.17854,  longitude=53.22347,  spot_price_premium=0.88, fuel_price_premium=0.75, max_vessel_dwt=None, tags='gulf,opec'),
        dict(region='ALASKA', latitude=59.18255,  longitude=-142.12799,spot_price_premium=1.40, fuel_price_premium=1.35, max_vessel_dwt=None, tags='arctic_adj'),
        dict(region='ARCTIC', latitude=71.47168,  longitude=33.20482,  spot_price_premium=1.80, fuel_price_premium=1.90, max_vessel_dwt=150000,tags='arctic,restricted'),
        dict(region='ARG',    latitude=-37.95789, longitude=-60.58108, spot_price_premium=1.10, fuel_price_premium=1.05, max_vessel_dwt=None, tags='latam'),
        dict(region='BALT',   latitude=58.34300,  longitude=17.07947,  spot_price_premium=1.10, fuel_price_premium=1.00, max_vessel_dwt=150000,tags='eu_port,baltic'),
        dict(region='BRZL',   latitude=-15.17165, longitude=-44.58835, spot_price_premium=1.15, fuel_price_premium=1.10, max_vessel_dwt=None, tags='latam'),
        dict(region='BSEA',   latitude=43.45947,  longitude=32.11065,  spot_price_premium=1.05, fuel_price_premium=0.95, max_vessel_dwt=150000,tags='black_sea'),
        dict(region='CBS',    latitude=14.96930,  longitude=-68.41213, spot_price_premium=1.00, fuel_price_premium=0.95, max_vessel_dwt=None, tags='caribbean'),
        dict(region='CCHINA', latitude=30.99621,  longitude=120.63592, spot_price_premium=1.05, fuel_price_premium=1.00, max_vessel_dwt=None, tags='china'),
        dict(region='EAFR',   latitude=-12.33216, longitude=45.65022,  spot_price_premium=1.20, fuel_price_premium=1.15, max_vessel_dwt=None, tags='africa'),
        dict(region='EAUS',   latitude=-25.30512, longitude=149.39018, spot_price_premium=1.25, fuel_price_premium=1.20, max_vessel_dwt=None, tags='pacific_rim'),
        dict(region='ECCAM',  latitude=12.37621,  longitude=-83.79660, spot_price_premium=1.05, fuel_price_premium=1.00, max_vessel_dwt=None, tags='caribbean,latam'),
        dict(region='ECCAN',  latitude=48.76211,  longitude=-64.05098, spot_price_premium=1.10, fuel_price_premium=1.05, max_vessel_dwt=None, tags='north_america'),
        dict(region='ECIND',  latitude=15.95854,  longitude=84.25477,  spot_price_premium=0.95, fuel_price_premium=0.90, max_vessel_dwt=None, tags='india'),
        dict(region='ECMEX',  latitude=20.38937,  longitude=-92.54476, spot_price_premium=0.95, fuel_price_premium=0.90, max_vessel_dwt=None, tags='latam,gulf_adj'),
        dict(region='GLAKES', latitude=44.01906,  longitude=-83.09020, spot_price_premium=1.30, fuel_price_premium=1.25, max_vessel_dwt=30000, tags='inland,restricted'),
        dict(region='HAW',    latitude=20.96425,  longitude=-157.19972,spot_price_premium=1.50, fuel_price_premium=1.45, max_vessel_dwt=None, tags='pacific_island'),
        dict(region='ICELAND',latitude=66.09715,  longitude=-34.76404, spot_price_premium=1.40, fuel_price_premium=1.35, max_vessel_dwt=None, tags='north_atlantic'),
        dict(region='KOR/JPN',latitude=35.19425,  longitude=133.59912, spot_price_premium=1.10, fuel_price_premium=1.05, max_vessel_dwt=None, tags='pacific_rim,east_asia'),
        dict(region='MED',    latitude=38.59241,  longitude=17.50651,  spot_price_premium=1.00, fuel_price_premium=1.00, max_vessel_dwt=None, tags='eu_port,mediterranean'),
        dict(region='NAUS',   latitude=-13.60542, longitude=131.25938, spot_price_premium=1.25, fuel_price_premium=1.20, max_vessel_dwt=None, tags='pacific_rim'),
        dict(region='NCHINA', latitude=37.86237,  longitude=120.49624, spot_price_premium=1.05, fuel_price_premium=1.00, max_vessel_dwt=None, tags='china,east_asia'),
        dict(region='NSEA',   latitude=60.46692,  longitude=5.27897,   spot_price_premium=1.00, fuel_price_premium=1.00, max_vessel_dwt=None, tags='eu_port,north_sea'),
        dict(region='NZ',     latitude=-41.05468, longitude=173.60067, spot_price_premium=1.30, fuel_price_premium=1.25, max_vessel_dwt=None, tags='pacific_island'),
        dict(region='PI',     latitude=-9.37023,  longitude=165.35753, spot_price_premium=1.40, fuel_price_premium=1.35, max_vessel_dwt=None, tags='pacific_island'),
        dict(region='RSEA',   latitude=21.47015,  longitude=39.20407,  spot_price_premium=0.92, fuel_price_premium=0.85, max_vessel_dwt=300000,tags='gulf,strategic'),
        dict(region='RUPAC',  latitude=49.12812,  longitude=140.64946, spot_price_premium=1.20, fuel_price_premium=1.15, max_vessel_dwt=None, tags='russia'),
        dict(region='SAFR',   latitude=-31.16293, longitude=22.98695,  spot_price_premium=1.15, fuel_price_premium=1.10, max_vessel_dwt=None, tags='africa'),
        dict(region='SAUS',   latitude=-37.04050, longitude=141.29493, spot_price_premium=1.20, fuel_price_premium=1.15, max_vessel_dwt=None, tags='pacific_rim'),
        dict(region='SCHINA', latitude=23.16138,  longitude=115.75299, spot_price_premium=1.05, fuel_price_premium=1.00, max_vessel_dwt=None, tags='china,east_asia'),
        dict(region='SEASIA', latitude=4.16868,   longitude=114.53225, spot_price_premium=1.05, fuel_price_premium=0.98, max_vessel_dwt=None, tags='southeast_asia'),
        dict(region='SING',   latitude=4.42869,   longitude=103.91118, spot_price_premium=1.00, fuel_price_premium=0.92, max_vessel_dwt=None, tags='southeast_asia,hub'),
        dict(region='UKC',    latitude=51.25948,  longitude=-2.06142,  spot_price_premium=1.02, fuel_price_premium=1.00, max_vessel_dwt=None, tags='eu_port,north_sea'),
        dict(region='USAC',   latitude=38.07642,  longitude=-75.21663, spot_price_premium=1.05, fuel_price_premium=1.02, max_vessel_dwt=None, tags='north_america'),
        dict(region='USG',    latitude=29.36369,  longitude=-90.68088, spot_price_premium=0.95, fuel_price_premium=0.90, max_vessel_dwt=None, tags='north_america,gulf_adj'),
        dict(region='USWC',   latitude=42.25999,  longitude=-121.99460,spot_price_premium=1.00, fuel_price_premium=0.95, max_vessel_dwt=None, tags='north_america'),
        dict(region='WAF',    latitude=7.35696,   longitude=0.43506,   spot_price_premium=1.15, fuel_price_premium=1.10, max_vessel_dwt=None, tags='africa,opec_adj'),
        dict(region='WAUS',   latitude=-24.30734, longitude=115.68478, spot_price_premium=1.20, fuel_price_premium=1.15, max_vessel_dwt=None, tags='pacific_rim'),
        dict(region='WCCAM',  latitude=10.76010,  longitude=-84.60013, spot_price_premium=1.00, fuel_price_premium=0.95, max_vessel_dwt=None, tags='latam,pacific_adj'),
        dict(region='WCCAN',  latitude=50.12589,  longitude=-124.79562,spot_price_premium=1.10, fuel_price_premium=1.05, max_vessel_dwt=None, tags='north_america'),
        dict(region='WCIND',  latitude=19.71253,  longitude=71.68801,  spot_price_premium=0.95, fuel_price_premium=0.88, max_vessel_dwt=None, tags='india'),
        dict(region='WCMEX',  latitude=24.28707,  longitude=-108.06046,spot_price_premium=0.95, fuel_price_premium=0.92, max_vessel_dwt=None, tags='latam,pacific_adj'),
        dict(region='WCSAM',  latitude=-22.86175, longitude=-74.72249, spot_price_premium=1.10, fuel_price_premium=1.05, max_vessel_dwt=None, tags='latam'),
    ])

def template_region_demand() -> pd.DataFrame:
    rows = [
        dict(region='CCHINA', company='CNOOC',      product='Arab Heavy', volume_mean_mmt=85.0,  volume_std_mmt=6.0,  price_mean_usd_t=385.0, price_std_usd_t=20.0, growth_rate_annual=0.045),
        dict(region='SCHINA', company='CNOOC',      product='Arab Heavy', volume_mean_mmt=70.0,  volume_std_mmt=5.0,  price_mean_usd_t=385.0, price_std_usd_t=20.0, growth_rate_annual=0.040),
        dict(region='NCHINA', company='CNOOC',      product='Urals',      volume_mean_mmt=35.0,  volume_std_mmt=4.0,  price_mean_usd_t=360.0, price_std_usd_t=22.0, growth_rate_annual=0.035),
        dict(region='KOR/JPN',company='__free__',   product='Arab Heavy', volume_mean_mmt=90.0,  volume_std_mmt=5.0,  price_mean_usd_t=390.0, price_std_usd_t=18.0, growth_rate_annual=0.005),
        dict(region='KOR/JPN',company='__free__',   product='Brent',      volume_mean_mmt=20.0,  volume_std_mmt=3.0,  price_mean_usd_t=395.0, price_std_usd_t=18.0, growth_rate_annual=0.005),
        dict(region='WCIND',  company='__free__',   product='Arab Heavy', volume_mean_mmt=55.0,  volume_std_mmt=4.0,  price_mean_usd_t=382.0, price_std_usd_t=18.0, growth_rate_annual=0.060),
        dict(region='ECIND',  company='__free__',   product='Arab Heavy', volume_mean_mmt=45.0,  volume_std_mmt=4.0,  price_mean_usd_t=382.0, price_std_usd_t=18.0, growth_rate_annual=0.060),
        dict(region='MED',    company='__free__',   product='Urals',      volume_mean_mmt=45.0,  volume_std_mmt=5.0,  price_mean_usd_t=362.0, price_std_usd_t=25.0, growth_rate_annual=0.000),
        dict(region='MED',    company='Shell',      product='Brent',      volume_mean_mmt=30.0,  volume_std_mmt=3.0,  price_mean_usd_t=392.0, price_std_usd_t=18.0, growth_rate_annual=0.000),
        dict(region='NSEA',   company='Shell',      product='Brent',      volume_mean_mmt=25.0,  volume_std_mmt=3.0,  price_mean_usd_t=392.0, price_std_usd_t=18.0, growth_rate_annual=-0.010),
        dict(region='UKC',    company='BP',         product='Brent',      volume_mean_mmt=20.0,  volume_std_mmt=2.0,  price_mean_usd_t=392.0, price_std_usd_t=18.0, growth_rate_annual=-0.005),
        dict(region='BALT',   company='Rosneft',    product='Urals',      volume_mean_mmt=18.0,  volume_std_mmt=3.0,  price_mean_usd_t=358.0, price_std_usd_t=25.0, growth_rate_annual=0.005),
        dict(region='USG',    company='ExxonMobil', product='Arab Heavy', volume_mean_mmt=40.0,  volume_std_mmt=4.0,  price_mean_usd_t=380.0, price_std_usd_t=20.0, growth_rate_annual=-0.005),
        dict(region='USG',    company='ExxonMobil', product='WTI',        volume_mean_mmt=35.0,  volume_std_mmt=3.5,  price_mean_usd_t=402.0, price_std_usd_t=22.0, growth_rate_annual=-0.005),
        dict(region='USAC',   company='ExxonMobil', product='Brent',      volume_mean_mmt=25.0,  volume_std_mmt=3.0,  price_mean_usd_t=395.0, price_std_usd_t=20.0, growth_rate_annual=-0.005),
        dict(region='USWC',   company='__free__',   product='Arab Heavy', volume_mean_mmt=18.0,  volume_std_mmt=2.0,  price_mean_usd_t=385.0, price_std_usd_t=18.0, growth_rate_annual=0.000),
        dict(region='SEASIA', company='__free__',   product='Arab Heavy', volume_mean_mmt=40.0,  volume_std_mmt=4.0,  price_mean_usd_t=383.0, price_std_usd_t=20.0, growth_rate_annual=0.040),
        dict(region='SING',   company='__free__',   product='Arab Heavy', volume_mean_mmt=22.0,  volume_std_mmt=2.5,  price_mean_usd_t=380.0, price_std_usd_t=18.0, growth_rate_annual=0.025),
        dict(region='WAF',    company='__free__',   product='Brent',      volume_mean_mmt=8.0,   volume_std_mmt=1.5,  price_mean_usd_t=390.0, price_std_usd_t=25.0, growth_rate_annual=0.020),
        dict(region='BRZL',   company='__free__',   product='WTI',        volume_mean_mmt=10.0,  volume_std_mmt=1.5,  price_mean_usd_t=400.0, price_std_usd_t=22.0, growth_rate_annual=0.015),
        dict(region='ARG',    company='__free__',   product='WTI',        volume_mean_mmt=5.0,   volume_std_mmt=1.0,  price_mean_usd_t=398.0, price_std_usd_t=22.0, growth_rate_annual=0.010),
    ]
    return pd.DataFrame(rows)

def template_region_supply() -> pd.DataFrame:
    rows = [
        dict(region='AG',    company='Saudi Aramco',product='Arab Heavy', volume_mean_mmt=185.0, volume_std_mmt=10.0, price_mean_usd_t=340.0, price_std_usd_t=15.0, growth_rate_annual=0.020),
        dict(region='AG',    company='__free__',    product='Arab Heavy', volume_mean_mmt=40.0,  volume_std_mmt=5.0,  price_mean_usd_t=342.0, price_std_usd_t=18.0, growth_rate_annual=0.015),
        dict(region='RSEA',  company='Saudi Aramco',product='Arab Heavy', volume_mean_mmt=30.0,  volume_std_mmt=4.0,  price_mean_usd_t=338.0, price_std_usd_t=15.0, growth_rate_annual=0.010),
        dict(region='BALT',  company='Rosneft',     product='Urals',      volume_mean_mmt=80.0,  volume_std_mmt=8.0,  price_mean_usd_t=330.0, price_std_usd_t=20.0, growth_rate_annual=0.000),
        dict(region='BSEA',  company='Rosneft',     product='Urals',      volume_mean_mmt=55.0,  volume_std_mmt=6.0,  price_mean_usd_t=328.0, price_std_usd_t=20.0, growth_rate_annual=0.000),
        dict(region='BSEA',  company='__free__',    product='Urals',      volume_mean_mmt=25.0,  volume_std_mmt=4.0,  price_mean_usd_t=325.0, price_std_usd_t=22.0, growth_rate_annual=0.005),
        dict(region='NSEA',  company='Shell',       product='Brent',      volume_mean_mmt=55.0,  volume_std_mmt=5.0,  price_mean_usd_t=360.0, price_std_usd_t=18.0, growth_rate_annual=-0.020),
        dict(region='NSEA',  company='BP',          product='Brent',      volume_mean_mmt=20.0,  volume_std_mmt=3.0,  price_mean_usd_t=360.0, price_std_usd_t=18.0, growth_rate_annual=-0.015),
        dict(region='WAF',   company='__free__',    product='Brent',      volume_mean_mmt=75.0,  volume_std_mmt=7.0,  price_mean_usd_t=355.0, price_std_usd_t=22.0, growth_rate_annual=0.015),
        dict(region='USG',   company='ExxonMobil',  product='WTI',        volume_mean_mmt=90.0,  volume_std_mmt=8.0,  price_mean_usd_t=375.0, price_std_usd_t=20.0, growth_rate_annual=0.010),
        dict(region='USG',   company='__free__',    product='WTI',        volume_mean_mmt=35.0,  volume_std_mmt=4.0,  price_mean_usd_t=373.0, price_std_usd_t=22.0, growth_rate_annual=0.005),
        dict(region='BRZL',  company='__free__',    product='WTI',        volume_mean_mmt=55.0,  volume_std_mmt=6.0,  price_mean_usd_t=370.0, price_std_usd_t=20.0, growth_rate_annual=0.030),
        dict(region='WCSAM', company='__free__',    product='WTI',        volume_mean_mmt=25.0,  volume_std_mmt=3.0,  price_mean_usd_t=368.0, price_std_usd_t=20.0, growth_rate_annual=0.010),
        dict(region='EAFR',  company='__free__',    product='Brent',      volume_mean_mmt=8.0,   volume_std_mmt=2.0,  price_mean_usd_t=350.0, price_std_usd_t=25.0, growth_rate_annual=0.040),
        dict(region='USWC',  company='ExxonMobil',  product='WTI',        volume_mean_mmt=15.0,  volume_std_mmt=2.0,  price_mean_usd_t=370.0, price_std_usd_t=18.0, growth_rate_annual=-0.010),
        dict(region='ALASKA',company='ExxonMobil',  product='WTI',        volume_mean_mmt=12.0,  volume_std_mmt=2.0,  price_mean_usd_t=372.0, price_std_usd_t=18.0, growth_rate_annual=-0.020),
        dict(region='SEASIA',company='__free__',    product='Arab Heavy', volume_mean_mmt=25.0,  volume_std_mmt=4.0,  price_mean_usd_t=360.0, price_std_usd_t=20.0, growth_rate_annual=0.000),
    ]
    return pd.DataFrame(rows)

def template_region_storage() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region='AG',     company='Saudi Aramco', total_mmt=120.0, available_mmt=100.0),
        dict(region='AG',     company='__free__',      total_mmt=30.0,  available_mmt=25.0),
        dict(region='RSEA',   company='__free__',      total_mmt=15.0,  available_mmt=12.0),
        dict(region='BALT',   company='Rosneft',       total_mmt=40.0,  available_mmt=35.0),
        dict(region='BSEA',   company='Rosneft',       total_mmt=25.0,  available_mmt=20.0),
        dict(region='NSEA',   company='Shell',         total_mmt=30.0,  available_mmt=25.0),
        dict(region='UKC',    company='BP',            total_mmt=25.0,  available_mmt=20.0),
        dict(region='MED',    company='__free__',      total_mmt=35.0,  available_mmt=28.0),
        dict(region='WAF',    company='__free__',      total_mmt=20.0,  available_mmt=15.0),
        dict(region='USG',    company='ExxonMobil',    total_mmt=55.0,  available_mmt=48.0),
        dict(region='USG',    company='__free__',      total_mmt=20.0,  available_mmt=18.0),
        dict(region='USAC',   company='ExxonMobil',    total_mmt=25.0,  available_mmt=22.0),
        dict(region='USWC',   company='__free__',      total_mmt=18.0,  available_mmt=15.0),
        dict(region='BRZL',   company='__free__',      total_mmt=20.0,  available_mmt=18.0),
        dict(region='SEASIA', company='__free__',      total_mmt=30.0,  available_mmt=25.0),
        dict(region='SING',   company='__free__',      total_mmt=40.0,  available_mmt=35.0),
        dict(region='CCHINA', company='CNOOC',         total_mmt=45.0,  available_mmt=38.0),
        dict(region='SCHINA', company='CNOOC',         total_mmt=35.0,  available_mmt=30.0),
        dict(region='KOR/JPN',company='__free__',      total_mmt=30.0,  available_mmt=25.0),
    ])

def template_port_times() -> pd.DataFrame:
    rows = []
    all_regions = [r['region'] for r in template_regions().to_dict('records')]
    for code in all_regions:
        rows.append(dict(region=code, ship_type='__default__',
            load_mean_days=1.5, load_std_days=0.3,
            unload_mean_days=1.5, unload_std_days=0.3,
            bunker_mean_days=0.5, bunker_std_days=0.1))
    for code in ['AG','RSEA','NSEA','WAF','USG','BRZL']:
        rows.append(dict(region=code, ship_type='VLCC',
            load_mean_days=2.0, load_std_days=0.4,
            unload_mean_days=2.0, unload_std_days=0.4,
            bunker_mean_days=0.7, bunker_std_days=0.15))
    for code in ['ARCTIC','ALASKA']:
        rows.append(dict(region=code, ship_type='__default__',
            load_mean_days=3.0, load_std_days=0.8,
            unload_mean_days=2.5, unload_std_days=0.6,
            bunker_mean_days=1.0, bunker_std_days=0.3))
    return pd.DataFrame(rows)

def load_regions(df_regions, df_demand, df_supply, df_storage, df_port_times) -> Dict[str, Region]:
    regions: Dict[str, Region] = {}
    for _, row in df_regions.iterrows():
        name = str(row["region"])
        regions[name] = Region(
            name=name,
            latitude=float(_get(row, "latitude", 0.0)),
            longitude=float(_get(row, "longitude", 0.0)),
            spot_price_premium=float(_get(row, "spot_price_premium", 1.0)),
            fuel_price_premium=float(_get(row, "fuel_price_premium", 1.0)),
            max_vessel_dwt=_get(row, "max_vessel_dwt"),
            tags=_split(_get(row, "tags", "")),
        )
    for _, row in df_demand.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        cv = CompanyVolume(product=str(row["product"]),
            volume=_ms(row, "volume_mean_mmt", "volume_std_mmt"),
            price=_ms(row, "price_mean_usd_t", "price_std_usd_t"))
        company_key = str(row["company"])
        r.demand[company_key] = cv
        r.demand_growth.by_entity[company_key] = float(_get(row, "growth_rate_annual", 0.0))
        cv._seasonal = _seasonal(row, "season")
    for _, row in df_supply.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        cv = CompanyVolume(product=str(row["product"]),
            volume=_ms(row, "volume_mean_mmt", "volume_std_mmt"),
            price=_ms(row, "price_mean_usd_t", "price_std_usd_t"))
        company_key = str(row["company"])
        r.supply[company_key] = cv
        r.supply_growth.by_entity[company_key] = float(_get(row, "growth_rate_annual", 0.0))
        cv._seasonal = _seasonal(row, "season")
    for _, row in df_storage.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        r.storage[str(row["company"])] = StorageSlot(
            total_mmt=float(_get(row, "total_mmt", 0.0)),
            available_mmt=float(_get(row, "available_mmt", 0.0)))
    for _, row in df_port_times.iterrows():
        r = regions.get(str(row["region"]))
        if r is None: continue
        r.port_times[str(row["ship_type"])] = PortTime(
            load_days=_ms(row, "load_mean_days", "load_std_days", 1.0, 0.2),
            unload_days=_ms(row, "unload_mean_days", "unload_std_days", 1.0, 0.2),
            bunker_days=_ms(row, "bunker_mean_days", "bunker_std_days", 0.5, 0.1))
    return regions


# ══════════════════════════════════════════════════════════════════════════════
# 3. NETWORK — NODES & EDGES (with gateways)
# ══════════════════════════════════════════════════════════════════════════════

def template_nodes() -> pd.DataFrame:
    """
    Region port nodes + 10 strategic chokepoints.
    is_gateway=True nodes (Suez, Gibraltar, Panama, Malacca/Singapore) trigger
    alternate routing when closed.
    """
    region_nodes = [
        dict(node_id=code, node_type='port', region_name=code,
             transit_time_mean_days=0.5, transit_time_std_days=0.1,
             max_vessels_per_period=None, max_vessel_dwt=None, is_open=True, is_gateway=False)
        for code in [r['region'] for r in template_regions().to_dict('records')]
    ]
    chokepoints = [
        dict(node_id='Suez Canal',         node_type='canal',   region_name=None, max_vessels_per_period=450,  transit_time_mean_days=1.0,  transit_time_std_days=0.3, max_vessel_dwt=240000, is_open=True, is_gateway=True),
        dict(node_id='Strait of Hormuz',   node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.5,  transit_time_std_days=0.1, max_vessel_dwt=None,   is_open=True, is_gateway=True),
        dict(node_id='Strait of Malacca',  node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.75, transit_time_std_days=0.2, max_vessel_dwt=300000, is_open=True, is_gateway=True),
        dict(node_id='Gibraltar Strait',   node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.25, transit_time_std_days=0.1, max_vessel_dwt=None,   is_open=True, is_gateway=True),
        dict(node_id='Panama Canal',       node_type='canal',   region_name=None, max_vessels_per_period=200,  transit_time_mean_days=1.0,  transit_time_std_days=0.4, max_vessel_dwt=120000, is_open=True, is_gateway=True),
        dict(node_id='Singapore Strait',   node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.3,  transit_time_std_days=0.1, max_vessel_dwt=None,   is_open=True, is_gateway=True),
        dict(node_id='Danish Straits',     node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.25, transit_time_std_days=0.1, max_vessel_dwt=150000, is_open=True, is_gateway=True),
        dict(node_id='Bab el-Mandeb',      node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.3,  transit_time_std_days=0.1, max_vessel_dwt=None,   is_open=True, is_gateway=True),
        dict(node_id='Turkish Straits',    node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.5,  transit_time_std_days=0.2, max_vessel_dwt=150000, is_open=True, is_gateway=False),
        dict(node_id='Cape of Good Hope',  node_type='open_sea',region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.0,  transit_time_std_days=0.0, max_vessel_dwt=None,   is_open=True, is_gateway=False),
        dict(node_id='Cape Horn',          node_type='open_sea',region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.0,  transit_time_std_days=0.0, max_vessel_dwt=None,   is_open=True, is_gateway=False),
        dict(node_id='Lombok Strait',      node_type='strait',  region_name=None, max_vessels_per_period=None, transit_time_mean_days=0.5,  transit_time_std_days=0.1, max_vessel_dwt=None,   is_open=True, is_gateway=False),
    ]
    return pd.DataFrame(region_nodes + chokepoints)

def template_edges() -> pd.DataFrame:
    """
    Key directed routing edges.
    requires_nodes: gateways that must be open for this edge to be available.
    alternate_for:  gateways this edge bypasses when they're closed.
    Speed baseline: 14 kn → 1nm ≈ 0.00298 days.
    """
    rows = [
        # ── Persian Gulf (AG) primary routes ──
        dict(from_node='AG', to_node='MED',     distance_nm=6500,  base_transit_mean_days=19.5, base_transit_std_days=2.0,  requires_nodes='Strait of Hormuz,Bab el-Mandeb,Suez Canal', alternate_for=''),
        dict(from_node='AG', to_node='MED',     distance_nm=14000, base_transit_mean_days=42.0, base_transit_std_days=3.0,  requires_nodes='Strait of Hormuz,Cape of Good Hope',         alternate_for='Suez Canal,Bab el-Mandeb'),
        dict(from_node='AG', to_node='RSEA',    distance_nm=1500,  base_transit_mean_days=4.5,  base_transit_std_days=0.5,  requires_nodes='Strait of Hormuz,Bab el-Mandeb',             alternate_for=''),
        dict(from_node='AG', to_node='SEASIA',  distance_nm=5500,  base_transit_mean_days=16.5, base_transit_std_days=1.5,  requires_nodes='Strait of Hormuz,Strait of Malacca',         alternate_for=''),
        dict(from_node='AG', to_node='SEASIA',  distance_nm=7200,  base_transit_mean_days=21.6, base_transit_std_days=2.0,  requires_nodes='Strait of Hormuz,Lombok Strait',             alternate_for='Strait of Malacca'),
        dict(from_node='AG', to_node='SING',    distance_nm=5700,  base_transit_mean_days=17.1, base_transit_std_days=1.5,  requires_nodes='Strait of Hormuz,Singapore Strait',          alternate_for=''),
        dict(from_node='AG', to_node='SCHINA',  distance_nm=6200,  base_transit_mean_days=18.6, base_transit_std_days=1.8,  requires_nodes='Strait of Hormuz,Strait of Malacca',         alternate_for=''),
        dict(from_node='AG', to_node='CCHINA',  distance_nm=6500,  base_transit_mean_days=19.5, base_transit_std_days=2.0,  requires_nodes='Strait of Hormuz,Strait of Malacca',         alternate_for=''),
        dict(from_node='AG', to_node='KOR/JPN', distance_nm=7000,  base_transit_mean_days=21.0, base_transit_std_days=2.0,  requires_nodes='Strait of Hormuz,Strait of Malacca',         alternate_for=''),
        dict(from_node='AG', to_node='USG',     distance_nm=17000, base_transit_mean_days=51.0, base_transit_std_days=4.0,  requires_nodes='Strait of Hormuz,Cape of Good Hope',         alternate_for=''),
        dict(from_node='AG', to_node='EAFR',    distance_nm=3800,  base_transit_mean_days=11.4, base_transit_std_days=1.2,  requires_nodes='Strait of Hormuz',                           alternate_for=''),
        # ── Red Sea ──
        dict(from_node='RSEA', to_node='MED',   distance_nm=3200,  base_transit_mean_days=9.6,  base_transit_std_days=1.0,  requires_nodes='Bab el-Mandeb,Suez Canal',                   alternate_for=''),
        dict(from_node='RSEA', to_node='MED',   distance_nm=12000, base_transit_mean_days=36.0, base_transit_std_days=3.0,  requires_nodes='Cape of Good Hope',                          alternate_for='Suez Canal,Bab el-Mandeb'),
        dict(from_node='RSEA', to_node='NSEA',  distance_nm=8500,  base_transit_mean_days=25.5, base_transit_std_days=2.5,  requires_nodes='Bab el-Mandeb,Suez Canal,Gibraltar Strait',  alternate_for=''),
        dict(from_node='RSEA', to_node='UKC',   distance_nm=8800,  base_transit_mean_days=26.4, base_transit_std_days=2.5,  requires_nodes='Bab el-Mandeb,Suez Canal,Gibraltar Strait',  alternate_for=''),
        # ── Black Sea / Baltic ──
        dict(from_node='BSEA', to_node='MED',   distance_nm=1200,  base_transit_mean_days=3.6,  base_transit_std_days=0.5,  requires_nodes='Turkish Straits',                            alternate_for=''),
        dict(from_node='BALT', to_node='NSEA',  distance_nm=900,   base_transit_mean_days=2.7,  base_transit_std_days=0.4,  requires_nodes='Danish Straits',                             alternate_for=''),
        dict(from_node='BALT', to_node='UKC',   distance_nm=1200,  base_transit_mean_days=3.6,  base_transit_std_days=0.5,  requires_nodes='Danish Straits',                             alternate_for=''),
        dict(from_node='BALT', to_node='MED',   distance_nm=4500,  base_transit_mean_days=13.5, base_transit_std_days=1.5,  requires_nodes='Danish Straits,Gibraltar Strait',            alternate_for=''),
        # ── North Sea / UK ──
        dict(from_node='NSEA', to_node='MED',   distance_nm=3800,  base_transit_mean_days=11.4, base_transit_std_days=1.0,  requires_nodes='Gibraltar Strait',                           alternate_for=''),
        dict(from_node='NSEA', to_node='USG',   distance_nm=7500,  base_transit_mean_days=22.5, base_transit_std_days=2.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='UKC',  to_node='MED',   distance_nm=3600,  base_transit_mean_days=10.8, base_transit_std_days=1.0,  requires_nodes='Gibraltar Strait',                           alternate_for=''),
        # ── West Africa ──
        dict(from_node='WAF',  to_node='MED',   distance_nm=3500,  base_transit_mean_days=10.5, base_transit_std_days=1.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='WAF',  to_node='UKC',   distance_nm=3800,  base_transit_mean_days=11.4, base_transit_std_days=1.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='WAF',  to_node='USG',   distance_nm=5200,  base_transit_mean_days=15.6, base_transit_std_days=1.5,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='WAF',  to_node='USAC',  distance_nm=5000,  base_transit_mean_days=15.0, base_transit_std_days=1.5,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='WAF',  to_node='BRZL',  distance_nm=3200,  base_transit_mean_days=9.6,  base_transit_std_days=1.0,  requires_nodes='',                                           alternate_for=''),
        # ── Americas ──
        dict(from_node='USG',  to_node='USAC',  distance_nm=1800,  base_transit_mean_days=5.4,  base_transit_std_days=0.6,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='USG',  to_node='MED',   distance_nm=7800,  base_transit_mean_days=23.4, base_transit_std_days=2.0,  requires_nodes='Gibraltar Strait',                           alternate_for=''),
        dict(from_node='WCSAM',to_node='USG',   distance_nm=5500,  base_transit_mean_days=16.5, base_transit_std_days=1.5,  requires_nodes='Panama Canal',                               alternate_for=''),
        dict(from_node='WCSAM',to_node='USG',   distance_nm=12000, base_transit_mean_days=36.0, base_transit_std_days=3.0,  requires_nodes='Cape Horn',                                  alternate_for='Panama Canal'),
        dict(from_node='BRZL', to_node='NSEA',  distance_nm=8000,  base_transit_mean_days=24.0, base_transit_std_days=2.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='BRZL', to_node='MED',   distance_nm=6500,  base_transit_mean_days=19.5, base_transit_std_days=2.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='USWC', to_node='SEASIA',distance_nm=7700,  base_transit_mean_days=23.1, base_transit_std_days=2.0,  requires_nodes='',                                           alternate_for=''),
        dict(from_node='USWC', to_node='KOR/JPN',distance_nm=4700, base_transit_mean_days=14.1, base_transit_std_days=1.5,  requires_nodes='',                                           alternate_for=''),
        # ── Southeast Asia ──
        dict(from_node='SEASIA',to_node='MED',  distance_nm=11500, base_transit_mean_days=34.5, base_transit_std_days=3.0,  requires_nodes='Strait of Malacca,Suez Canal',               alternate_for=''),
        dict(from_node='SEASIA',to_node='NSEA', distance_nm=13000, base_transit_mean_days=39.0, base_transit_std_days=3.5,  requires_nodes='Strait of Malacca,Suez Canal,Gibraltar Strait',alternate_for=''),
        dict(from_node='SEASIA',to_node='UKC',  distance_nm=13500, base_transit_mean_days=40.5, base_transit_std_days=3.5,  requires_nodes='Strait of Malacca,Suez Canal,Gibraltar Strait',alternate_for=''),
        dict(from_node='SING',  to_node='MED',  distance_nm=11200, base_transit_mean_days=33.6, base_transit_std_days=3.0,  requires_nodes='Singapore Strait,Suez Canal',               alternate_for=''),
        dict(from_node='SING',  to_node='USG',  distance_nm=18000, base_transit_mean_days=54.0, base_transit_std_days=4.5,  requires_nodes='Singapore Strait,Cape of Good Hope',        alternate_for=''),
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
            is_gateway=bool(_get(row, "is_gateway", False)),
        )
    return out

def load_edges(df: pd.DataFrame) -> list:
    out = []
    for _, row in df.iterrows():
        out.append(Edge(
            from_node=str(row["from_node"]),
            to_node=str(row["to_node"]),
            distance_nm=float(_get(row, "distance_nm", 0)),
            base_transit_days=_ms(row, "base_transit_mean_days", "base_transit_std_days", 5.0, 0.5),
            requires_nodes=_split(_get(row, "requires_nodes", "")),
            alternate_for=_split(_get(row, "alternate_for", "")),
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 4. COMPANIES
# ══════════════════════════════════════════════════════════════════════════════

def template_companies() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name='Saudi Aramco', supply_regions='AG,RSEA',            demand_regions='MED,SEASIA,SING,KOR/JPN,CCHINA,SCHINA,NCHINA', supply_growth_default=0.02, demand_growth_default=0.02, supply_volatility=0.05, demand_volatility=0.05, wtp_spot=32000, contract_fraction=0.70, is_sanctioned=False, associated_countries='uae',             tags='opec,gulf'),
        dict(name='Shell',        supply_regions='NSEA,WAF',           demand_regions='NSEA,MED,UKC,USG',                              supply_growth_default=0.01, demand_growth_default=0.01, supply_volatility=0.08, demand_volatility=0.08, wtp_spot=30000, contract_fraction=0.60, is_sanctioned=False, associated_countries='other_western',    tags='western,ioc'),
        dict(name='ExxonMobil',   supply_regions='USG,USWC,ALASKA',    demand_regions='USG,USAC,USWC,MED',                             supply_growth_default=0.01, demand_growth_default=0.01, supply_volatility=0.08, demand_volatility=0.08, wtp_spot=29000, contract_fraction=0.65, is_sanctioned=False, associated_countries='usa',             tags='western,ioc,us'),
        dict(name='BP',           supply_regions='NSEA',               demand_regions='NSEA,UKC,MED',                                  supply_growth_default=0.00, demand_growth_default=0.00, supply_volatility=0.10, demand_volatility=0.10, wtp_spot=28000, contract_fraction=0.60, is_sanctioned=False, associated_countries='other_western',    tags='western,ioc'),
        dict(name='Rosneft',      supply_regions='BALT,BSEA',          demand_regions='MED,SEASIA,CCHINA,SCHINA',                      supply_growth_default=0.01, demand_growth_default=0.01, supply_volatility=0.12, demand_volatility=0.12, wtp_spot=25000, contract_fraction=0.50, is_sanctioned=False, associated_countries='russia',           tags='russian,noc,sanctionable'),
        dict(name='CNOOC',        supply_regions='SEASIA,CCHINA,SCHINA,NCHINA', demand_regions='CCHINA,SCHINA,NCHINA,KOR/JPN',         supply_growth_default=0.04, demand_growth_default=0.04, supply_volatility=0.08, demand_volatility=0.08, wtp_spot=28000, contract_fraction=0.55, is_sanctioned=False, associated_countries='china',            tags='chinese,noc'),
        dict(name='Independent',  supply_regions='',                   demand_regions='',                                              supply_growth_default=0.02, demand_growth_default=0.02, supply_volatility=0.20, demand_volatility=0.20, wtp_spot=35000, contract_fraction=0.20, is_sanctioned=False, associated_countries='',                tags='spot,independent'),
    ])

def load_companies(df: pd.DataFrame) -> Dict[str, OilCompany]:
    out = {}
    for _, row in df.iterrows():
        name = str(row["name"])
        countries_raw = _split(_get(row, "associated_countries", ""))
        countries = []
        for c in countries_raw:
            try: countries.append(ShipCountry(c))
            except ValueError: pass
        out[name] = OilCompany(
            name=name,
            supply_regions=_split(_get(row, "supply_regions", "")),
            demand_regions=_split(_get(row, "demand_regions", "")),
            supply_growth=GrowthRate(default=float(_get(row, "supply_growth_default", 0.02))),
            demand_growth=GrowthRate(default=float(_get(row, "demand_growth_default", 0.02))),
            supply_volatility=float(_get(row, "supply_volatility", 0.05)),
            demand_volatility=float(_get(row, "demand_volatility", 0.05)),
            wtp_spot=float(_get(row, "wtp_spot", 30000)),
            contract_fraction=float(_get(row, "contract_fraction", 0.60)),
            is_sanctioned=bool(_get(row, "is_sanctioned", False)),
            associated_countries=countries,
            tags=_split(_get(row, "tags", "")),
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5. VESSEL GROUP SYSTEM  (new in v3)
# ══════════════════════════════════════════════════════════════════════════════

def template_vessel_groups() -> pd.DataFrame:
    """
    Defines all vessel group dimensions and their values.
    group_id is the unique key used everywhere (in vessel_group_members, constraints, etc).
    """
    return pd.DataFrame([
        # ── Size class ──
        dict(group_id='class:vlcc',    dimension='class',    label='VLCC',       description='Very Large Crude Carrier 200k-320k DWT', color='#00e5ff', map_radius=9,  sort_order=1),
        dict(group_id='class:suezmax', dimension='class',    label='Suezmax',    description='120k-200k DWT, Suez-capable',             color='#4ade80', map_radius=7,  sort_order=2),
        dict(group_id='class:aframax', dimension='class',    label='Aframax',    description='80k-120k DWT',                            color='#ffd23f', map_radius=5,  sort_order=3),
        dict(group_id='class:panamax', dimension='class',    label='Panamax',    description='55k-80k DWT, old-Panama-capable',         color='#fb923c', map_radius=4,  sort_order=4),
        dict(group_id='class:mr',      dimension='class',    label='MR Tanker',  description='Medium Range 25k-55k DWT',                color='#94a3b8', map_radius=3,  sort_order=5),
        dict(group_id='class:lr1',     dimension='class',    label='LR1',        description='Long Range 1, 45k-80k DWT',               color='#c084fc', map_radius=4,  sort_order=6),
        dict(group_id='class:lr2',     dimension='class',    label='LR2',        description='Long Range 2, 80k-160k DWT',              color='#818cf8', map_radius=6,  sort_order=7),
        # ── Flag / registry ──
        dict(group_id='flag:russia',   dimension='flag',     label='Russian flag',    description='Registered in Russia or Russian-controlled registry', color='#f472b6', map_radius=0, sort_order=10),
        dict(group_id='flag:china',    dimension='flag',     label='Chinese flag',    description='PRC-registered vessels',                             color='#f87171', map_radius=0, sort_order=11),
        dict(group_id='flag:greece',   dimension='flag',     label='Greek flag',      description='Greek-registered',                                   color='',        map_radius=0, sort_order=12),
        dict(group_id='flag:norway',   dimension='flag',     label='Norwegian flag',  description='Norwegian-registered',                               color='',        map_radius=0, sort_order=13),
        dict(group_id='flag:usa',      dimension='flag',     label='US flag',         description='US-flagged (Jones Act etc.)',                         color='',        map_radius=0, sort_order=14),
        dict(group_id='flag:shadow',   dimension='flag',     label='Shadow fleet',    description='Unverifiable flag, sanctions-grey zone',             color='#6b7280', map_radius=0, sort_order=15),
        dict(group_id='flag:western',  dimension='flag',     label='Western flag',    description='EU/UK/US/Norway/Japan/Korea flagged',                 color='',        map_radius=0, sort_order=16),
        dict(group_id='flag:other',    dimension='flag',     label='Other flag',      description='Remaining flags',                                    color='',        map_radius=0, sort_order=17),
        # ── Build country ──
        dict(group_id='build:korea',   dimension='build',    label='Korean-built',    description='Built in South Korean shipyards (HHI, DSME, SHI)', color='', map_radius=0, sort_order=20),
        dict(group_id='build:china',   dimension='build',    label='Chinese-built',   description='Built in Chinese yards',                           color='', map_radius=0, sort_order=21),
        dict(group_id='build:japan',   dimension='build',    label='Japanese-built',  description='Built in Japanese yards',                          color='', map_radius=0, sort_order=22),
        dict(group_id='build:europe',  dimension='build',    label='European-built',  description='Built in European yards',                          color='', map_radius=0, sort_order=23),
        # ── Scrubber ──
        dict(group_id='scrubber:yes',  dimension='scrubber', label='Scrubber fitted', description='Exhaust gas cleaning system installed',           color='', map_radius=0, sort_order=30),
        dict(group_id='scrubber:no',   dimension='scrubber', label='No scrubber',     description='VLSFO-only compliance',                          color='', map_radius=0, sort_order=31),
        # ── STS capability ──
        dict(group_id='sts:capable',   dimension='sts',      label='STS capable',     description='Ship-to-ship transfer equipped',                  color='', map_radius=0, sort_order=40),
        dict(group_id='sts:no',        dimension='sts',      label='No STS',          description='Cannot perform ship-to-ship transfers',           color='', map_radius=0, sort_order=41),
        # ── Commercial mode ──
        dict(group_id='trade:spot',    dimension='trade',    label='Spot market',     description='Available for spot fixtures anywhere',            color='#39ff14', map_radius=0, sort_order=50),
        dict(group_id='trade:contract',dimension='trade',    label='Contract',        description='Dedicated to long-term contract trades',          color='',        map_radius=0, sort_order=51),
        dict(group_id='trade:captive', dimension='trade',    label='Captive fleet',   description='Owner-dedicated, not available to spot market',   color='',        map_radius=0, sort_order=52),
        # ── Age ──
        dict(group_id='age:new',       dimension='age',      label='New (<5yr)',       description='Under 5 years old',                              color='', map_radius=0, sort_order=60),
        dict(group_id='age:mid',       dimension='age',      label='Mid-life (5-15yr)',description='5-15 years old',                                 color='', map_radius=0, sort_order=61),
        dict(group_id='age:old',       dimension='age',      label='Old (>15yr)',      description='Over 15 years old, scrapping candidates',        color='', map_radius=0, sort_order=62),
    ])

def template_vessel_group_members() -> pd.DataFrame:
    """
    Many-to-many: (vessel_id, group_id, step_from, step_to).
    vessel_id matches fleet.vessel_id.
    step_from / step_to: inclusive step range; blank = always active.
    """
    return pd.DataFrame([
        # VLCC_KR — Korean-built VLCC, western flag, no scrubber, spot capable
        dict(vessel_id='VLCC_KR',          group_id='class:vlcc',    step_from=None, step_to=None),
        dict(vessel_id='VLCC_KR',          group_id='build:korea',   step_from=None, step_to=None),
        dict(vessel_id='VLCC_KR',          group_id='flag:western',  step_from=None, step_to=None),
        dict(vessel_id='VLCC_KR',          group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='VLCC_KR',          group_id='trade:contract',step_from=None, step_to=None),
        # VLCC_scrubber_KR — same but with scrubber
        dict(vessel_id='VLCC_scrubber_KR', group_id='class:vlcc',    step_from=None, step_to=None),
        dict(vessel_id='VLCC_scrubber_KR', group_id='build:korea',   step_from=None, step_to=None),
        dict(vessel_id='VLCC_scrubber_KR', group_id='flag:western',  step_from=None, step_to=None),
        dict(vessel_id='VLCC_scrubber_KR', group_id='scrubber:yes',  step_from=None, step_to=None),
        dict(vessel_id='VLCC_scrubber_KR', group_id='trade:contract',step_from=None, step_to=None),
        # VLCC_CN — Chinese-built, Chinese flag, no scrubber, spot
        dict(vessel_id='VLCC_CN',          group_id='class:vlcc',    step_from=None, step_to=None),
        dict(vessel_id='VLCC_CN',          group_id='build:china',   step_from=None, step_to=None),
        dict(vessel_id='VLCC_CN',          group_id='flag:china',    step_from=None, step_to=None),
        dict(vessel_id='VLCC_CN',          group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='VLCC_CN',          group_id='trade:spot',    step_from=None, step_to=None),
        # Suezmax_KR
        dict(vessel_id='Suezmax_KR',       group_id='class:suezmax', step_from=None, step_to=None),
        dict(vessel_id='Suezmax_KR',       group_id='build:korea',   step_from=None, step_to=None),
        dict(vessel_id='Suezmax_KR',       group_id='flag:western',  step_from=None, step_to=None),
        dict(vessel_id='Suezmax_KR',       group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='Suezmax_KR',       group_id='trade:spot',    step_from=None, step_to=None),
        # Aframax_GR
        dict(vessel_id='Aframax_GR',       group_id='class:aframax', step_from=None, step_to=None),
        dict(vessel_id='Aframax_GR',       group_id='flag:greece',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_GR',       group_id='build:korea',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_GR',       group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_GR',       group_id='trade:spot',    step_from=None, step_to=None),
        # Aframax_RU — Russian-flag, can enter shadow zone from step 12
        dict(vessel_id='Aframax_RU',       group_id='class:aframax', step_from=None, step_to=None),
        dict(vessel_id='Aframax_RU',       group_id='flag:russia',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_RU',       group_id='build:europe',  step_from=None, step_to=None),
        dict(vessel_id='Aframax_RU',       group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_RU',       group_id='sts:capable',   step_from=None, step_to=None),
        dict(vessel_id='Aframax_RU',       group_id='trade:contract',step_from=None, step_to=11),   # step 0-11 contract
        dict(vessel_id='Aframax_RU',       group_id='trade:spot',    step_from=12,   step_to=None), # step 12+ spot/shadow
        dict(vessel_id='Aframax_RU',       group_id='flag:shadow',   step_from=12,   step_to=None), # becomes shadow fleet
        # MR_NO
        dict(vessel_id='MR_NO',            group_id='class:mr',      step_from=None, step_to=None),
        dict(vessel_id='MR_NO',            group_id='flag:norway',   step_from=None, step_to=None),
        dict(vessel_id='MR_NO',            group_id='build:korea',   step_from=None, step_to=None),
        dict(vessel_id='MR_NO',            group_id='scrubber:no',   step_from=None, step_to=None),
        dict(vessel_id='MR_NO',            group_id='trade:spot',    step_from=None, step_to=None),
    ])

def load_vessel_groups(df: pd.DataFrame) -> Dict[str, VesselGroup]:
    out = {}
    for _, row in df.iterrows():
        gid = str(row["group_id"])
        out[gid] = VesselGroup(
            group_id=gid,
            dimension=str(_get(row, "dimension", "")),
            label=str(_get(row, "label", gid)),
            description=str(_get(row, "description", "")),
            color=str(_get(row, "color", "")),
            map_radius=int(_get(row, "map_radius", 0)),
            sort_order=int(_get(row, "sort_order", 99)),
        )
    return out

def load_vessel_group_members(df: pd.DataFrame) -> List[VesselGroupMembership]:
    out = []
    for _, row in df.iterrows():
        sf = _get(row, "step_from")
        st = _get(row, "step_to")
        out.append(VesselGroupMembership(
            vessel_id=str(row["vessel_id"]),
            group_id=str(row["group_id"]),
            step_from=int(sf) if sf is not None and not (isinstance(sf, float) and np.isnan(sf)) else None,
            step_to=int(st) if st is not None and not (isinstance(st, float) and np.isnan(st)) else None,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 6. SHIP TYPES & FLEET
# ══════════════════════════════════════════════════════════════════════════════

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
        dict(name="VLCC_KR",          group="VLCC",    dwt_mean=300_000, dwt_std=5000,  speed_mean_kn=15.5, speed_std_kn=0.5, daily_opex_mean=8500,  daily_opex_std=500, fuel_cons_t_day=90.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=120.0, scrap_value_musd=30.0, build_time_years=2.5, build_time_std_years=0.25, economic_life_years=25.0, can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="VLCC_scrubber_KR", group="VLCC",    dwt_mean=300_000, dwt_std=5000,  speed_mean_kn=15.5, speed_std_kn=0.5, daily_opex_mean=9200,  daily_opex_std=500, fuel_cons_t_day=90.0, fuel_ballast_factor=0.75, scrubber_fitted=True,  build_cost_musd=125.0, scrap_value_musd=30.0, build_time_years=2.5, build_time_std_years=0.25, economic_life_years=25.0, can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="VLCC_CN",          group="VLCC",    dwt_mean=298_000, dwt_std=6000,  speed_mean_kn=15.2, speed_std_kn=0.6, daily_opex_mean=7800,  daily_opex_std=600, fuel_cons_t_day=92.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=105.0, scrap_value_musd=28.0, build_time_years=2.0, build_time_std_years=0.20, economic_life_years=22.0, can_be_storage=True, country="china",       compatible_products=""),
        dict(name="Suezmax_KR",       group="Suezmax", dwt_mean=158_000, dwt_std=3000,  speed_mean_kn=15.0, speed_std_kn=0.4, daily_opex_mean=6500,  daily_opex_std=400, fuel_cons_t_day=58.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=78.0,  scrap_value_musd=18.0, build_time_years=2.0, build_time_std_years=0.20, economic_life_years=25.0, can_be_storage=True, country="south_korea", compatible_products=""),
        dict(name="Aframax_GR",       group="Aframax", dwt_mean=105_000, dwt_std=2000,  speed_mean_kn=14.5, speed_std_kn=0.4, daily_opex_mean=5200,  daily_opex_std=350, fuel_cons_t_day=44.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=56.0,  scrap_value_musd=12.0, build_time_years=1.8, build_time_std_years=0.20, economic_life_years=25.0, can_be_storage=False,country="greece",      compatible_products=""),
        dict(name="Aframax_RU",       group="Aframax", dwt_mean=100_000, dwt_std=3000,  speed_mean_kn=14.2, speed_std_kn=0.5, daily_opex_mean=4800,  daily_opex_std=400, fuel_cons_t_day=46.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=48.0,  scrap_value_musd=10.0, build_time_years=2.2, build_time_std_years=0.30, economic_life_years=20.0, can_be_storage=False,country="russia",      compatible_products="Urals"),
        dict(name="MR_NO",            group="MR",      dwt_mean=47_000,  dwt_std=1500,  speed_mean_kn=14.0, speed_std_kn=0.3, daily_opex_mean=3500,  daily_opex_std=300, fuel_cons_t_day=30.0, fuel_ballast_factor=0.75, scrubber_fitted=False, build_cost_musd=38.0,  scrap_value_musd=7.0,  build_time_years=1.5, build_time_std_years=0.20, economic_life_years=25.0, can_be_storage=False,country="norway",      compatible_products=""),
    ])

def template_fleet() -> pd.DataFrame:
    return pd.DataFrame([
        dict(vessel_id='VLCC_KR',          ship_type='VLCC_KR',          owner='Saudi Aramco', count=6,  count_storage=0, avg_age_years=6.0),
        dict(vessel_id='VLCC_scrubber_KR', ship_type='VLCC_scrubber_KR', owner='Saudi Aramco', count=3,  count_storage=0, avg_age_years=3.0),
        dict(vessel_id='VLCC_CN',          ship_type='VLCC_CN',          owner='CNOOC',        count=5,  count_storage=0, avg_age_years=4.0),
        dict(vessel_id='VLCC_KR_IND',      ship_type='VLCC_KR',          owner='Independent',  count=8,  count_storage=0, avg_age_years=10.0),
        dict(vessel_id='Suezmax_KR',       ship_type='Suezmax_KR',       owner='Shell',        count=6,  count_storage=0, avg_age_years=8.0),
        dict(vessel_id='Suezmax_KR_BP',    ship_type='Suezmax_KR',       owner='BP',           count=4,  count_storage=0, avg_age_years=7.0),
        dict(vessel_id='Suezmax_KR_IND',   ship_type='Suezmax_KR',       owner='Independent',  count=10, count_storage=0, avg_age_years=12.0),
        dict(vessel_id='Aframax_GR_BP',    ship_type='Aframax_GR',       owner='BP',           count=5,  count_storage=0, avg_age_years=9.0),
        dict(vessel_id='Aframax_GR_EMB',   ship_type='Aframax_GR',       owner='ExxonMobil',   count=4,  count_storage=0, avg_age_years=8.0),
        dict(vessel_id='Aframax_RU',       ship_type='Aframax_RU',       owner='Rosneft',      count=8,  count_storage=0, avg_age_years=7.0),
        dict(vessel_id='Aframax_GR_IND',   ship_type='Aframax_GR',       owner='Independent',  count=12, count_storage=0, avg_age_years=14.0),
        dict(vessel_id='MR_NO',            ship_type='MR_NO',            owner='Shell',        count=4,  count_storage=0, avg_age_years=6.0),
        dict(vessel_id='MR_NO_IND',        ship_type='MR_NO',            owner='Independent',  count=9,  count_storage=0, avg_age_years=11.0),
    ])

def load_ship_types(df: pd.DataFrame) -> Dict[str, ShipType]:
    out = {}
    for _, row in df.iterrows():
        name = str(row["name"])
        prods_raw = _get(row, "compatible_products", "")
        prods = _split(str(prods_raw)) if prods_raw else []
        try: country = ShipCountry(_get(row, "country", "other_western"))
        except ValueError: country = ShipCountry.OTHER_WESTERN
        out[name] = ShipType(
            name=name, group=str(_get(row, "group", "")),
            dwt=_ms(row, "dwt_mean", "dwt_std", 300_000, 5_000),
            speed_knots=_ms(row, "speed_mean_kn", "speed_std_kn", 15.0, 0.5),
            daily_opex=_ms(row, "daily_opex_mean", "daily_opex_std", 8_000, 500),
            fuel_consumption_tons_day=float(_get(row, "fuel_cons_t_day", 60.0)),
            fuel_consumption_ballast_factor=float(_get(row, "fuel_ballast_factor", 0.75)),
            scrubber_fitted=bool(_get(row, "scrubber_fitted", False)),
            build_cost_musd=float(_get(row, "build_cost_musd", 100.0)),
            scrap_value_musd=float(_get(row, "scrap_value_musd", 20.0)),
            build_time_years=float(_get(row, "build_time_years", 2.5)),
            build_time_std_years=float(_get(row, "build_time_std_years", 0.25)),
            economic_life_years=float(_get(row, "economic_life_years", 25.0)),
            can_be_storage=bool(_get(row, "can_be_storage", True)),
            country=country, compatible_products=prods,
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 7. ORDERBOOK
# ══════════════════════════════════════════════════════════════════════════════

def template_orderbook() -> pd.DataFrame:
    return pd.DataFrame([
        dict(ship_type="VLCC_KR",          owner="Saudi Aramco", delivery_year=2026, delivery_month=3, count=2, build_cost_musd=120.0, shipyard_country="south_korea"),
        dict(ship_type="VLCC_CN",          owner="CNOOC",        delivery_year=2026, delivery_month=6, count=3, build_cost_musd=106.0, shipyard_country="china"),
        dict(ship_type="Suezmax_KR",       owner="Independent",  delivery_year=2026, delivery_month=9, count=2, build_cost_musd=78.0,  shipyard_country="south_korea"),
        dict(ship_type="Aframax_GR",       owner="BP",           delivery_year=2025, delivery_month=12,count=1, build_cost_musd=56.0,  shipyard_country="south_korea"),
        dict(ship_type="VLCC_scrubber_KR", owner="Saudi Aramco", delivery_year=2027, delivery_month=1, count=2, build_cost_musd=125.0, shipyard_country="south_korea"),
    ])

def load_orderbook(df: pd.DataFrame, ship_types: Dict[str, ShipType]) -> List[OrderbookEntry]:
    out = []
    for _, row in df.iterrows():
        st_name = str(row["ship_type"])
        if st_name not in ship_types: continue
        count = int(_get(row, "count", 1))
        yr  = int(_get(row, "delivery_year",  2026))
        mo  = int(_get(row, "delivery_month", 1))
        delivery_day = (yr - 2025) * 365 + (mo - 1) * 30.0
        try: sy_country = ShipCountry(_get(row, "shipyard_country", "south_korea"))
        except ValueError: sy_country = ShipCountry.SOUTH_KOREA
        for _ in range(count):
            out.append(OrderbookEntry(
                ship_type=st_name, owner=str(row["owner"]),
                ordered_on_day=0.0, delivery_day=delivery_day,
                build_cost_musd=float(_get(row, "build_cost_musd", 100.0)),
                shipyard_country=sy_country,
            ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 8. CONSTRAINTS  (v3: step-based, group-targeted)
# ══════════════════════════════════════════════════════════════════════════════

def template_constraints() -> pd.DataFrame:
    return pd.DataFrame([
        # Example: Hormuz closure, step 6-12
        dict(constraint_id='hormuz_crisis',   constraint_type='node_closure',      step_from=6,  step_to=12, apply_on_day=0, end_on_day=None,
             description='Strait of Hormuz closed steps 6-12',
             target_nodes='Strait of Hormuz', target_vessel_groups='', target_product_groups='', target_region_tags='',
             target_companies='', target_countries='', target_regions='', target_products='',
             multiplier=0.0, additive=0, capacity_vessels=None, enabled=False),
        # Russian flag vessels banned from EU ports from step 0 onwards
        dict(constraint_id='ru_flag_eu_ban',  constraint_type='sanction_ship_flag',step_from=0,  step_to=None, apply_on_day=0, end_on_day=None,
             description='Russian-flag vessels banned from EU ports',
             target_nodes='', target_vessel_groups='flag:russia', target_product_groups='', target_region_tags='eu_port',
             target_companies='', target_countries='russia', target_regions='BALT,MED,NSEA,UKC', target_products='',
             multiplier=0.0, additive=0, capacity_vessels=None, enabled=False),
        # Urals supply cut — step 0 onwards, 35% reduction for Rosneft in BALT/BSEA
        dict(constraint_id='urals_supply_cut',constraint_type='supply_shock',      step_from=0,  step_to=None, apply_on_day=0, end_on_day=None,
             description='Urals supply reduced 35% in Baltic/Black Sea',
             target_nodes='', target_vessel_groups='', target_product_groups='russian', target_region_tags='',
             target_companies='Rosneft', target_countries='', target_regions='BALT,BSEA', target_products='Urals',
             multiplier=0.35, additive=0, capacity_vessels=None, enabled=False),
        # IMO 2020: fuel surcharge on non-scrubber vessels
        dict(constraint_id='imo2020',          constraint_type='fuel_regulation',  step_from=0,  step_to=None, apply_on_day=0, end_on_day=None,
             description='IMO 2020: +150 USD/t surcharge for non-scrubber vessels',
             target_nodes='', target_vessel_groups='scrubber:no', target_product_groups='', target_region_tags='',
             target_companies='', target_countries='', target_regions='', target_products='',
             multiplier=1.0, additive=150, capacity_vessels=None, enabled=False),
    ])

def load_constraints(df: pd.DataFrame) -> List[ScenarioConstraint]:
    out = []
    for _, row in df.iterrows():
        if str(_get(row, "enabled", "true")).lower() in ("false", "0", "no"):
            continue
        try: ct = ConstraintType(str(row["constraint_type"]))
        except ValueError: continue

        def _si(col):
            v = _get(row, col)
            if v is None or (isinstance(v, float) and np.isnan(v)): return None
            return int(v)
        def _sf(col):
            v = _get(row, col)
            if v is None or (isinstance(v, float) and np.isnan(v)): return None
            return float(v)

        target_countries = []
        for c in _split(_get(row, "target_countries", "")):
            try: target_countries.append(ShipCountry(c))
            except ValueError: pass

        out.append(ScenarioConstraint(
            constraint_id=str(row["constraint_id"]),
            constraint_type=ct,
            step_from=int(_get(row, "step_from", 0) or 0),
            step_to=_si("step_to"),
            apply_on_day=float(_get(row, "apply_on_day", 0) or 0),
            end_on_day=_sf("end_on_day"),
            description=str(_get(row, "description", "")),
            target_nodes=_split(_get(row, "target_nodes", "")),
            target_companies=_split(_get(row, "target_companies", "")),
            target_countries=target_countries,
            target_regions=_split(_get(row, "target_regions", "")),
            target_products=_split(_get(row, "target_products", "")),
            target_vessel_groups=_split(_get(row, "target_vessel_groups", "")),
            target_product_groups=_split(_get(row, "target_product_groups", "")),
            target_region_tags=_split(_get(row, "target_region_tags", "")),
            multiplier=float(_get(row, "multiplier", 1.0) or 1.0),
            additive=float(_get(row, "additive", 0) or 0),
            capacity_vessels=_si("capacity_vessels"),
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 9. SEASONALITY
# ══════════════════════════════════════════════════════════════════════════════

def template_seasonality() -> pd.DataFrame:
    return pd.DataFrame([
        dict(entity_type='region', entity_name='NSEA', attribute='demand',
             season_1=1.15,season_2=1.12,season_3=1.05,season_4=0.95,
             season_5=0.88,season_6=0.85,season_7=0.85,season_8=0.88,
             season_9=0.95,season_10=1.05,season_11=1.12,season_12=1.15),
        dict(entity_type='region', entity_name='UKC', attribute='demand',
             season_1=1.12,season_2=1.10,season_3=1.03,season_4=0.95,
             season_5=0.90,season_6=0.88,season_7=0.88,season_8=0.90,
             season_9=0.97,season_10=1.05,season_11=1.10,season_12=1.12),
        dict(entity_type='region', entity_name='MED', attribute='demand',
             season_1=1.05,season_2=1.03,season_3=1.00,season_4=0.97,
             season_5=0.97,season_6=1.00,season_7=1.05,season_8=1.05,
             season_9=1.00,season_10=0.97,season_11=0.98,season_12=1.03),
        dict(entity_type='region', entity_name='AG', attribute='supply',
             season_1=1.00,season_2=1.00,season_3=1.00,season_4=1.00,
             season_5=1.00,season_6=0.97,season_7=0.95,season_8=0.95,
             season_9=0.97,season_10=1.00,season_11=1.00,season_12=1.00),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# ALL_TEMPLATES registry
# ══════════════════════════════════════════════════════════════════════════════

ALL_TEMPLATES = {
    "products":             template_products,
    "regions":              template_regions,
    "region_demand":        template_region_demand,
    "region_supply":        template_region_supply,
    "region_storage":       template_region_storage,
    "port_times":           template_port_times,
    "nodes":                template_nodes,
    "edges":                template_edges,
    "companies":            template_companies,
    "ship_groups":          template_ship_groups,
    "ship_types":           template_ship_types,
    "fleet":                template_fleet,
    "orderbook":            template_orderbook,
    "constraints":          template_constraints,
    "seasonality":          template_seasonality,
    "vessel_groups":        template_vessel_groups,
    "vessel_group_members": template_vessel_group_members,
}
