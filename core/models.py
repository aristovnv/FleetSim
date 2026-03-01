"""
Domain model dataclasses for Maritime Fleet Simulation v2.

Design principles:
 - Separates *what exists* (entities) from *what happens* (simulation state).
 - All stochastic parameters carry both mean and std-dev so callers decide
   how to draw samples.
 - Growth rates are dictionaries keyed by company name; a special key "__all__"
   provides the default that company-specific entries override.
 - Prices and volumes are in consistent SI-ish units:
     volumes  : million metric tonnes (MMT)   [or MT where stated]
     prices   : USD / metric tonne  (supply/demand prices)
                USD / day           (spot freight rates)
     distances: nautical miles (nm)
     time     : days (simulation clock is always in fractional days)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from core.enums import (
    NodeType, ProductType, ShipCountry, VesselStatus, ConstraintType
)


# ──────────────────────────────────────────────────────────────────────────────
# PRIMITIVE VALUE TYPES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MeanStd:
    """A stochastic scalar: Normal(mean, std).  std=0 ⇒ deterministic."""
    mean: float
    std: float = 0.0

    def sample(self, rng) -> float:
        if self.std == 0:
            return self.mean
        return float(rng.normal(self.mean, self.std))

    def __repr__(self):
        return f"N({self.mean:.3g}, {self.std:.3g})"


@dataclass
class GrowthRate:
    """
    Per-entity growth rate dictionary.
    Keys are company names.  Special key '__all__' is the default for any
    company not explicitly listed.
    Values are annual fractional rates, e.g. 0.02 = 2 %/yr.
    """
    by_entity: Dict[str, float] = field(default_factory=dict)
    default: float = 0.0

    def get(self, entity: str) -> float:
        return self.by_entity.get(entity, self.default)

    @classmethod
    def uniform(cls, rate: float) -> "GrowthRate":
        return cls(default=rate)


@dataclass
class SeasonalCoeff:
    """
    12 monthly multipliers (Jan..Dec).  Multiplied against base value each period.
    Default all-ones = no seasonality.
    """
    coeffs: List[float] = field(default_factory=lambda: [1.0] * 12)

    def __post_init__(self):
        if len(self.coeffs) != 12:
            raise ValueError("SeasonalCoeff needs exactly 12 monthly values.")

    def get(self, month_1indexed: int) -> float:
        return self.coeffs[month_1indexed - 1]


# ──────────────────────────────────────────────────────────────────────────────
# PRODUCT DEFINITIONS
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Product:
    """
    A tradable commodity (crude grade, product, etc.).
    """
    name: str                           # e.g. "WTI", "Brent", "VLSFO"
    product_type: ProductType = ProductType.CRUDE_OIL
    energy_density_gj_per_t: float = 42.0   # for fuel-equivalence calcs
    # API gravity / quality proxy – used for cargo compatibility checks
    api_gravity: Optional[float] = None
    sulfur_pct: Optional[float] = None

    def __hash__(self): return hash(self.name)
    def __eq__(self, other): return isinstance(other, Product) and self.name == other.name


@dataclass
class ProductMix:
    """
    A blend expressed as fractional weights summing to 1.0.
    E.g. {"WTI": 0.7, "Brent": 0.3} or {"WTI": 1.0} for pure WTI.
    Allows modelling cargo substitution / upgrading / blending.
    """
    name: str
    components: Dict[str, float]         # {product_name: fraction}

    def __post_init__(self):
        total = sum(self.components.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ProductMix '{self.name}' fractions sum to {total}, not 1.0")


# ──────────────────────────────────────────────────────────────────────────────
# REGION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompanyVolume:
    """Demand or supply volume for a single (company, product) pair."""
    product: str                  # product name
    volume: MeanStd               # MMT per simulation period (before growth/season)
    price: MeanStd                # USD / MT


@dataclass
class StorageSlot:
    """Storage capacity held by one entity at a region."""
    total_mmt: float              # maximum MMT storable
    available_mmt: float          # currently free MMT


@dataclass
class PortTime:
    """Loading / unloading / bunkering time for a ship type at this location."""
    load_days:    MeanStd = field(default_factory=lambda: MeanStd(1.0, 0.2))
    unload_days:  MeanStd = field(default_factory=lambda: MeanStd(1.0, 0.2))
    bunker_days:  MeanStd = field(default_factory=lambda: MeanStd(0.5, 0.1))


@dataclass
class Region:
    """
    A geographic demand/supply area.

    Volumes & prices per period are per-company dicts with a special
    '__free__' key for the open/spot market not tied to any company.

    Growth rates: GrowthRate objects allow a global default plus per-company
    overrides.
    """
    name: str

    # ── Demand side ────────────────────────────────────────────────────────
    # {company_name: CompanyVolume}  +  '__free__' key for spot market
    demand: Dict[str, CompanyVolume] = field(default_factory=dict)

    # ── Supply side ────────────────────────────────────────────────────────
    supply: Dict[str, CompanyVolume] = field(default_factory=dict)

    # ── Storage ────────────────────────────────────────────────────────────
    storage: Dict[str, StorageSlot] = field(default_factory=dict)

    # ── Pricing modifiers ──────────────────────────────────────────────────
    # Multipliers relative to global base; 1.0 = neutral
    spot_price_premium:  float = 1.0   # e.g. 1.5 for remote/risky, 0.8 for hub
    fuel_price_premium:  float = 1.0

    # ── Growth rates (annual fraction) ────────────────────────────────────
    demand_growth: GrowthRate = field(default_factory=GrowthRate.uniform.__func__
                                       .__get__(None, GrowthRate)
                                       if False else GrowthRate)
    supply_growth: GrowthRate = field(default_factory=GrowthRate.uniform.__func__
                                       .__get__(None, GrowthRate)
                                       if False else GrowthRate)

    # ── Seasonality ────────────────────────────────────────────────────────
    demand_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)
    supply_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)
    spot_price_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)

    # ── Port logistics ──────────────────────────────────────────────────────
    # {ship_type_name: PortTime}; '__default__' used as fallback
    port_times: Dict[str, PortTime] = field(default_factory=dict)

    # ── Physical ───────────────────────────────────────────────────────────
    latitude:  float = 0.0
    longitude: float = 0.0
    max_vessel_dwt: Optional[float] = None   # draft restriction; None = unrestricted

    def get_port_time(self, ship_type_name: str) -> PortTime:
        return self.port_times.get(ship_type_name,
               self.port_times.get("__default__", PortTime()))

    def __post_init__(self):
        # Ensure GrowthRate objects (not lambda-broken defaults)
        if not isinstance(self.demand_growth, GrowthRate):
            self.demand_growth = GrowthRate(default=self.demand_growth)
        if not isinstance(self.supply_growth, GrowthRate):
            self.supply_growth = GrowthRate(default=self.supply_growth)


# ──────────────────────────────────────────────────────────────────────────────
# NETWORK (NODES + EDGES)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Node:
    """
    Network node.  Regions are PORT nodes; channels/straits are CANAL/STRAIT.
    The network uses region names as port node IDs.
    """
    node_id: str
    node_type: NodeType = NodeType.PORT
    region_name: Optional[str] = None    # links back to Region if PORT

    # Capacity constraints (relevant for CANAL / STRAIT)
    max_vessels_per_period: Optional[int] = None   # None = unlimited
    transit_time_days: MeanStd = field(default_factory=lambda: MeanStd(0.5, 0.1))
    max_vessel_dwt: Optional[float] = None

    # Whether currently open (scenario can set to False)
    is_open: bool = True
    closure_reason: Optional[str] = None

    def __hash__(self): return hash(self.node_id)
    def __eq__(self, other): return isinstance(other, Node) and self.node_id == other.node_id


@dataclass
class Edge:
    """
    Directed arc between two nodes.
    'available_for' lists ship type names that can use this edge
    (empty list = all types permitted).
    """
    from_node: str
    to_node:   str
    distance_nm: float
    # Derived: transit_days = distance_nm / (speed_kn * 24) — but we cache a base here
    base_transit_days: MeanStd = field(default_factory=lambda: MeanStd(5.0, 0.5))
    available_for: List[str] = field(default_factory=list)   # empty = all
    requires_nodes: List[str] = field(default_factory=list)  # must pass through (e.g. "Suez")
    fuel_consumption_multiplier: float = 1.0  # weather / current adjustment

    @property
    def edge_id(self) -> str:
        return f"{self.from_node}→{self.to_node}"


# ──────────────────────────────────────────────────────────────────────────────
# OIL COMPANY
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OilCompany:
    name: str
    supply_regions: List[str]           # region names where they produce
    demand_regions: List[str]           # region names where they consume / sell
    supply_growth:  GrowthRate = field(default_factory=GrowthRate)
    demand_growth:  GrowthRate = field(default_factory=GrowthRate)
    supply_volatility: float = 0.05     # fractional std dev of supply
    demand_volatility: float = 0.05
    wtp_spot: float = 30000.0           # willingness to pay on spot ($/day)
    contract_fraction: float = 0.6      # fraction of volume under long-term contract
    # Sanction exposure
    is_sanctioned: bool = False
    associated_countries: List[ShipCountry] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# SHIP TYPE & VESSEL
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ShipGroupType:
    """
    Abstract vessel class (e.g. VLCC, Suezmax).
    Concrete ShipType instances extend this with flag/yard detail.
    """
    name: str           # e.g. "VLCC", "Suezmax"
    dwt_range: Tuple[float, float] = (0, 999_999)
    description: str = ""


@dataclass
class ShipType:
    """
    Specific vessel specification.  Name encodes key details, e.g.
    'VLCC_scrubber_KR' = VLCC, scrubber fitted, South-Korean built.
    """
    name: str                               # unique identifier
    group: str                              # ShipGroupType.name
    dwt: MeanStd = field(default_factory=lambda: MeanStd(300_000, 5_000))
    speed_knots: MeanStd = field(default_factory=lambda: MeanStd(15.5, 0.5))
    daily_opex: MeanStd = field(default_factory=lambda: MeanStd(8_500, 500))
    fuel_consumption_tons_day: float = 90.0   # at design speed, fully laden
    fuel_consumption_ballast_factor: float = 0.75  # fraction when in ballast
    scrubber_fitted: bool = False
    build_cost_musd: float = 120.0
    scrap_value_musd: float = 30.0
    build_time_years: float = 2.5           # average; actual drawn per order
    build_time_std_years: float = 0.25
    economic_life_years: float = 25.0
    can_be_storage: bool = True             # VLCC/Suezmax can convert to FSO
    country: ShipCountry = ShipCountry.OTHER_WESTERN
    compatible_products: List[str] = field(default_factory=list)  # empty = all crude

    # Capacity constraints per canal/strait
    max_beam_m: Optional[float] = None
    max_draft_m: Optional[float] = None


@dataclass
class Vessel:
    """
    Individual vessel instance tracked during simulation.
    """
    vessel_id: str
    ship_type: str                    # ShipType.name
    owner: str                        # OilCompany.name or "Independent"
    age_years: float = 0.0
    status: VesselStatus = VesselStatus.ACTIVE
    current_node: str = ""            # Node.node_id
    destination_node: Optional[str] = None
    cargo_product: Optional[str] = None
    cargo_volume_mt: float = 0.0
    utilization: float = 1.0          # fraction of DWT used for cargo
    days_in_status: float = 0.0       # how long in current status
    last_trade: Optional[str] = None  # last company served

    # Delivery tracking (for orderbook vessels)
    ordered_by: Optional[str] = None
    delivery_day: Optional[float] = None   # simulation day of delivery


# ──────────────────────────────────────────────────────────────────────────────
# ORDERBOOK ENTRY
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OrderbookEntry:
    ship_type: str
    owner: str
    ordered_on_day: float
    delivery_day: float        # simulation day
    build_cost_musd: float
    shipyard_country: ShipCountry = ShipCountry.SOUTH_KOREA


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO CONSTRAINT
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScenarioConstraint:
    """
    A structural change applied at a given simulation day.
    Parameters are flexible: the engine looks up keys it knows about.
    """
    constraint_id: str
    constraint_type: ConstraintType
    apply_on_day: float                   # simulation day (0 = start)
    end_on_day: Optional[float] = None   # None = permanent
    description: str = ""

    # Targets (set whichever are relevant)
    target_nodes:    List[str] = field(default_factory=list)
    target_companies: List[str] = field(default_factory=list)
    target_countries: List[ShipCountry] = field(default_factory=list)
    target_regions:  List[str] = field(default_factory=list)
    target_products: List[str] = field(default_factory=list)

    # Magnitude
    multiplier: float = 1.0    # e.g. 0.0 = full block, 0.7 = 30% reduction
    additive:   float = 0.0    # e.g. +150 USD/MT fuel premium
    capacity_vessels: Optional[int] = None   # new cap for node


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SimConfig:
    """
    Top-level simulation configuration.  Does NOT contain scenario constraints
    (those live in the Scenario object) or entity definitions (those are loaded
    from DataFrames / defaults).
    """
    from .enums import Granularity   # local import to avoid circular

    granularity: "Granularity"       # WEEK / MONTH / QUARTER / YEAR
    n_periods: int = 40              # number of steps to simulate
    start_year: int = 2025
    start_month: int = 1             # 1-based
    random_seed: int = 42

    # Global market baselines
    wti_price_usd_bbl: float = 75.0         # global crude benchmark
    wti_price_volatility: float = 0.15
    base_spot_rate_usd_day: float = 25_000.0
    spot_rate_volatility: float = 0.25
    hfo_price_usd_t: float = 450.0          # HFO (non-compliant fuel)
    vlsfo_price_usd_t: float = 600.0        # VLSFO (IMO 2020 compliant)
    fuel_price_volatility: float = 0.15

    # Fleet dynamics (Engelen et al.)
    ordering_sensitivity: float = 0.30
    scrapping_threshold_usd_day: float = 8_000.0
    storage_conversion_sd_ratio: float = 1.4   # S/D ratio trigger
    max_newbuilds_per_period_global: int = 50   # yard capacity constraint

    # Active scenario (applied on top of baseline)
    # Populated at runtime; not used for construction
    active_constraints: List["ScenarioConstraint"] = field(default_factory=list)
