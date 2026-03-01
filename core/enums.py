"""
Core enumerations for Maritime Fleet Simulation v2
"""

from enum import Enum, auto


class Granularity(Enum):
    """Simulation time granularity.

    Sub-period lengths used internally for each:
        WEEK     -> sub-period = 1 day    (7 sub-periods per step)
        MONTH    -> sub-period = 1 day    (28/29/30/31 sub-periods, or simplified 30)
        QUARTER  -> sub-period = 1 week   (13 sub-periods per step)
        YEAR     -> sub-period = 1 month  (12 sub-periods per step)
    """
    WEEK    = "week"
    MONTH   = "month"
    QUARTER = "quarter"
    YEAR    = "year"

    @property
    def days(self) -> float:
        return {
            Granularity.WEEK:    7.0,
            Granularity.MONTH:   30.0,
            Granularity.QUARTER: 91.25,
            Granularity.YEAR:    365.0,
        }[self]

    @property
    def sub_period_days(self) -> float:
        """Finest resolution used for intra-step dynamics."""
        return {
            Granularity.WEEK:    1.0,
            Granularity.MONTH:   1.0,
            Granularity.QUARTER: 7.0,
            Granularity.YEAR:    30.0,
        }[self]

    @property
    def sub_periods(self) -> int:
        return int(self.days / self.sub_period_days)

    @property
    def years(self) -> float:
        return self.days / 365.0


class ShipCountry(Enum):
    """Flag / owner country classification — affects sanction applicability."""
    UNKNOWN       = "unknown"
    USA           = "usa"
    RUSSIA        = "russia"
    CHINA         = "china"
    GREECE        = "greece"
    NORWAY        = "norway"
    JAPAN         = "japan"
    SOUTH_KOREA   = "south_korea"
    UAE           = "uae"
    INDIA         = "india"
    OTHER_WESTERN = "other_western"
    OTHER_EASTERN = "other_eastern"
    SHADOW        = "shadow"      # no clear flag, sanctions-grey zone


class VesselStatus(Enum):
    ACTIVE          = "active"         # trading
    LAID_UP         = "laid_up"        # idle, preservable
    STORAGE         = "storage"        # FSO / floating storage
    IN_TRANSIT      = "in_transit"     # en-route (tracked at edge level)
    LOADING         = "loading"        # at origin port
    UNLOADING       = "unloading"      # at destination port
    BUNKERING       = "bunkering"      # taking fuel
    UNDER_REPAIR    = "under_repair"
    SCRAPPED        = "scrapped"
    ON_ORDER        = "on_order"       # in orderbook, not yet delivered


class NodeType(Enum):
    PORT           = "port"            # loading / unloading terminal
    ANCHORAGE      = "anchorage"       # waiting area, no transfer
    CANAL          = "canal"           # capacity-constrained chokepoint
    STRAIT         = "strait"          # capacity-constrained chokepoint
    OPEN_SEA       = "open_sea"        # routing waypoint, no constraint


class ProductType(Enum):
    CRUDE_OIL   = "crude_oil"
    FUEL_OIL    = "fuel_oil"
    DISTILLATES = "distillates"
    LNG         = "lng"
    LPG         = "lpg"
    CHEMICALS   = "chemicals"
    DRY_BULK    = "dry_bulk"


class ConstraintType(Enum):
    """Types of scenario constraints (regime changes)."""
    SANCTION_SHIP_FLAG      = "sanction_ship_flag"      # ships of country X banned
    SANCTION_PORT           = "sanction_port"           # port/region banned
    SANCTION_COMPANY        = "sanction_company"        # company banned
    NODE_CLOSURE            = "node_closure"            # canal/strait closed (Hormuz!)
    NODE_CAPACITY_CHANGE    = "node_capacity_change"    # Suez width limit etc.
    DEMAND_SHOCK            = "demand_shock"            # global/regional demand multiplier
    SUPPLY_SHOCK            = "supply_shock"
    FUEL_REGULATION         = "fuel_regulation"         # IMO 2020 style
    SPOT_PRICE_SHOCK        = "spot_price_shock"
    NEWBUILD_LIMIT          = "newbuild_limit"          # yards saturated


class SeasonIndex(Enum):
    """Calendar months for seasonality coefficients."""
    JAN = 1; FEB = 2; MAR = 3; APR = 4
    MAY = 5; JUN = 6; JUL = 7; AUG = 8
    SEP = 9; OCT = 10; NOV = 11; DEC = 12
