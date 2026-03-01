"""
Maritime Fleet Composition Simulation Engine
Based on Engelen, Meersman & Van de Voorde (2006) System Dynamics approach
Extended with regime-aware structural breaks and adaptive fleet composition
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import random
from enum import Enum

# ──────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────────────────────

class Granularity(Enum):
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"

@dataclass
class Region:
    name: str
    latitude: float
    longitude: float
    company_demand_tons: float        # MT per period
    avail_demand_tons: float        # MT per period
    #demand_growth_rate: float      # annual %
    company_demand_std: float       # std dev as fraction of mean
    avail_demand_std: float       # std dev as fraction of mean
    company_storage_capacity: float        # MT (land-based)
    avail_storage_capacity: float        # MT (land-based)
    total_storage_capacity: float #avail_storage_capacity + total_storage_capacity
    company_price: float
    avail_price: float
    company_price_std: float
    avail_price_std: float
    spot_price_premium: float
    fuel_price_premium: float
    #port_capacity: float           # max vessels simultaneously - doesn't work for regions and time stamp

@dataclass
class OilCompany: #hm
    name: str
    home_region: str
    supply_regions: List[str]      # where they produce
    demand_regions: List[str]      # where they need delivery
    base_supply_tons: float        # MT per period
    supply_growth_rate: float
    supply_volatility: float
    wtp_spot: float                # willingness to pay on spot market ($/ton)
    contract_fraction: float       # fraction under long-term contract

@dataclass
class ShipType:
    name: str                      # e.g. VLCC, Suezmax, Aframax
    dwt: float                     # deadweight tons
    dwt_std: float                     # deadweight tons
    speed_knots: float
    speed_knots_std: float 
    daily_opex: float              # $/day operating cost
    daily_opex_std: float              # $/day operating cost dev
    fuel_consumption_tons_day: float
    scrubber_fitted: bool
    build_cost_musd: float
    scrap_value_musd: float
    build_time_years: float
    economic_life_years: float
    can_be_storage: bool           # can convert to FSO

@dataclass 
class Vessel: #hm
    vessel_id: str
    ship_type: ShipType
    owner: str                     # oil company or independent
    age_years: float
    status: str                    # 'active', 'storage', 'laid_up', 'scrapped'
    current_region: str
    utilization: float             # 0-1
    last_cargo: Optional[str] = None

@dataclass
class SimConfig:
    """All tunable parameters surfaced to Streamlit UI"""
    # Simulation control
    sim_periods: int = 100
    sim_granularity: Granularity = Granularity.WEEK
    time_step_days: int = 7
    random_seed: int = 42

    # Market parameters
    base_spot_rate_usd_day: float = 25000.0
    spot_rate_std: float = 0.25
    fuel_price_usd_ton: float = 600.0
    fuel_price_std: float = 0.15
    
    # Fleet dynamics (Engelen et al. stock-flow)
    ordering_lag_years: float = 2.5        # avg time from order to delivery
    ordering_sensitivity: float = 0.3      # how strongly owners react to rate signals
    scrapping_threshold_usd_day: float = 8000.0  # below this rate, scrap old vessels
    scrapping_age_threshold: float = 25.0  # mandatory scrapping age
    
    # Storage conversion
    storage_conversion_threshold: float = 0.6   # supply/demand ratio above which storage attractive
    storage_daily_rate_usd: float = 35000.0      # rate when used as FSO
    storage_conversion_cost_musd: float = 5.0
    
    # Regime switches (structural breaks)
    enable_imo2020: bool = True
    imo2020_year: int = 3          # year within simulation
    imo2020_fuel_premium: float = 150.0  # $/ton increase for non-compliant
    
    enable_sanctions: bool = False
    sanctions_year: int = 5
    sanctions_region: str = "Baltic"
    sanctions_capacity_reduction: float = 0.3
    
    enable_demand_shock: bool = False
    demand_shock_year: int = 4
    demand_shock_magnitude: float = -0.25   # -25% demand collapse
    demand_shock_duration_years: float = 1.5

    # Regions active
    active_regions: List[str] = field(default_factory=lambda: [
        "USGulf", "North Sea", "Baltic", "Mediterranean", 
        "Persian Gulf", "West Africa", "Southeast Asia"
    ])


# ──────────────────────────────────────────────────────────────────────────────
# DEFAULT WORLD STATE
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_REGIONS = {
    "USGulf":        Region("USGulf",        29.5, -90.5, 45.0, 0.02, 0.10, 80.0,  12),
    "North Sea":     Region("North Sea",     57.0,   2.0, 30.0, 0.01, 0.12, 40.0,  8),
    "Baltic":        Region("Baltic",        59.0,  22.0, 20.0, 0.01, 0.15, 25.0,  6),
    "Mediterranean": Region("Mediterranean", 38.0,  18.0, 35.0, 0.02, 0.10, 50.0,  10),
    "Persian Gulf":  Region("Persian Gulf",  26.0,  54.0, 90.0, 0.03, 0.08, 100.0, 20),
    "West Africa":   Region("West Africa",    4.0,   3.0, 25.0, 0.04, 0.18, 20.0,  6),
    "Southeast Asia":Region("Southeast Asia", 5.0, 110.0, 55.0, 0.04, 0.12, 60.0,  15),
    "Alaska":        Region("Alaska",        61.0,-150.0, 10.0, 0.00, 0.20, 10.0,  3),
    "Caribbean":     Region("Caribbean",     15.0, -75.0, 18.0, 0.02, 0.12, 20.0,  5),
}

DEFAULT_COMPANIES = {
    "Saudi Aramco": OilCompany("Saudi Aramco", "Persian Gulf",
        supply_regions=["Persian Gulf"],
        demand_regions=["Mediterranean", "Southeast Asia", "USGulf"],
        base_supply_tons=80.0, supply_growth_rate=0.02, supply_volatility=0.05,
        wtp_spot=30000, contract_fraction=0.7),
    "Shell":        OilCompany("Shell", "North Sea",
        supply_regions=["North Sea", "West Africa"],
        demand_regions=["North Sea", "Mediterranean", "USGulf"],
        base_supply_tons=40.0, supply_growth_rate=0.01, supply_volatility=0.10,
        wtp_spot=28000, contract_fraction=0.6),
    "ExxonMobil":   OilCompany("ExxonMobil", "USGulf",
        supply_regions=["USGulf", "Alaska"],
        demand_regions=["USGulf", "Caribbean", "Mediterranean"],
        base_supply_tons=35.0, supply_growth_rate=0.01, supply_volatility=0.10,
        wtp_spot=27000, contract_fraction=0.65),
    "BP":           OilCompany("BP", "North Sea",
        supply_regions=["North Sea", "Caribbean"],
        demand_regions=["North Sea", "Mediterranean"],
        base_supply_tons=30.0, supply_growth_rate=0.01, supply_volatility=0.12,
        wtp_spot=27500, contract_fraction=0.6),
    "Rosneft":      OilCompany("Rosneft", "Baltic",
        supply_regions=["Baltic"],
        demand_regions=["Mediterranean", "Southeast Asia"],
        base_supply_tons=25.0, supply_growth_rate=0.02, supply_volatility=0.15,
        wtp_spot=25000, contract_fraction=0.5),
    "Independent":  OilCompany("Independent", "USGulf",
        supply_regions=list(DEFAULT_REGIONS.keys()) if False else [],
        demand_regions=list(DEFAULT_REGIONS.keys()) if False else [],
        base_supply_tons=10.0, supply_growth_rate=0.02, supply_volatility=0.25,
        wtp_spot=32000, contract_fraction=0.2),
}
# patch Independent regions post-init
DEFAULT_COMPANIES["Independent"].supply_regions = list(DEFAULT_REGIONS.keys())
DEFAULT_COMPANIES["Independent"].demand_regions = list(DEFAULT_REGIONS.keys())

DEFAULT_SHIP_TYPES = {
    "VLCC":    ShipType("VLCC",    300000, 15.5, 8500,  90.0, False, 120.0, 30.0, 2.5, 25, True),
    "Suezmax": ShipType("Suezmax", 160000, 15.0, 6500,  60.0, False,  75.0, 18.0, 2.0, 25, True),
    "Aframax": ShipType("Aframax",  80000, 14.5, 5000,  45.0, False,  55.0, 12.0, 2.0, 25, True),
    "Panamax": ShipType("Panamax",  60000, 14.0, 4200,  38.0, False,  45.0,  9.0, 2.0, 25, False),
    "MR":      ShipType("MR",       45000, 14.0, 3500,  30.0, False,  38.0,  7.0, 1.5, 25, False),
}

# Initial fleet: {ship_type: {owner: count}}
DEFAULT_FLEET = {
    "VLCC":    {"Saudi Aramco": 8,  "Shell": 3, "ExxonMobil": 2, "Independent": 5},
    "Suezmax": {"Saudi Aramco": 4,  "Shell": 6, "BP": 4,         "Independent": 8},
    "Aframax": {"ExxonMobil": 5,    "BP": 4,    "Rosneft": 6,    "Independent": 10},
    "Panamax": {"ExxonMobil": 3,    "BP": 3,    "Independent": 7},
    "MR":      {"Shell": 4,         "BP": 3,    "Independent": 8},
}


# ──────────────────────────────────────────────────────────────────────────────
# SIMULATION ENGINE
# ──────────────────────────────────────────────────────────────────────────────

class MaritimeSimulation:
    """
    System dynamics model of maritime oil tanker market.
    Two equilibria:
      1. Oil supply/demand equilibrium  (commodity market)
      2. Vessel supply/demand equilibrium (freight market)
    
    Stock-flow structure follows Engelen et al. (2006):
      - Vessels ordered → under construction → active fleet → scrapped
      - Cargo demand drives freight rates
      - Freight rates drive ordering and scrapping decisions
    """

    def __init__(self, config: SimConfig,
                 regions: Dict[str, Region] = None,
                 companies: Dict[str, OilCompany] = None,
                 ship_types: Dict[str, ShipType] = None,
                 initial_fleet: Dict[str, Dict[str, int]] = None):

        self.config = config
        self.regions   = regions   or DEFAULT_REGIONS
        self.companies = companies or DEFAULT_COMPANIES
        self.ship_types = ship_types or DEFAULT_SHIP_TYPES
        
        self.rng = np.random.default_rng(config.random_seed)

        # ── State variables ──────────────────────────────────────────────────
        self.time_step = 0
        self.current_year = 0.0

        # Fleet state: {ship_type: {owner: count_active}}
        self.fleet_active: Dict[str, Dict[str, int]] = {}
        # FSO / storage vessels: {ship_type: {owner: count}}
        self.fleet_storage: Dict[str, Dict[str, int]] = {}
        # Vessels on order (pipeline): list of (delivery_year, ship_type, owner)
        self.orderbook: List[Tuple[float, str, str]] = []

        # Initialize fleet from defaults
        fleet_def = initial_fleet or DEFAULT_FLEET
        for st in self.ship_types:
            self.fleet_active[st] = {}
            self.fleet_storage[st] = {}
            if st in fleet_def:
                for owner, count in fleet_def[st].items():
                    self.fleet_active[st][owner] = count
                    self.fleet_storage[st][owner] = 0

        # ── Market state ──────────────────────────────────────────────────────
        self.spot_rate: float = config.base_spot_rate_usd_day
        self.fuel_price: float = config.fuel_price_usd_ton
        # per-region demand (MT/period)
        self.regional_demand: Dict[str, float] = {
            r: reg.base_demand_tons for r, reg in self.regions.items()
        }
        # per-company supply (MT/period)
        self.company_supply: Dict[str, float] = {
            c: comp.base_supply_tons for c, comp in self.companies.items()
        }
        # storage inventory per region (MT)
        self.storage_inventory: Dict[str, float] = {r: 0.0 for r in self.regions}

        # ── Regime flags ──────────────────────────────────────────────────────
        self.imo2020_active = False
        self.sanctions_active = False
        self.demand_shock_active = False

        # ── History collector ─────────────────────────────────────────────────
        self.history: List[Dict] = []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def total_active_vessels(self, ship_type: Optional[str] = None) -> int:
        if ship_type:
            return sum(self.fleet_active.get(ship_type, {}).values())
        return sum(sum(d.values()) for d in self.fleet_active.values())

    def total_storage_vessels(self) -> int:
        return sum(sum(d.values()) for d in self.fleet_storage.values())

    def total_fleet_capacity_dwt(self) -> float:
        cap = 0.0
        for st, owners in self.fleet_active.items():
            cap += sum(owners.values()) * self.ship_types[st].dwt
        return cap

    def total_demand_mt(self) -> float:
        return sum(self.regional_demand.values())

    def total_supply_mt(self) -> float:
        return sum(self.company_supply.values())

    # ── Regime transitions ────────────────────────────────────────────────────

    def _apply_regimes(self):
        cfg = self.config
        yr = self.current_year

        # IMO 2020 – fuel premium
        if cfg.enable_imo2020 and not self.imo2020_active and yr >= cfg.imo2020_year:
            self.imo2020_active = True
            # Non-scrubber vessels face higher opex
            for st in self.ship_types.values():
                if not st.scrubber_fitted:
                    st.daily_opex += cfg.imo2020_fuel_premium * st.fuel_consumption_tons_day / 1000

        # Geopolitical sanctions on a region
        if cfg.enable_sanctions and not self.sanctions_active and yr >= cfg.sanctions_year:
            self.sanctions_active = True
            reg = cfg.sanctions_region
            if reg in self.regional_demand:
                self.regional_demand[reg] *= (1 - cfg.sanctions_capacity_reduction)
            # Rosneft supply cut (if Baltic sanctioned)
            if reg == "Baltic" and "Rosneft" in self.company_supply:
                self.company_supply["Rosneft"] *= (1 - cfg.sanctions_capacity_reduction)

        # Demand shock (COVID-like)
        if cfg.enable_demand_shock and yr >= cfg.demand_shock_year:
            if not self.demand_shock_active:
                self.demand_shock_active = True
            t_since = yr - cfg.demand_shock_year
            if t_since <= cfg.demand_shock_duration_years:
                shock_factor = 1 + cfg.demand_shock_magnitude * np.sin(
                    np.pi * t_since / cfg.demand_shock_duration_years)
                for r in self.regional_demand:
                    self.regional_demand[r] = (
                        self.regions[r].base_demand_tons
                        * (1 + self.regions[r].demand_growth_rate * yr)
                        * shock_factor
                    )
            else:
                self.demand_shock_active = False

    # ── Oil market equilibrium (Engelen et al. §3) ────────────────────────────

    def _update_oil_market(self, dt_years: float):
        """
        Simple supply-demand balance for oil.
        Excess supply → inventory build → price pressure down
        Excess demand → inventory draw → price pressure up
        """
        total_supply = self.total_supply_mt()
        total_demand = self.total_demand_mt()
        balance = total_supply - total_demand   # MT/period

        # Add to / draw from storage
        for r in self.storage_inventory:
            reg = self.regions[r]
            # Proportional share of surplus
            share = self.regional_demand[r] / max(total_demand, 1)
            delta = balance * share * dt_years
            self.storage_inventory[r] = max(
                0, min(reg.storage_capacity, self.storage_inventory[r] + delta))

        # Demand growth
        for r, reg in self.regions.items():
            if r in self.regional_demand:
                self.regional_demand[r] *= (1 + reg.demand_growth_rate * dt_years)
                noise = self.rng.normal(0, reg.demand_volatility * dt_years)
                self.regional_demand[r] *= (1 + noise)

        # Supply noise
        for c, comp in self.companies.items():
            noise = self.rng.normal(0, comp.supply_volatility * dt_years)
            self.company_supply[c] = comp.base_supply_tons * (
                1 + comp.supply_growth_rate * self.current_year) * (1 + noise)

    # ── Freight market equilibrium ────────────────────────────────────────────

    def _update_freight_market(self, dt_years: float):
        """
        Vessel supply/demand balance drives spot rate.
        Rate signal → ordering / scrapping decisions.
        """
        # Effective cargo ton-miles demand (simplified: total trade * avg distance)
        AVG_DISTANCE_FACTOR = 1.0  # normalized; can be region-pair specific
        cargo_demand_mt = self.total_demand_mt() * AVG_DISTANCE_FACTOR

        # Effective supply: active fleet capacity * utilization factor
        effective_dwt = self.total_fleet_capacity_dwt()
        # Capacity utilization (demand / supply ratio)
        if effective_dwt > 0:
            load_factor = min(1.05, cargo_demand_mt / (effective_dwt / 1000))  # rough
        else:
            load_factor = 1.05

        # Spot rate adjusts based on load factor (non-linear, tanker market typical)
        # Below 85% utilization: rates fall; above 95%: spike
        utilization_normalized = (load_factor - 0.85) / 0.10
        rate_adjustment = np.tanh(utilization_normalized) * 0.4  # ±40%
        
        target_rate = self.config.base_spot_rate_usd_day * (1 + rate_adjustment)
        # Mean-reversion dynamics
        RATE_MEAN_REVERSION_SPEED = 2.0  # per year
        self.spot_rate += (target_rate - self.spot_rate) * RATE_MEAN_REVERSION_SPEED * dt_years
        # Add stochastic component
        self.spot_rate *= (1 + self.rng.normal(0, self.config.spot_rate_volatility * np.sqrt(dt_years)))
        self.spot_rate = max(5000, self.spot_rate)  # floor

        # Fuel price update
        self.fuel_price *= (1 + self.rng.normal(0, self.config.fuel_price_volatility * np.sqrt(dt_years)))
        self.fuel_price = max(200, self.fuel_price)

    # ── Fleet dynamics (Engelen et al. stock-flow) ────────────────────────────

    def _update_fleet_ordering(self, dt_years: float):
        """
        Ordering decision: owners compare spot rate to breakeven.
        Engelen et al.: ordering is a function of (spot rate - LRMC) * sensitivity
        """
        for st_name, st in self.ship_types.items():
            # Long-run marginal cost (breakeven rate)
            lrmc = (st.daily_opex + 
                    st.fuel_consumption_tons_day * self.fuel_price / 1000 +
                    st.build_cost_musd * 1e6 / (st.economic_life_years * 365))
            
            profitability_signal = (self.spot_rate - lrmc) / lrmc

            if profitability_signal > 0:
                # Positive signal → orders placed
                # Number of orders proportional to signal and existing fleet size
                current_fleet = self.total_active_vessels(st_name)
                max_orders = max(1, int(current_fleet * 0.1))  # cap at 10% per period
                n_orders = int(
                    self.config.ordering_sensitivity * profitability_signal 
                    * current_fleet * dt_years * self.rng.uniform(0.5, 1.5)
                )
                n_orders = min(n_orders, max_orders)
                
                for _ in range(n_orders):
                    delivery_year = self.current_year + st.build_time_years + self.rng.uniform(-0.3, 0.3)
                    # Assign to company with highest WTP (simplified: largest fleet owner)
                    if st_name in self.fleet_active and self.fleet_active[st_name]:
                        owner = max(self.fleet_active[st_name], 
                                    key=lambda o: self.fleet_active[st_name][o])
                    else:
                        owner = "Independent"
                    self.orderbook.append((delivery_year, st_name, owner))

    def _deliver_vessels(self):
        """Move vessels from orderbook to active fleet when delivery year reached."""
        remaining = []
        for (delivery_yr, st_name, owner) in self.orderbook:
            if delivery_yr <= self.current_year:
                if owner not in self.fleet_active[st_name]:
                    self.fleet_active[st_name][owner] = 0
                    self.fleet_storage[st_name][owner] = 0
                self.fleet_active[st_name][owner] += 1
            else:
                remaining.append((delivery_yr, st_name, owner))
        self.orderbook = remaining

    def _scrap_vessels(self, dt_years: float):
        """
        Scrapping decision based on rate and age proxy.
        Old vessels (proxy: high opex relative to rate) get scrapped first.
        """
        for st_name, st in self.ship_types.items():
            scrap_signal = self.config.scrapping_threshold_usd_day - self.spot_rate
            
            if scrap_signal > 0 and self.fleet_active[st_name]:
                # Scrap some vessels - independent owners first (price sensitive)
                n_to_scrap = max(0, int(scrap_signal / 5000 * dt_years))
                for owner in ["Independent", "Rosneft", "BP", "ExxonMobil", "Shell", "Saudi Aramco"]:
                    if n_to_scrap <= 0:
                        break
                    if owner in self.fleet_active[st_name] and self.fleet_active[st_name][owner] > 0:
                        actual_scrap = min(n_to_scrap, self.fleet_active[st_name][owner])
                        self.fleet_active[st_name][owner] -= actual_scrap
                        n_to_scrap -= actual_scrap

    def _storage_conversion(self):
        """
        Convert active tankers to FSO/storage if supply >> demand.
        Engelen et al. feedback: excess supply → storage play → reduces effective supply.
        """
        total_supply = self.total_supply_mt()
        total_demand = self.total_demand_mt()
        
        if total_demand > 0:
            ratio = total_supply / total_demand
        else:
            ratio = 1.0

        if ratio > self.config.storage_conversion_threshold:
            # Storage is attractive
            for st_name, st in self.ship_types.items():
                if not st.can_be_storage:
                    continue
                for owner, count in self.fleet_active[st_name].items():
                    if count > 1:  # keep at least 1 active
                        # Convert a fraction to storage
                        n_convert = max(0, int((ratio - 1) * count * 0.3))
                        n_convert = min(n_convert, count - 1)
                        if n_convert > 0:
                            self.fleet_active[st_name][owner] -= n_convert
                            self.fleet_storage[st_name][owner] = (
                                self.fleet_storage[st_name].get(owner, 0) + n_convert)
        else:
            # Return storage vessels to active if market tightens
            if ratio < 0.95:
                for st_name in self.ship_types:
                    for owner in list(self.fleet_storage[st_name].keys()):
                        n_return = self.fleet_storage[st_name][owner]
                        if n_return > 0:
                            self.fleet_active[st_name][owner] = (
                                self.fleet_active[st_name].get(owner, 0) + n_return)
                            self.fleet_storage[st_name][owner] = 0

    # ── Record keeping ────────────────────────────────────────────────────────

    def _record_state(self):
        record = {
            "year": round(self.current_year, 3),
            "step": self.time_step,
            "spot_rate_usd_day": round(self.spot_rate, 0),
            "fuel_price_usd_ton": round(self.fuel_price, 1),
            "total_active_vessels": self.total_active_vessels(),
            "total_storage_vessels": self.total_storage_vessels(),
            "orderbook_count": len(self.orderbook),
            "total_supply_mt": round(self.total_supply_mt(), 2),
            "total_demand_mt": round(self.total_demand_mt(), 2),
            "supply_demand_ratio": round(
                self.total_supply_mt() / max(self.total_demand_mt(), 0.01), 3),
            "fleet_capacity_dwt": round(self.total_fleet_capacity_dwt(), 0),
            "imo2020_active": int(self.imo2020_active),
            "sanctions_active": int(self.sanctions_active),
            "demand_shock_active": int(self.demand_shock_active),
        }
        # Per ship type fleet counts
        for st_name in self.ship_types:
            record[f"active_{st_name}"] = self.total_active_vessels(st_name)
            record[f"storage_{st_name}"] = sum(self.fleet_storage[st_name].values())

        # Per region demand
        for r, d in self.regional_demand.items():
            record[f"demand_{r}"] = round(d, 2)

        # Per company supply
        for c, s in self.company_supply.items():
            record[f"supply_{c}"] = round(s, 2)

        self.history.append(record)

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> pd.DataFrame:
        """Run the simulation and return history as DataFrame."""
        dt_years = self.config.time_step_days / 365.0
        total_steps = int(self.config.sim_years / dt_years)

        for step in range(total_steps):
            self.time_step = step
            self.current_year = step * dt_years

            # 1. Apply structural regime changes
            self._apply_regimes()

            # 2. Oil market equilibrium
            self._update_oil_market(dt_years)

            # 3. Storage conversion decision
            self._storage_conversion()

            # 4. Freight market equilibrium
            self._update_freight_market(dt_years)

            # 5. Fleet ordering
            self._update_fleet_ordering(dt_years)

            # 6. Deliver ordered vessels
            self._deliver_vessels()

            # 7. Scrapping
            self._scrap_vessels(dt_years)

            # 8. Record
            self._record_state()

        return pd.DataFrame(self.history)


# ──────────────────────────────────────────────────────────────────────────────
# CONVENIENCE RUNNER
# ──────────────────────────────────────────────────────────────────────────────

def run_scenario(config: SimConfig, **kwargs) -> pd.DataFrame:
    sim = MaritimeSimulation(config, **kwargs)
    return sim.run()
