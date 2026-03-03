"""
Domain model dataclasses for Maritime Fleet Simulation v3.

Key changes from v2:
  - Vessel tag-group hierarchy: each vessel belongs to multiple named groups
    (e.g. flag:russia, build:china, scrubber:no, sts:capable, class:vlcc).
    Constraints target any set of groups — no need to predefine every combination.
  - Constraints have step_from / step_to (simulation step numbers, not days).
  - Gateway nodes (Gibraltar, Suez, Panama, Singapore/Malacca) are real routing
    waypoints with capacity constraints; closures force rerouting.
  - ShipType is now a flat spec; group membership lives in vessel_groups table.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum

from core.enums import (
    NodeType, ProductType, ShipCountry, VesselStatus, ConstraintType
)


# ──────────────────────────────────────────────────────────────────────────────
# PRIMITIVE VALUE TYPES  (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MeanStd:
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
    by_entity: Dict[str, float] = field(default_factory=dict)
    default: float = 0.0

    def get(self, entity: str) -> float:
        return self.by_entity.get(entity, self.default)

    @classmethod
    def uniform(cls, rate: float) -> "GrowthRate":
        return cls(default=rate)


@dataclass
class SeasonalCoeff:
    coeffs: List[float] = field(default_factory=lambda: [1.0] * 12)

    def __post_init__(self):
        if len(self.coeffs) != 12:
            raise ValueError("SeasonalCoeff needs exactly 12 monthly values.")

    def get(self, month_1indexed: int) -> float:
        return self.coeffs[month_1indexed - 1]


# ──────────────────────────────────────────────────────────────────────────────
# PRODUCT
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Product:
    name: str
    product_type: ProductType = ProductType.CRUDE_OIL
    energy_density_gj_per_t: float = 42.0
    api_gravity: Optional[float] = None
    sulfur_pct: Optional[float] = None
    # Product group tags — constraints can target a group (e.g. "sanctioned_crude")
    tags: List[str] = field(default_factory=list)

    def __hash__(self): return hash(self.name)
    def __eq__(self, other): return isinstance(other, Product) and self.name == other.name


@dataclass
class ProductMix:
    name: str
    components: Dict[str, float]

    def __post_init__(self):
        total = sum(self.components.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ProductMix '{self.name}' fractions sum to {total}, not 1.0")


# ──────────────────────────────────────────────────────────────────────────────
# REGION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompanyVolume:
    product: str
    volume: MeanStd
    price: MeanStd


@dataclass
class StorageSlot:
    total_mmt: float
    available_mmt: float


@dataclass
class PortTime:
    load_days:    MeanStd = field(default_factory=lambda: MeanStd(1.0, 0.2))
    unload_days:  MeanStd = field(default_factory=lambda: MeanStd(1.0, 0.2))
    bunker_days:  MeanStd = field(default_factory=lambda: MeanStd(0.5, 0.1))


@dataclass
class Region:
    name: str
    demand: Dict[str, CompanyVolume] = field(default_factory=dict)
    supply: Dict[str, CompanyVolume] = field(default_factory=dict)
    storage: Dict[str, StorageSlot] = field(default_factory=dict)
    spot_price_premium: float = 1.0
    fuel_price_premium: float = 1.0
    demand_growth: GrowthRate = field(default_factory=GrowthRate)
    supply_growth: GrowthRate = field(default_factory=GrowthRate)
    demand_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)
    supply_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)
    spot_price_seasonal: SeasonalCoeff = field(default_factory=SeasonalCoeff)
    port_times: Dict[str, PortTime] = field(default_factory=dict)
    latitude: float = 0.0
    longitude: float = 0.0
    max_vessel_dwt: Optional[float] = None
    # Region group tags for constraint targeting (e.g. "eu_sanctioned", "arctic")
    tags: List[str] = field(default_factory=list)

    def get_port_time(self, ship_type_name: str) -> PortTime:
        return self.port_times.get(ship_type_name,
               self.port_times.get("__default__", PortTime()))

    def __post_init__(self):
        if not isinstance(self.demand_growth, GrowthRate):
            self.demand_growth = GrowthRate(default=self.demand_growth)
        if not isinstance(self.supply_growth, GrowthRate):
            self.supply_growth = GrowthRate(default=self.supply_growth)


# ──────────────────────────────────────────────────────────────────────────────
# NETWORK NODES & EDGES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Node:
    node_id: str
    node_type: NodeType = NodeType.PORT
    region_name: Optional[str] = None
    max_vessels_per_period: Optional[int] = None
    transit_time_days: MeanStd = field(default_factory=lambda: MeanStd(0.5, 0.1))
    max_vessel_dwt: Optional[float] = None
    is_open: bool = True
    closure_reason: Optional[str] = None
    # Gateway nodes (Suez, Gibraltar, Panama, Malacca) have is_gateway=True.
    # Their closure triggers automatic rerouting via alternate edges.
    is_gateway: bool = False

    def __hash__(self): return hash(self.node_id)
    def __eq__(self, other): return isinstance(other, Node) and self.node_id == other.node_id


@dataclass
class Edge:
    from_node: str
    to_node: str
    distance_nm: float
    base_transit_days: MeanStd = field(default_factory=lambda: MeanStd(5.0, 0.5))
    available_for: List[str] = field(default_factory=list)   # ship type names; [] = all
    requires_nodes: List[str] = field(default_factory=list)  # gateway nodes on this path
    fuel_consumption_multiplier: float = 1.0
    # If alternate_for is set, this edge is used when those gateway nodes are closed
    alternate_for: List[str] = field(default_factory=list)

    @property
    def edge_id(self) -> str:
        return f"{self.from_node}→{self.to_node}"


# ──────────────────────────────────────────────────────────────────────────────
# OIL COMPANY
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OilCompany:
    name: str
    supply_regions: List[str]
    demand_regions: List[str]
    supply_growth: GrowthRate = field(default_factory=GrowthRate)
    demand_growth: GrowthRate = field(default_factory=GrowthRate)
    supply_volatility: float = 0.05
    demand_volatility: float = 0.05
    wtp_spot: float = 30000.0
    contract_fraction: float = 0.6
    is_sanctioned: bool = False
    associated_countries: List[ShipCountry] = field(default_factory=list)
    # Company group tags for constraint targeting
    tags: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# VESSEL GROUP SYSTEM  (new in v3)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class VesselGroup:
    """
    A named group that vessels can belong to.

    Groups are hierarchical and orthogonal — a vessel can be in many groups
    simultaneously. The group system replaces the old "ship type encodes all
    attributes in its name" approach.

    Group dimensions (examples):
      class:vlcc, class:suezmax, class:aframax, class:panamax, class:mr
      flag:russia, flag:china, flag:greece, flag:norway, flag:shadow
      build:korea, build:china, build:japan, build:europe
      scrubber:yes, scrubber:no
      sts:capable, sts:no          (ship-to-ship transfer capable)
      trade:spot, trade:contract   (commercial mode)
      age:new, age:mid, age:old    (can be auto-assigned by engine)

    Constraints targeting group "flag:russia" apply to ALL vessels in that group,
    regardless of their class, scrubber status, etc.

    step_from / step_to: a vessel is in this group only during these simulation
    steps (inclusive). Blank = always. This handles "this ship only available
    steps 12-36", "Rosneft fleet sanctioned from step 6 onwards", etc.
    """
    group_id: str               # e.g. "flag:russia", "class:vlcc", "trade:spot"
    dimension: str              # e.g. "flag", "class", "scrubber", "trade"
    label: str = ""             # display label
    description: str = ""
    color: str = ""             # optional map/chart color override
    map_radius: int = 0         # 0 = inherit from class group
    sort_order: int = 99


@dataclass
class VesselGroupMembership:
    """
    Many-to-many: which vessels belong to which groups, and when.

    vessel_id matches fleet.vessel_id (or ship_type if no individual tracking yet).
    step_from / step_to: simulation step range (inclusive); None = always.
    """
    vessel_id: str              # fleet row identifier
    group_id: str               # VesselGroup.group_id
    step_from: Optional[int] = None
    step_to: Optional[int] = None

    def active_at(self, step: int) -> bool:
        if self.step_from is not None and step < self.step_from:
            return False
        if self.step_to is not None and step > self.step_to:
            return False
        return True


# ──────────────────────────────────────────────────────────────────────────────
# SHIP TYPE & VESSEL  (ShipType simplified — group membership is external)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ShipGroupType:
    """Abstract size class (VLCC, Suezmax...). Maps to class:* group dimension."""
    name: str
    dwt_range: Tuple[float, float] = (0, 999_999)
    description: str = ""


@dataclass
class ShipType:
    """
    Vessel specification. Name is now just a unique id — attributes encoded
    as group memberships (flag, build, scrubber, etc.) instead of in the name.
    """
    name: str
    group: str                  # size class group_id (e.g. "class:vlcc" or legacy "VLCC")
    dwt: MeanStd = field(default_factory=lambda: MeanStd(300_000, 5_000))
    speed_knots: MeanStd = field(default_factory=lambda: MeanStd(15.5, 0.5))
    daily_opex: MeanStd = field(default_factory=lambda: MeanStd(8_500, 500))
    fuel_consumption_tons_day: float = 90.0
    fuel_consumption_ballast_factor: float = 0.75
    scrubber_fitted: bool = False
    build_cost_musd: float = 120.0
    scrap_value_musd: float = 30.0
    build_time_years: float = 2.5
    build_time_std_years: float = 0.25
    economic_life_years: float = 25.0
    can_be_storage: bool = True
    country: ShipCountry = ShipCountry.OTHER_WESTERN
    compatible_products: List[str] = field(default_factory=list)
    max_beam_m: Optional[float] = None
    max_draft_m: Optional[float] = None
    # Explicit group tags (supplement the group memberships table)
    # These are evaluated every step — no step range restriction here.
    static_groups: List[str] = field(default_factory=list)


@dataclass
class Vessel:
    vessel_id: str
    ship_type: str
    owner: str
    age_years: float = 0.0
    status: VesselStatus = VesselStatus.ACTIVE
    current_node: str = ""
    destination_node: Optional[str] = None
    cargo_product: Optional[str] = None
    cargo_volume_mt: float = 0.0
    utilization: float = 1.0
    days_in_status: float = 0.0
    last_trade: Optional[str] = None
    ordered_by: Optional[str] = None
    delivery_day: Optional[float] = None


# ──────────────────────────────────────────────────────────────────────────────
# ORDERBOOK
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OrderbookEntry:
    ship_type: str
    owner: str
    ordered_on_day: float
    delivery_day: float
    build_cost_musd: float
    shipyard_country: ShipCountry = ShipCountry.SOUTH_KOREA


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO CONSTRAINT  (v3: step-based, group-targeted)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScenarioConstraint:
    """
    Structural change applied between simulation steps step_from..step_to.

    Target system (any combination):
      target_vessel_groups  — group_ids; constraint applies to vessels in ANY of these groups
      target_product_groups — product tags; applies to those products/cargoes
      target_regions        — region names or region tags
      target_nodes          — node ids (for closures/capacity changes)
      target_companies      — company names or company tags

    Backward-compatible: target_countries still works as shorthand for flag:* groups.
    """
    constraint_id: str
    constraint_type: ConstraintType
    # Step range (simulation steps, inclusive).  None = no bound.
    step_from: int = 0
    step_to: Optional[int] = None
    # Legacy day-based: still honoured if step_from/step_to are not set
    apply_on_day: float = 0.0
    end_on_day: Optional[float] = None
    description: str = ""

    # Targets
    target_nodes:          List[str] = field(default_factory=list)
    target_companies:      List[str] = field(default_factory=list)
    target_countries:      List[ShipCountry] = field(default_factory=list)
    target_regions:        List[str] = field(default_factory=list)
    target_products:       List[str] = field(default_factory=list)
    # v3 group-based targets
    target_vessel_groups:  List[str] = field(default_factory=list)  # e.g. ["flag:russia"]
    target_product_groups: List[str] = field(default_factory=list)  # e.g. ["sanctioned_crude"]
    target_region_tags:    List[str] = field(default_factory=list)  # e.g. ["eu_port"]

    # Magnitude
    multiplier: float = 1.0
    additive: float = 0.0
    capacity_vessels: Optional[int] = None

    def active_at_step(self, step: int, day: float) -> bool:
        """Returns True if this constraint is active at the given step/day."""
        # Step-based check takes priority
        if self.step_from != 0 or self.step_to is not None:
            if step < self.step_from:
                return False
            if self.step_to is not None and step > self.step_to:
                return False
            return True
        # Fall back to day-based
        if self.apply_on_day > day:
            return False
        if self.end_on_day is not None and day > self.end_on_day:
            return False
        return True


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SimConfig:
    from .enums import Granularity

    granularity: "Granularity"
    n_periods: int = 40
    start_year: int = 2025
    start_month: int = 1
    random_seed: int = 42

    wti_price_usd_bbl: float = 75.0
    wti_price_volatility: float = 0.15
    base_spot_rate_usd_day: float = 25_000.0
    spot_rate_volatility: float = 0.25
    hfo_price_usd_t: float = 450.0
    vlsfo_price_usd_t: float = 600.0
    fuel_price_volatility: float = 0.15

    ordering_sensitivity: float = 0.30
    scrapping_threshold_usd_day: float = 8_000.0
    storage_conversion_sd_ratio: float = 1.4
    max_newbuilds_per_period_global: int = 50

    active_constraints: List["ScenarioConstraint"] = field(default_factory=list)
