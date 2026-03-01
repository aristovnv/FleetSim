"""
portal_schemas.py
=================
Config tables that drive the portal's visual layer.
These are separate from simulation data (schemas.py) — they control
how the portal looks, what it shows, and how parameters are exposed.

All tables here are editable in the browser under the Settings tab.

Tables:
  viz_companies     — company display: color, label, default_color fallback
  viz_ship_groups   — ship group display: map circle radius, color override
  viz_regions       — region map pin coordinates + display label
  viz_nodes         — chokepoint map coordinates + display label
  viz_routes        — trade route waypoints (replaces ROUTES hardcode)
  portal_params     — simulation run parameters with metadata (type, range, label)
  dashboard_charts  — which charts appear on dashboard, order, enabled flag
  portal_settings   — misc UI settings (map center, zoom, animation speed, etc.)
  table_registry    — labels, groups, and display order for config table nav
"""

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# viz_companies
# One row per company. color drives vessel dot and legend.
# owner_patterns: comma-separated substrings to match in ship_type name
# when the fleet table doesn't provide a direct owner link (fallback only).
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_companies() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="Saudi Aramco", color="#00d4ff", label="Saudi Aramco",
             owner_patterns="VLCC_KR,scrubber", sort_order=1),
        dict(name="Shell",        color="#ffd23f", label="Shell",
             owner_patterns="NO",               sort_order=2),
        dict(name="ExxonMobil",   color="#ff6b35", label="ExxonMobil",
             owner_patterns="US",               sort_order=3),
        dict(name="BP",           color="#4ade80", label="BP",
             owner_patterns="GR",               sort_order=4),
        dict(name="Rosneft",      color="#f472b6", label="Rosneft",
             owner_patterns="RU",               sort_order=5),
        dict(name="CNOOC",        color="#fb923c", label="CNOOC",
             owner_patterns="CN",               sort_order=6),
        dict(name="Independent",  color="#94a3b8", label="Independent",
             owner_patterns="",                 sort_order=7),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_ship_groups
# Controls the radius (pixels) of vessel dots on the map per group.
# Also optional color_override: if set, overrides company color for this group.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_ship_groups() -> pd.DataFrame:
    return pd.DataFrame([
        dict(group="VLCC",    map_radius=9,  color_override="", label="VLCC",    sort_order=1),
        dict(group="Suezmax", map_radius=7,  color_override="", label="Suezmax", sort_order=2),
        dict(group="Aframax", map_radius=5,  color_override="", label="Aframax", sort_order=3),
        dict(group="Panamax", map_radius=4,  color_override="", label="Panamax", sort_order=4),
        dict(group="MR",      map_radius=3,  color_override="", label="MR",      sort_order=5),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_regions
# Map pin coordinates for each simulation region.
# The 'region' name must match exactly the name used in the regions table.
# popup_fields: comma-separated step field names to show in hover popup.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_regions() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region="USGulf",         lat=28.5,  lon=-90.0, label="US Gulf",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="North Sea",      lat=57.5,  lon=  2.5, label="North Sea",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Baltic",         lat=59.5,  lon= 22.0, label="Baltic",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Mediterranean",  lat=37.5,  lon= 18.0, label="Mediterranean",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Persian Gulf",   lat=26.0,  lon= 54.0, label="Persian Gulf",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="West Africa",    lat= 3.5,  lon=  3.5, label="West Africa",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Southeast Asia", lat= 4.5,  lon=110.5, label="SE Asia",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Alaska",         lat=60.5,  lon=-149.5,label="Alaska",
             popup_fields="supply,demand,storage", enabled=True),
        dict(region="Caribbean",      lat=14.5,  lon=-75.0, label="Caribbean",
             popup_fields="supply,demand,storage", enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_nodes
# Map pin coordinates for network nodes (chokepoints, canals).
# The 'node' name must match exactly the node names in the nodes table.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_nodes() -> pd.DataFrame:
    return pd.DataFrame([
        dict(node="Strait of Hormuz",   lat=26.6,  lon= 56.4,
             label="Hormuz",  color_open="#ffd23f", color_closed="#ff3860", enabled=True),
        dict(node="Suez Canal",          lat=30.7,  lon= 32.3,
             label="Suez",    color_open="#ffd23f", color_closed="#ff3860", enabled=True),
        dict(node="Strait of Malacca",   lat= 3.0,  lon=101.5,
             label="Malacca", color_open="#ffd23f", color_closed="#ff3860", enabled=True),
        dict(node="Danish Straits",      lat=57.8,  lon= 10.5,
             label="Danish",  color_open="#ffd23f", color_closed="#ff3860", enabled=True),
        dict(node="Panama Canal",        lat= 9.1,  lon=-79.7,
             label="Panama",  color_open="#ffd23f", color_closed="#ff3860", enabled=True),
        dict(node="Cape of Good Hope",   lat=-34.4, lon= 18.5,
             label="Cape",    color_open="#ffd23f", color_closed="#ff3860", enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_routes
# Each row is one waypoint of a trade route.
# route_id:   string identifier grouping waypoints of the same route
# from_region / to_region: endpoints (must match viz_regions.region)
# via_nodes:  semicolon-separated node names (must match viz_nodes.node)
# seq:        waypoint sequence number (1-based)
# lat / lon:  waypoint coordinate
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_routes() -> pd.DataFrame:
    """
    Routes are stored as individual waypoint rows so they're fully editable
    in the config table UI. The portal reassembles them by (route_id, seq).
    """
    rows = []

    def add(route_id, fr, to, via, waypoints):
        for i, (la, lo) in enumerate(waypoints, 1):
            rows.append(dict(
                route_id=route_id, from_region=fr, to_region=to,
                via_nodes=via, seq=i, lat=la, lon=lo, enabled=True,
            ))

    add("PG_MED",   "Persian Gulf", "Mediterranean",
        "Strait of Hormuz;Suez Canal",
        [[25.5,57],[27,51],[27.5,43],[29.5,38],[30.7,32.3],[31.5,29],[33,25],[35,22],[36.5,18.5],[37.5,18]])

    add("PG_SEA",   "Persian Gulf", "Southeast Asia",
        "Strait of Hormuz;Strait of Malacca",
        [[25.5,57],[15,65],[8,77],[4,82],[3,95],[3,101.5],[4,107],[4.5,110.5]])

    add("PG_USGULF","Persian Gulf", "USGulf",
        "Strait of Hormuz;Cape of Good Hope",
        [[25.5,57],[15,52],[5,45],[-5,38],[-15,30],[-25,22],[-34.4,18.5],[-35,5],[-25,-15],[-10,-30],[5,-40],[15,-55],[22,-72],[28.5,-90]])

    add("BAL_MED",  "Baltic",       "Mediterranean",
        "Danish Straits",
        [[59.5,22],[58.5,15],[57.8,10.5],[56,8],[54,7],[52,4],[50,2],[46,3],[43,6],[40,12],[37.5,18]])

    add("NS_MED",   "North Sea",    "Mediterranean",
        "",
        [[57.5,2.5],[55,1],[52,3],[49,2],[46,3],[44,8],[40,12],[37.5,18]])

    add("WA_USGULF","West Africa",  "USGulf",
        "",
        [[3.5,3.5],[5,-5],[8,-20],[12,-35],[18,-55],[22,-72],[28.5,-90]])

    add("WA_MED",   "West Africa",  "Mediterranean",
        "",
        [[3.5,3.5],[10,0],[20,-5],[28,-2],[33,5],[36,10],[37.5,18]])

    add("UG_CAR",   "USGulf",       "Caribbean",
        "",
        [[28.5,-90],[25,-84],[22,-80],[18,-77],[14.5,-75]])

    add("AK_UG",    "Alaska",       "USGulf",
        "",
        [[60.5,-149.5],[55,-140],[50,-130],[45,-125],[38,-123],[30,-115],[28.5,-90]])

    add("SEA_NS",   "Southeast Asia","North Sea",
        "Strait of Malacca;Suez Canal",
        [[4.5,110.5],[3,101.5],[3,90],[8,77],[15,60],[25,45],[28,38],[30.7,32.3],[32,29],[35,25],[37,22],[39,16],[42,10],[46,5],[50,2],[54,5],[57.5,2.5]])

    add("MED_PG",   "Mediterranean","Persian Gulf",
        "Suez Canal;Strait of Hormuz",
        [[37.5,18],[35,22],[33,25],[31.5,29],[30.7,32.3],[29.5,38],[27.5,43],[27,51],[25.5,57],[26,54]])

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# portal_params
# One row per simulation parameter. Drives the Scenario tab form.
# Adding a new SimConfig param = add a row here + update models.py.
# No JS or portal.py edit needed.
#
# Columns:
#   key          — matches the key in run_config dict AND SimConfig field
#   label        — human-readable name shown in UI
#   param_type   — select | number | bool | text
#   default_val  — default value (stored as string, cast by type)
#   min_val      — for number type
#   max_val      — for number type
#   step         — for number type
#   options      — for select type: semicolon-separated option list
#   group        — groups params in the Scenario tab UI
#   description  — tooltip text
#   enabled      — show in UI
# ─────────────────────────────────────────────────────────────────────────────
def template_portal_params() -> pd.DataFrame:
    return pd.DataFrame([
        # ── Run control ──
        dict(key="granularity",    label="Granularity",      param_type="select",
             default_val="month", min_val=None, max_val=None, step=None,
             options="week;month;quarter;year", group="Run Control",
             description="Time step size for each simulation period", enabled=True),
        dict(key="n_periods",      label="Periods",          param_type="number",
             default_val="48",    min_val=5,    max_val=240,  step=1,
             options="", group="Run Control",
             description="Total number of simulation periods to run", enabled=True),
        dict(key="seed",           label="Random seed",      param_type="number",
             default_val="42",    min_val=0,    max_val=9999, step=1,
             options="", group="Run Control",
             description="Seed for reproducible stochastic draws", enabled=True),

        # ── Market ──
        dict(key="base_spot_rate", label="Base spot rate ($/day)", param_type="number",
             default_val="25000", min_val=5000, max_val=100000, step=500,
             options="", group="Market",
             description="Long-run equilibrium freight spot rate", enabled=True),
        dict(key="spot_volatility",label="Spot volatility",  param_type="number",
             default_val="0.25",  min_val=0.01, max_val=0.8,  step=0.01,
             options="", group="Market",
             description="Annual volatility of spot rate (fraction)", enabled=True),
        dict(key="wti_price",      label="WTI price ($/bbl)", param_type="number",
             default_val="75",    min_val=10,   max_val=250,  step=1,
             options="", group="Market",
             description="Base West Texas Intermediate crude price", enabled=True),
        dict(key="fuel_vlsfo",     label="VLSFO price ($/t)", param_type="number",
             default_val="600",   min_val=100,  max_val=1500, step=10,
             options="", group="Market",
             description="Very Low Sulfur Fuel Oil price (post-IMO2020)", enabled=True),
        dict(key="fuel_hfo",       label="HFO price ($/t)",   param_type="number",
             default_val="450",   min_val=100,  max_val=1000, step=10,
             options="", group="Market",
             description="Heavy Fuel Oil price (scrubber vessels)", enabled=True),

        # ── Fleet dynamics ──
        dict(key="ordering_sensitivity", label="Ordering sensitivity", param_type="number",
             default_val="0.30", min_val=0.01, max_val=1.0, step=0.01,
             options="", group="Fleet Dynamics",
             description="How aggressively owners order ships above LRMC (fraction)", enabled=True),
        dict(key="scrapping_threshold",  label="Scrapping threshold ($/day)", param_type="number",
             default_val="8000", min_val=1000, max_val=30000, step=500,
             options="", group="Fleet Dynamics",
             description="Spot rate below which vessels are scrapped first", enabled=True),
        dict(key="storage_sd_threshold", label="Storage S/D trigger", param_type="number",
             default_val="1.4",  min_val=1.0,  max_val=2.5,  step=0.05,
             options="", group="Fleet Dynamics",
             description="S/D ratio above which VLCCs convert to floating storage", enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# dashboard_charts
# One row per chart panel. The portal renders them in (row, col) order.
# Deactivate a chart by setting enabled=False — no code change needed.
#
# series_fields: semicolon-separated sim step field names to plot
# series_labels: matching labels
# series_colors: matching hex colors
# chart_type:    line | bar | area
# height:        px height of the chart canvas
# width_class:   wide (2/3) | half (1/3) | third (1/3 of row)
# y_label:       y-axis label
# hline:         optional horizontal reference line value (or blank)
# ─────────────────────────────────────────────────────────────────────────────
def template_dashboard_charts() -> pd.DataFrame:
    return pd.DataFrame([
        dict(chart_id="spot_rate",    title="Spot Rate",
             series_fields="spot_rate",
             series_labels="$/day",
             series_colors="#00e5ff",
             chart_type="area", height=220, width_class="wide",
             y_label="$/day", hline="", sort_order=1, enabled=True),
        dict(chart_id="fleet_comp",   title="Fleet: Active / Storage / Orderbook",
             series_fields="fleet_active;fleet_storage;orderbook",
             series_labels="Active;Storage FSO;Orderbook",
             series_colors="#4ade80;#a78bfa;#ffd23f",
             chart_type="line", height=220, width_class="half",
             y_label="vessels", hline="", sort_order=2, enabled=True),
        dict(chart_id="sd_ratio",     title="Supply / Demand Ratio",
             series_fields="sd_ratio",
             series_labels="S/D ratio",
             series_colors="#ffd23f",
             chart_type="area", height=160, width_class="third",
             y_label="ratio", hline="1.0", sort_order=3, enabled=True),
        dict(chart_id="wti",          title="WTI Price",
             series_fields="wti",
             series_labels="$/bbl",
             series_colors="#ff6b35",
             chart_type="area", height=160, width_class="third",
             y_label="$/bbl", hline="", sort_order=4, enabled=True),
        dict(chart_id="orderbook",    title="Orderbook",
             series_fields="orderbook",
             series_labels="ships",
             series_colors="#f472b6",
             chart_type="area", height=160, width_class="third",
             y_label="ships", hline="", sort_order=5, enabled=True),
        dict(chart_id="load_factor",  title="Load Factor",
             series_fields="load_factor",
             series_labels="fraction",
             series_colors="#39ff14",
             chart_type="area", height=160, width_class="half",
             y_label="fraction", hline="0.85", sort_order=6, enabled=True),
        dict(chart_id="fuel_prices",  title="Fuel Prices",
             series_fields="vlsfo;hfo",
             series_labels="VLSFO $/t;HFO $/t",
             series_colors="#00e5ff;#7a9abb",
             chart_type="line", height=160, width_class="half",
             y_label="$/t", hline="", sort_order=7, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# portal_settings
# Key-value table for UI-level settings.
# ─────────────────────────────────────────────────────────────────────────────
def template_portal_settings() -> pd.DataFrame:
    return pd.DataFrame([
        dict(key="map_center_lat",       value="20",     group="Map",
             description="Initial map center latitude"),
        dict(key="map_center_lon",       value="20",     group="Map",
             description="Initial map center longitude"),
        dict(key="map_zoom",             value="2",      group="Map",
             description="Initial map zoom level (2-6)"),
        dict(key="animation_tick_ms",    value="600",    group="Animation",
             description="Milliseconds between animation frames"),
        dict(key="autoplay_on_load",     value="true",   group="Animation",
             description="Auto-start animation when simulation result loads"),
        dict(key="vessel_opacity",       value="0.85",   group="Map",
             description="Vessel dot opacity (0-1)"),
        dict(key="route_opacity",        value="0.08",   group="Map",
             description="Trade route line opacity (0-1)"),
        dict(key="show_region_pins",     value="true",   group="Map",
             description="Show region info cards on map"),
        dict(key="show_node_pins",       value="true",   group="Map",
             description="Show chokepoint markers on map"),
        dict(key="show_route_lines",     value="true",   group="Map",
             description="Show trade route dashed lines"),
        dict(key="theme_bg",             value="#050c18", group="Theme",
             description="Portal background color"),
        dict(key="theme_accent",         value="#00e5ff", group="Theme",
             description="Primary accent color"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# table_registry
# Drives the Configure tab navigation: labels, group headers, display order.
# Add new tables here to make them appear in the nav without editing portal.py.
# ─────────────────────────────────────────────────────────────────────────────
def template_table_registry() -> pd.DataFrame:
    return pd.DataFrame([
        # Simulation data tables
        dict(table_name="products",        label="Products",        group="Market",    sort_order=1,  enabled=True),
        dict(table_name="regions",         label="Regions",         group="Market",    sort_order=2,  enabled=True),
        dict(table_name="region_demand",   label="Demand",          group="Market",    sort_order=3,  enabled=True),
        dict(table_name="region_supply",   label="Supply",          group="Market",    sort_order=4,  enabled=True),
        dict(table_name="region_storage",  label="Storage",         group="Market",    sort_order=5,  enabled=True),
        dict(table_name="seasonality",     label="Seasonality",     group="Market",    sort_order=6,  enabled=True),
        dict(table_name="nodes",           label="Nodes",           group="Network",   sort_order=7,  enabled=True),
        dict(table_name="edges",           label="Edges",           group="Network",   sort_order=8,  enabled=True),
        dict(table_name="port_times",      label="Port Times",      group="Network",   sort_order=9,  enabled=True),
        dict(table_name="companies",       label="Companies",       group="Actors",    sort_order=10, enabled=True),
        dict(table_name="ship_groups",     label="Ship Groups",     group="Fleet",     sort_order=11, enabled=True),
        dict(table_name="ship_types",      label="Ship Types",      group="Fleet",     sort_order=12, enabled=True),
        dict(table_name="fleet",           label="Initial Fleet",   group="Fleet",     sort_order=13, enabled=True),
        dict(table_name="orderbook",       label="Orderbook",       group="Fleet",     sort_order=14, enabled=True),
        dict(table_name="constraints",     label="Constraints",     group="Scenarios", sort_order=15, enabled=True),
        dict(table_name="scenario_presets", label="Scenario Presets", group="Scenarios", sort_order=16, enabled=True),
        # Portal visual config tables
        dict(table_name="viz_companies",   label="Company Colors",  group="Visual",    sort_order=16, enabled=True),
        dict(table_name="viz_ship_groups", label="Group Sizes",     group="Visual",    sort_order=17, enabled=True),
        dict(table_name="viz_regions",     label="Region Pins",     group="Visual",    sort_order=18, enabled=True),
        dict(table_name="viz_nodes",       label="Node Pins",       group="Visual",    sort_order=19, enabled=True),
        dict(table_name="viz_routes",      label="Trade Routes",    group="Visual",    sort_order=20, enabled=True),
        dict(table_name="portal_params",   label="Sim Parameters",  group="Visual",    sort_order=21, enabled=True),
        dict(table_name="dashboard_charts",label="Dashboard Charts",group="Visual",    sort_order=22, enabled=True),
        dict(table_name="portal_settings", label="UI Settings",     group="Visual",    sort_order=23, enabled=True),
        dict(table_name="table_registry",  label="Table Registry",  group="Visual",    sort_order=24, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# ALL_PORTAL_TEMPLATES — registered here, loaded by portal.py
# ─────────────────────────────────────────────────────────────────────────────
ALL_PORTAL_TEMPLATES = {
    "viz_companies":    template_viz_companies,
    "viz_ship_groups":  template_viz_ship_groups,
    "viz_regions":      template_viz_regions,
    "viz_nodes":        template_viz_nodes,
    "viz_routes":       template_viz_routes,
    "portal_params":    template_portal_params,
    "dashboard_charts": template_dashboard_charts,
    "portal_settings":  template_portal_settings,
    "table_registry":   template_table_registry,
}


# ─────────────────────────────────────────────────────────────────────────────
# scenario_presets  — replaces JS PRESETS hardcode
# Each row is one clickable preset button on the Scenario tab.
# cfg_overrides : semicolon-separated key=value pairs applied to run config
# constraint_*  : if set, adds one constraint row when the preset is clicked
# ─────────────────────────────────────────────────────────────────────────────
def template_scenario_presets() -> pd.DataFrame:
    rows = [
        dict(preset_id="baseline_48mo",   name="Baseline 48mo",
             cfg_overrides="granularity=month;n_periods=48;seed=42",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="", description="Default 4-year monthly run",
             sort_order=1, enabled=True),
        dict(preset_id="hormuz_crisis",   name="Hormuz Crisis",
             cfg_overrides="",
             constraint_type="node_closure", target_nodes="Strait of Hormuz",
             target_companies="", target_regions="",
             apply_on_day=30, end_on_day=90, multiplier=0, additive=0,
             description="Hormuz closed days 30–90, reroute via Cape",
             sort_order=2, enabled=True),
        dict(preset_id="ru_sanctions",    name="Russian Sanctions",
             cfg_overrides="",
             constraint_type="sanction_ship_flag", target_nodes="",
             target_companies="Rosneft", target_regions="Baltic",
             apply_on_day=0, end_on_day="", multiplier=0.35, additive=0,
             description="Rosneft fleet / Baltic supply cut to 35%",
             sort_order=3, enabled=True),
        dict(preset_id="covid_shock",     name="COVID Demand Shock",
             cfg_overrides="",
             constraint_type="demand_shock", target_nodes="",
             target_companies="", target_regions="",
             apply_on_day=60, end_on_day=600, multiplier=0.72, additive=0,
             description="Global demand drops 28% for ~18 months",
             sort_order=4, enabled=True),
        dict(preset_id="imo2020",         name="IMO 2020 Fuel Rules",
             cfg_overrides="",
             constraint_type="fuel_regulation", target_nodes="",
             target_companies="", target_regions="",
             apply_on_day=0, end_on_day="", multiplier=1, additive=150,
             description="VLSFO +150 $/t surcharge for non-scrubber ships",
             sort_order=5, enabled=True),
        dict(preset_id="quarterly_5yr",   name="Quarterly 5yr",
             cfg_overrides="granularity=quarter;n_periods=20",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="", description="Coarser 5-year view",
             sort_order=6, enabled=True),
        dict(preset_id="annual_10yr",     name="Annual 10yr",
             cfg_overrides="granularity=year;n_periods=10",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="", description="Strategic 10-year annual view",
             sort_order=7, enabled=True),
    ]
    return pd.DataFrame(rows)


ALL_PORTAL_TEMPLATES["scenario_presets"] = template_scenario_presets
