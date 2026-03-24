"""
portal_schemas.py  (v4 — complete)
====================================
Config tables that drive the portal's visual layer.
All 43 real maritime regions seeded from regional_centroids_spherical.csv.
All gatekeeper ports from regional_gatekeeper_ports.csv included as viz_nodes.
Routes expanded to cover major inter-regional trade flows.

Tables:
  viz_companies     — company display: color, label, owner_patterns
  viz_ship_groups   — ship group map dot radius
  viz_regions       — 43 region map pin coords + display label  ← COMPLETE
  viz_nodes         — chokepoints + gatekeeper ports            ← COMPLETE
  viz_routes        — trade route waypoints                     ← EXPANDED
  portal_params     — simulation run parameters with UI metadata
  dashboard_charts  — dashboard chart definitions
  portal_settings   — misc UI settings
  table_registry    — config nav labels/groups/order
  scenario_presets  — clickable preset scenario buttons
"""

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# viz_companies
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_companies() -> pd.DataFrame:
    return pd.DataFrame([
        dict(name="Saudi Aramco", color="#00d4ff", label="Saudi Aramco", owner_patterns="VLCC_KR,scrubber", sort_order=1),
        dict(name="Shell",        color="#ffd23f", label="Shell",        owner_patterns="NO",               sort_order=2),
        dict(name="ExxonMobil",   color="#ff6b35", label="ExxonMobil",   owner_patterns="US",               sort_order=3),
        dict(name="BP",           color="#4ade80", label="BP",           owner_patterns="GR",               sort_order=4),
        dict(name="Rosneft",      color="#f472b6", label="Rosneft",      owner_patterns="RU",               sort_order=5),
        dict(name="CNOOC",        color="#fb923c", label="CNOOC",        owner_patterns="CN",               sort_order=6),
        dict(name="Independent",  color="#94a3b8", label="Independent",  owner_patterns="",                 sort_order=7),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_ship_groups
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
# viz_regions  — all 43 regions from regional_centroids_spherical.csv
# Coordinates are the C_LON, C_LAT centroid values.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_regions() -> pd.DataFrame:
    return pd.DataFrame([
        dict(region="AG",     lat=26.179,  lon=53.223,   label="Arabian Gulf",          popup_fields="supply,demand,storage", enabled=True),
        dict(region="ALASKA", lat=59.183,  lon=-142.128, label="Alaska",                popup_fields="supply,demand,storage", enabled=True),
        dict(region="ARCTIC", lat=71.472,  lon=33.205,   label="Arctic",                popup_fields="supply,demand,storage", enabled=True),
        dict(region="ARG",    lat=-37.958, lon=-60.581,  label="Argentina",             popup_fields="supply,demand,storage", enabled=True),
        dict(region="BALT",   lat=58.343,  lon=17.079,   label="Baltic",                popup_fields="supply,demand,storage", enabled=True),
        dict(region="BRZL",   lat=-15.172, lon=-44.588,  label="Brazil",                popup_fields="supply,demand,storage", enabled=True),
        dict(region="BSEA",   lat=43.459,  lon=32.111,   label="Black Sea",             popup_fields="supply,demand,storage", enabled=True),
        dict(region="CBS",    lat=14.969,  lon=-68.412,  label="Caribbean/Barranquilla",popup_fields="supply,demand,storage", enabled=True),
        dict(region="CCHINA", lat=30.996,  lon=120.636,  label="C China",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="EAFR",   lat=-12.332, lon=45.650,   label="East Africa",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="EAUS",   lat=-25.305, lon=149.390,  label="East Australia",        popup_fields="supply,demand,storage", enabled=True),
        dict(region="ECCAM",  lat=12.376,  lon=-83.797,  label="E Caribbean/C America", popup_fields="supply,demand,storage", enabled=True),
        dict(region="ECCAN",  lat=48.762,  lon=-64.051,  label="E Canada",              popup_fields="supply,demand,storage", enabled=True),
        dict(region="ECIND",  lat=15.959,  lon=84.255,   label="E Coast India",         popup_fields="supply,demand,storage", enabled=True),
        dict(region="ECMEX",  lat=20.389,  lon=-92.545,  label="E Coast Mexico",        popup_fields="supply,demand,storage", enabled=True),
        dict(region="GLAKES", lat=44.019,  lon=-83.090,  label="Great Lakes",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="HAW",    lat=20.964,  lon=-157.200, label="Hawaii",                popup_fields="supply,demand,storage", enabled=True),
        dict(region="ICELAND",lat=66.097,  lon=-34.764,  label="Iceland",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="KOR/JPN",lat=35.194,  lon=133.599,  label="Korea/Japan",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="MED",    lat=38.592,  lon=17.507,   label="Mediterranean",         popup_fields="supply,demand,storage", enabled=True),
        dict(region="NAUS",   lat=-13.605, lon=131.259,  label="N Australia",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="NCHINA", lat=37.862,  lon=120.496,  label="N China",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="NSEA",   lat=60.467,  lon=5.279,    label="North Sea",             popup_fields="supply,demand,storage", enabled=True),
        dict(region="NZ",     lat=-41.055, lon=173.601,  label="New Zealand",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="PI",     lat=-9.370,  lon=165.358,  label="Pacific Islands",       popup_fields="supply,demand,storage", enabled=True),
        dict(region="RSEA",   lat=21.470,  lon=39.204,   label="Red Sea",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="RUPAC",  lat=49.128,  lon=140.649,  label="Russia Pacific",        popup_fields="supply,demand,storage", enabled=True),
        dict(region="SAFR",   lat=-31.163, lon=22.987,   label="South Africa",          popup_fields="supply,demand,storage", enabled=True),
        dict(region="SAUS",   lat=-37.041, lon=141.295,  label="S Australia",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="SCHINA", lat=23.161,  lon=115.753,  label="S China",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="SEASIA", lat=4.169,   lon=114.532,  label="SE Asia",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="SING",   lat=4.429,   lon=103.911,  label="Singapore",             popup_fields="supply,demand,storage", enabled=True),
        dict(region="UKC",    lat=51.259,  lon=-2.061,   label="UK/Continent",          popup_fields="supply,demand,storage", enabled=True),
        dict(region="USAC",   lat=38.076,  lon=-75.217,  label="US Atlantic",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="USG",    lat=29.364,  lon=-90.681,  label="US Gulf",               popup_fields="supply,demand,storage", enabled=True),
        dict(region="USWC",   lat=42.260,  lon=-121.995, label="US West Coast",         popup_fields="supply,demand,storage", enabled=True),
        dict(region="WAF",    lat=7.357,   lon=0.435,    label="West Africa",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="WAUS",   lat=-24.307, lon=115.685,  label="W Australia",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="WCCAM",  lat=10.760,  lon=-84.600,  label="W C America",           popup_fields="supply,demand,storage", enabled=True),
        dict(region="WCCAN",  lat=50.126,  lon=-124.796, label="W Canada",              popup_fields="supply,demand,storage", enabled=True),
        dict(region="WCIND",  lat=19.713,  lon=71.688,   label="W Coast India",         popup_fields="supply,demand,storage", enabled=True),
        dict(region="WCMEX",  lat=24.287,  lon=-108.060, label="W Coast Mexico",        popup_fields="supply,demand,storage", enabled=True),
        dict(region="WCSAM",  lat=-22.862, lon=-74.722,  label="W Coast S America",     popup_fields="supply,demand,storage", enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_nodes  — 7 primary gateways + secondary chokepoints + key gatekeeper ports
# is_gateway=True nodes trigger routing changes when closed.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_nodes() -> pd.DataFrame:
    return pd.DataFrame([
        # ── Primary gateways (diamond icons) ──────────────────────────────
        dict(node="Suez Canal",         lat=30.70,  lon=32.30,  label="Suez",        color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Strait of Hormuz",   lat=26.60,  lon=56.40,  label="Hormuz",      color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Strait of Malacca",  lat=3.00,   lon=101.50, label="Malacca",     color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Gibraltar Strait",   lat=35.98,  lon=-5.45,  label="Gibraltar",   color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Panama Canal",       lat=9.10,   lon=-79.70, label="Panama",      color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Singapore Strait",   lat=1.27,   lon=103.83, label="Singapore",   color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        dict(node="Bab el-Mandeb",      lat=12.60,  lon=43.40,  label="Bab el-M",    color_open="#ffd23f", color_closed="#ff3860", enabled=True,  is_gateway=True,  icon_shape="diamond"),
        # ── Secondary chokepoints (circle icons) ──────────────────────────
        dict(node="Danish Straits",     lat=57.80,  lon=10.50,  label="Danish",      color_open="#94a3b8", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Turkish Straits",    lat=41.10,  lon=29.00,  label="Bosphorus",   color_open="#94a3b8", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Cape of Good Hope",  lat=-34.40, lon=18.50,  label="Cape",        color_open="#94a3b8", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Lombok Strait",      lat=-8.70,  lon=115.70, label="Lombok",      color_open="#94a3b8", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Cape Horn",          lat=-55.90, lon=-67.20, label="C.Horn",      color_open="#94a3b8", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Northwest Passage",  lat=73.00,  lon=-90.00, label="NW Passage",  color_open="#94a3b8", color_closed="#ff3860", enabled=False, is_gateway=False, icon_shape="circle"),
        # ── Key gatekeeper ports (from regional_gatekeeper_ports.csv) ─────
        dict(node="Ras Tanura",         lat=26.62,  lon=50.07,  label="Ras Tanura",  color_open="#00d4ff", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Kharg Island",       lat=29.24,  lon=50.33,  label="Kharg",       color_open="#00d4ff", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Primorsk",           lat=60.37,  lon=28.62,  label="Primorsk",    color_open="#f472b6", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Novorossiysk",       lat=44.72,  lon=37.77,  label="Novorossiysk",color_open="#f472b6", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Rotterdam",          lat=51.90,  lon=4.45,   label="Rotterdam",   color_open="#4ade80", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Houston",            lat=29.73,  lon=-95.00, label="Houston",     color_open="#ff6b35", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
        dict(node="Ningbo-Zhoushan",    lat=29.87,  lon=121.55, label="Ningbo",      color_open="#fb923c", color_closed="#ff3860", enabled=True,  is_gateway=False, icon_shape="circle"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# viz_routes  — comprehensive trade routes covering all major flows
# Each row = one waypoint. Reassembled by (route_id, seq) in portal.py.
# ─────────────────────────────────────────────────────────────────────────────
def template_viz_routes() -> pd.DataFrame:
    rows = []

    def add(route_id, fr, to, via, waypoints):
        for i, (la, lo) in enumerate(waypoints, 1):
            rows.append(dict(
                route_id=route_id, from_region=fr, to_region=to,
                via_nodes=via, seq=i, lat=la, lon=lo, enabled=True,
            ))

    # ── Arabian Gulf (AG) → multiple destinations ─────────────────────────
    add("AG_MED",      "AG", "MED",
        "Strait of Hormuz;Bab el-Mandeb;Suez Canal",
        [[26.6,56.4],[24,58],[20,60],[14,43],[12.6,43.4],[15,40],[22,37],
         [27,34],[30.7,32.3],[32,30],[35,25],[37,22],[38.5,18.5],[38.5,18]])

    add("AG_MED_CAPE", "AG", "MED",
        "Strait of Hormuz;Cape of Good Hope",
        [[26.6,56.4],[15,63],[5,55],[-5,48],[-15,38],[-25,28],[-34.4,18.5],
         [-38,12],[-30,-10],[-20,-17],[-10,-18],[0,-15],[8,-15],[18,-18],
         [28,-14],[34,-10],[36,-7],[35.98,-5.45],[36,0],[37.5,18]])

    add("AG_SEASIA",   "AG", "SEASIA",
        "Strait of Hormuz;Strait of Malacca",
        [[26.6,56.4],[20,65],[12,72],[8,78],[5,85],[3,95],[3,101.5],[4,107],[4.2,114.5]])

    add("AG_SING",     "AG", "SING",
        "Strait of Hormuz;Singapore Strait",
        [[26.6,56.4],[18,64],[10,72],[5,80],[3,95],[3,101.5],[1.27,103.83]])

    add("AG_SCHINA",   "AG", "SCHINA",
        "Strait of Hormuz;Strait of Malacca",
        [[26.6,56.4],[18,64],[8,78],[3,101.5],[5,108],[15,115],[23.2,115.8]])

    add("AG_CCHINA",   "AG", "CCHINA",
        "Strait of Hormuz;Strait of Malacca",
        [[26.6,56.4],[18,64],[8,78],[3,101.5],[5,110],[18,115],[25,118],[31,121]])

    add("AG_NCHINA",   "AG", "NCHINA",
        "Strait of Hormuz;Strait of Malacca",
        [[26.6,56.4],[18,64],[8,78],[3,101.5],[5,110],[18,116],[28,120],[37.9,120.5]])

    add("AG_KOR_JPN",  "AG", "KOR/JPN",
        "Strait of Hormuz;Strait of Malacca",
        [[26.6,56.4],[18,64],[8,78],[3,101.5],[5,110],[20,120],[30,125],[35.2,133.6]])

    add("AG_USG",      "AG", "USG",
        "Strait of Hormuz;Cape of Good Hope",
        [[26.6,56.4],[15,63],[5,55],[-5,48],[-15,38],[-25,28],[-34.4,18.5],
         [-38,5],[-30,-20],[-20,-30],[-5,-38],[10,-48],[22,-68],[28,-85],[29.4,-90.7]])

    add("AG_USAC",     "AG", "USAC",
        "Strait of Hormuz;Suez Canal;Gibraltar Strait",
        [[26.6,56.4],[20,60],[12.6,43.4],[22,37],[30.7,32.3],[35,25],[37.5,18],
         [37,14],[36,10],[38,5],[36,-1],[35.98,-5.45],[35,-10],[30,-20],[20,-35],
         [15,-50],[20,-65],[32,-72],[38,-75.2]])

    add("AG_WCIND",    "AG", "WCIND",
        "Strait of Hormuz",
        [[26.6,56.4],[24,62],[22,66],[19.7,71.7]])

    add("AG_ECIND",    "AG", "ECIND",
        "Strait of Hormuz",
        [[26.6,56.4],[18,64],[12,72],[10,78],[16,84.3]])

    add("AG_WAF",      "AG", "WAF",
        "Strait of Hormuz",
        [[26.6,56.4],[15,55],[5,50],[-5,45],[-10,35],[0,20],[7.4,0.4]])

    add("AG_RSEA",     "AG", "RSEA",
        "Strait of Hormuz;Bab el-Mandeb",
        [[26.6,56.4],[20,57],[15,52],[12.6,43.4],[20,40],[21.5,39.2]])

    add("AG_EAFR",     "AG", "EAFR",
        "Strait of Hormuz",
        [[26.6,56.4],[18,57],[10,55],[0,48],[-12.3,45.7]])

    # ── Red Sea (RSEA) ────────────────────────────────────────────────────
    add("RSEA_MED",    "RSEA", "MED",
        "Bab el-Mandeb;Suez Canal",
        [[21.5,39.2],[15,40],[12.6,43.4],[18,38],[22,38],[27,34],[30.7,32.3],[35,25],[37.5,18]])

    add("RSEA_MED_CAPE","RSEA", "MED",
        "Cape of Good Hope",
        [[21.5,39.2],[12,45],[2,52],[-10,48],[-20,40],[-30,28],[-34.4,18.5],
         [-25,0],[-10,-15],[5,-5],[20,0],[35,-2],[37.5,18]])

    add("RSEA_NSEA",   "RSEA", "NSEA",
        "Bab el-Mandeb;Suez Canal;Gibraltar Strait",
        [[21.5,39.2],[12.6,43.4],[22,38],[30.7,32.3],[35.98,-5.45],[38,0],[40,5],
         [46,3],[50,2],[54,5],[60.5,5.3]])

    add("RSEA_UKC",    "RSEA", "UKC",
        "Bab el-Mandeb;Suez Canal;Gibraltar Strait",
        [[21.5,39.2],[12.6,43.4],[22,38],[30.7,32.3],[35.98,-5.45],[38,-2],[44,0],
         [47,2],[50,2],[51.3,-2.1]])

    # ── Baltic / Black Sea ────────────────────────────────────────────────
    add("BSEA_MED",    "BSEA", "MED",
        "Turkish Straits",
        [[43.5,32.1],[42,30],[41.1,29.0],[39,26],[37.5,18]])

    add("BALT_NSEA",   "BALT", "NSEA",
        "Danish Straits",
        [[58.3,17.1],[57.8,10.5],[57,8],[56,6],[58,4],[60.5,5.3]])

    add("BALT_UKC",    "BALT", "UKC",
        "Danish Straits",
        [[58.3,17.1],[57.8,10.5],[55,7],[52,4],[50,2],[51.3,-2.1]])

    add("BALT_MED",    "BALT", "MED",
        "Danish Straits;Gibraltar Strait",
        [[58.3,17.1],[57.8,10.5],[56,7],[54,7],[52,3],[50,-1],[48,-5],
         [44,-8],[40,-9],[36,-9],[35.98,-5.45],[36,0],[37.5,18]])

    # ── North Sea / UK Continent ──────────────────────────────────────────
    add("NSEA_MED",    "NSEA", "MED",
        "Gibraltar Strait",
        [[60.5,5.3],[56,1],[52,-2],[48,-6],[44,-9],[40,-9],[36,-9],
         [35.98,-5.45],[36,0],[37.5,18]])

    add("NSEA_USG",    "NSEA", "USG",
        "",
        [[60.5,5.3],[56,1],[52,-2],[48,-5],[44,-10],[38,-20],[30,-40],
         [25,-60],[28,-80],[29.4,-90.7]])

    add("NSEA_USAC",   "NSEA", "USAC",
        "",
        [[60.5,5.3],[56,0],[52,-3],[48,-8],[44,-18],[38,-30],[35,-40],[35,-60],[36,-68],[38,-75.2]])

    add("UKC_MED",     "UKC", "MED",
        "Gibraltar Strait",
        [[51.3,-2.1],[48,-5],[44,-8],[40,-9],[36,-9],[35.98,-5.45],[36,0],[37.5,18]])

    add("UKC_WAF",     "UKC", "WAF",
        "",
        [[51.3,-2.1],[48,-5],[44,-10],[38,-18],[28,-18],[18,-15],[10,-5],[7.4,0.4]])

    # ── West Africa ───────────────────────────────────────────────────────
    add("WAF_MED",     "WAF", "MED",
        "Gibraltar Strait",
        [[7.4,0.4],[4,-3],[5,-10],[10,-17],[18,-18],[28,-14],[34,-10],[36,-7],[35.98,-5.45],[36,0],[37.5,18]])

    add("WAF_UKC",     "WAF", "UKC",
        "",
        [[7.4,0.4],[12,-3],[18,-15],[28,-18],[38,-12],[44,-8],[48,-5],[51.3,-2.1]])

    add("WAF_USG",     "WAF", "USG",
        "",
        [[7.4,0.4],[5,-5],[8,-20],[12,-35],[18,-55],[22,-72],[28,-85],[29.4,-90.7]])

    add("WAF_USAC",    "WAF", "USAC",
        "",
        [[7.4,0.4],[5,-8],[8,-25],[15,-45],[22,-62],[30,-72],[36,-72],[38,-75.2]])

    add("WAF_BRZL",    "WAF", "BRZL",
        "",
        [[7.4,0.4],[3,-5],[0,-15],[-8,-28],[-15,-42]])

    add("WAF_SAFR",    "WAF", "SAFR",
        "Cape of Good Hope",
        [[7.4,0.4],[0,-5],[-10,-2],[-20,8],[-30,18],[-31.2,23.0]])

    # ── Americas ──────────────────────────────────────────────────────────
    add("USG_USAC",    "USG", "USAC",
        "",
        [[29.4,-90.7],[27,-83],[25,-80],[25,-78],[28,-75],[38,-75.2]])

    add("USG_MED",     "USG", "MED",
        "Gibraltar Strait",
        [[29.4,-90.7],[28,-80],[28,-75],[30,-60],[32,-45],[34,-30],[35,-20],
         [35.98,-5.45],[36,0],[37.5,18]])

    add("USG_NSEA",    "USG", "NSEA",
        "",
        [[29.4,-90.7],[28,-80],[30,-60],[34,-40],[38,-20],[44,-10],[48,-5],[52,-2],[57,2],[60.5,5.3]])

    add("USG_UKC",     "USG", "UKC",
        "",
        [[29.4,-90.7],[28,-80],[30,-60],[34,-40],[38,-22],[44,-12],[48,-5],[51.3,-2.1]])

    add("USG_WAF",     "USG", "WAF",
        "",
        [[29.4,-90.7],[26,-80],[22,-72],[18,-55],[12,-35],[8,-20],[5,-5],[7.4,0.4]])

    add("USAC_MED",    "USAC", "MED",
        "Gibraltar Strait",
        [[38,-75.2],[36,-68],[34,-45],[34,-28],[35,-15],[35.98,-5.45],[36,0],[37.5,18]])

    add("USAC_NSEA",   "USAC", "NSEA",
        "",
        [[38,-75.2],[40,-60],[44,-40],[48,-20],[52,-5],[56,0],[60.5,5.3]])

    add("USWC_SEASIA", "USWC", "SEASIA",
        "",
        [[42.3,-122.0],[35,-130],[25,-148],[15,-160],[10,-170],[5,-185],[3,-210],[3,-230],[4.2,-246]])

    add("USWC_KOR_JPN","USWC", "KOR/JPN",
        "",
        [[42.3,-122.0],[40,-140],[38,-155],[37,-170],[36,-185],[35,-200],[35.2,-226.4]])

    add("USWC_CCHINA", "USWC", "CCHINA",
        "",
        [[42.3,-122.0],[38,-140],[34,-158],[31,-175],[30,-190],[30,-208],[31,-239]])

    add("USWC_WCCAN",  "USWC", "WCCAN",
        "",
        [[42.3,-122.0],[44,-124],[48,-124],[50.1,-124.8]])

    add("WCCAN_USWC",  "WCCAN", "USWC",
        "",
        [[50.1,-124.8],[48,-124],[44,-124],[42.3,-122.0]])

    add("WCCAN_KOR_JPN","WCCAN", "KOR/JPN",
        "",
        [[50.1,-124.8],[48,-130],[45,-145],[42,-160],[40,-175],[38,-195],[35.2,-226.4]])

    add("WCSAM_USG",   "WCSAM", "USG",
        "Panama Canal",
        [[-22.9,-74.7],[-18,-74],[-10,-78],[0,-78],[5,-78],[9.1,-79.7],[10,-78],[12,-75],[22,-72],[29.4,-90.7]])

    add("WCSAM_USG_HORN","WCSAM", "USG",
        "Cape Horn",
        [[-22.9,-74.7],[-30,-72],[-40,-60],[-50,-55],[-55.9,-67.2],[-55,-65],
         [-50,-45],[-40,-35],[-25,-30],[-10,-25],[0,-15],[8,-15],[15,-45],[22,-60],[29.4,-90.7]])

    add("WCSAM_WCMEX", "WCSAM", "WCMEX",
        "",
        [[-22.9,-74.7],[-15,-76],[-5,-80],[5,-78],[12,-88],[24.3,-108.1]])

    add("WCMEX_USWC",  "WCMEX", "USWC",
        "",
        [[24.3,-108.1],[28,-110],[32,-115],[35,-118],[38,-120],[42.3,-122.0]])

    add("BRZL_NSEA",   "BRZL", "NSEA",
        "",
        [[-15.2,-44.6],[-8,-38],[0,-30],[8,-22],[18,-18],[28,-18],[38,-10],[46,-2],[52,-2],[57,2],[60.5,5.3]])

    add("BRZL_MED",    "BRZL", "MED",
        "",
        [[-15.2,-44.6],[-8,-35],[0,-25],[8,-18],[18,-12],[28,-5],[34,0],[37.5,18]])

    add("BRZL_WAF",    "BRZL", "WAF",
        "",
        [[-15.2,-44.6],[-5,-28],[0,-15],[5,-5],[7.4,0.4]])

    add("ARG_USAC",    "ARG", "USAC",
        "",
        [[-38,-60.6],[-28,-48],[-18,-38],[-5,-28],[8,-20],[20,-35],[30,-55],[35,-62],[38,-75.2]])

    add("ARG_MED",     "ARG", "MED",
        "",
        [[-38,-60.6],[-28,-46],[-15,-30],[0,-20],[12,-18],[25,-12],[34,-2],[37.5,18]])

    add("ARG_SAFR",    "ARG", "SAFR",
        "Cape Horn",
        [[-38,-60.6],[-45,-55],[-55.9,-67.2],[-55,-60],[-48,-40],[-38,-25],[-31.2,23.0]])

    # ── Southeast Asia / Oceania ──────────────────────────────────────────
    add("SEASIA_MED",  "SEASIA", "MED",
        "Strait of Malacca;Suez Canal",
        [[4.2,114.5],[3,101.5],[5,90],[8,78],[12,72],[15,60],[22,52],
         [12.6,43.4],[15,40],[22,38],[30.7,32.3],[35,25],[37.5,18]])

    add("SEASIA_NSEA", "SEASIA", "NSEA",
        "Strait of Malacca;Suez Canal;Gibraltar Strait",
        [[4.2,114.5],[3,101.5],[5,90],[8,78],[12.6,43.4],[22,38],[30.7,32.3],
         [35.98,-5.45],[38,0],[44,3],[50,2],[57,2],[60.5,5.3]])

    add("SEASIA_UKC",  "SEASIA", "UKC",
        "Strait of Malacca;Suez Canal;Gibraltar Strait",
        [[4.2,114.5],[3,101.5],[5,90],[8,78],[12.6,43.4],[30.7,32.3],
         [35.98,-5.45],[44,0],[48,-2],[51.3,-2.1]])

    add("SEASIA_EAUS", "SEASIA", "EAUS",
        "",
        [[4.2,114.5],[5,118],[2,120],[-8,130],[-15,140],[-25,149.4]])

    add("SEASIA_KOR_JPN","SEASIA", "KOR/JPN",
        "",
        [[4.2,114.5],[8,118],[15,122],[25,125],[35.2,133.6]])

    add("SING_MED",    "SING", "MED",
        "Singapore Strait;Suez Canal",
        [[4.4,103.9],[3,101.5],[5,90],[8,78],[12.6,43.4],[22,38],[30.7,32.3],[37.5,18]])

    add("SING_USG",    "SING", "USG",
        "Singapore Strait;Cape of Good Hope",
        [[4.4,103.9],[3,101.5],[2,95],[0,80],[-5,60],[-10,48],[-20,38],
         [-30,25],[-34.4,18.5],[-35,5],[-25,-15],[-10,-30],[8,-40],[22,-68],[29.4,-90.7]])

    add("SING_USAC",   "SING", "USAC",
        "Singapore Strait;Suez Canal;Gibraltar Strait",
        [[4.4,103.9],[3,101.5],[5,90],[8,78],[12.6,43.4],[30.7,32.3],
         [35.98,-5.45],[34,-20],[33,-35],[35,-55],[36,-65],[38,-75.2]])

    # ── Korea/Japan ───────────────────────────────────────────────────────
    add("KOR_JPN_USG",  "KOR/JPN", "USG",
        "Strait of Malacca;Suez Canal;Gibraltar Strait",
        [[35.2,133.6],[30,120],[20,115],[5,108],[3,101.5],[8,78],[12.6,43.4],
         [30.7,32.3],[35.98,-5.45],[33,-20],[30,-40],[27,-65],[29.4,-90.7]])

    add("KOR_JPN_USWC", "KOR/JPN", "USWC",
        "",
        [[35.2,133.6],[37,148],[40,163],[42,178],[42,195],[40,210],[40,225],[42.3,238]])

    # ── China regions ─────────────────────────────────────────────────────
    add("NCHINA_SCHINA","NCHINA", "SCHINA",
        "",
        [[37.9,120.5],[32,120],[25,118],[23.2,115.8]])

    add("NCHINA_SING",  "NCHINA", "SING",
        "",
        [[37.9,120.5],[30,120],[20,118],[12,110],[5,108],[4.4,103.9]])

    add("CCHINA_SCHINA","CCHINA", "SCHINA",
        "",
        [[31,121],[28,120],[25,118],[23.2,115.8]])

    # ── East Africa ───────────────────────────────────────────────────────
    add("EAFR_AG",      "EAFR", "AG",
        "",
        [[-12.3,45.7],[0,50],[10,55],[18,56],[26.6,56.4]])

    add("EAFR_MED",     "EAFR", "MED",
        "Suez Canal",
        [[-12.3,45.7],[0,48],[8,52],[12.6,43.4],[22,38],[30.7,32.3],[37.5,18]])

    add("EAFR_SAFR",    "EAFR", "SAFR",
        "",
        [[-12.3,45.7],[-18,40],[-25,32],[-31.2,23.0]])

    # ── South Africa ──────────────────────────────────────────────────────
    add("SAFR_MED",     "SAFR", "MED",
        "Cape of Good Hope;Gibraltar Strait",
        [[-31.2,23.0],[-34.4,18.5],[-30,8],[-20,3],[-10,0],[0,-8],[8,-15],
         [18,-18],[28,-14],[34,-10],[36,-7],[35.98,-5.45],[36,0],[37.5,18]])

    add("SAFR_NSEA",    "SAFR", "NSEA",
        "Cape of Good Hope;Gibraltar Strait",
        [[-31.2,23.0],[-34.4,18.5],[-25,5],[-12,2],[-2,-5],[8,-15],
         [18,-18],[28,-14],[34,-10],[36,-7],[35.98,-5.45],[40,0],[46,2],[50,2],[57,2],[60.5,5.3]])

    add("SAFR_UKC",     "SAFR", "UKC",
        "Cape of Good Hope",
        [[-31.2,23.0],[-34.4,18.5],[-25,5],[-10,0],[0,-8],[8,-15],
         [18,-18],[28,-14],[34,-10],[36,-7],[35.98,-5.45],[44,0],[48,-2],[51.3,-2.1]])

    add("SAFR_USG",     "SAFR", "USG",
        "Cape of Good Hope",
        [[-31.2,23.0],[-34.4,18.5],[-30,-5],[-20,-20],[-5,-35],[8,-42],
         [18,-55],[25,-68],[29.4,-90.7]])

    # ── Australia ─────────────────────────────────────────────────────────
    add("EAUS_SEASIA",  "EAUS", "SEASIA",
        "",
        [[-25.3,149.4],[-15,144],[-8,138],[-2,130],[4.2,114.5]])

    add("EAUS_KOR_JPN", "EAUS", "KOR/JPN",
        "",
        [[-25.3,149.4],[-18,150],[-8,150],[5,148],[15,138],[25,132],[35.2,133.6]])

    add("EAUS_CCHINA",  "EAUS", "CCHINA",
        "",
        [[-25.3,149.4],[-15,150],[-5,148],[5,145],[15,138],[22,128],[28,122],[31,121]])

    add("WAUS_SEASIA",  "WAUS", "SEASIA",
        "",
        [[-24.3,115.7],[-18,112],[-10,110],[-2,108],[4.2,114.5]])

    add("WAUS_SING",    "WAUS", "SING",
        "",
        [[-24.3,115.7],[-18,112],[-8,108],[2,104],[4.4,103.9]])

    add("NAUS_SEASIA",  "NAUS", "SEASIA",
        "",
        [[-13.6,131.3],[-8,130],[-2,122],[4.2,114.5]])

    add("SAUS_MED",     "SAUS", "MED",
        "Cape of Good Hope;Suez Canal",
        [[-37,141.3],[-38,130],[-38,110],[-35,90],[-32,70],[-20,55],
         [-10,48],[-34.4,18.5],[-25,5],[0,0],[8,78],[12.6,43.4],
         [22,38],[30.7,32.3],[37.5,18]])

    add("SAUS_USAC",    "SAUS", "USAC",
        "Cape Horn;Panama Canal",
        [[-37,141.3],[-45,155],[-55,170],[-57,185],[-57,210],[-57,240],
         [-56,260],[-55.9,292.8],[-52,305],[-40,320],[-25,332],[-10,330],
         [5,325],[9.1,320],[15,312],[22,305],[30,300],[38,284.8]])

    add("SAUS_SEASIA",  "SAUS", "SEASIA",
        "",
        [[-37,141.3],[-30,138],[-20,130],[-12,118],[-5,112],[4.2,114.5]])

    add("SAUS_KOR_JPN", "SAUS", "KOR/JPN",
        "",
        [[-37,141.3],[-28,145],[-15,148],[-2,145],[10,138],[20,134],[35.2,133.6]])

    add("SAUS_CCHINA",  "SAUS", "CCHINA",
        "",
        [[-37,141.3],[-25,143],[-12,142],[0,140],[12,135],[22,128],[31,121]])

    # ── Pacific regions ───────────────────────────────────────────────────
    add("RUPAC_KOR_JPN","RUPAC", "KOR/JPN",
        "",
        [[49.1,140.6],[45,138],[40,135],[35.2,133.6]])

    add("RUPAC_CCHINA", "RUPAC", "CCHINA",
        "",
        [[49.1,140.6],[45,138],[38,128],[32,122],[31,121]])

    add("HAW_USWC",     "HAW", "USWC",
        "",
        [[21.0,-157.2],[25,-148],[30,-140],[35,-130],[38,-124],[42.3,-122.0]])

    add("HAW_KOR_JPN",  "HAW", "KOR/JPN",
        "",
        [[21.0,-157.2],[25,-165],[28,-175],[30,-185],[32,-200],[35.2,-226.4]])

    add("PI_KOR_JPN",   "PI", "KOR/JPN",
        "",
        [[-9.4,165.4],[0,170],[10,162],[20,148],[28,138],[35.2,133.6]])

    add("PI_EAUS",      "PI", "EAUS",
        "",
        [[-9.4,165.4],[-15,162],[-20,158],[-25.3,149.4]])

    add("NZ_EAUS",      "NZ", "EAUS",
        "",
        [[-41,173.6],[-35,165],[-30,155],[-25.3,149.4]])

    add("NZ_SEASIA",    "NZ", "SEASIA",
        "",
        [[-41,173.6],[-30,160],[-15,148],[-2,130],[4.2,114.5]])

    # ── Indian subcontinent ───────────────────────────────────────────────
    add("WCIND_AG",     "WCIND", "AG",
        "",
        [[19.7,71.7],[22,64],[24,60],[26.6,56.4]])

    add("WCIND_MED",    "WCIND", "MED",
        "Suez Canal",
        [[19.7,71.7],[15,65],[10,60],[12.6,43.4],[22,38],[30.7,32.3],[37.5,18]])

    add("ECIND_SEASIA", "ECIND", "SEASIA",
        "",
        [[16,84.3],[12,88],[8,90],[5,100],[4.2,114.5]])

    add("ECIND_SING",   "ECIND", "SING",
        "",
        [[16,84.3],[12,88],[8,90],[5,98],[4.4,103.9]])

    # ── Iceland / Arctic ─────────────────────────────────────────────────
    add("ICELAND_UKC",  "ICELAND", "UKC",
        "",
        [[66.1,-34.8],[62,-28],[58,-20],[54,-10],[51.3,-2.1]])

    add("ICELAND_NSEA", "ICELAND", "NSEA",
        "",
        [[66.1,-34.8],[63,-22],[60,-10],[59,0],[60.5,5.3]])

    add("ARCTIC_BALT",  "ARCTIC", "BALT",
        "",
        [[71.5,33.2],[68,28],[65,22],[62,18],[60,16],[58.3,17.1]])

    add("ARCTIC_NSEA",  "ARCTIC", "NSEA",
        "",
        [[71.5,33.2],[70,15],[66,8],[62,4],[60.5,5.3]])

    # ── Caribbean / C America ────────────────────────────────────────────
    add("CBS_USG",      "CBS", "USG",
        "",
        [[15,-68.4],[18,-77],[22,-80],[25,-84],[28,-87],[29.4,-90.7]])

    add("CBS_USAC",     "CBS", "USAC",
        "",
        [[15,-68.4],[18,-72],[22,-72],[28,-74],[32,-70],[36,-68],[38,-75.2]])

    add("ECCAM_USG",    "ECCAM", "USG",
        "",
        [[12.4,-83.8],[15,-85],[18,-87],[22,-88],[26,-88],[29.4,-90.7]])

    add("ECCAM_USAC",   "ECCAM", "USAC",
        "",
        [[12.4,-83.8],[14,-82],[18,-78],[22,-74],[26,-70],[32,-68],[38,-75.2]])

    add("WCCAM_WCMEX",  "WCCAM", "WCMEX",
        "",
        [[10.8,-84.6],[14,-88],[18,-92],[22,-98],[24.3,-108.1]])

    add("WCCAM_USG",    "WCCAM", "USG",
        "Panama Canal",
        [[10.8,-84.6],[9.1,-79.7],[10,-78],[15,-75],[22,-72],[29.4,-90.7]])

    add("ECMEX_USG",    "ECMEX", "USG",
        "",
        [[20.4,-92.5],[22,-90],[25,-89],[27,-89],[29.4,-90.7]])

    add("WCMEX_USWC",   "WCMEX", "USWC",
        "",
        [[24.3,-108.1],[28,-112],[32,-116],[36,-120],[42.3,-122.0]])

    # ── Canada ────────────────────────────────────────────────────────────
    add("ECCAN_USAC",   "ECCAN", "USAC",
        "",
        [[48.8,-64.1],[45,-64],[42,-68],[40,-70],[38,-75.2]])

    add("ECCAN_UKC",    "ECCAN", "UKC",
        "",
        [[48.8,-64.1],[48,-55],[48,-40],[50,-25],[52,-10],[51.3,-2.1]])

    add("ECCAN_NSEA",   "ECCAN", "NSEA",
        "",
        [[48.8,-64.1],[50,-45],[52,-30],[54,-18],[56,-8],[58,-2],[60.5,5.3]])

    # ── Great Lakes (inland — limited access) ─────────────────────────────
    add("GLAKES_USG",   "GLAKES", "USG",
        "",
        [[44,-83.1],[42,-82],[40,-80],[38,-78],[34,-78],[29.4,-90.7]])

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# portal_params  — simulation run parameters
# ─────────────────────────────────────────────────────────────────────────────
def template_portal_params() -> pd.DataFrame:
    return pd.DataFrame([
        # ── Run Control ──
        dict(key="granularity",    label="Granularity",              param_type="select",
             default_val="month",  min_val=None, max_val=None, step=None,
             options="week;month;quarter;year", group="Run Control",
             description="Time step size for each simulation period", enabled=True),
        dict(key="n_periods",      label="Periods",                  param_type="number",
             default_val="48",     min_val=5,    max_val=240,  step=1,
             options="", group="Run Control",
             description="Total number of simulation periods to run", enabled=True),
        dict(key="seed",           label="Random seed",              param_type="number",
             default_val="42",     min_val=0,    max_val=9999, step=1,
             options="", group="Run Control",
             description="Seed for reproducible stochastic draws", enabled=True),
        # ── Market ──
        dict(key="base_spot_rate", label="Base spot rate ($/day)",   param_type="number",
             default_val="25000",  min_val=5000, max_val=100000, step=500,
             options="", group="Market",
             description="Long-run equilibrium freight spot rate", enabled=True),
        dict(key="spot_volatility",label="Spot volatility",          param_type="number",
             default_val="0.25",   min_val=0.01, max_val=0.8,   step=0.01,
             options="", group="Market",
             description="Annual volatility of spot rate (fraction)", enabled=True),
        dict(key="wti_price",      label="WTI price ($/bbl)",        param_type="number",
             default_val="75",     min_val=10,   max_val=250,   step=1,
             options="", group="Market",
             description="Base West Texas Intermediate crude price", enabled=True),
        dict(key="fuel_vlsfo",     label="VLSFO price ($/t)",        param_type="number",
             default_val="600",    min_val=100,  max_val=1500,  step=10,
             options="", group="Market",
             description="Very Low Sulfur Fuel Oil price (post-IMO2020)", enabled=True),
        dict(key="fuel_hfo",       label="HFO price ($/t)",          param_type="number",
             default_val="450",    min_val=100,  max_val=1000,  step=10,
             options="", group="Market",
             description="Heavy Fuel Oil price (scrubber vessels)", enabled=True),
        # ── Fleet Dynamics ──
        dict(key="ordering_sensitivity",  label="Ordering sensitivity",      param_type="number",
             default_val="0.30",   min_val=0.01, max_val=1.0,  step=0.01,
             options="", group="Fleet Dynamics",
             description="How aggressively owners order ships above LRMC", enabled=True),
        dict(key="scrapping_threshold",   label="Scrapping threshold ($/day)", param_type="number",
             default_val="8000",   min_val=1000, max_val=30000, step=500,
             options="", group="Fleet Dynamics",
             description="Spot rate below which vessels are scrapped first", enabled=True),
        dict(key="storage_sd_threshold",  label="Storage S/D trigger",       param_type="number",
             default_val="1.4",    min_val=1.0,  max_val=2.5,  step=0.05,
             options="", group="Fleet Dynamics",
             description="S/D ratio above which VLCCs convert to floating storage", enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# dashboard_charts
# ─────────────────────────────────────────────────────────────────────────────
def template_dashboard_charts() -> pd.DataFrame:
    return pd.DataFrame([
        dict(chart_id="spot_rate",   title="Spot Rate",
             series_fields="spot_rate", series_labels="$/day", series_colors="#00e5ff",
             chart_type="area", height=220, width_class="wide",
             y_label="$/day", hline="", sort_order=1, enabled=True),
        dict(chart_id="fleet_comp",  title="Fleet: Active / Storage / Orderbook",
             series_fields="fleet_active;fleet_storage;orderbook",
             series_labels="Active;Storage FSO;Orderbook",
             series_colors="#4ade80;#a78bfa;#ffd23f",
             chart_type="line", height=220, width_class="half",
             y_label="vessels", hline="", sort_order=2, enabled=True),
        dict(chart_id="sd_ratio",    title="Supply / Demand Ratio",
             series_fields="sd_ratio", series_labels="S/D ratio", series_colors="#ffd23f",
             chart_type="area", height=160, width_class="third",
             y_label="ratio", hline="1.0", sort_order=3, enabled=True),
        dict(chart_id="wti",         title="WTI Price",
             series_fields="wti", series_labels="$/bbl", series_colors="#ff6b35",
             chart_type="area", height=160, width_class="third",
             y_label="$/bbl", hline="", sort_order=4, enabled=True),
        dict(chart_id="orderbook",   title="Orderbook",
             series_fields="orderbook", series_labels="ships", series_colors="#f472b6",
             chart_type="area", height=160, width_class="third",
             y_label="ships", hline="", sort_order=5, enabled=True),
        dict(chart_id="load_factor", title="Load Factor",
             series_fields="load_factor", series_labels="fraction", series_colors="#39ff14",
             chart_type="area", height=160, width_class="half",
             y_label="fraction", hline="0.85", sort_order=6, enabled=True),
        dict(chart_id="fuel_prices", title="Fuel Prices",
             series_fields="vlsfo;hfo",
             series_labels="VLSFO $/t;HFO $/t", series_colors="#00e5ff;#7a9abb",
             chart_type="line", height=160, width_class="half",
             y_label="$/t", hline="", sort_order=7, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# portal_settings  — UI key-value configuration
# ─────────────────────────────────────────────────────────────────────────────
def template_portal_settings() -> pd.DataFrame:
    return pd.DataFrame([
        dict(key="map_center_lat",    value="20",     group="Map",       description="Initial map center latitude"),
        dict(key="map_center_lon",    value="20",     group="Map",       description="Initial map center longitude"),
        dict(key="map_zoom",          value="2",      group="Map",       description="Initial map zoom level (2-6)"),
        dict(key="animation_tick_ms", value="600",    group="Animation", description="Milliseconds between animation frames"),
        dict(key="autoplay_on_load",  value="false",  group="Animation", description="Auto-start animation when result loads (true/false)"),
        dict(key="vessel_opacity",    value="0.85",   group="Map",       description="Vessel dot opacity (0-1)"),
        dict(key="route_opacity",     value="0.08",   group="Map",       description="Trade route line opacity (0-1)"),
        dict(key="show_region_pins",  value="true",   group="Map",       description="Show region info cards on map"),
        dict(key="show_node_pins",    value="true",   group="Map",       description="Show chokepoint markers on map"),
        dict(key="show_route_lines",  value="true",   group="Map",       description="Show trade route dashed lines"),
        dict(key="theme_bg",          value="#050c18", group="Theme",    description="Portal background color"),
        dict(key="theme_accent",      value="#00e5ff", group="Theme",    description="Primary accent color"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# table_registry  — drives config tab navigation
# ─────────────────────────────────────────────────────────────────────────────
def template_table_registry() -> pd.DataFrame:
    return pd.DataFrame([
        # Simulation data
        dict(table_name="products",              label="Products",            group="Market",    sort_order=1,  enabled=True),
        dict(table_name="regions",               label="Regions (43)",        group="Market",    sort_order=2,  enabled=True),
        dict(table_name="region_demand",         label="Demand",              group="Market",    sort_order=3,  enabled=True),
        dict(table_name="region_supply",         label="Supply",              group="Market",    sort_order=4,  enabled=True),
        dict(table_name="region_storage",        label="Storage",             group="Market",    sort_order=5,  enabled=True),
        dict(table_name="seasonality",           label="Seasonality",         group="Market",    sort_order=6,  enabled=True),
        dict(table_name="nodes",                 label="Nodes",               group="Network",   sort_order=7,  enabled=True),
        dict(table_name="edges",                 label="Edges",               group="Network",   sort_order=8,  enabled=True),
        dict(table_name="port_times",            label="Port Times",          group="Network",   sort_order=9,  enabled=True),
        dict(table_name="companies",             label="Companies",           group="Actors",    sort_order=10, enabled=True),
        dict(table_name="ship_groups",           label="Ship Groups",         group="Fleet",     sort_order=11, enabled=True),
        dict(table_name="ship_types",            label="Ship Types",          group="Fleet",     sort_order=12, enabled=True),
        dict(table_name="fleet",                 label="Initial Fleet",       group="Fleet",     sort_order=13, enabled=True),
        dict(table_name="vessel_groups",         label="Vessel Groups",       group="Fleet",     sort_order=14, enabled=True),
        dict(table_name="vessel_group_members",  label="Group Members",       group="Fleet",     sort_order=15, enabled=True),
        dict(table_name="orderbook",             label="Orderbook",           group="Fleet",     sort_order=16, enabled=True),
        dict(table_name="constraints",           label="Constraints",         group="Scenarios", sort_order=17, enabled=True),
        dict(table_name="scenario_presets",      label="Scenario Presets",    group="Scenarios", sort_order=18, enabled=True),
        # Groups system (constraint engine hierarchy)
        dict(table_name="groups",               label="Groups",              group="Groups",    sort_order=28, enabled=True),
        dict(table_name="group_hierarchy",      label="Group Hierarchy",     group="Groups",    sort_order=29, enabled=True),
        dict(table_name="object_group_map",     label="Object → Groups",     group="Groups",    sort_order=30, enabled=True),
        # Conflict resolution rules
        dict(table_name="conflict_rules",       label="Conflict Rules",      group="Rules",     sort_order=31, enabled=True),
        dict(table_name="object_fields",         label="Field Specs",         group="Meta",      sort_order=40, enabled=True),
        dict(table_name="object_lists",          label="Object Registry",     group="Meta",      sort_order=41, enabled=True),
        # Visual config
        dict(table_name="viz_companies",         label="Company Colors",      group="Visual",    sort_order=19, enabled=True),
        dict(table_name="viz_ship_groups",       label="Group Sizes",         group="Visual",    sort_order=20, enabled=True),
        dict(table_name="viz_regions",           label="Region Pins (43)",    group="Visual",    sort_order=21, enabled=True),
        dict(table_name="viz_nodes",             label="Node Pins",           group="Visual",    sort_order=22, enabled=True),
        dict(table_name="viz_routes",            label="Trade Routes",        group="Visual",    sort_order=23, enabled=True),
        dict(table_name="portal_params",         label="Sim Parameters",      group="Visual",    sort_order=24, enabled=True),
        dict(table_name="dashboard_charts",      label="Dashboard Charts",    group="Visual",    sort_order=25, enabled=True),
        dict(table_name="portal_settings",       label="UI Settings",         group="Visual",    sort_order=26, enabled=True),
        dict(table_name="table_registry",        label="Table Registry",      group="Visual",    sort_order=27, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# scenario_presets  — clickable preset buttons on Scenario tab
# ─────────────────────────────────────────────────────────────────────────────
def template_scenario_presets() -> pd.DataFrame:
    return pd.DataFrame([
        dict(preset_id="baseline_48mo",   name="Baseline 48mo",
             cfg_overrides="granularity=month;n_periods=48;seed=42",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="",
             description="Default 4-year monthly run", sort_order=1, enabled=True),

        dict(preset_id="hormuz_crisis",   name="Hormuz Crisis",
             cfg_overrides="",
             constraint_type="node_closure", target_nodes="Strait of Hormuz",
             target_companies="", target_regions="",
             apply_on_day=30, end_on_day=90, multiplier=0, additive=0,
             description="Hormuz closed days 30–90, full reroute via Cape", sort_order=2, enabled=True),

        dict(preset_id="suez_closure",    name="Suez Blockage",
             cfg_overrides="",
             constraint_type="node_closure", target_nodes="Suez Canal",
             target_companies="", target_regions="",
             apply_on_day=15, end_on_day=45, multiplier=0, additive=0,
             description="Suez Canal blocked 30 days (Ever Given style)", sort_order=3, enabled=True),

        dict(preset_id="bab_houthi",      name="Bab el-Mandeb Threat",
             cfg_overrides="",
             constraint_type="node_closure", target_nodes="Bab el-Mandeb",
             target_companies="", target_regions="",
             apply_on_day=0, end_on_day=180, multiplier=0.3, additive=0,
             description="70% traffic diversion via Cape (Houthi-style threat)", sort_order=4, enabled=True),

        dict(preset_id="ru_sanctions",    name="Russian Sanctions",
             cfg_overrides="",
             constraint_type="sanction_ship_flag", target_nodes="",
             target_companies="Rosneft", target_regions="BALT,BSEA",
             apply_on_day=0, end_on_day="", multiplier=0.35, additive=0,
             description="Rosneft fleet / Baltic supply cut to 35%", sort_order=5, enabled=True),

        dict(preset_id="ru_full_embargo", name="Full Russia Embargo",
             cfg_overrides="",
             constraint_type="sanction_ship_flag", target_nodes="",
             target_companies="Rosneft", target_regions="",
             apply_on_day=0, end_on_day="", multiplier=0.0, additive=0,
             description="Complete Russian crude export embargo (flag:russia banned)", sort_order=6, enabled=True),

        dict(preset_id="covid_shock",     name="COVID Demand Shock",
             cfg_overrides="",
             constraint_type="demand_shock", target_nodes="",
             target_companies="", target_regions="",
             apply_on_day=60, end_on_day=600, multiplier=0.72, additive=0,
             description="Global demand drops 28% for ~18 months", sort_order=7, enabled=True),

        dict(preset_id="china_boom",      name="China Demand Boom",
             cfg_overrides="",
             constraint_type="demand_shock", target_nodes="",
             target_companies="CNOOC", target_regions="CCHINA,SCHINA,NCHINA",
             apply_on_day=0, end_on_day="", multiplier=1.25, additive=0,
             description="China demand +25% sustained surge", sort_order=8, enabled=True),

        dict(preset_id="imo2020",         name="IMO 2020 Fuel Rules",
             cfg_overrides="",
             constraint_type="fuel_regulation", target_nodes="",
             target_companies="", target_regions="",
             apply_on_day=0, end_on_day="", multiplier=1, additive=150,
             description="VLSFO +150 $/t surcharge for non-scrubber ships", sort_order=9, enabled=True),

        dict(preset_id="panama_drought",  name="Panama Low Water",
             cfg_overrides="",
             constraint_type="node_capacity_change", target_nodes="Panama Canal",
             target_companies="", target_regions="",
             apply_on_day=0, end_on_day=180, multiplier=0.4, additive=0,
             description="Panama Canal capacity cut 60% (drought/water level)", sort_order=10, enabled=True),

        dict(preset_id="malacca_threat",  name="Malacca Piracy Threat",
             cfg_overrides="",
             constraint_type="node_capacity_change", target_nodes="Strait of Malacca",
             target_companies="", target_regions="",
             apply_on_day=30, end_on_day=120, multiplier=0.6, additive=0,
             description="Malacca Strait throughput reduced 40% due to piracy/threat", sort_order=11, enabled=True),

        dict(preset_id="quarterly_5yr",   name="Quarterly 5yr",
             cfg_overrides="granularity=quarter;n_periods=20",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="",
             description="Coarser 5-year strategic view", sort_order=12, enabled=True),

        dict(preset_id="annual_10yr",     name="Annual 10yr",
             cfg_overrides="granularity=year;n_periods=10",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="",
             description="Strategic 10-year annual view", sort_order=13, enabled=True),

        dict(preset_id="weekly_short",    name="Weekly short-run",
             cfg_overrides="granularity=week;n_periods=52",
             constraint_type="", target_nodes="", target_companies="",
             target_regions="", apply_on_day="", end_on_day="",
             multiplier="", additive="",
             description="52-week high-resolution short run", sort_order=14, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# groups / group_hierarchy / object_group_map  — constraint engine hierarchy
# ─────────────────────────────────────────────────────────────────────────────
def template_groups() -> pd.DataFrame:
    """Named groups that can be targeted by constraints.
    object_type: vessel | region | company | node | route
    """
    return pd.DataFrame([
        # Vessel class groups
        dict(group_id="class:vlcc",    name="VLCC Class",          object_type="vessel",  description="Very Large Crude Carriers ≥200k DWT",                 sort_order=1,  enabled=True),
        dict(group_id="class:suezmax", name="Suezmax Class",       object_type="vessel",  description="Suezmax 120–200k DWT",                                 sort_order=2,  enabled=True),
        dict(group_id="class:aframax", name="Aframax Class",       object_type="vessel",  description="Aframax 80–120k DWT",                                  sort_order=3,  enabled=True),
        dict(group_id="class:panamax", name="Panamax Class",       object_type="vessel",  description="Panamax 55–80k DWT",                                   sort_order=4,  enabled=True),
        dict(group_id="class:mr",      name="MR Class",            object_type="vessel",  description="Medium Range tankers 25–55k DWT",                      sort_order=5,  enabled=True),
        # Flag groups
        dict(group_id="flag:russia",   name="Russian Flag",        object_type="vessel",  description="Russian flag / shadow fleet vessels",                  sort_order=10, enabled=True),
        dict(group_id="flag:china",    name="Chinese Flag",        object_type="vessel",  description="Chinese flag vessels (CNOOC, Cosco)",                  sort_order=11, enabled=True),
        dict(group_id="flag:greece",   name="Greek Flag",          object_type="vessel",  description="Greek-managed vessels",                                sort_order=12, enabled=True),
        dict(group_id="flag:western",  name="Western Flag",        object_type="vessel",  description="US/EU/UK/Norway-flagged vessels",                      sort_order=13, enabled=True),
        dict(group_id="flag:shadow",   name="Shadow Fleet",        object_type="vessel",  description="Dark fleet / sanction-evading vessels",                sort_order=14, enabled=True),
        # Scrubber / tech groups
        dict(group_id="scrubber:yes",  name="Scrubber Fitted",     object_type="vessel",  description="Vessels with exhaust gas cleaning systems (EGCS)",     sort_order=20, enabled=True),
        dict(group_id="scrubber:no",   name="No Scrubber",         object_type="vessel",  description="Vessels burning VLSFO/MGO only",                       sort_order=21, enabled=True),
        dict(group_id="sts:capable",   name="STS Capable",         object_type="vessel",  description="Ship-to-ship transfer capable",                        sort_order=22, enabled=True),
        # Trade mode groups
        dict(group_id="trade:spot",    name="Spot Market",         object_type="vessel",  description="Vessels trading on spot / voyage charters",            sort_order=30, enabled=True),
        dict(group_id="trade:contract",name="Contract/TC",         object_type="vessel",  description="Vessels on time-charter or COA contracts",             sort_order=31, enabled=True),
        dict(group_id="trade:captive", name="Captive Fleet",       object_type="vessel",  description="Company-owned captive fleet vessels",                  sort_order=32, enabled=True),
        # Age cohorts
        dict(group_id="age:new",       name="New Build (≤5yr)",    object_type="vessel",  description="Vessels aged 0–5 years",                              sort_order=40, enabled=True),
        dict(group_id="age:mid",       name="Mid Age (6–15yr)",    object_type="vessel",  description="Vessels aged 6–15 years",                              sort_order=41, enabled=True),
        dict(group_id="age:old",       name="Old (16yr+)",         object_type="vessel",  description="Vessels aged 16+ years, scrapping candidates",         sort_order=42, enabled=True),
        # Region groups
        dict(group_id="region:opec",   name="OPEC Regions",        object_type="region",  description="Regions hosting OPEC+ production",                    sort_order=50, enabled=True),
        dict(group_id="region:euimport",name="EU Import Regions",  object_type="region",  description="European import destination regions",                 sort_order=51, enabled=True),
        dict(group_id="region:asiaimport",name="Asia Import Regions",object_type="region", description="Asia-Pacific import destination regions",            sort_order=52, enabled=True),
        # Node groups
        dict(group_id="node:chokepoint",name="Chokepoints",        object_type="node",    description="Strategic maritime chokepoints",                      sort_order=60, enabled=True),
        dict(group_id="node:gateway",  name="Primary Gateways",    object_type="node",    description="Primary gateway nodes (Suez, Hormuz, Malacca, etc.)", sort_order=61, enabled=True),
        # Company groups
        dict(group_id="company:major", name="Major IOCs",          object_type="company", description="International Oil Companies (Shell, ExxonMobil, BP)", sort_order=70, enabled=True),
        dict(group_id="company:noc",   name="NOCs",                object_type="company", description="National Oil Companies (Aramco, Rosneft, CNOOC)",     sort_order=71, enabled=True),
    ])


def template_group_hierarchy() -> pd.DataFrame:
    """Parent-child relationships between groups (many-to-many).
    A child group is a subset of its parent.
    """
    return pd.DataFrame([
        # All vessel classes roll up to 'all:vessels'
        dict(parent_group_id="class:vlcc",     child_group_id="age:new",         description="New VLCCs"),
        dict(parent_group_id="class:vlcc",     child_group_id="flag:shadow",      description="Shadow-fleet VLCCs"),
        dict(parent_group_id="class:suezmax",  child_group_id="age:new",         description="New Suezmaxes"),
        dict(parent_group_id="flag:russia",    child_group_id="flag:shadow",      description="Russian-flagged shadow fleet vessels"),
        dict(parent_group_id="node:gateway",   child_group_id="node:chokepoint",  description="All gateways are chokepoints"),
        dict(parent_group_id="company:major",  child_group_id="trade:contract",   description="IOC vessels predominantly on contract"),
        dict(parent_group_id="company:noc",    child_group_id="trade:captive",    description="NOC vessels predominantly captive"),
        dict(parent_group_id="region:opec",    child_group_id="region:euimport",  description="Some OPEC regions also EU-import destinations"),
    ])


def template_object_group_map() -> pd.DataFrame:
    """Maps individual objects (vessels, regions, nodes, companies) to group(s).
    One row per object-group membership.
    """
    return pd.DataFrame([
        # Vessel-class memberships (sample fleet vessels)
        dict(object_id="vessel:v001", object_type="vessel", group_id="class:vlcc",     notes="VLCC 300k DWT"),
        dict(object_id="vessel:v001", object_type="vessel", group_id="flag:western",   notes="Marshall Islands"),
        dict(object_id="vessel:v001", object_type="vessel", group_id="scrubber:yes",   notes="EGCS fitted 2020"),
        dict(object_id="vessel:v001", object_type="vessel", group_id="trade:spot",     notes="Voyages spot market"),
        dict(object_id="vessel:v002", object_type="vessel", group_id="class:suezmax",  notes="Suezmax 150k DWT"),
        dict(object_id="vessel:v002", object_type="vessel", group_id="flag:greece",    notes="Greek-managed"),
        dict(object_id="vessel:v002", object_type="vessel", group_id="scrubber:no",    notes="VLSFO burner"),
        dict(object_id="vessel:v002", object_type="vessel", group_id="trade:contract", notes="3yr TC Shell"),
        dict(object_id="vessel:v003", object_type="vessel", group_id="class:aframax",  notes="Aframax 105k DWT"),
        dict(object_id="vessel:v003", object_type="vessel", group_id="flag:russia",    notes="Russian flag"),
        dict(object_id="vessel:v003", object_type="vessel", group_id="flag:shadow",    notes="AIS dark history"),
        dict(object_id="vessel:v003", object_type="vessel", group_id="age:mid",        notes="Built 2012"),
        # Region memberships
        dict(object_id="AG",          object_type="region", group_id="region:opec",      notes="Arabian Gulf OPEC+"),
        dict(object_id="RSEA",        object_type="region", group_id="region:opec",      notes="Red Sea/Saudi"),
        dict(object_id="WAF",         object_type="region", group_id="region:opec",      notes="West Africa OPEC"),
        dict(object_id="MED",         object_type="region", group_id="region:euimport",  notes="Med EU import hub"),
        dict(object_id="NSEA",        object_type="region", group_id="region:euimport",  notes="North Sea EU"),
        dict(object_id="UKC",         object_type="region", group_id="region:euimport",  notes="UK Continent"),
        dict(object_id="CCHINA",      object_type="region", group_id="region:asiaimport",notes="Central China imports"),
        dict(object_id="KOR_JPN",     object_type="region", group_id="region:asiaimport",notes="Korea/Japan imports"),
        dict(object_id="SEASIA",      object_type="region", group_id="region:asiaimport",notes="SE Asia imports"),
        # Node memberships
        dict(object_id="Suez Canal",          object_type="node", group_id="node:gateway",   notes="Primary Suez gateway"),
        dict(object_id="Strait of Hormuz",    object_type="node", group_id="node:gateway",   notes="Primary Hormuz gateway"),
        dict(object_id="Strait of Malacca",   object_type="node", group_id="node:gateway",   notes="Primary Malacca gateway"),
        dict(object_id="Gibraltar Strait",    object_type="node", group_id="node:gateway",   notes="Primary Gibraltar gateway"),
        dict(object_id="Panama Canal",        object_type="node", group_id="node:gateway",   notes="Primary Panama gateway"),
        dict(object_id="Suez Canal",          object_type="node", group_id="node:chokepoint",notes="Chokepoint"),
        dict(object_id="Strait of Hormuz",    object_type="node", group_id="node:chokepoint",notes="Chokepoint"),
        dict(object_id="Cape of Good Hope",   object_type="node", group_id="node:chokepoint",notes="Alternate route chokepoint"),
        # Company memberships
        dict(object_id="Shell",       object_type="company", group_id="company:major",  notes="IOC"),
        dict(object_id="ExxonMobil",  object_type="company", group_id="company:major",  notes="IOC"),
        dict(object_id="BP",          object_type="company", group_id="company:major",  notes="IOC"),
        dict(object_id="Saudi Aramco",object_type="company", group_id="company:noc",    notes="Saudi NOC"),
        dict(object_id="Rosneft",     object_type="company", group_id="company:noc",    notes="Russian NOC"),
        dict(object_id="CNOOC",       object_type="company", group_id="company:noc",    notes="Chinese NOC"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# conflict_rules  — configurable resolution priorities for fleet dynamics
# ─────────────────────────────────────────────────────────────────────────────
def template_conflict_rules() -> pd.DataFrame:
    """Named priority rules for conflict resolution in fleet dynamics.

    rule_type values:
      scrapping          — which vessel groups are scrapped first when rates fall
      ordering_priority  — which groups get new-build allocation priority
      storage_preference — which vessel types convert to floating storage first
      routing_preference — which routes are preferred when alternates exist

    priority_rank: lower number = higher priority (1 = first/most preferred).
    condition: freeform tag for when rule applies (optional, e.g. 'spot_below_10k').
    """
    return pd.DataFrame([
        # ── Scrapping priority ───────────────────────────────────────────────
        # Economics-first: oldest / smallest / worst-positioned vessels scrapped
        # first. No political ordering. Flags do NOT drive scrapping decisions —
        # that is determined by market economics, age, and trading position.
        dict(rule_id="scrap_1",  rule_name="Scrap: Overage vessels",
             rule_type="scrapping", group_id="age:old",         priority_rank=1,
             condition="always",   enabled=True,
             description="Vessels >16yr past economic life are first candidates"),
        dict(rule_id="scrap_2",  rule_name="Scrap: Mid-age under pressure",
             rule_type="scrapping", group_id="age:mid",         priority_rank=2,
             condition="always",   enabled=True,
             description="Mid-age vessels 6-15yr when sustained low rates persist"),
        dict(rule_id="scrap_3",  rule_name="Scrap: No-scrubber on high fuel",
             rule_type="scrapping", group_id="scrubber:no",     priority_rank=3,
             condition="fuel_premium", enabled=True,
             description="VLSFO-burning vessels scrapped earlier when fuel spread widens"),
        dict(rule_id="scrap_4",  rule_name="Scrap: Spot-exposed vessels",
             rule_type="scrapping", group_id="trade:spot",      priority_rank=4,
             condition="always",   enabled=True,
             description="Spot-market vessels have no TC backstop; scrapped before contract vessels"),
        dict(rule_id="scrap_5",  rule_name="Scrap: MR class first",
             rule_type="scrapping", group_id="class:mr",        priority_rank=5,
             condition="always",   enabled=True,
             description="Smaller MR tankers have shorter economic lives"),
        dict(rule_id="scrap_6",  rule_name="Scrap: Panamax class",
             rule_type="scrapping", group_id="class:panamax",   priority_rank=6,
             condition="always",   enabled=True,
             description="Panamax scrapped before Aframax when both under pressure"),
        dict(rule_id="scrap_7",  rule_name="Scrap: Aframax class",
             rule_type="scrapping", group_id="class:aframax",   priority_rank=7,
             condition="always",   enabled=True,
             description=""),
        dict(rule_id="scrap_8",  rule_name="Scrap: Suezmax class",
             rule_type="scrapping", group_id="class:suezmax",   priority_rank=8,
             condition="always",   enabled=True,
             description=""),
        dict(rule_id="scrap_9",  rule_name="Scrap: VLCC last",
             rule_type="scrapping", group_id="class:vlcc",      priority_rank=9,
             condition="always",   enabled=True,
             description="VLCCs have highest capital value; scrapped last"),
        # ── Ordering priority ────────────────────────────────────────────────
        dict(rule_id="order_1", rule_name="Order: NOC captive first",
             rule_type="ordering_priority", group_id="trade:captive",  priority_rank=1,
             condition="always",   enabled=True,
             description="NOC captive fleets order regardless of spot signal"),
        dict(rule_id="order_2", rule_name="Order: Contract vessels",
             rule_type="ordering_priority", group_id="trade:contract", priority_rank=2,
             condition="profit_signal_positive", enabled=True,
             description="Time-charter operators order when TC rates justify"),
        dict(rule_id="order_3", rule_name="Order: Spot traders",
             rule_type="ordering_priority", group_id="trade:spot",     priority_rank=3,
             condition="profit_signal_high",     enabled=True,
             description="Spot traders order only on strong profit signals"),
        # ── Storage conversion priority ──────────────────────────────────────
        dict(rule_id="stor_1",  rule_name="Storage: VLCC preferred",
             rule_type="storage_preference", group_id="class:vlcc",   priority_rank=1,
             condition="oversupply",  enabled=True,
             description="VLCCs are preferred floating storage due to volume"),
        dict(rule_id="stor_2",  rule_name="Storage: Suezmax second",
             rule_type="storage_preference", group_id="class:suezmax",priority_rank=2,
             condition="oversupply",  enabled=True,
             description=""),
    ])


# ─────────────────────────────────────────────────────────────────────────────
def template_node_vessel_limits() -> pd.DataFrame:
    """
    DWT limits per node.  These are PHYSICAL constraints (canal locks, channel
    depth, bridge clearance) — not political ones.  Political/commercial limits
    belong in constraints.csv.

    max_dwt_t:      Maximum vessel displacement in tonnes.  Vessels exceeding
                    this are routed via alternate edges automatically.
    reason:         Human-readable reason (lock size, channel depth, etc.)
    source_year:    Year of the specification (update when canal expands/floods)
    enabled:        Set False to temporarily disable the limit (e.g. model a
                    canal expansion or a drought scenario via a branch fork).

    Updating this table is the correct way to model:
      - Panama Canal drought (reduce max_dwt_t, or set enabled=False for large)
      - Canal expansion (increase max_dwt_t)
      - New lock construction (add a row)
      - Turkish Straits seasonal depth limits (branch fork with reduced limit)
    """
    return pd.DataFrame([
        # ── Panama Canal ─────────────────────────────────────────────────────
        # New Panamax locks (2016) handle up to ~120k DWT Neopanamax.
        # Old locks ~65k DWT.  Crude tankers rarely use Panama regardless —
        # VLCCs/Suezmaxes never fit.  Most Panama crude is small product tankers.
        dict(node_id="Panama Canal", limit_name="Neopanamax lock limit",
             max_dwt_t=120_000, group_applies_to="class:vlcc,class:suezmax",
             reason="Lock chamber dimensions: 427m × 55m × 18.3m max draft",
             source_year=2016, enabled=True),

        # ── Turkish Straits (Bosphorus) ───────────────────────────────────────
        # 150k DWT max, draft limit 17.5m.  Suezmaxes barely fit; VLCCs cannot.
        dict(node_id="Turkish Straits", limit_name="Bosphorus draft/beam limit",
             max_dwt_t=150_000, group_applies_to="class:vlcc",
             reason="Bosphorus: 17.5m max draft, 45m min width at narrowest point",
             source_year=2024, enabled=True),

        # ── Danish Straits ────────────────────────────────────────────────────
        # Great Belt: 68m air draft, 15m water draft.  Limits largest VLCCs.
        dict(node_id="Danish Straits", limit_name="Great Belt draft limit",
             max_dwt_t=150_000, group_applies_to="class:vlcc",
             reason="Great Belt Bridge: 65m air clearance, 15m channel draft limit",
             source_year=2024, enabled=True),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# object_fields  — column specifications for every editable table
# Drives the dynamic Config tab editor: types, labels, select options, refs
# ─────────────────────────────────────────────────────────────────────────────
def template_object_fields() -> pd.DataFrame:
    """
    Column metadata for every editable table.  The Config tab reads this to
    render the right input widget for each cell:

      field_type:
        text        — plain text input
        number      — numeric input (with optional min/max/step)
        bool        — checkbox (values: True / False)
        select      — dropdown; options= semicolon-separated values
        group_ref   — links to groups.table group_id column
        node_ref    — links to nodes.node_id column
        region_ref  — links to regions.region_id column
        vessel_ref  — links to vessel_groups.group_id
        multiref    — comma-separated list of refs

    editable: whether this column can be edited in the UI
    required: whether the field must be non-empty on save
    """
    def F(table, field, label, ftype, options='', description='',
          sort_order=0, editable=True, required=False,
          min_val='', max_val='', step=''):
        return dict(table_name=table, field_name=field, field_label=label,
                    field_type=ftype, options=options, description=description,
                    sort_order=sort_order, editable=editable, required=required,
                    min_val=min_val, max_val=max_val, step=step)
    rows = [
        # ── groups ──────────────────────────────────────────────────────────
        F('groups','group_id',      'Group ID',      'text',   required=True,  sort_order=1,
          description='Unique key e.g. class:vlcc, flag:russia, region:opec'),
        F('groups','name',          'Display Name',  'text',   required=True,  sort_order=2),
        F('groups','object_type',   'Object Type',   'select',
          options='vessel;region;company;node;route', sort_order=3, required=True),
        F('groups','description',   'Description',   'text',   sort_order=4),
        F('groups','sort_order',    'Order',         'number', sort_order=5, min_val='0', step='1'),
        F('groups','enabled',       'Enabled',       'bool',   sort_order=6),

        # ── group_hierarchy ──────────────────────────────────────────────────
        F('group_hierarchy','parent_group_id','Parent Group','group_ref',required=True,sort_order=1),
        F('group_hierarchy','child_group_id', 'Child Group', 'group_ref',required=True,sort_order=2),
        F('group_hierarchy','description',    'Description', 'text',              sort_order=3),

        # ── object_group_map ────────────────────────────────────────────────
        F('object_group_map','object_id',   'Object ID',   'text',      required=True, sort_order=1),
        F('object_group_map','object_type', 'Object Type', 'select',
          options='vessel;region;company;node;route', sort_order=2, required=True),
        F('object_group_map','group_id',    'Group',       'group_ref', required=True, sort_order=3),
        F('object_group_map','notes',       'Notes',       'text',      sort_order=4),

        # ── conflict_rules ───────────────────────────────────────────────────
        F('conflict_rules','rule_id',       'Rule ID',     'text',   required=True, sort_order=1),
        F('conflict_rules','rule_name',     'Rule Name',   'text',   required=True, sort_order=2),
        F('conflict_rules','rule_type',     'Rule Type',   'select',
          options='scrapping;ordering_priority;storage_preference;routing_preference',
          sort_order=3, required=True),
        F('conflict_rules','group_id',      'Group',       'group_ref', required=True, sort_order=4),
        F('conflict_rules','priority_rank', 'Priority',    'number', min_val='1', step='1', sort_order=5),
        F('conflict_rules','condition',     'Condition',   'text',   sort_order=6),
        F('conflict_rules','enabled',       'Enabled',     'bool',   sort_order=7),
        F('conflict_rules','description',   'Description', 'text',   sort_order=8),

        # ── constraints ─────────────────────────────────────────────────────
        F('constraints','constraint_id',  'ID',         'text', required=True, sort_order=1),
        F('constraints','constraint_type','Type',       'select',
          options='node_closure;node_capacity_change;node_group_ban;supply_shock;demand_shock;sanction_ship_flag;sanction_company;sanction_port;fuel_regulation;spot_price_shock;newbuild_limit',
          sort_order=2, required=True),
        F('constraints','target_nodes',   'Target Nodes',   'multiref', sort_order=3),
        F('constraints','target_vessel_groups','Vessel Groups','multiref',sort_order=4),
        F('constraints','target_regions', 'Regions',    'multiref', sort_order=5),
        F('constraints','target_companies','Companies', 'multiref', sort_order=6),
        F('constraints','apply_on_day',   'Start Day',  'number', min_val='0', step='1', sort_order=7),
        F('constraints','end_on_day',     'End Day',    'number', min_val='0', step='1', sort_order=8),
        F('constraints','multiplier',     'Multiplier', 'number', step='0.05', sort_order=9,
          description='0=block, 1=no change, 1.5=+50%'),
        F('constraints','additive',       'Additive',   'number', step='10', sort_order=10),
        F('constraints','enabled',        'Enabled',    'bool',  sort_order=11),
        F('constraints','description',    'Description','text',  sort_order=12),

        # ── scenario_presets ─────────────────────────────────────────────────
        F('scenario_presets','preset_id',       'Preset ID',   'text', required=True, sort_order=1),
        F('scenario_presets','name',            'Name',        'text', required=True, sort_order=2),
        F('scenario_presets','constraint_type', 'Constraint',  'select',
          options='node_closure;node_group_ban;supply_shock;demand_shock;sanction_ship_flag;fuel_regulation;spot_price_shock',
          sort_order=3),
        F('scenario_presets','target_nodes',    'Target Nodes','multiref', sort_order=4),
        F('scenario_presets','target_regions',  'Regions',     'multiref', sort_order=5),
        F('scenario_presets','cfg_overrides',   'Config Overrides','text', sort_order=6,
          description='key=value;key=value pairs to override portal_params'),
        F('scenario_presets','apply_on_day',    'Start Day',   'number', min_val='0', sort_order=7),
        F('scenario_presets','end_on_day',      'End Day',     'number', min_val='0', sort_order=8),
        F('scenario_presets','multiplier',      'Multiplier',  'number', step='0.05', sort_order=9),
        F('scenario_presets','enabled',         'Enabled',     'bool', sort_order=10),
        F('scenario_presets','description',     'Description', 'text', sort_order=11),

        # ── regions ──────────────────────────────────────────────────────────
        F('regions','region',            'Region ID',       'text',   required=True, editable=False, sort_order=1),
        F('regions','label',             'Display Label',   'text',   sort_order=2),
        F('regions','tags',              'Tags',            'text',   sort_order=3,
          description='Comma-separated: opec, eu_import, arctic, etc.'),
        F('regions','spot_premium',      'Spot Premium',    'number', step='0.05', sort_order=4),
        F('regions','fuel_premium',      'Fuel Premium',    'number', step='0.05', sort_order=5),
        F('regions','max_vessel_dwt',    'Max DWT (t)',     'number', step='1000',  sort_order=6),

        # ── nodes ────────────────────────────────────────────────────────────
        F('nodes','node_id',         'Node ID',       'text',   required=True, editable=False, sort_order=1),
        F('nodes','node_type',       'Type',          'select',
          options='port;gateway;chokepoint;anchorage', sort_order=2),
        F('nodes','is_gateway',      'Is Gateway',    'bool',   sort_order=3),
        F('nodes','is_open',         'Is Open',       'bool',   sort_order=4),
        F('nodes','transit_time_days','Transit Days', 'number', step='0.5', sort_order=5),

        # ── vessel_groups ────────────────────────────────────────────────────
        F('vessel_groups','group_id',   'Group ID',     'text',   required=True, sort_order=1),
        F('vessel_groups','group_type', 'Group Type',   'select',
          options='class;flag;build;scrubber;sts;trade;age', sort_order=2),
        F('vessel_groups','min_dwt',    'Min DWT',      'number', step='1000', sort_order=3),
        F('vessel_groups','max_dwt',    'Max DWT',      'number', step='1000', sort_order=4),
        F('vessel_groups','description','Description',  'text',   sort_order=5),
        F('vessel_groups','enabled',    'Enabled',      'bool',   sort_order=6),

        # ── portal_params ────────────────────────────────────────────────────
        F('portal_params','key',         'Parameter Key', 'text',   editable=False, sort_order=1),
        F('portal_params','label',       'Label',         'text',   sort_order=2),
        F('portal_params','default_val', 'Default Value', 'text',   sort_order=3),
        F('portal_params','param_type',  'Type',          'select',
          options='number;text;bool;select', sort_order=4),
        F('portal_params','min_val',     'Min',           'number', sort_order=5),
        F('portal_params','max_val',     'Max',           'number', sort_order=6),
        F('portal_params','step',        'Step',          'number', sort_order=7),
        F('portal_params','group',       'Group',         'text',   sort_order=8),
        F('portal_params','description', 'Description',   'text',   sort_order=9),
        F('portal_params','enabled',     'Enabled',       'bool',   sort_order=10),

        # ── viz_regions ──────────────────────────────────────────────────────
        F('viz_regions','region',      'Region ID',  'text',   editable=False, sort_order=1),
        F('viz_regions','label',       'Label',      'text',   sort_order=2),
        F('viz_regions','lat',         'Latitude',   'number', step='0.001', sort_order=3),
        F('viz_regions','lon',         'Longitude',  'number', step='0.001', sort_order=4),
        F('viz_regions','popup_fields','Popup Fields','text',  sort_order=5,
          description='Comma-separated fields shown in hover/click popup'),
        F('viz_regions','enabled',     'Enabled',    'bool',   sort_order=6),

        # ── viz_nodes ────────────────────────────────────────────────────────
        F('viz_nodes','node',          'Node ID',    'text',   editable=False, sort_order=1),
        F('viz_nodes','label',         'Label',      'text',   sort_order=2),
        F('viz_nodes','lat',           'Latitude',   'number', step='0.001', sort_order=3),
        F('viz_nodes','lon',           'Longitude',  'number', step='0.001', sort_order=4),
        F('viz_nodes','is_gateway',    'Is Gateway', 'bool',   sort_order=5),
        F('viz_nodes','color_open',    'Color Open', 'text',   sort_order=6),
        F('viz_nodes','color_closed',  'Color Closed','text',  sort_order=7),
        F('viz_nodes','enabled',       'Enabled',    'bool',   sort_order=8),

        # ── viz_routes ───────────────────────────────────────────────────────
        F('viz_routes','route_id',    'Route ID',   'text',   sort_order=1),
        F('viz_routes','seq',         'Seq',        'number', step='1', sort_order=2),
        F('viz_routes','lat',         'Lat',        'number', step='0.001', sort_order=3),
        F('viz_routes','lon',         'Lon',        'number', step='0.001', sort_order=4),
        F('viz_routes','enabled',     'Enabled',    'bool',   sort_order=5),

        # ── edges ────────────────────────────────────────────────────────────
        F('edges','from_node',            'From',              'node_ref', required=True, sort_order=1),
        F('edges','to_node',              'To',                'node_ref', required=True, sort_order=2),
        F('edges','distance_nm',          'Distance (nm)',     'number', step='50',  sort_order=3),
        F('edges','base_transit_mean_days','Transit Days',     'number', step='0.5', sort_order=4),
        F('edges','base_transit_std_days', 'Transit Std',      'number', step='0.5', sort_order=5),
        F('edges','requires_nodes',       'Required Nodes',    'multiref', sort_order=6),
        F('edges','alternate_for',        'Alternate For',     'multiref', sort_order=7),

        # ── portal_settings ───────────────────────────────────────────────────
        F('portal_settings','key',  'Setting Key','text',   editable=False, sort_order=1),
        F('portal_settings','value','Value',      'text',   sort_order=2),
        F('portal_settings','label','Label',      'text',   editable=False, sort_order=3),
    ]
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# object_lists  — registry of all domain-object tables
# Each row = one navigable entity table. The Config "Objects" section
# reads this to build navigation and uses object_fields to render columns.
# ─────────────────────────────────────────────────────────────────────────────
def template_object_lists() -> pd.DataFrame:
    """
    Registry of domain-object tables — things that EXIST in the simulation
    (vessels, companies, regions, nodes, products, groups…) as opposed to
    configuration/rules tables.

    Columns:
      table_name    — key matching tables[] in the browser
      label         — display name in the Objects nav panel  
      object_type   — vessel | region | company | node | product | group | route
      id_field      — the primary-key column name in that table
      label_field   — the human-readable name column
      description   — one-liner about what this table contains
      icon          — emoji icon for nav
      sort_order    — display order in nav
      enabled       — show in UI
    """
    return pd.DataFrame([
        dict(table_name='fleet',          label='Fleet',           object_type='vessel',
             id_field='vessel_id',  label_field='ship_type',
             description='Active vessel fleet — counts per type and owner',
             icon='🚢', sort_order=1, enabled=True),
        dict(table_name='ship_types',     label='Ship Types',      object_type='vessel',
             id_field='name',       label_field='name',
             description='Vessel class specifications: DWT, speed, opex, build cost',
             icon='⚓', sort_order=2, enabled=True),
        dict(table_name='vessel_groups',  label='Vessel Groups',   object_type='vessel',
             id_field='group_id',   label_field='group_id',
             description='Named vessel groups: class:vlcc, flag:russia, age:old …',
             icon='🏷', sort_order=3, enabled=True),
        dict(table_name='companies',      label='Companies',       object_type='company',
             id_field='name',       label_field='name',
             description='Oil companies: supply/demand regions, sanctionability',
             icon='🏢', sort_order=4, enabled=True),
        dict(table_name='regions',        label='Regions',         object_type='region',
             id_field='region',     label_field='label',
             description='Geographic trading regions: supply, demand, storage',
             icon='🗺', sort_order=5, enabled=True),
        dict(table_name='nodes',          label='Nodes / Chokepoints', object_type='node',
             id_field='node_id',    label_field='node_id',
             description='Ports, gateways, chokepoints — transit constraints',
             icon='🔀', sort_order=6, enabled=True),
        dict(table_name='edges',          label='Trade Routes',    object_type='route',
             id_field='',           label_field='',
             description='Directed shipping routes with distance and transit days',
             icon='📍', sort_order=7, enabled=True),
        dict(table_name='groups',         label='Groups',          object_type='group',
             id_field='group_id',   label_field='name',
             description='All named groups — vessels, regions, companies, nodes',
             icon='📦', sort_order=8, enabled=True),
        dict(table_name='object_group_map', label='Group Memberships', object_type='group',
             id_field='',           label_field='',
             description='Maps objects to their groups',
             icon='🔗', sort_order=9, enabled=True),
        dict(table_name='constraints',    label='Constraints',     object_type='rule',
             id_field='constraint_id', label_field='description',
             description='Active scenario constraints including node_group_ban rules',
             icon='🚫', sort_order=10, enabled=True),
    ])

# ALL_PORTAL_TEMPLATES  — registered here, loaded by portal.py
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
    "scenario_presets": template_scenario_presets,
    "groups":            template_groups,
    "group_hierarchy":   template_group_hierarchy,
    "object_group_map":  template_object_group_map,
    "conflict_rules":     template_conflict_rules,
    "object_fields":       template_object_fields,
    "object_lists":        template_object_lists,
}
