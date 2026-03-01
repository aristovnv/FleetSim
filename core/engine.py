"""
Maritime Fleet Simulation Engine v2

Architecture:
  SimulationWorld  – holds all entity state
  ConstraintEngine – applies/expires ScenarioConstraints each tick
  OilMarket        – equilibrium 1: supply/demand for crude/products
  FreightMarket    – equilibrium 2: vessel supply/demand → spot rate
  FleetDynamics    – stock-flow: ordering, delivery, scrapping, storage conversion
  SimulationRunner – orchestrates, records history

Granularity variants:
  WEEK    → sub-periods are days   → port times, transit times resolved at day level
  MONTH   → sub-periods are days   → same
  QUARTER → sub-periods are weeks  → transit/port times in fractional weeks
  YEAR    → sub-periods are months → coarser dynamics

Each main-loop tick is one granularity period.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import copy
import math

from core.enums import Granularity, ConstraintType, ShipCountry, NodeType, VesselStatus
from core.models import (
    Region, OilCompany, ShipType, Vessel, OrderbookEntry,
    ScenarioConstraint, SimConfig, Node, Edge, MeanStd, CompanyVolume
)


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION WORLD STATE
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class WorldState:
    """
    Mutable simulation state.  Everything that changes over time lives here.
    All entity *definitions* (ShipType, Region, OilCompany, ...) are passed in
    by reference and should not be mutated; instead, the engine uses multipliers
    and delta-dicts to represent constraint effects.
    """
    # ── Fleet ────────────────────────────────────────────────────────────────
    # {ship_type_name: {owner: count_active}}
    fleet_active:  Dict[str, Dict[str, int]] = field(default_factory=dict)
    fleet_storage: Dict[str, Dict[str, int]] = field(default_factory=dict)
    fleet_ages:    Dict[str, Dict[str, float]] = field(default_factory=dict)  # avg age proxy

    # Orderbook
    orderbook: List[OrderbookEntry] = field(default_factory=list)

    # ── Oil market ────────────────────────────────────────────────────────────
    # Effective volumes this period (after growth, seasonality, constraints)
    supply_mmt: Dict[str, Dict[str, float]] = field(default_factory=dict)  # {region: {company: mmt}}
    demand_mmt: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Storage inventory (MT) {region: {company: mmt}}
    storage_inventory: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # ── Freight market ────────────────────────────────────────────────────────
    spot_rate_usd_day: float = 25_000.0
    wti_price_usd_bbl: float = 75.0
    fuel_price_vlsfo: float = 600.0
    fuel_price_hfo:   float = 450.0

    # ── Node state (chokepoint open/closed, reduced capacity) ────────────────
    node_open:     Dict[str, bool]            = field(default_factory=dict)
    node_cap:      Dict[str, Optional[int]]   = field(default_factory=dict)

    # ── Active constraint multipliers (accumulated per period) ───────────────
    # {region: demand_multiplier}
    demand_multipliers: Dict[str, float] = field(default_factory=dict)
    supply_multipliers: Dict[str, Dict[str, float]] = field(default_factory=dict)  # {region: {company}}
    # Ships of these countries are barred from trading (sanctions)
    banned_countries: set = field(default_factory=set)
    # Extra fuel cost per MT (IMO 2020 style)
    fuel_additive_usd_t: float = 0.0

    # ── Clock ────────────────────────────────────────────────────────────────
    current_day: float = 0.0    # simulation day (0 = start_date)
    current_year_offset: float = 0.0   # fractional years since sim start
    current_month_1: int = 1    # 1-12


# ──────────────────────────────────────────────────────────────────────────────
# CONSTRAINT ENGINE
# ──────────────────────────────────────────────────────────────────────────────

class ConstraintEngine:
    """
    Applies and expires ScenarioConstraints.
    Each tick: reset multipliers → apply all active constraints.
    """

    def __init__(self, constraints: List[ScenarioConstraint]):
        self._constraints = constraints
        self._active_ids: set = set()

    def tick(self, world: WorldState, all_regions: List[str], all_nodes: Dict[str, Node]):
        day = world.current_day

        # Reset to neutral
        world.demand_multipliers = {r: 1.0 for r in all_regions}
        world.supply_multipliers = {}
        world.banned_countries = set()
        world.fuel_additive_usd_t = 0.0
        # Node states: restore open unless constraint says otherwise
        for nid, node in all_nodes.items():
            world.node_open[nid] = node.is_open
            world.node_cap[nid]  = node.max_vessels_per_period

        for c in self._constraints:
            if c.apply_on_day > day:
                continue  # not yet active
            if c.end_on_day is not None and day > c.end_on_day:
                self._active_ids.discard(c.constraint_id)
                continue  # expired

            self._active_ids.add(c.constraint_id)
            self._apply(c, world, all_regions)

    def _apply(self, c: ScenarioConstraint, world: WorldState, all_regions: List[str]):
        ct = c.constraint_type

        if ct == ConstraintType.DEMAND_SHOCK:
            targets = c.target_regions if c.target_regions else all_regions
            for r in targets:
                world.demand_multipliers[r] = world.demand_multipliers.get(r, 1.0) * c.multiplier

        elif ct == ConstraintType.SUPPLY_SHOCK:
            targets = c.target_regions if c.target_regions else all_regions
            for r in targets:
                for company in (c.target_companies or ["__all__"]):
                    if r not in world.supply_multipliers:
                        world.supply_multipliers[r] = {}
                    world.supply_multipliers[r][company] = (
                        world.supply_multipliers[r].get(company, 1.0) * c.multiplier)

        elif ct in (ConstraintType.SANCTION_SHIP_FLAG, ConstraintType.SANCTION_COMPANY):
            # Banned countries → ships cannot trade
            for country in c.target_countries:
                world.banned_countries.add(country)
            # Supply reduction for sanctioned regions/companies
            targets = c.target_regions if c.target_regions else all_regions
            for r in targets:
                for company in (c.target_companies or ["__all__"]):
                    if r not in world.supply_multipliers:
                        world.supply_multipliers[r] = {}
                    key = company
                    world.supply_multipliers[r][key] = (
                        world.supply_multipliers[r].get(key, 1.0) * c.multiplier)

        elif ct == ConstraintType.SANCTION_PORT:
            targets = c.target_regions if c.target_regions else []
            for r in targets:
                world.demand_multipliers[r] = 0.0
                if r not in world.supply_multipliers:
                    world.supply_multipliers[r] = {}
                world.supply_multipliers[r]["__all__"] = 0.0

        elif ct == ConstraintType.NODE_CLOSURE:
            for nid in c.target_nodes:
                world.node_open[nid] = False

        elif ct == ConstraintType.NODE_CAPACITY_CHANGE:
            for nid in c.target_nodes:
                if c.capacity_vessels is not None:
                    world.node_cap[nid] = c.capacity_vessels

        elif ct == ConstraintType.FUEL_REGULATION:
            world.fuel_additive_usd_t += c.additive

        elif ct == ConstraintType.SPOT_PRICE_SHOCK:
            # Treated in FreightMarket as a multiplier on base rate
            pass  # stored via multiplier field accessed by freight market

    @property
    def active_constraint_ids(self) -> set:
        return self._active_ids


# ──────────────────────────────────────────────────────────────────────────────
# OIL MARKET (Equilibrium 1)
# ──────────────────────────────────────────────────────────────────────────────

class OilMarket:
    """
    Resolves effective supply and demand each period.

    1. Base volumes drawn from Region definitions with growth compounding.
    2. Seasonality coefficients applied by current month.
    3. Constraint multipliers applied.
    4. Stochastic noise added.
    5. Supply/demand balance → inventory change.
    """

    def __init__(self, regions: Dict[str, Region], rng):
        self.regions = regions
        self.rng = rng
        # Accumulate compounded growth state
        self._demand_growth_state: Dict[str, Dict[str, float]] = {}
        self._supply_growth_state: Dict[str, Dict[str, float]] = {}
        for rname, reg in regions.items():
            self._demand_growth_state[rname] = {}
            self._supply_growth_state[rname] = {}
            for company in reg.demand:
                self._demand_growth_state[rname][company] = 1.0
            for company in reg.supply:
                self._supply_growth_state[rname][company] = 1.0

    def tick(self, world: WorldState, granularity: Granularity):
        dt_years = granularity.years
        month = world.current_month_1

        world.supply_mmt = {}
        world.demand_mmt = {}

        for rname, reg in self.regions.items():
            world.supply_mmt[rname] = {}
            world.demand_mmt[rname] = {}
            demand_mult = world.demand_multipliers.get(rname, 1.0)

            # Demand
            for company, cv in reg.demand.items():
                # Compound growth
                growth = reg.demand_growth.get(company)
                self._demand_growth_state[rname][company] = (
                    self._demand_growth_state[rname].get(company, 1.0)
                    * (1 + growth * dt_years)
                )
                base = cv.volume.mean * self._demand_growth_state[rname][company]
                # Seasonality
                seasonal = getattr(cv, "_seasonal", None)
                if seasonal is not None:
                    base *= seasonal.get(month)
                # Noise
                noise = self.rng.normal(0, cv.volume.std * math.sqrt(dt_years))
                vol = max(0.0, base + noise)
                # Constraint
                vol *= demand_mult
                world.demand_mmt[rname][company] = vol

            # Supply
            sup_mult_region = world.supply_multipliers.get(rname, {})
            for company, cv in reg.supply.items():
                growth = reg.supply_growth.get(company)
                self._supply_growth_state[rname][company] = (
                    self._supply_growth_state[rname].get(company, 1.0)
                    * (1 + growth * dt_years)
                )
                base = cv.volume.mean * self._supply_growth_state[rname][company]
                seasonal = getattr(cv, "_seasonal", None)
                if seasonal is not None:
                    base *= seasonal.get(month)
                noise = self.rng.normal(0, cv.volume.std * math.sqrt(dt_years))
                vol = max(0.0, base + noise)
                # Company-specific or __all__ multiplier
                mult = sup_mult_region.get(company, sup_mult_region.get("__all__", 1.0))
                vol *= mult
                world.supply_mmt[rname][company] = vol

        # Update storage inventories
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

    @property
    def total_demand(self, world: Optional[WorldState] = None) -> float:
        # Only useful when called with a world snapshot — see SimulationRunner
        return 0.0

    def aggregate_supply(self, world: WorldState) -> float:
        return sum(v for rv in world.supply_mmt.values() for v in rv.values())

    def aggregate_demand(self, world: WorldState) -> float:
        return sum(v for rv in world.demand_mmt.values() for v in rv.values())


# ──────────────────────────────────────────────────────────────────────────────
# FREIGHT MARKET (Equilibrium 2)
# ──────────────────────────────────────────────────────────────────────────────

class FreightMarket:
    """
    Vessel supply/demand equilibrium.

    Effective cargo demand (ton-miles proxy) vs. active fleet capacity
    → load factor → nonlinear rate adjustment (tanh curve)
    → mean-reversion spot rate with stochastic component.

    Sanctions: ships of banned_countries are excluded from effective supply.
    Node closures: increase average route distance → increase demand ton-miles.
    """

    # Ton-mile multiplier per closed chokepoint (rough order of magnitude)
    CHOKEPOINT_TONMILE_FACTORS: Dict[str, float] = {
        "Strait of Hormuz": 1.35,   # reroute around Cape adds ~35% ton-miles
        "Suez Canal":       1.25,
        "Strait of Malacca": 1.15,
        "Panama Canal":     1.20,
        "Danish Straits":   1.10,
    }

    def __init__(self, ship_types: Dict[str, ShipType], rng):
        self.ship_types = ship_types
        self.rng = rng

    def _effective_fleet_dwt(self, world: WorldState) -> float:
        """DWT of tradeable vessels (excludes banned countries, storage)."""
        total = 0.0
        for st_name, owners in world.fleet_active.items():
            st = self.ship_types.get(st_name)
            if st is None:
                continue
            if st.country in world.banned_countries:
                continue
            count = sum(owners.values())
            total += count * st.dwt.mean

        return total

    def _tonmile_multiplier(self, world: WorldState) -> float:
        mult = 1.0
        for node_id, factor in self.CHOKEPOINT_TONMILE_FACTORS.items():
            if not world.node_open.get(node_id, True):
                mult *= factor
        return mult

    def _lrmc(self, st: ShipType, world: WorldState, granularity: Granularity) -> float:
        """Long-run marginal cost (breakeven spot rate) for a ship type."""
        # Fuel cost (daily)
        effective_fuel_price = world.fuel_price_vlsfo if st.scrubber_fitted else (
            world.fuel_price_hfo + world.fuel_additive_usd_t)
        fuel_cost = st.fuel_consumption_tons_day * effective_fuel_price / 1000.0
        # OpEx
        opex = st.daily_opex.mean
        # Capex annuity
        capex_daily = st.build_cost_musd * 1e6 / (st.economic_life_years * 365.0)
        return opex + fuel_cost + capex_daily

    def tick(self, world: WorldState, oil_market: OilMarket,
             granularity: Granularity, config: SimConfig,
             active_constraints: List[ScenarioConstraint]):
        dt_years = granularity.years
        month = world.current_month_1

        # Effective fleet supply
        eff_dwt = self._effective_fleet_dwt(world)

        # Cargo demand (converted from MMT to MT, scaled by ton-mile factor)
        total_demand_mt = oil_market.aggregate_demand(world) * 1e6
        tonmile_mult = self._tonmile_multiplier(world)
        adjusted_demand_mt = total_demand_mt * tonmile_mult

        # Load factor
        if eff_dwt > 0:
            load_factor = min(1.10, adjusted_demand_mt / eff_dwt)
        else:
            load_factor = 1.10

        # Nonlinear rate signal: tanh centred at 85% utilization
        # full => rates spike sharply above ~95%
        util_signal = (load_factor - 0.85) / 0.10
        rate_adjustment = math.tanh(util_signal) * 0.5  # ±50% of base

        # Apply spot price shock constraints
        spot_mult = 1.0
        for c in active_constraints:
            if c.constraint_type == ConstraintType.SPOT_PRICE_SHOCK:
                if c.apply_on_day <= world.current_day:
                    if c.end_on_day is None or world.current_day <= c.end_on_day:
                        spot_mult *= c.multiplier

        # Target rate with seasonality already in spot_mult
        target_rate = config.base_spot_rate_usd_day * (1 + rate_adjustment) * spot_mult

        # Mean-reversion
        reversion_speed = {
            Granularity.WEEK:    8.0,
            Granularity.MONTH:   4.0,
            Granularity.QUARTER: 2.0,
            Granularity.YEAR:    1.0,
        }[granularity]
        world.spot_rate_usd_day += (
            (target_rate - world.spot_rate_usd_day)
            * reversion_speed * dt_years
        )
        # Stochastic shock
        world.spot_rate_usd_day *= (
            1 + self.rng.normal(0, config.spot_rate_volatility * math.sqrt(dt_years))
        )
        world.spot_rate_usd_day = max(3_000.0, world.spot_rate_usd_day)

        # Fuel price random walk
        world.fuel_price_vlsfo *= (
            1 + self.rng.normal(0, config.fuel_price_volatility * math.sqrt(dt_years))
        )
        world.fuel_price_hfo *= (
            1 + self.rng.normal(0, config.fuel_price_volatility * math.sqrt(dt_years))
        )
        world.fuel_price_vlsfo = max(200.0, world.fuel_price_vlsfo)
        world.fuel_price_hfo   = max(150.0, world.fuel_price_hfo)

        # WTI random walk (correlated with fuel)
        world.wti_price_usd_bbl *= (
            1 + self.rng.normal(0, config.wti_price_volatility * math.sqrt(dt_years))
        )
        world.wti_price_usd_bbl = max(20.0, world.wti_price_usd_bbl)

        return eff_dwt, load_factor


# ──────────────────────────────────────────────────────────────────────────────
# FLEET DYNAMICS (Engelen et al. stock-flow)
# ──────────────────────────────────────────────────────────────────────────────

class FleetDynamics:
    """
    Ordering, delivery, scrapping, and storage conversion.

    Ordering: owners compare spot rate to LRMC.  Positive signal → orders.
    Build time: drawn from ShipType distribution for each order.
    Delivery: orderbook entries with delivery_day <= current_day move to active fleet.
    Scrapping: low rates → oldest/cheapest vessels exit.  Age proxy via avg_age.
    Storage: S/D ratio > threshold → VLCCs/Suezmaxes converted to FSO.
    Limits: config.max_newbuilds_per_period_global caps total orders placed per period.
    """

    def __init__(self, ship_types: Dict[str, ShipType],
                 companies: Dict[str, OilCompany], rng):
        self.ship_types = ship_types
        self.companies = companies
        self.rng = rng
        self._vessel_counter = 0

    def _lrmc(self, st: ShipType, world: WorldState) -> float:
        eff_fuel = world.fuel_price_vlsfo if st.scrubber_fitted else (
            world.fuel_price_hfo + world.fuel_additive_usd_t)
        fuel_daily = st.fuel_consumption_tons_day * eff_fuel / 1000.0
        capex_daily = st.build_cost_musd * 1e6 / (st.economic_life_years * 365.0)
        return st.daily_opex.mean + fuel_daily + capex_daily

    def tick_ordering(self, world: WorldState, config: SimConfig, granularity: Granularity):
        dt_years = granularity.years
        budget = config.max_newbuilds_per_period_global

        for st_name, st in self.ship_types.items():
            if budget <= 0:
                break
            # Skip if ships of this flag are sanctioned
            if st.country in world.banned_countries:
                continue

            lrmc = self._lrmc(st, world)
            profit_signal = (world.spot_rate_usd_day - lrmc) / max(lrmc, 1.0)

            if profit_signal <= 0:
                continue

            current_fleet = sum(world.fleet_active.get(st_name, {}).values())
            max_orders = max(1, int(current_fleet * 0.12))
            n_orders = int(
                config.ordering_sensitivity
                * profit_signal
                * current_fleet
                * dt_years
                * self.rng.uniform(0.5, 1.5)
            )
            n_orders = min(n_orders, max_orders, budget)

            # Determine ordering company (largest owner of this type → reinvests)
            owners = world.fleet_active.get(st_name, {})
            if owners:
                orderer = max(owners, key=lambda o: owners[o])
            else:
                orderer = "Independent"

            for _ in range(n_orders):
                bt = st.build_time_years + self.rng.normal(0, st.build_time_std_years)
                bt = max(0.5, bt)
                delivery_day = world.current_day + bt * 365.0
                world.orderbook.append(OrderbookEntry(
                    ship_type=st_name,
                    owner=orderer,
                    ordered_on_day=world.current_day,
                    delivery_day=delivery_day,
                    build_cost_musd=st.build_cost_musd,
                ))
                budget -= 1

    def tick_delivery(self, world: WorldState):
        remaining = []
        for entry in world.orderbook:
            if entry.delivery_day <= world.current_day:
                if entry.ship_type not in world.fleet_active:
                    world.fleet_active[entry.ship_type]  = {}
                    world.fleet_storage[entry.ship_type] = {}
                    world.fleet_ages[entry.ship_type]    = {}
                world.fleet_active[entry.ship_type][entry.owner] = (
                    world.fleet_active[entry.ship_type].get(entry.owner, 0) + 1)
                # New vessel: very young, update avg age proxy
                prev = world.fleet_ages[entry.ship_type].get(entry.owner, 0.0)
                count = world.fleet_active[entry.ship_type][entry.owner]
                world.fleet_ages[entry.ship_type][entry.owner] = (
                    (prev * (count - 1) + 0.0) / count)
            else:
                remaining.append(entry)
        world.orderbook = remaining

    def tick_scrapping(self, world: WorldState, config: SimConfig, granularity: Granularity):
        dt_years = granularity.years
        scrap_pressure = max(0.0,
            config.scrapping_threshold_usd_day - world.spot_rate_usd_day)

        if scrap_pressure <= 0:
            # Age-mandatory scrapping (vessels beyond economic life)
            for st_name, st in self.ship_types.items():
                for owner in list(world.fleet_active.get(st_name, {})):
                    avg_age = world.fleet_ages.get(st_name, {}).get(owner, 0.0)
                    if avg_age > st.economic_life_years:
                        count = world.fleet_active[st_name][owner]
                        if count > 0:
                            world.fleet_active[st_name][owner] = max(0, count - 1)
            return

        # Price-driven scrapping: independent / shadow first
        priority_order = [
            ShipCountry.SHADOW,
            ShipCountry.RUSSIA,
            ShipCountry.OTHER_EASTERN,
            ShipCountry.CHINA,
            ShipCountry.INDIA,
            ShipCountry.OTHER_WESTERN,
            ShipCountry.GREECE,
            ShipCountry.NORWAY,
            ShipCountry.JAPAN,
            ShipCountry.SOUTH_KOREA,
            ShipCountry.USA,
        ]
        n_to_scrap_total = max(0, int(scrap_pressure / 3_000 * dt_years))

        for priority_country in priority_order:
            if n_to_scrap_total <= 0:
                break
            for st_name, st in self.ship_types.items():
                if st.country != priority_country:
                    continue
                for owner in sorted(world.fleet_active.get(st_name, {}),
                                    key=lambda o: world.fleet_ages.get(st_name, {}).get(o, 0.0),
                                    reverse=True):
                    if n_to_scrap_total <= 0:
                        break
                    count = world.fleet_active[st_name][owner]
                    if count > 0:
                        world.fleet_active[st_name][owner] -= 1
                        n_to_scrap_total -= 1

    def tick_storage_conversion(self, world: WorldState,
                                oil_market: OilMarket, config: SimConfig):
        total_supply = oil_market.aggregate_supply(world)
        total_demand = oil_market.aggregate_demand(world)
        sd_ratio = total_supply / max(total_demand, 0.001)

        if sd_ratio > config.storage_conversion_sd_ratio:
            # Convert some large vessels to storage
            for st_name, st in self.ship_types.items():
                if not st.can_be_storage:
                    continue
                for owner in list(world.fleet_active.get(st_name, {})):
                    active = world.fleet_active[st_name].get(owner, 0)
                    if active <= 1:
                        continue
                    n_convert = max(0, int((sd_ratio - 1.0) * active * 0.25))
                    n_convert = min(n_convert, active - 1)
                    if n_convert > 0:
                        world.fleet_active[st_name][owner] -= n_convert
                        world.fleet_storage[st_name][owner] = (
                            world.fleet_storage[st_name].get(owner, 0) + n_convert)
        else:
            # Return storage vessels when market tightens
            if sd_ratio < 0.97:
                for st_name in list(world.fleet_storage):
                    for owner in list(world.fleet_storage[st_name]):
                        n_back = world.fleet_storage[st_name].get(owner, 0)
                        if n_back > 0:
                            world.fleet_active[st_name][owner] = (
                                world.fleet_active[st_name].get(owner, 0) + n_back)
                            world.fleet_storage[st_name][owner] = 0

    def tick_age(self, world: WorldState, granularity: Granularity):
        """Increment vessel ages by one period."""
        dt_years = granularity.years
        for st_name in world.fleet_ages:
            for owner in world.fleet_ages[st_name]:
                world.fleet_ages[st_name][owner] = (
                    world.fleet_ages[st_name].get(owner, 0.0) + dt_years)


# ──────────────────────────────────────────────────────────────────────────────
# CLOCK UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def _day_to_month(day: float, start_year: int, start_month: int) -> Tuple[int, int]:
    """Return (year, month_1indexed) for a given simulation day."""
    total_months = int(start_month - 1 + day / 30.4375)
    year   = start_year + total_months // 12
    month  = (total_months % 12) + 1
    return year, month


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION RUNNER
# ──────────────────────────────────────────────────────────────────────────────

class SimulationRunner:
    """
    Orchestrates one complete simulation run.

    Parameters
    ----------
    config      : SimConfig
    regions     : from load_regions()
    companies   : from load_companies()
    ship_types  : from load_ship_types()
    fleet_df    : raw fleet DataFrame (template_fleet() shape)
    orderbook_entries : from load_orderbook()
    nodes       : from load_nodes()
    edges       : from load_edges()
    constraints : from load_constraints()
    """

    def __init__(self, config: SimConfig,
                 regions: Dict[str, Region],
                 companies: Dict[str, OilCompany],
                 ship_types: Dict[str, ShipType],
                 fleet_df: pd.DataFrame,
                 orderbook_entries: List[OrderbookEntry],
                 nodes: Dict[str, Node],
                 edges: list,
                 constraints: List[ScenarioConstraint]):

        self.config     = config
        self.regions    = regions
        self.companies  = companies
        self.ship_types = ship_types
        self.nodes      = nodes
        self.edges      = edges

        self.rng = np.random.default_rng(config.random_seed)

        # ── Initialize world state ────────────────────────────────────────
        self.world = WorldState(
            spot_rate_usd_day=config.base_spot_rate_usd_day,
            wti_price_usd_bbl=config.wti_price_usd_bbl,
            fuel_price_vlsfo=config.vlsfo_price_usd_t,
            fuel_price_hfo=config.hfo_price_usd_t,
        )

        # Fleet from template
        for _, row in fleet_df.iterrows():
            st_name = str(row["ship_type"])
            owner   = str(row["owner"])
            count   = int(row.get("count", 0))
            cstor   = int(row.get("count_storage", 0))
            age     = float(row.get("avg_age_years", 5.0))
            if st_name not in self.world.fleet_active:
                self.world.fleet_active[st_name]  = {}
                self.world.fleet_storage[st_name] = {}
                self.world.fleet_ages[st_name]    = {}
            self.world.fleet_active[st_name][owner]  = count
            self.world.fleet_storage[st_name][owner] = cstor
            self.world.fleet_ages[st_name][owner]    = age

        # Initial orderbook
        self.world.orderbook = list(orderbook_entries)

        # Initial storage
        for rname, reg in regions.items():
            self.world.storage_inventory[rname] = {
                c: slot.available_mmt for c, slot in reg.storage.items()
            }

        # Subsystems
        self._constraint_engine = ConstraintEngine(constraints)
        self._oil_market   = OilMarket(regions, self.rng)
        self._freight      = FreightMarket(ship_types, self.rng)
        self._fleet_dyn    = FleetDynamics(ship_types, companies, self.rng)

        # History
        self._history: List[Dict] = []

    # ── Main run ─────────────────────────────────────────────────────────────

    def run(self) -> pd.DataFrame:
        gran    = self.config.granularity
        n_steps = self.config.n_periods
        step_days = gran.days

        for step in range(n_steps):
            self.world.current_day          = step * step_days
            self.world.current_year_offset  = self.world.current_day / 365.0
            cal_year, cal_month = _day_to_month(
                self.world.current_day,
                self.config.start_year,
                self.config.start_month,
            )
            self.world.current_month_1 = cal_month

            # 1. Constraints
            self._constraint_engine.tick(
                self.world, list(self.regions.keys()), self.nodes)

            # 2. Oil market
            self._oil_market.tick(self.world, gran)

            # 3. Storage conversion (before freight so capacity is correct)
            self._fleet_dyn.tick_storage_conversion(
                self.world, self._oil_market, self.config)

            # 4. Freight market
            eff_dwt, load_factor = self._freight.tick(
                self.world, self._oil_market, gran, self.config,
                list(self._constraint_engine._constraints))

            # 5. Fleet dynamics
            self._fleet_dyn.tick_ordering(self.world, self.config, gran)
            self._fleet_dyn.tick_delivery(self.world)
            self._fleet_dyn.tick_scrapping(self.world, self.config, gran)
            self._fleet_dyn.tick_age(self.world, gran)

            # 6. Record
            self._record(step, cal_year, cal_month, eff_dwt, load_factor)

        return pd.DataFrame(self._history)

    # ── Recording ────────────────────────────────────────────────────────────

    def _total_active(self, st_name: Optional[str] = None) -> int:
        if st_name:
            return sum(self.world.fleet_active.get(st_name, {}).values())
        return sum(sum(d.values()) for d in self.world.fleet_active.values())

    def _total_storage(self) -> int:
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

            # Market
            "spot_rate":        round(w.spot_rate_usd_day, 0),
            "wti_usd_bbl":      round(w.wti_price_usd_bbl, 2),
            "vlsfo_usd_t":      round(w.fuel_price_vlsfo, 1),
            "hfo_usd_t":        round(w.fuel_price_hfo, 1),
            "load_factor":      round(load_factor, 4),
            "effective_dwt_mt": round(eff_dwt / 1e6, 2),

            # Fleet totals
            "fleet_active":     self._total_active(),
            "fleet_storage":    self._total_storage(),
            "orderbook":        len(w.orderbook),

            # Oil balance
            "total_supply_mmt": round(self._oil_market.aggregate_supply(w), 3),
            "total_demand_mmt": round(self._oil_market.aggregate_demand(w), 3),
            "sd_ratio":         round(self._oil_market.aggregate_supply(w) /
                                      max(self._oil_market.aggregate_demand(w), 0.001), 4),

            # Active constraints
            "active_constraints": ";".join(sorted(
                self._constraint_engine.active_constraint_ids)),
        }

        # Per ship type
        for st_name in self.ship_types:
            rec[f"active_{st_name}"]  = self._total_active(st_name)
            rec[f"storage_{st_name}"] = sum(
                self.world.fleet_storage.get(st_name, {}).values())

        # Per region demand & supply
        for rname in self.regions:
            rec[f"demand_{rname}"] = round(
                sum(w.demand_mmt.get(rname, {}).values()), 3)
            rec[f"supply_{rname}"] = round(
                sum(w.supply_mmt.get(rname, {}).values()), 3)
            inv = w.storage_inventory.get(rname, {})
            rec[f"storage_inv_{rname}"] = round(sum(inv.values()), 3)

        # Node closure flags
        for nid in self.nodes:
            safe_key = nid.replace(" ", "_").replace(".", "")
            rec[f"node_{safe_key}"] = int(w.node_open.get(nid, True))

        self._history.append(rec)


