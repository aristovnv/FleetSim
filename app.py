"""
Maritime Fleet Simulation — Streamlit Interface
Industrial/technical aesthetic with dark navy theme
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import time

from simulation import (
    SimConfig, MaritimeSimulation,
    DEFAULT_REGIONS, DEFAULT_COMPANIES, DEFAULT_SHIP_TYPES, DEFAULT_FLEET,
    Region, OilCompany
)

# ──────────────────────────────────────────────────────────────────────────────
# PAGE SETUP
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Maritime Fleet Simulation",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

:root {
    --navy:    #0a1628;
    --navy2:   #112240;
    --navy3:   #1a3a5c;
    --cyan:    #00d4ff;
    --orange:  #ff6b35;
    --green:   #39ff14;
    --yellow:  #ffd23f;
    --text:    #ccd6f6;
    --muted:   #8892b0;
}

.stApp { background: var(--navy); color: var(--text); font-family: 'IBM Plex Sans', sans-serif; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--navy2);
    border-right: 1px solid var(--navy3);
}
[data-testid="stSidebar"] .stMarkdown h2 { 
    color: var(--cyan); 
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    border-bottom: 1px solid var(--navy3);
    padding-bottom: 6px;
    margin-top: 20px;
}

/* Headers */
h1 { font-family: 'Space Mono', monospace; color: var(--cyan) !important; letter-spacing: -0.02em; }
h2 { font-family: 'Space Mono', monospace; color: var(--text) !important; font-size: 1rem !important; letter-spacing: 0.05em; text-transform: uppercase; }
h3 { color: var(--cyan) !important; font-family: 'IBM Plex Sans', sans-serif; font-weight: 300; }

/* Metric cards */
[data-testid="metric-container"] {
    background: var(--navy2);
    border: 1px solid var(--navy3);
    border-left: 3px solid var(--cyan);
    padding: 12px 16px;
    border-radius: 4px;
}
[data-testid="metric-container"] label { color: var(--muted) !important; font-size: 0.75rem !important; text-transform: uppercase; letter-spacing: 0.1em; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: var(--cyan) !important; font-family: 'Space Mono', monospace; }
[data-testid="metric-container"] [data-testid="stMetricDelta"] { font-size: 0.8rem; }

/* Sliders */
[data-testid="stSlider"] > div > div > div { background: var(--navy3); }
.stSlider [data-baseweb="slider"] [role="slider"] { background: var(--cyan); }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background: var(--navy2); border-bottom: 1px solid var(--navy3); }
.stTabs [data-baseweb="tab"] { color: var(--muted); font-family: 'Space Mono', monospace; font-size: 0.8rem; }
.stTabs [aria-selected="true"] { color: var(--cyan) !important; border-bottom: 2px solid var(--cyan); }

/* Buttons */
.stButton > button {
    background: transparent;
    border: 1px solid var(--cyan);
    color: var(--cyan);
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
    letter-spacing: 0.1em;
    transition: all 0.2s;
}
.stButton > button:hover {
    background: var(--cyan);
    color: var(--navy);
}

/* Regime badge */
.regime-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 2px;
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.1em;
    margin: 2px;
}
.regime-on  { background: rgba(255,107,53,0.2); border: 1px solid #ff6b35; color: #ff6b35; }
.regime-off { background: rgba(136,146,176,0.1); border: 1px solid #3a4466; color: #556; }

.header-row {
    display: flex; align-items: baseline; gap: 16px;
    border-bottom: 1px solid var(--navy3);
    padding-bottom: 12px; margin-bottom: 24px;
}
.subtitle { color: var(--muted); font-size: 0.85rem; font-family: 'IBM Plex Sans'; }

.section-rule { border: none; border-top: 1px solid var(--navy3); margin: 24px 0; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# PLOTLY THEME
# ──────────────────────────────────────────────────────────────────────────────

PLOTLY_LAYOUT = dict(
    paper_bgcolor="#0a1628",
    plot_bgcolor="#0d1f38",
    font=dict(family="IBM Plex Sans", color="#ccd6f6", size=11),
    xaxis=dict(gridcolor="#1a3a5c", linecolor="#1a3a5c", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#1a3a5c", linecolor="#1a3a5c", tickfont=dict(size=10)),
    margin=dict(l=50, r=20, t=40, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#1a3a5c", borderwidth=1),
)

COLORS = {
    "spot_rate":   "#00d4ff",
    "demand":      "#39ff14",
    "supply":      "#ffd23f",
    "fleet":       "#ff6b35",
    "storage":     "#a78bfa",
    "orderbook":   "#f472b6",
    "VLCC":        "#00d4ff",
    "Suezmax":     "#39ff14",
    "Aframax":     "#ffd23f",
    "Panamax":     "#ff6b35",
    "MR":          "#a78bfa",
}

COMPANY_COLORS = {
    "Saudi Aramco": "#00d4ff",
    "Shell":        "#ffd23f",
    "ExxonMobil":   "#ff6b35",
    "BP":           "#39ff14",
    "Rosneft":      "#f472b6",
    "Independent":  "#8892b0",
}


# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR — PARAMETER PANELS
# ──────────────────────────────────────────────────────────────────────────────

def build_sidebar() -> SimConfig:
    with st.sidebar:
        st.markdown("## 🛢️ MARITIME SIM")
        st.markdown('<p class="subtitle">Engelen–Meersman–Van de Voorde (2006) System Dynamics</p>',
                    unsafe_allow_html=True)

        # ── Simulation Control ───────────────────────────────────────────────
        st.markdown("## ⚙ Simulation Control")
        sim_years = st.slider("Horizon (years)", 5, 30, 10, 1)
        time_step = st.select_slider("Time step", [7, 14, 30, 60, 90], value=30,
                                      format_func=lambda x: f"{x}d")
        seed = st.number_input("Random seed", 0, 9999, 42)

        # ── Market Parameters ────────────────────────────────────────────────
        st.markdown("## 📈 Freight Market")
        base_rate = st.slider("Base spot rate ($/day)", 10000, 80000, 25000, 1000,
                               format="$%d")
        rate_vol = st.slider("Rate volatility", 0.05, 0.60, 0.25, 0.01,
                              format="%.2f")
        fuel_price = st.slider("Fuel price ($/MT)", 200, 1200, 600, 10, format="$%d")
        fuel_vol = st.slider("Fuel price volatility", 0.05, 0.40, 0.15, 0.01,
                              format="%.2f")

        st.markdown("## 🚢 Fleet Dynamics")
        ordering_lag = st.slider("Ordering lag (years)", 1.0, 5.0, 2.5, 0.25)
        ordering_sens = st.slider("Ordering sensitivity", 0.05, 0.80, 0.30, 0.05)
        scrap_rate = st.slider("Scrapping threshold ($/day)", 3000, 20000, 8000, 500,
                                format="$%d")
        storage_thresh = st.slider("Storage conversion S/D ratio", 1.0, 2.0, 1.4, 0.05)
        storage_rate = st.slider("FSO daily rate ($/day)", 10000, 60000, 35000, 1000,
                                  format="$%d")

        # ── Regime Switches ──────────────────────────────────────────────────
        st.markdown("## 🔴 Structural Breaks / Regimes")
        
        with st.expander("IMO 2020 — Sulfur Cap", expanded=False):
            imo_on = st.checkbox("Enable IMO 2020", value=True, key="imo_on")
            imo_yr = st.slider("Trigger year", 1, sim_years, min(3, sim_years), key="imo_yr",
                                disabled=not imo_on)
            imo_prem = st.slider("Fuel premium non-compliant ($/MT)", 0, 400, 150, 10,
                                  key="imo_prem", disabled=not imo_on)

        with st.expander("Geopolitical Sanctions", expanded=False):
            sanc_on = st.checkbox("Enable sanctions", value=False, key="sanc_on")
            sanc_yr = st.slider("Trigger year", 1, sim_years, min(5, sim_years),
                                  key="sanc_yr", disabled=not sanc_on)
            sanc_reg = st.selectbox("Target region",
                list(DEFAULT_REGIONS.keys()), index=2, key="sanc_reg",
                disabled=not sanc_on)
            sanc_cut = st.slider("Capacity reduction", 0.05, 0.80, 0.30, 0.05,
                                  format="%.0f%%",
                                  help="Fraction of target region demand/supply removed",
                                  key="sanc_cut", disabled=not sanc_on)

        with st.expander("Demand Shock (COVID-like)", expanded=False):
            shock_on = st.checkbox("Enable demand shock", value=False, key="shock_on")
            shock_yr = st.slider("Trigger year", 1, sim_years, min(4, sim_years),
                                  key="shock_yr", disabled=not shock_on)
            shock_mag = st.slider("Shock magnitude", -0.60, -0.05, -0.25, 0.01,
                                   format="%.0f%%", key="shock_mag", disabled=not shock_on)
            shock_dur = st.slider("Duration (years)", 0.5, 4.0, 1.5, 0.25,
                                   key="shock_dur", disabled=not shock_on)

    return SimConfig(
        sim_years=sim_years,
        time_step_days=time_step,
        random_seed=seed,
        base_spot_rate_usd_day=float(base_rate),
        spot_rate_volatility=rate_vol,
        fuel_price_usd_ton=float(fuel_price),
        fuel_price_volatility=fuel_vol,
        ordering_lag_years=ordering_lag,
        ordering_sensitivity=ordering_sens,
        scrapping_threshold_usd_day=float(scrap_rate),
        storage_conversion_threshold=storage_thresh,
        storage_daily_rate_usd=float(storage_rate),
        enable_imo2020=imo_on,
        imo2020_year=imo_yr,
        imo2020_fuel_premium=float(imo_prem),
        enable_sanctions=sanc_on,
        sanctions_year=sanc_yr,
        sanctions_region=sanc_reg,
        sanctions_capacity_reduction=sanc_cut,
        enable_demand_shock=shock_on,
        demand_shock_year=shock_yr,
        demand_shock_magnitude=shock_mag,
        demand_shock_duration_years=shock_dur,
    )


# ──────────────────────────────────────────────────────────────────────────────
# CHART HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def add_regime_lines(fig, df, row=1, col=1):
    """Add vertical lines where regime changes occur."""
    for col_flag, label, color in [
        ("imo2020_active",    "IMO 2020",        "#ffd23f"),
        ("sanctions_active",  "Sanctions",       "#ff6b35"),
        ("demand_shock_active","Demand Shock",   "#f472b6"),
    ]:
        if col_flag in df.columns:
            transitions = df[df[col_flag].diff() == 1]["year"]
            for yr in transitions:
                fig.add_vline(
                    x=yr, line_dash="dot", line_color=color, line_width=1.5,
                    annotation_text=label,
                    annotation_font=dict(size=9, color=color),
                    annotation_position="top left",
                    row=row, col=col,
                )


def chart_freight_market(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.6, 0.4],
                        subplot_titles=["Spot Rate ($/day)", "Fuel Price ($/MT)"])
    
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["spot_rate_usd_day"],
        mode="lines", name="Spot Rate",
        line=dict(color=COLORS["spot_rate"], width=2),
        fill="tozeroy", fillcolor="rgba(0,212,255,0.05)"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["fuel_price_usd_ton"],
        mode="lines", name="Fuel Price",
        line=dict(color=COLORS["supply"], width=1.5),
    ), row=2, col=1)

    add_regime_lines(fig, df, row=1)
    fig.update_layout(**PLOTLY_LAYOUT, height=420, showlegend=False)
    return fig


def chart_oil_balance(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.6, 0.4],
                        subplot_titles=["Supply vs Demand (MT/period)", "Supply/Demand Ratio"])

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["total_supply_mt"],
        mode="lines", name="Supply",
        line=dict(color=COLORS["supply"], width=2)
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["total_demand_mt"],
        mode="lines", name="Demand",
        line=dict(color=COLORS["demand"], width=2)
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["supply_demand_ratio"],
        mode="lines", name="S/D Ratio",
        line=dict(color=COLORS["orderbook"], width=1.5),
        fill="tozeroy", fillcolor="rgba(244,114,182,0.05)"
    ), row=2, col=1)
    fig.add_hline(y=1.0, line_dash="dash", line_color="#556", row=2, col=1)

    add_regime_lines(fig, df, row=1)
    fig.update_layout(**PLOTLY_LAYOUT, height=420)
    return fig


def chart_fleet_composition(df: pd.DataFrame) -> go.Figure:
    ship_types = [c.replace("active_", "") for c in df.columns if c.startswith("active_")]
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.55, 0.45],
                        subplot_titles=["Active Fleet by Type", "Orderbook & Storage Vessels"])

    for st in ship_types:
        fig.add_trace(go.Scatter(
            x=df["year"], y=df[f"active_{st}"],
            mode="lines", name=st,
            line=dict(color=COLORS.get(st, "#8892b0"), width=1.5),
            stackgroup="fleet"
        ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["orderbook_count"],
        mode="lines", name="Orderbook",
        line=dict(color=COLORS["orderbook"], width=1.5, dash="dash")
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["total_storage_vessels"],
        mode="lines", name="FSO/Storage",
        line=dict(color=COLORS["storage"], width=1.5),
        fill="tozeroy", fillcolor="rgba(167,139,250,0.1)"
    ), row=2, col=1)

    add_regime_lines(fig, df, row=1)
    fig.update_layout(**PLOTLY_LAYOUT, height=450)
    return fig


def chart_regional_demand(df: pd.DataFrame) -> go.Figure:
    demand_cols = [c for c in df.columns if c.startswith("demand_")]
    regions = [c.replace("demand_", "") for c in demand_cols]
    
    fig = go.Figure()
    region_colors = px.colors.qualitative.Dark24
    for i, (col, reg) in enumerate(zip(demand_cols, regions)):
        fig.add_trace(go.Scatter(
            x=df["year"], y=df[col],
            mode="lines", name=reg,
            line=dict(color=region_colors[i % len(region_colors)], width=1.5),
        ))

    add_regime_lines(fig, df)
    fig.update_layout(**PLOTLY_LAYOUT, height=360,
                       title_text="Regional Demand (MT/period)")
    return fig


def chart_company_supply(df: pd.DataFrame) -> go.Figure:
    supply_cols = [c for c in df.columns if c.startswith("supply_")]
    companies = [c.replace("supply_", "") for c in supply_cols]

    fig = go.Figure()
    for col, comp in zip(supply_cols, companies):
        fig.add_trace(go.Scatter(
            x=df["year"], y=df[col],
            mode="lines", name=comp,
            line=dict(color=COMPANY_COLORS.get(comp, "#8892b0"), width=1.5),
            stackgroup="supply",
        ))

    fig.update_layout(**PLOTLY_LAYOUT, height=320,
                       title_text="Company Supply Stack (MT/period)")
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# FLEET EDITOR (ADVANCED)
# ──────────────────────────────────────────────────────────────────────────────

def fleet_editor() -> dict:
    """Returns a fleet dict matching DEFAULT_FLEET structure."""
    st.markdown("### Initial Fleet Configuration")
    st.caption("Adjust the number of vessels per ship type and owner company.")

    fleet = {}
    for st_name, owners in DEFAULT_FLEET.items():
        st.markdown(f"**{st_name}** ({DEFAULT_SHIP_TYPES[st_name].dwt/1000:.0f}k DWT)")
        cols = st.columns(len(owners))
        fleet[st_name] = {}
        for col, (owner, default_count) in zip(cols, owners.items()):
            with col:
                val = st.number_input(
                    owner, 0, 50, default_count,
                    key=f"fleet_{st_name}_{owner}", label_visibility="collapsed"
                )
                st.caption(f"_{owner[:8]}_")
                fleet[st_name][owner] = val
        st.markdown('<hr style="border-color:#1a3a5c; margin:8px 0">', unsafe_allow_html=True)
    
    return fleet


# ──────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────────────────────────────────────

def main():
    # Header
    st.markdown("""
    <div class="header-row">
        <h1>MARITIME FLEET SIM</h1>
        <span class="subtitle">System Dynamics · Two-Equilibrium Model · Engelen-Meersman-Van de Voorde (2006)</span>
    </div>
    """, unsafe_allow_html=True)

    config = build_sidebar()

    # ── Tab layout ──────────────────────────────────────────────────────────
    tab_run, tab_fleet, tab_results, tab_about = st.tabs([
        "▶  RUN SIMULATION", "🚢  FLEET SETUP", "📊  RESULTS EXPLORER", "ℹ  MODEL NOTES"
    ])

    # ── RUN TAB ─────────────────────────────────────────────────────────────
    with tab_run:
        col_left, col_right = st.columns([2, 1])
        
        with col_left:
            st.markdown("### Scenario Summary")
            
            # Regime badges
            regimes_html = ""
            badges = [
                (config.enable_imo2020,       f"IMO 2020 @ yr {config.imo2020_year}"),
                (config.enable_sanctions,     f"Sanctions ({config.sanctions_region}) @ yr {config.sanctions_year}"),
                (config.enable_demand_shock,  f"Demand Shock @ yr {config.demand_shock_year}"),
            ]
            for active, label in badges:
                cls = "regime-on" if active else "regime-off"
                regimes_html += f'<span class="regime-badge {cls}">{label}</span>'
            st.markdown(regimes_html, unsafe_allow_html=True)

            st.markdown(f"""
            <div style="margin-top:16px; padding:16px; background:#112240; border:1px solid #1a3a5c; border-radius:4px; font-family:'Space Mono',monospace; font-size:0.8rem; line-height:1.8;">
                Horizon: <span style="color:#00d4ff">{config.sim_years} years</span> · 
                Step: <span style="color:#00d4ff">{config.time_step_days}d</span> · 
                Steps: <span style="color:#00d4ff">{int(config.sim_years * 365 / config.time_step_days)}</span><br>
                Base rate: <span style="color:#ffd23f">${config.base_spot_rate_usd_day:,.0f}/day</span> · 
                Fuel: <span style="color:#ffd23f">${config.fuel_price_usd_ton}/MT</span><br>
                Ordering lag: <span style="color:#39ff14">{config.ordering_lag_years}yr</span> · 
                Sensitivity: <span style="color:#39ff14">{config.ordering_sensitivity:.2f}</span>
            </div>
            """, unsafe_allow_html=True)

        with col_right:
            st.markdown("### Launch")
            n_runs = st.number_input("Monte Carlo runs", 1, 20, 1,
                                      help="Run multiple seeds for uncertainty bands")
            run_btn = st.button("▶  RUN", use_container_width=True)

        if run_btn:
            results_list = []
            progress = st.progress(0, "Running simulation...")
            
            for i in range(n_runs):
                cfg_i = SimConfig(**{**config.__dict__, "random_seed": config.random_seed + i})
                sim = MaritimeSimulation(cfg_i)
                df_i = sim.run()
                df_i["run"] = i
                results_list.append(df_i)
                progress.progress((i + 1) / n_runs, f"Run {i+1}/{n_runs} complete")
            
            progress.empty()
            
            df_all = pd.concat(results_list, ignore_index=True)
            df_base = results_list[0]
            st.session_state["results"] = df_base
            st.session_state["results_all"] = df_all
            st.session_state["n_runs"] = n_runs
            st.success(f"✓ Simulation complete — {len(df_base)} steps × {n_runs} run(s)")

        # Show quick summary if results available
        if "results" in st.session_state:
            df = st.session_state["results"]
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
            st.markdown("### Key Outcomes")
            
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Final Spot Rate", 
                       f"${df['spot_rate_usd_day'].iloc[-1]:,.0f}/d",
                       f"{df['spot_rate_usd_day'].iloc[-1] - df['spot_rate_usd_day'].iloc[0]:+,.0f}")
            m2.metric("Final Active Fleet", 
                       f"{df['total_active_vessels'].iloc[-1]} vessels",
                       f"{df['total_active_vessels'].iloc[-1] - df['total_active_vessels'].iloc[0]:+d}")
            m3.metric("Max Storage Vessels", 
                       f"{df['total_storage_vessels'].max():.0f}")
            m4.metric("Peak Orderbook", 
                       f"{df['orderbook_count'].max():.0f}")
            m5.metric("Final S/D Ratio", 
                       f"{df['supply_demand_ratio'].iloc[-1]:.3f}",
                       f"{df['supply_demand_ratio'].iloc[-1] - 1.0:+.3f}")

            # Mini charts on run page
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(chart_freight_market(df), use_container_width=True)
            with c2:
                st.plotly_chart(chart_fleet_composition(df), use_container_width=True)

    # ── FLEET SETUP TAB ──────────────────────────────────────────────────────
    with tab_fleet:
        st.markdown("### Ship Type Parameters")
        st.caption("Technical and economic parameters for each vessel class.")
        
        ship_data = []
        for st_name, st_obj in DEFAULT_SHIP_TYPES.items():
            ship_data.append({
                "Type": st_name,
                "DWT": f"{st_obj.dwt/1000:.0f}k",
                "Speed (kn)": st_obj.speed_knots,
                "OpEx ($/d)": f"${st_obj.daily_opex:,.0f}",
                "Fuel (t/d)": st_obj.fuel_consumption_tons_day,
                "Build ($M)": f"${st_obj.build_cost_musd:.0f}M",
                "Life (yr)": st_obj.economic_life_years,
                "Build Lag": st_obj.build_time_years,
                "FSO-capable": "✓" if st_obj.can_be_storage else "—",
            })
        st.dataframe(pd.DataFrame(ship_data).set_index("Type"), use_container_width=True)

        st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
        
        st.markdown("### Company Supply Parameters")
        comp_data = []
        for c_name, c_obj in DEFAULT_COMPANIES.items():
            comp_data.append({
                "Company": c_name,
                "Base Supply (MT)": c_obj.base_supply_tons,
                "Growth %/yr": f"{c_obj.supply_growth_rate*100:.1f}%",
                "Volatility": f"{c_obj.supply_volatility*100:.0f}%",
                "WTP ($/d)": f"${c_obj.wtp_spot:,}",
                "Contract %": f"{c_obj.contract_fraction*100:.0f}%",
                "Home Region": c_obj.home_region,
            })
        st.dataframe(pd.DataFrame(comp_data).set_index("Company"), use_container_width=True)

        st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
        
        st.markdown("### Region Parameters")
        reg_data = []
        for r_name, r_obj in DEFAULT_REGIONS.items():
            reg_data.append({
                "Region": r_name,
                "Base Demand (MT)": r_obj.base_demand_tons,
                "Growth %/yr": f"{r_obj.demand_growth_rate*100:.1f}%",
                "Volatility": f"{r_obj.demand_volatility*100:.0f}%",
                "Storage Cap (MT)": r_obj.storage_capacity,
                "Port Cap (vessels)": r_obj.port_capacity,
            })
        st.dataframe(pd.DataFrame(reg_data).set_index("Region"), use_container_width=True)

    # ── RESULTS TAB ──────────────────────────────────────────────────────────
    with tab_results:
        if "results" not in st.session_state:
            st.info("Run the simulation first to see results.")
        else:
            df = st.session_state["results"]
            df_all = st.session_state.get("results_all", df)
            n_runs = st.session_state.get("n_runs", 1)

            st.markdown("### Freight Market")
            st.plotly_chart(chart_freight_market(df), use_container_width=True)

            st.markdown("### Oil Supply / Demand Balance")
            st.plotly_chart(chart_oil_balance(df), use_container_width=True)

            st.markdown("### Fleet Composition Dynamics")
            st.plotly_chart(chart_fleet_composition(df), use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### Regional Demand")
                st.plotly_chart(chart_regional_demand(df), use_container_width=True)
            with col2:
                st.markdown("### Company Supply Stack")
                st.plotly_chart(chart_company_supply(df), use_container_width=True)

            # Monte Carlo uncertainty bands (if >1 run)
            if n_runs > 1:
                st.markdown("### Monte Carlo — Spot Rate Uncertainty")
                pivot = df_all.pivot(index="year", columns="run", values="spot_rate_usd_day")
                fig_mc = go.Figure()
                fig_mc.add_trace(go.Scatter(
                    x=pivot.index,
                    y=pivot.quantile(0.9, axis=1),
                    mode="lines", line=dict(width=0),
                    showlegend=False, name="P90"
                ))
                fig_mc.add_trace(go.Scatter(
                    x=pivot.index,
                    y=pivot.quantile(0.1, axis=1),
                    mode="lines", line=dict(width=0),
                    fill="tonexty", fillcolor="rgba(0,212,255,0.15)",
                    name="P10-P90 band"
                ))
                fig_mc.add_trace(go.Scatter(
                    x=pivot.index, y=pivot.median(axis=1),
                    mode="lines", line=dict(color="#00d4ff", width=2),
                    name="Median"
                ))
                fig_mc.update_layout(**PLOTLY_LAYOUT, height=320,
                                      title_text=f"Spot Rate Distribution ({n_runs} runs)")
                st.plotly_chart(fig_mc, use_container_width=True)

            st.markdown("### Raw Data")
            st.dataframe(df.set_index("year").round(2), use_container_width=True)
            
            csv = df.to_csv(index=False).encode()
            st.download_button("⬇ Download CSV", csv, "maritime_sim_results.csv",
                                "text/csv", use_container_width=False)

    # ── ABOUT TAB ────────────────────────────────────────────────────────────
    with tab_about:
        st.markdown("""
### Model Architecture

This simulation implements a **system dynamics approach** to the global tanker market,
closely following the stock-flow framework of Engelen, Meersman & Van de Voorde (2006).

#### Two Equilibria

**1. Oil Supply/Demand Equilibrium**  
Each period, regional demand grows stochastically around a trend. Company supply
responds to growth and noise. Excess supply accumulates in land-based or floating
storage; excess demand draws inventories down. This feeds back into the freight market
through cargo volumes.

**2. Vessel Supply/Demand Equilibrium**  
Effective cargo demand (in ton-miles) is matched against active fleet capacity.
A load-factor calculation drives the spot rate via a nonlinear tanh adjustment.
Spot rate deviations from long-run marginal cost trigger:
- **Ordering** (positive signal → newbuildings enter pipeline with build lag)
- **Scrapping** (negative signal → oldest/cheapest-to-scrap vessels exit)
- **Storage conversion** (supply glut → VLCCs/Suezmaxes become FSOs)

#### Structural Regime Changes (Extensions beyond Engelen et al.)

| Regime | Mechanism |
|--------|-----------|
| IMO 2020 sulfur cap | Fuel premium increases OpEx for non-scrubber vessels → shifts LRMC → ordering/scrapping threshold moves |
| Geopolitical sanctions | Hard reduction in target region demand & linked company supply → network topology shift |
| COVID-like demand shock | Sinusoidal demand collapse over configurable duration → rate crash → accelerated scrapping |

#### Stock-Flow Structure

```
Orderbook ──(build lag)──▶ Active Fleet ──(low rates)──▶ Scrapped
                                  │
                         (supply glut)
                                  ▼
                          FSO/Storage Fleet
                                  │
                         (market tightens)
                                  ▼
                          Back to Active
```

#### References
- Engelen, S., Meersman, H., & Van de Voorde, E.V.D. (2006). *Using system dynamics in maritime economics: an endogenous decision model for shipowners in the dry bulk sector.* Maritime Policy & Management.
- Pantuso et al. (2014). Fleet size and mix survey.
- Scarsi (2007). Bulk shipping market cycles and behavioral biases.
        """)


if __name__ == "__main__":
    main()
