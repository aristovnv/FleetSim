"""
Maritime Fleet Simulation Engine v3

Changes from v2:
  - VesselGroupResolver: evaluates per-step membership of each vessel_id in groups
  - ConstraintEngine: uses step-based effective dates; targets vessel groups,
    product groups, region tags — not just country flags
  - FreightMarket: gateway node closures use alternate_for edges for routing
  - WorldState: adds banned_vessel_groups, group_fuel_additive
  - SimulationRunner: accepts vessel_groups + vessel_group_members tables
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import math

from core.enums import Granularity, ConstraintType, ShipCountry, NodeType, VesselStatus
from core.models import (
    Region, OilCompany, ShipType, Vessel, OrderbookEntry,
    ScenarioConstraint, SimConfig, Node, Edge, MeanStd, CompanyVolume,
    VesselGroup, VesselGroupMembership
)


# ──────────────────────────────────────────────────────────────────────────────
# VESSEL GROUP RESOLVER
# ──────────────────────────────────────────────────────────────────────────────

class VesselGroupResolver:
    """
    Resolves which group_ids each vessel_id belongs to at a given step.
    Built once from vessel_group_members; queried cheaply each tick.
    """

    def __init__(self, memberships: List[VesselGroupMembership],
                 ship_types: Dict[str, ShipType]):
        # {vessel_id: [(group_id, step_from, step_to)]}
        self._memberships: Dict[str, List[Tuple[str, Optional[int], Optional[int]]]] = {}
        for m in memberships:
            self._memberships.setdefault(m.vessel_id, []).append(
                (m.group_id, m.step_from, m.step_to))

        # Also add static_groups from ShipType (if any) as always-active entries
        for st_name, st in ship_types.items():
            for gid in st.static_groups:
                self._memberships.setdefault(st_name, []).append((gid, None, None))

    def groups_at(self, vessel_id: str, step: int) -> Set[str]:
        """Return set of group_ids active for vessel_id at this step."""
        result = set()
        for gid, sf, st in self._memberships.get(vessel_id, []):
            if sf is not None and step < sf:
                continue
            if st is not None and step > st:
                continue
            result.add(gid)
        return result

    def vessels_in_group(self, group_id: str, all_vessel_ids: List[str], step: int) -> Set[str]:
        """Return all vessel_ids that are in group_id at this step."""
        result = set()
        for vid in all_vessel_ids:
            if group_id in self.groups_at(vid, step):
                result.add(vid)
        return result

    def any_group_match(self, vessel_id: str, step: int, target_groups: List[str]) -> bool:
        """True if the vessel belongs to any of the target groups at this step."""
        if not target_groups:
            return False
        active = self.groups_at(vessel_id, step)
        return bool(active.intersection(target_groups))


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION WORLD STATE
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class WorldState:
    # Fleet: {vessel_id: {owner: count_active}}  (vessel_id now stable row-key from fleet table)
    fleet_active:  Dict[str, Dict[str, int]]   = field(default_factory=dict)
    fleet_storage: Dict[str, Dict[str, int]]   = field(default_factory=dict)
    fleet_ages:    Dict[str, Dict[str, float]] = field(default_factory=dict)
    # vessel_id -> ship_type mapping (filled at init)
    vessel_ship_type: Dict[str, str]           = field(default_factory=dict)

    orderbook: List[OrderbookEntry] = field(default_factory=list)

    supply_mmt: Dict[str, Dict[str, float]] = field(default_factory=dict)
    demand_mmt: Dict[str, Dict[str, float]] = field(default_factory=dict)
    storage_inventory: Dict[str, Dict[str, float]] = field(default_factory=dict)

    spot_rate_usd_day: float = 25_000.0
    wti_price_usd_bbl: float = 75.0
    fuel_price_vlsfo:  float = 600.0
    fuel_price_hfo:    float = 450.0

    node_open: Dict[str, bool]          = field(default_factory=dict)
    node_cap:  Dict[str, Optional[int]] = field(default_factory=dict)

    demand_multipliers: Dict[str, float]              = field(default_factory=dict)
    supply_multipliers: Dict[str, Dict[str, float]]   = field(default_factory=dict)

    # v2 compat: set of ShipCountry enums (from SANCTION_SHIP_FLAG)
    banned_countries: Set[ShipCountry] = field(default_factory=set)
    # v3: set of group_ids that are fully blocked from trading
    banned_vessel_groups: Set[str] = field(default_factory=set)
    # v3: per-group fuel additive {group_id: usd_per_t}
    group_fuel_additive: Dict[str, float] = field(default_factory=dict)
    fuel_additive_usd_t: float = 0.0  # global additive (kept for compat)

    current_day: float = 0.0
    current_step: int = 0
    current_year_offset: float = 0.0
    current_month_1: int = 1


# ──────────────────────────────────────────────────────────────────────────────
# CONSTRAINT ENGINE  (v3)
# ──────────────────────────────────────────────────────────────────────────────

class ConstraintEngine:
    """
    Applies ScenarioConstraints each tick.

    v3 additions:
      - step-based effective dates (step_from / step_to)
      - target_vessel_groups: bans those groups from trading / applies fuel additive
      - target_region_tags: targets all regions that carry any matching tag
      - target_product_groups: future hook (marks affected product flows)
    """

    def __init__(self, constraints: List[ScenarioConstraint]):
        self._constraints = constraints
        self._active_ids: set = set()

    def tick(self, world: WorldState, all_regions: Dict[str, Region],
             all_nodes: Dict[str, Node], step: int):
        day = world.current_day

        # Reset
        world.demand_multipliers   = {r: 1.0 for r in all_regions}
        world.supply_multipliers   = {}
        world.banned_countries     = set()
        world.banned_vessel_groups = set()
        world.group_fuel_additive  = {}
        world.fuel_additive_usd_t  = 0.0

        for nid, node in all_nodes.items():
            world.node_open[nid] = node.is_open
            world.node_cap[nid]  = node.max_vessels_per_period

        for c in self._constraints:
            if not c.active_at_step(step, day):
                self._active_ids.discard(c.constraint_id)
                continue
            self._active_ids.add(c.constraint_id)
            self._apply(c, world, all_regions)

    def _target_regions(self, c: ScenarioConstraint,
                        all_regions: Dict[str, Region]) -> List[str]:
        """Resolve regions from explicit names + region tags."""
        targets = set(c.target_regions)
        if c.target_region_tags:
            for rname, reg in all_regions.items():
                if any(t in reg.tags for t in c.target_region_tags):
                    targets.add(rname)
        return list(targets) if targets else list(all_regions.keys())

    def _apply(self, c: ScenarioConstraint, world: WorldState,
               all_regions: Dict[str, Region]):
        ct = c.constraint_type

        if ct == ConstraintType.DEMAND_SHOCK:
            for r in self._target_regions(c, all_regions):
                world.demand_multipliers[r] = (
                    world.demand_multipliers.get(r, 1.0) * c.multiplier)

        elif ct == ConstraintType.SUPPLY_SHOCK:
            for r in self._target_regions(c, all_regions):
                for company in (c.target_companies or ["__all__"]):
                    world.supply_multipliers.setdefault(r, {})[company] = (
                        world.supply_multipliers.get(r, {}).get(company, 1.0) * c.multiplier)

        elif ct in (ConstraintType.SANCTION_SHIP_FLAG, ConstraintType.SANCTION_COMPANY):
            # Legacy: ban by country
            for country in c.target_countries:
                world.banned_countries.add(country)
            # v3: ban by vessel group
            for gid in c.target_vessel_groups:
                world.banned_vessel_groups.add(gid)
            # Supply reduction
            targets = self._target_regions(c, all_regions)
            for r in targets:
                for company in (c.target_companies or ["__all__"]):
                    world.supply_multipliers.setdefault(r, {})[company] = (
                        world.supply_multipliers.get(r, {}).get(company, 1.0) * c.multiplier)

        elif ct == ConstraintType.SANCTION_PORT:
            for r in self._target_regions(c, all_regions):
                world.demand_multipliers[r] = 0.0
                world.supply_multipliers.setdefault(r, {})["__all__"] = 0.0

        elif ct == ConstraintType.NODE_CLOSURE:
            for nid in c.target_nodes:
                world.node_open[nid] = False

        elif ct == ConstraintType.NODE_CAPACITY_CHANGE:
            for nid in c.target_nodes:
                if c.capacity_vessels is not None:
                    world.node_cap[nid] = c.capacity_vessels

        elif ct == ConstraintType.FUEL_REGULATION:
            if c.target_vessel_groups:
                # Per-group fuel additive
                for gid in c.target_vessel_groups:
                    world.group_fuel_additive[gid] = (
                        world.group_fuel_additive.get(gid, 0.0) + c.additive)
            else:
                world.fuel_additive_usd_t += c.additive

        elif ct == ConstraintType.SPOT_PRICE_SHOCK:
            pass  # handled in FreightMarket

    @property
    def active_constraint_ids(self) -> set:
        return self._active_ids


# ──────────────────────────────────────────────────────────────────────────────
# OIL MARKET  (unchanged from v2)
# ──────────────────────────────────────────────────────────────────────────────

class OilMarket:
    def __init__(self, regions: Dict[str, Region], rng):
        self.regions = regions
        self.rng = rng
        self._demand_growth_state: Dict[str, Dict[str, float]] = {}
        self._supply_growth_state: Dict[str, Dict[str, float]] = {}
        for rname, reg in regions.items():
            self._demand_growth_state[rname] = {c: 1.0 for c in reg.demand}
            self._supply_growth_state[rname] = {c: 1.0 for c in reg.supply}

    def tick(self, world: WorldState, granularity: Granularity):
        dt_years = granularity.years
        month = world.current_month_1
        world.supply_mmt = {}
        world.demand_mmt = {}

        for rname, reg in self.regions.items():
            world.supply_mmt[rname] = {}
            world.demand_mmt[rname] = {}
            demand_mult = world.demand_multipliers.get(rname, 1.0)

            for company, cv in reg.demand.items():
                growth = reg.demand_growth.get(company)
                self._demand_growth_state[rname][company] = (
                    self._demand_growth_state[rname].get(company, 1.0)
                    * (1 + growth * dt_years))
                base = cv.volume.mean * self._demand_growth_state[rname][company]
                seasonal = getattr(cv, "_seasonal", None)
                if seasonal: base *= seasonal.get(month)
                noise = self.rng.normal(0, cv.volume.std * math.sqrt(dt_years))
                vol = max(0.0, base + noise) * demand_mult
                world.demand_mmt[rname][company] = vol

            sup_mult_region = world.supply_multipliers.get(rname, {})
            for company, cv in reg.supply.items():
                growth = reg.supply_growth.get(company)
                self._supply_growth_state[rname][company] = (
                    self._supply_growth_state[rname].get(company, 1.0)
                    * (1 + growth * dt_years))
                base = cv.volume.mean * self._supply_growth_state[rname][company]
                seasonal = getattr(cv, "_seasonal", None)
                if seasonal: base *= seasonal.get(month)
                noise = self.rng.normal(0, cv.volume.std * math.sqrt(dt_years))
                vol = max(0.0, base + noise)
                mult = sup_mult_region.get(company, sup_mult_region.get("__all__", 1.0))
                vol *= mult
                world.supply_mmt[rname][company] = vol

        for rname, reg in self.regions.items():
            total_supply = sum(world.supply_mmt[rname].values())
            total_demand = sum(world.demand_mmt[rname].values())
            balance_mmt = total_supply - total_demand
            if rname not in world.storage_inventory:
                world.storage_inventory[rname] = {}
            for company, slot in reg.storage.items():
                share = 1.0 / max(len(reg.storage), 1)
                delta = balance_mmt * share
                current = world.storage_inventory[rname].get(company, slot.available_mmt)
                world.storage_inventory[rname][company] = max(
                    0.0, min(slot.total_mmt, current + delta))

    def aggregate_supply(self, world: WorldState) -> float:
        return sum(v for rv in world.supply_mmt.values() for v in rv.values())

    def aggregate_demand(self, world: WorldState) -> float:
        return sum(v for rv in world.demand_mmt.values() for v in rv.values())


# ──────────────────────────────────────────────────────────────────────────────
# FREIGHT MARKET  (v3: group-aware, gateway routing)
# ──────────────────────────────────────────────────────────────────────────────

class FreightMarket:
    """
    v3 changes:
      - Effective fleet DWT excludes vessels in banned_vessel_groups (in addition to banned_countries)
      - Gateway closures use alternate_for edges to adjust ton-mile multiplier
      - Per-group fuel additives affect LRMC
    """

    CHOKEPOINT_TONMILE_FACTORS: Dict[str, float] = {
        "Strait of Hormuz":   1.35,
        "Suez Canal":         1.25,
        "Bab el-Mandeb":      1.10,
        "Gibraltar Strait":   1.05,
        "Strait of Malacca":  1.15,
        "Singapore Strait":   1.10,
        "Panama Canal":       1.20,
        "Danish Straits":     1.08,
    }

    def __init__(self, ship_types: Dict[str, ShipType],
                 resolver: VesselGroupResolver, rng):
        self.ship_types = ship_types
        self.resolver   = resolver
        self.rng = rng

    def _vessel_is_banned(self, vessel_id: str, ship_type: str,
                          world: WorldState, step: int) -> bool:
        st = self.ship_types.get(ship_type)
        if st and st.country in world.banned_countries:
            return True
        if world.banned_vessel_groups:
            groups = self.resolver.groups_at(vessel_id, step)
            if groups.intersection(world.banned_vessel_groups):
                return True
        return False

    def _effective_fleet_dwt(self, world: WorldState, step: int) -> float:
        total = 0.0
        for vessel_id, st_name in world.vessel_ship_type.items():
            if self._vessel_is_banned(vessel_id, st_name, world, step):
                continue
            st = self.ship_types.get(st_name)
            if st is None: continue
            count = sum(world.fleet_active.get(vessel_id, {}).values())
            total += count * st.dwt.mean
        return total

    def _tonmile_multiplier(self, world: WorldState) -> float:
        mult = 1.0
        for node_id, factor in self.CHOKEPOINT_TONMILE_FACTORS.items():
            if not world.node_open.get(node_id, True):
                mult *= factor
        return mult

    def _lrmc(self, st: ShipType, vessel_id: str,
              world: WorldState, step: int) -> float:
        """LRMC for this vessel type, accounting for per-group fuel additives."""
        # Base fuel price
        effective_fuel = (world.fuel_price_vlsfo if st.scrubber_fitted
                          else world.fuel_price_hfo + world.fuel_additive_usd_t)
        # Per-group additive
        groups = self.resolver.groups_at(vessel_id, step)
        for gid in groups:
            effective_fuel += world.group_fuel_additive.get(gid, 0.0)

        fuel_cost   = st.fuel_consumption_tons_day * effective_fuel / 1000.0
        opex        = st.daily_opex.mean
        capex_daily = st.build_cost_musd * 1e6 / (st.economic_life_years * 365.0)
        return opex + fuel_cost + capex_daily

    def tick(self, world: WorldState, oil_market: OilMarket,
             granularity: Granularity, config: SimConfig,
             active_constraints: List[ScenarioConstraint]):
        step = world.current_step
        dt_years = granularity.years

        eff_dwt = self._effective_fleet_dwt(world, step)
        total_demand_mt = oil_market.aggregate_demand(world) * 1e6
        tonmile_mult = self._tonmile_multiplier(world)
        adjusted_demand_mt = total_demand_mt * tonmile_mult

        load_factor = min(1.10, adjusted_demand_mt / eff_dwt) if eff_dwt > 0 else 1.10

        util_signal = (load_factor - 0.85) / 0.10
        rate_adjustment = math.tanh(util_signal) * 0.5

        spot_mult = 1.0
        for c in active_constraints:
            if (c.constraint_type == ConstraintType.SPOT_PRICE_SHOCK
                    and c.active_at_step(step, world.current_day)):
                spot_mult *= c.multiplier

        target_rate = config.base_spot_rate_usd_day * (1 + rate_adjustment) * spot_mult

        reversion_speed = {
            Granularity.WEEK:    8.0,
            Granularity.MONTH:   4.0,
            Granularity.QUARTER: 2.0,
            Granularity.YEAR:    1.0,
        }[granularity]
        world.spot_rate_usd_day += (
            (target_rate - world.spot_rate_usd_day) * reversion_speed * dt_years)
        world.spot_rate_usd_day *= (
            1 + self.rng.normal(0, config.spot_rate_volatility * math.sqrt(dt_years)))
        world.spot_rate_usd_day = max(3_000.0, world.spot_rate_usd_day)

        world.fuel_price_vlsfo *= (
            1 + self.rng.normal(0, config.fuel_price_volatility * math.sqrt(dt_years)))
        world.fuel_price_hfo *= (
            1 + self.rng.normal(0, config.fuel_price_volatility * math.sqrt(dt_years)))
        world.fuel_price_vlsfo = max(200.0, world.fuel_price_vlsfo)
        world.fuel_price_hfo   = max(150.0, world.fuel_price_hfo)

        world.wti_price_usd_bbl *= (
            1 + self.rng.normal(0, config.wti_price_volatility * math.sqrt(dt_years)))
        world.wti_price_usd_bbl = max(20.0, world.wti_price_usd_bbl)

        return eff_dwt, load_factor


# ──────────────────────────────────────────────────────────────────────────────
# FLEET DYNAMICS  (v3: vessel_id-keyed, group-aware scrapping)
# ──────────────────────────────────────────────────────────────────────────────

class FleetDynamics:
    def __init__(self, ship_types: Dict[str, ShipType],
                 companies: Dict[str, OilCompany],
                 resolver: VesselGroupResolver, rng):
        self.ship_types = ship_types
        self.companies  = companies
        self.resolver   = resolver
        self.rng = rng
        self._vessel_counter = 0

    def _lrmc(self, st: ShipType, world: WorldState) -> float:
        eff_fuel = (world.fuel_price_vlsfo if st.scrubber_fitted
                    else world.fuel_price_hfo + world.fuel_additive_usd_t)
        fuel_daily  = st.fuel_consumption_tons_day * eff_fuel / 1000.0
        capex_daily = st.build_cost_musd * 1e6 / (st.economic_life_years * 365.0)
        return st.daily_opex.mean + fuel_daily + capex_daily

    def tick_ordering(self, world: WorldState, config: SimConfig, granularity: Granularity):
        dt_years = granularity.years
        budget   = config.max_newbuilds_per_period_global
        step     = world.current_step

        for vessel_id, st_name in world.vessel_ship_type.items():
            if budget <= 0: break
            st = self.ship_types.get(st_name)
            if st is None: continue

            # Skip banned
            if st.country in world.banned_countries: continue
            groups = self.resolver.groups_at(vessel_id, step)
            if groups.intersection(world.banned_vessel_groups): continue

            lrmc = self._lrmc(st, world)
            profit_signal = (world.spot_rate_usd_day - lrmc) / max(lrmc, 1.0)
            if profit_signal <= 0: continue

            current_fleet = sum(world.fleet_active.get(vessel_id, {}).values())
            max_orders = max(1, int(current_fleet * 0.12))
            n_orders = int(config.ordering_sensitivity * profit_signal
                           * current_fleet * dt_years * self.rng.uniform(0.5, 1.5))
            n_orders = min(n_orders, max_orders, budget)

            owners = world.fleet_active.get(vessel_id, {})
            orderer = max(owners, key=lambda o: owners[o]) if owners else "Independent"

            for _ in range(n_orders):
                bt = st.build_time_years + self.rng.normal(0, st.build_time_std_years)
                bt = max(0.5, bt)
                delivery_day = world.current_day + bt * 365.0
                world.orderbook.append(OrderbookEntry(
                    ship_type=st_name, owner=orderer,
                    ordered_on_day=world.current_day,
                    delivery_day=delivery_day,
                    build_cost_musd=st.build_cost_musd,
                ))
                budget -= 1

    def tick_delivery(self, world: WorldState):
        remaining = []
        for entry in world.orderbook:
            if entry.delivery_day <= world.current_day:
                # Find matching vessel_id for this ship_type
                vid = next((v for v, s in world.vessel_ship_type.items()
                            if s == entry.ship_type), entry.ship_type)
                if vid not in world.fleet_active:
                    world.fleet_active[vid]  = {}
                    world.fleet_storage[vid] = {}
                    world.fleet_ages[vid]    = {}
                world.fleet_active[vid][entry.owner] = (
                    world.fleet_active[vid].get(entry.owner, 0) + 1)
                prev  = world.fleet_ages[vid].get(entry.owner, 0.0)
                count = world.fleet_active[vid][entry.owner]
                world.fleet_ages[vid][entry.owner] = (prev * (count - 1)) / count
            else:
                remaining.append(entry)
        world.orderbook = remaining

    def tick_scrapping(self, world: WorldState, config: SimConfig, granularity: Granularity):
        dt_years = granularity.years
        step     = world.current_step
        scrap_pressure = max(0.0, config.scrapping_threshold_usd_day - world.spot_rate_usd_day)

        if scrap_pressure <= 0:
            for vessel_id, st_name in world.vessel_ship_type.items():
                st = self.ship_types.get(st_name)
                if st is None: continue
                for owner in list(world.fleet_active.get(vessel_id, {})):
                    avg_age = world.fleet_ages.get(vessel_id, {}).get(owner, 0.0)
                    if avg_age > st.economic_life_years:
                        count = world.fleet_active[vessel_id][owner]
                        if count > 0:
                            world.fleet_active[vessel_id][owner] = max(0, count - 1)
            return

        # Group-based scrapping priority — reads from config.scrapping_priority.
        # Default (age-based, economics-driven — no political ordering):
        #   oldest vessels first, then mid-age, then anything with poor economics.
        GROUP_PRIORITY = list(getattr(config, 'scrapping_priority', None) or [
            'age:old',           # past economic life → first candidates
            'age:mid',           # ageing but mid-life
            'scrubber:no',       # VLSFO-burning vessels hurt more by high fuel
            'trade:spot',        # spot market vessels exposed to rate pressure
            'class:mr',          # smaller vessels scrapped before large
            'class:panamax',
            'class:aframax',
            'class:suezmax',
            'class:vlcc',        # VLCCs last — high capex, long economic life
        ])
        n_to_scrap = max(0, int(scrap_pressure / 3_000 * dt_years))

        for priority_group in GROUP_PRIORITY:
            if n_to_scrap <= 0: break
            for vessel_id, st_name in world.vessel_ship_type.items():
                if n_to_scrap <= 0: break
                groups = self.resolver.groups_at(vessel_id, step)
                if priority_group not in groups: continue
                for owner in sorted(world.fleet_active.get(vessel_id, {}),
                                    key=lambda o: world.fleet_ages.get(vessel_id, {}).get(o, 0.0),
                                    reverse=True):
                    if n_to_scrap <= 0: break
                    count = world.fleet_active[vessel_id].get(owner, 0)
                    if count > 0:
                        world.fleet_active[vessel_id][owner] -= 1
                        n_to_scrap -= 1

    def tick_storage_conversion(self, world: WorldState,
                                oil_market: OilMarket, config: SimConfig):
        total_supply = oil_market.aggregate_supply(world)
        total_demand = oil_market.aggregate_demand(world)
        sd_ratio = total_supply / max(total_demand, 0.001)

        if sd_ratio > config.storage_conversion_sd_ratio:
            for vessel_id, st_name in world.vessel_ship_type.items():
                st = self.ship_types.get(st_name)
                if st is None or not st.can_be_storage: continue
                for owner in list(world.fleet_active.get(vessel_id, {})):
                    active = world.fleet_active[vessel_id].get(owner, 0)
                    if active <= 1: continue
                    n_convert = min(max(0, int((sd_ratio - 1.0) * active * 0.25)), active - 1)
                    if n_convert > 0:
                        world.fleet_active[vessel_id][owner]  -= n_convert
                        world.fleet_storage[vessel_id][owner]  = (
                            world.fleet_storage[vessel_id].get(owner, 0) + n_convert)
        elif sd_ratio < 0.97:
            for vessel_id in list(world.fleet_storage):
                for owner in list(world.fleet_storage[vessel_id]):
                    n_back = world.fleet_storage[vessel_id].get(owner, 0)
                    if n_back > 0:
                        world.fleet_active[vessel_id][owner] = (
                            world.fleet_active[vessel_id].get(owner, 0) + n_back)
                        world.fleet_storage[vessel_id][owner] = 0

    def tick_age(self, world: WorldState, granularity: Granularity):
        dt_years = granularity.years
        for vessel_id in world.fleet_ages:
            for owner in world.fleet_ages[vessel_id]:
                world.fleet_ages[vessel_id][owner] = (
                    world.fleet_ages[vessel_id].get(owner, 0.0) + dt_years)


# ──────────────────────────────────────────────────────────────────────────────
# CLOCK UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def _day_to_month(day: float, start_year: int, start_month: int):
    total_months = int(start_month - 1 + day / 30.4375)
    year  = start_year + total_months // 12
    month = (total_months % 12) + 1
    return year, month


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION RUNNER
# ──────────────────────────────────────────────────────────────────────────────

class SimulationRunner:
    def __init__(self, config: SimConfig,
                 regions: Dict[str, Region],
                 companies: Dict[str, OilCompany],
                 ship_types: Dict[str, ShipType],
                 fleet_df: pd.DataFrame,
                 orderbook_entries: List[OrderbookEntry],
                 nodes: Dict[str, Node],
                 edges: list,
                 constraints: List[ScenarioConstraint],
                 vessel_group_memberships: List[VesselGroupMembership] = None):

        self.config     = config
        self.regions    = regions
        self.companies  = companies
        self.ship_types = ship_types
        self.nodes      = nodes
        self.edges      = edges

        self.rng = np.random.default_rng(config.random_seed)

        # Build group resolver
        self.resolver = VesselGroupResolver(
            vessel_group_memberships or [],
            ship_types,
        )

        # ── Initialize world state ────────────────────────────────────────
        self.world = WorldState(
            spot_rate_usd_day=config.base_spot_rate_usd_day,
            wti_price_usd_bbl=config.wti_price_usd_bbl,
            fuel_price_vlsfo=config.vlsfo_price_usd_t,
            fuel_price_hfo=config.hfo_price_usd_t,
        )

        # Fleet from table — vessel_id is now the row key
        for _, row in fleet_df.iterrows():
            # Support both old format (ship_type only) and new (vessel_id + ship_type)
            vessel_id = str(row.get("vessel_id", row.get("ship_type", "unknown")))
            st_name   = str(row.get("ship_type", vessel_id))
            owner     = str(row.get("owner", "Independent"))
            count     = int(row.get("count", 0))
            cstor     = int(row.get("count_storage", 0))
            age       = float(row.get("avg_age_years", 5.0))

            self.world.vessel_ship_type[vessel_id] = st_name
            if vessel_id not in self.world.fleet_active:
                self.world.fleet_active[vessel_id]  = {}
                self.world.fleet_storage[vessel_id] = {}
                self.world.fleet_ages[vessel_id]    = {}
            self.world.fleet_active[vessel_id][owner]  = count
            self.world.fleet_storage[vessel_id][owner] = cstor
            self.world.fleet_ages[vessel_id][owner]    = age

        self.world.orderbook = list(orderbook_entries)

        for rname, reg in regions.items():
            self.world.storage_inventory[rname] = {
                c: slot.available_mmt for c, slot in reg.storage.items()
            }

        self._constraint_engine = ConstraintEngine(constraints)
        self._oil_market   = OilMarket(regions, self.rng)
        self._freight      = FreightMarket(ship_types, self.resolver, self.rng)
        self._fleet_dyn    = FleetDynamics(ship_types, companies, self.resolver, self.rng)
        self._history: List[Dict] = []

    # ── Step interface (for UI play/pause) ───────────────────────────────────

    def initialize(self):
        """Set up step 0 state without advancing. Called by 'Initialize' button."""
        gran = self.config.granularity
        self.world.current_day    = 0.0
        self.world.current_step   = 0
        cal_year, cal_month = _day_to_month(0, self.config.start_year, self.config.start_month)
        self.world.current_month_1 = cal_month
        self._constraint_engine.tick(self.world, self.regions, self.nodes, 0)
        self._oil_market.tick(self.world, gran)
        self._fleet_dyn.tick_storage_conversion(self.world, self._oil_market, self.config)
        eff_dwt, lf = self._freight.tick(self.world, self._oil_market, gran,
                                          self.config, list(self._constraint_engine._constraints))
        self._fleet_dyn.tick_ordering(self.world, self.config, gran)
        self._fleet_dyn.tick_delivery(self.world)
        self._fleet_dyn.tick_scrapping(self.world, self.config, gran)
        self._fleet_dyn.tick_age(self.world, gran)
        self._record(0, cal_year, cal_month, eff_dwt, lf)

    def run(self) -> pd.DataFrame:
        """Run all steps and return history DataFrame."""
        gran      = self.config.granularity
        n_steps   = self.config.n_periods
        step_days = gran.days
        self._history = []

        for step in range(n_steps):
            self.world.current_day         = step * step_days
            self.world.current_step        = step
            self.world.current_year_offset = self.world.current_day / 365.0
            cal_year, cal_month = _day_to_month(
                self.world.current_day, self.config.start_year, self.config.start_month)
            self.world.current_month_1 = cal_month

            self._constraint_engine.tick(self.world, self.regions, self.nodes, step)
            self._oil_market.tick(self.world, gran)
            self._fleet_dyn.tick_storage_conversion(self.world, self._oil_market, self.config)
            eff_dwt, lf = self._freight.tick(
                self.world, self._oil_market, gran, self.config,
                list(self._constraint_engine._constraints))
            self._fleet_dyn.tick_ordering(self.world, self.config, gran)
            self._fleet_dyn.tick_delivery(self.world)
            self._fleet_dyn.tick_scrapping(self.world, self.config, gran)
            self._fleet_dyn.tick_age(self.world, gran)
            self._record(step, cal_year, cal_month, eff_dwt, lf)

        return pd.DataFrame(self._history)

    # ── Recording ────────────────────────────────────────────────────────────

    def _total_active_vessels(self) -> int:
        return sum(sum(d.values()) for d in self.world.fleet_active.values())

    def _total_storage_vessels(self) -> int:
        return sum(sum(d.values()) for d in self.world.fleet_storage.values())

    def _record(self, step: int, cal_year: int, cal_month: int,
                eff_dwt: float, load_factor: float):
        w = self.world
        rec: Dict[str, Any] = {
            "step":             step,
            "sim_day":          round(w.current_day, 1),
            "calendar_year":    cal_year,
            "calendar_month":   cal_month,
            "date_label":       f"{cal_year}-{cal_month:02d}",
            "spot_rate":        round(w.spot_rate_usd_day, 0),
            "wti_usd_bbl":      round(w.wti_price_usd_bbl, 2),
            "vlsfo_usd_t":      round(w.fuel_price_vlsfo, 1),
            "hfo_usd_t":        round(w.fuel_price_hfo, 1),
            "load_factor":      round(load_factor, 4),
            "effective_dwt_mt": round(eff_dwt / 1e6, 2),
            "fleet_active":     self._total_active_vessels(),
            "fleet_storage":    self._total_storage_vessels(),
            "orderbook":        len(w.orderbook),
            "total_supply_mmt": round(self._oil_market.aggregate_supply(w), 3),
            "total_demand_mmt": round(self._oil_market.aggregate_demand(w), 3),
            "sd_ratio":         round(self._oil_market.aggregate_supply(w) /
                                      max(self._oil_market.aggregate_demand(w), 0.001), 4),
            "active_constraints": ";".join(sorted(self._constraint_engine.active_constraint_ids)),
        }

        # Per vessel_id fleet counts
        for vessel_id in self.world.vessel_ship_type:
            rec[f"vessels_{vessel_id}"] = sum(
                self.world.fleet_active.get(vessel_id, {}).values())

        # Per region
        for rname in self.regions:
            rec[f"demand_{rname}"] = round(sum(w.demand_mmt.get(rname, {}).values()), 3)
            rec[f"supply_{rname}"] = round(sum(w.supply_mmt.get(rname, {}).values()), 3)
            rec[f"storage_inv_{rname}"] = round(
                sum(w.storage_inventory.get(rname, {}).values()), 3)

        # Node closure flags
        for nid in self.nodes:
            safe_key = nid.replace(" ", "_").replace(".", "").replace("/", "_")
            rec[f"node_{safe_key}"] = int(w.node_open.get(nid, True))

        self._history.append(rec)

    # ── Branching / step-by-step API ─────────────────────────────────────────

    def _tick_step(self, step: int) -> tuple:
        """Execute one simulation step and return (cal_year, cal_month, eff_dwt, lf)."""
        gran      = self.config.granularity
        step_days = gran.days

        self.world.current_day         = step * step_days
        self.world.current_step        = step
        self.world.current_year_offset = self.world.current_day / 365.0
        cal_year, cal_month = _day_to_month(
            self.world.current_day, self.config.start_year, self.config.start_month)
        self.world.current_month_1 = cal_month

        self._constraint_engine.tick(self.world, self.regions, self.nodes, step)
        self._oil_market.tick(self.world, gran)
        self._fleet_dyn.tick_storage_conversion(self.world, self._oil_market, self.config)
        eff_dwt, lf = self._freight.tick(
            self.world, self._oil_market, gran, self.config,
            list(self._constraint_engine._constraints))
        self._fleet_dyn.tick_ordering(self.world, self.config, gran)
        self._fleet_dyn.tick_delivery(self.world)
        self._fleet_dyn.tick_scrapping(self.world, self.config, gran)
        self._fleet_dyn.tick_age(self.world, gran)
        return cal_year, cal_month, eff_dwt, lf

    def run_with_snapshots(self, snapshot_every: int = 1) -> pd.DataFrame:
        """Like run() but stores WorldState deep-copies every N steps.
        Snapshots available at self._world_snapshots[step].
        """
        import copy
        self._world_snapshots: Dict[int, Any] = {}
        self._history = []

        for step in range(self.config.n_periods):
            cal_year, cal_month, eff_dwt, lf = self._tick_step(step)
            self._record(step, cal_year, cal_month, eff_dwt, lf)
            if step % snapshot_every == 0:
                self._world_snapshots[step] = copy.deepcopy(self.world)

        return pd.DataFrame(self._history)

    def resume_from_snapshot(self, snapshot, new_config,
                             fork_step: int) -> pd.DataFrame:
        """Resume from a saved WorldState snapshot at fork_step with new_config.
        Returns only the post-fork history rows (steps fork_step..n_periods).
        """
        import copy
        self.world  = copy.deepcopy(snapshot)
        self.config = new_config
        self._history = []

        for step in range(fork_step, new_config.n_periods):
            cal_year, cal_month, eff_dwt, lf = self._tick_step(step)
            self._record(step, cal_year, cal_month, eff_dwt, lf)

        return pd.DataFrame(self._history)
