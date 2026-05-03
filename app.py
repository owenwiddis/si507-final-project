"""
app.py  —  Extreme Weather Cascade Explorer
Streamlit dashboard for the California Storm Events cascade graph.

Run:
    cd cascade_project
    streamlit run app.py
"""

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from disaster_event import DisasterEvent, CASCADE_RULES
from cascade_graph import CascadeGraph
from noaa_fetcher import NOAADataFetcher

# ── page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cascade | CA Weather Events",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── design tokens ──────────────────────────────────────────────────────────────
COLORS = {
    "Drought":     "#E86B2E",
    "Wildfire":    "#D94F2B",
    "Flood":       "#2B6CB0",
    "Debris Flow": "#7B5C3E",
    "Landslide":   "#8B7355",
    "Heat Wave":   "#C4821A",
    "High Wind":   "#6B8FA8",
    "Dust Storm":  "#B8A882",
}
DEFAULT_COLOR = "#888"

# ── custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=DM+Sans:wght@300;400;500;600&display=swap');

:root {
    --bg:       #0d0f14;
    --surface:  #161922;
    --border:   #252a36;
    --text:     #e8eaf0;
    --muted:    #6b7280;
    --accent:   #E8502A;
    --accent2:  #2B88D8;
}

html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'DM Sans', sans-serif;
}

[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] * { color: var(--text) !important; }

h1, h2, h3, h4 {
    font-family: 'Space Mono', monospace !important;
    letter-spacing: -0.02em;
}

.stSelectbox > div > div,
.stMultiSelect > div > div,
.stSlider > div {
    background: var(--surface) !important;
    border-color: var(--border) !important;
}

.metric-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent);
}
.metric-val {
    font-family: 'Space Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
    color: var(--text);
    line-height: 1;
}
.metric-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-top: 6px;
}

.event-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 10px;
    font-size: 0.88rem;
}
.event-type {
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.cascade-arrow {
    text-align: center;
    color: var(--muted);
    font-size: 1.4rem;
    margin: 2px 0;
}

.section-header {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    margin-bottom: 16px;
}

.about-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent2);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 28px;
    line-height: 1.7;
    font-size: 0.9rem;
    color: #c8cad4;
}
.about-box b { color: var(--text); }

div[data-testid="stTabs"] button {
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
}

[data-testid="stMarkdownContainer"] p { color: var(--text); }

.stButton > button {
    background: var(--accent) !important;
    color: white !important;
    border: none !important;
    border-radius: 4px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.05em !important;
}
.stButton > button:hover { opacity: 0.85; }
</style>
""", unsafe_allow_html=True)


# ── data loading ───────────────────────────────────────────────────────────────

@st.cache_resource
def load_graph() -> CascadeGraph:
    fetcher = NOAADataFetcher(cache_dir="data/raw", state="CA")
    events  = fetcher.fetch_events(start_year=2010, end_year=2025)
    g = CascadeGraph()
    g.add_events(events)
    g.build_edges()
    return g


# ── helpers ─────────────────────────────────────────────────────────────────────

def fmt_damage(v: float) -> str:
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    if v >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def color(event_type: str) -> str:
    return COLORS.get(event_type, DEFAULT_COLOR)


# ── network figure ──────────────────────────────────────────────────────────────

def build_network_figure(g: CascadeGraph, highlight_path: list = None, filter_type: str = None) -> go.Figure:
    graph = g.graph

    if filter_type and filter_type != "All":
        sub = g.filter_by_type(filter_type)
        graph = sub.graph
        events = sub.events
    else:
        events = g.events

    if graph.number_of_nodes() == 0:
        return go.Figure()

    pos = nx.spring_layout(graph, seed=42, k=2.5)

    highlight_ids = set()
    if highlight_path:
        highlight_ids = {e.event_id for e in highlight_path}

    edge_x, edge_y = [], []
    edge_x_hl, edge_y_hl = [], []

    for u, v in graph.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        in_path = u in highlight_ids and v in highlight_ids
        target_x = edge_x_hl if in_path else edge_x
        target_y = edge_y_hl if in_path else edge_y
        target_x += [x0, x1, None]
        target_y += [y0, y1, None]

    traces = []

    if edge_x:
        traces.append(go.Scatter(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(width=0.6, color="#2a3045"),
            hoverinfo="none", showlegend=False,
        ))

    if edge_x_hl:
        traces.append(go.Scatter(
            x=edge_x_hl, y=edge_y_hl, mode="lines",
            line=dict(width=2.5, color="#E8502A"),
            hoverinfo="none", showlegend=False,
        ))

    node_x, node_y, node_colors, node_sizes, node_hover = [], [], [], [], []
    for nid in graph.nodes():
        evt = events[nid]
        x, y = pos[nid]
        node_x.append(x); node_y.append(y)
        c = color(evt.event_type)
        if highlight_ids and nid not in highlight_ids:
            c = "#1e2230"
        node_colors.append(c)
        base_size = 8 + evt.severity_score * 0.18
        node_sizes.append(base_size * 1.6 if nid in highlight_ids else base_size)
        dmg = fmt_damage(evt.damage_property + evt.damage_crops)
        deaths = evt.deaths_direct + evt.deaths_indirect
        node_hover.append(
            f"<b>{evt.event_type}</b><br>"
            f"{evt.county} County<br>"
            f"{evt.start_date.strftime('%b %Y')}<br>"
            f"Severity: {evt.severity_score:.0f}/100<br>"
            f"Deaths: {deaths} | Damage: {dmg}"
        )

    traces.append(go.Scatter(
        x=node_x, y=node_y,
        mode="markers",
        marker=dict(
            size=node_sizes, color=node_colors,
            line=dict(width=1, color="#0d0f14"),
        ),
        hovertext=node_hover,
        hoverinfo="text",
        showlegend=False,
    ))

    fig = go.Figure(traces)
    fig.update_layout(
        paper_bgcolor="#0d0f14",
        plot_bgcolor="#0d0f14",
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=520,
        hoverlabel=dict(
            bgcolor="#161922", bordercolor="#252a36",
            font=dict(family="DM Sans", color="#e8eaf0"),
        ),
    )
    return fig


def build_timeline_figure(g: CascadeGraph, filter_type: str = None) -> go.Figure:
    events = list(g.events.values())
    if filter_type and filter_type != "All":
        events = [e for e in events if e.event_type == filter_type]
    events.sort(key=lambda e: e.start_date)

    fig = go.Figure()
    for i, evt in enumerate(events):
        end = evt.end_date if evt.end_date > evt.start_date else datetime(
            evt.end_date.year, evt.end_date.month, evt.end_date.day, 23, 59)
        dmg = fmt_damage(evt.damage_property)
        fig.add_trace(go.Scatter(
            x=[evt.start_date, end],
            y=[i, i],
            mode="lines",
            line=dict(color=color(evt.event_type), width=6),
            hovertext=(
                f"<b>{evt.event_type}</b> — {evt.county}<br>"
                f"{evt.start_date.strftime('%b %d, %Y')} -> {end.strftime('%b %d, %Y')}<br>"
                f"Severity: {evt.severity_score:.0f} | Damage: {dmg}"
            ),
            hoverinfo="text",
            showlegend=False,
        ))

    fig.update_layout(
        paper_bgcolor="#0d0f14", plot_bgcolor="#161922",
        xaxis=dict(color="#6b7280", gridcolor="#252a36", title=""),
        yaxis=dict(showticklabels=False, gridcolor="#252a36"),
        margin=dict(l=0, r=0, t=10, b=0),
        height=420,
        hoverlabel=dict(
            bgcolor="#161922", bordercolor="#252a36",
            font=dict(family="DM Sans", color="#e8eaf0"),
        ),
    )
    return fig


def build_severity_bar(g: CascadeGraph) -> go.Figure:
    ranked = sorted(g.events.values(), key=lambda e: e.severity_score, reverse=True)[:15]
    fig = go.Figure(go.Bar(
        x=[e.severity_score for e in ranked],
        y=[f"{e.county} {e.start_date.year}" for e in ranked],
        orientation="h",
        marker_color=[color(e.event_type) for e in ranked],
        hovertext=[
            f"{e.event_type} — {e.county}<br>Severity: {e.severity_score:.0f}<br>Damage: {fmt_damage(e.damage_property)}"
            for e in ranked
        ],
        hoverinfo="text",
    ))
    fig.update_layout(
        paper_bgcolor="#0d0f14", plot_bgcolor="#161922",
        xaxis=dict(color="#6b7280", gridcolor="#252a36", title="Severity Score"),
        yaxis=dict(color="#e8eaf0", tickfont=dict(size=11)),
        margin=dict(l=0, r=0, t=0, b=0),
        height=420,
        hoverlabel=dict(bgcolor="#161922", bordercolor="#252a36",
                        font=dict(family="DM Sans", color="#e8eaf0")),
    )
    return fig


# ── sidebar ─────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## CASCADE")
    st.markdown("<p style='color:#6b7280;font-size:0.8rem;margin-top:-12px;font-family:Space Mono'>CA Weather Event Network</p>", unsafe_allow_html=True)
    st.divider()

    st.markdown("<div class='section-header'>Filter</div>", unsafe_allow_html=True)

    filter_type = st.selectbox(
        "Event type",
        ["All"] + sorted(COLORS.keys()),
        index=0,
    )

    year_range = st.slider("Year range", 2010, 2025, (2010, 2025))
    min_severity = st.slider("Min severity", 0, 100, 0, step=5)

    st.divider()
    st.markdown("<div class='section-header'>Cascade Path Finder</div>", unsafe_allow_html=True)

    with st.spinner("Loading NOAA data..."):
        g = load_graph()

    all_events = sorted(g.events.values(), key=lambda e: e.start_date)
    event_labels = {
        f"{e.county} {e.start_date.strftime('%b %Y')} [{e.event_type}]": e.event_id
        for e in all_events
    }
    labels = list(event_labels.keys())

    src_label = st.selectbox("From", labels, index=0)
    dst_label = st.selectbox("To",   labels, index=min(5, len(labels)-1))

    find_path = st.button("Find Cascade Path")


# ── filter ────────────────────────────────────────────────────────────────────

filtered_events = [
    e for e in g.events.values()
    if year_range[0] <= e.start_date.year <= year_range[1]
    and e.severity_score >= min_severity
    and (filter_type == "All" or e.event_type == filter_type)
]

# ── header ────────────────────────────────────────────────────────────────────

st.markdown("# EXTREME WEATHER CASCADE EXPLORER")
st.markdown("<p style='color:#6b7280;margin-top:-12px'>California · 2010 – 2025 · NOAA Storm Events</p>", unsafe_allow_html=True)

# ── about ─────────────────────────────────────────────────────────────────────

st.markdown("""
<div class='about-box'>
    <b>What this tool does:</b> This dashboard models California climate disasters not as isolated incidents,
    but as a <b>cascade network</b> — where one event creates the physical conditions for the next.
    A multi-year drought desiccates vegetation, enabling wildfires that destabilize hillsides,
    which then collapse into debris flows and floods after rain. Each arrow in the network represents
    a plausible causal link derived from three criteria: event type compatibility, geographic proximity
    (&lt;150 km), and temporal window (type-specific, e.g. wildfire to debris flow within 2 years).<br><br>
    <b>Why it matters:</b> Traditional disaster databases — including NOAA's — treat every event as an
    independent row. That structure obscures compounding risk. Emergency planners, climate researchers,
    and infrastructure managers need to understand that a single drought can trigger a 5-event chain
    spanning years and counties. Visualizing these feedback loops is a first step toward building
    climate adaptation strategies that account for cascading, not just individual, hazards.
</div>
""", unsafe_allow_html=True)

# ── metrics ───────────────────────────────────────────────────────────────────

summary = g.summary()
total_deaths = sum(e.deaths_direct + e.deaths_indirect for e in g.events.values())
total_damage = sum(e.damage_property + e.damage_crops for e in g.events.values())

m1, m2, m3, m4, m5 = st.columns(5)
for col, val, label in [
    (m1, summary["n_events"],          "Events"),
    (m2, summary["n_edges"],           "Cascade Links"),
    (m3, summary["n_trigger_events"],  "Chain Origins"),
    (m4, total_deaths,                 "Total Deaths"),
    (m5, fmt_damage(total_damage),     "Total Damage"),
]:
    with col:
        st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-val'>{val}</div>
            <div class='metric-label'>{label}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── cascade path result ───────────────────────────────────────────────────────

cascade_path = None

if find_path:
    src_id = event_labels[src_label]
    dst_id = event_labels[dst_label]
    cascade_path = g.find_cascade_path(src_id, dst_id)

    if cascade_path:
        st.markdown("### Cascade Path Found")
        path_cols = st.columns(len(cascade_path) * 2 - 1)
        for i, evt in enumerate(cascade_path):
            with path_cols[i * 2]:
                dmg = fmt_damage(evt.damage_property)
                c = color(evt.event_type)
                st.markdown(f"""
                <div class='event-card' style='border-left-color:{c}'>
                    <div class='event-type' style='color:{c}'>{evt.event_type}</div>
                    <div style='font-weight:600;margin:4px 0'>{evt.county} County</div>
                    <div style='color:#6b7280;font-size:0.8rem'>{evt.start_date.strftime('%b %Y')}</div>
                    <div style='margin-top:8px;font-size:0.8rem'>
                        Severity <b>{evt.severity_score:.0f}</b> · {dmg}
                    </div>
                </div>""", unsafe_allow_html=True)
            if i < len(cascade_path) - 1:
                with path_cols[i * 2 + 1]:
                    st.markdown("<div class='cascade-arrow' style='margin-top:40px'>-></div>",
                                unsafe_allow_html=True)
    else:
        st.info("No cascade path found between those two events. They may not be causally connected.")

# ── tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(["Network", "Timeline", "Severity", "Top Cascades"])

with tab1:
    st.markdown("<div class='section-header'>Cascade Network — nodes sized by severity, edges = causal links</div>",
                unsafe_allow_html=True)
    fig_net = build_network_figure(g, cascade_path, filter_type)
    st.plotly_chart(fig_net, use_container_width=True)

    leg_cols = st.columns(len(COLORS))
    for col, (etype, ec) in zip(leg_cols, COLORS.items()):
        with col:
            st.markdown(f"<div style='font-size:0.72rem;color:{ec}'>{etype}</div>",
                        unsafe_allow_html=True)

with tab2:
    st.markdown("<div class='section-header'>Event Timeline — hover for details</div>",
                unsafe_allow_html=True)
    st.plotly_chart(build_timeline_figure(g, filter_type), use_container_width=True)

with tab3:
    st.markdown("<div class='section-header'>Top 15 Events by Severity Score</div>",
                unsafe_allow_html=True)
    st.plotly_chart(build_severity_bar(g), use_container_width=True)

with tab4:
    st.markdown("<div class='section-header'>Events Ranked by Cascade Potential</div>",
                unsafe_allow_html=True)
    ranked = g.rank_by_cascade_potential(top_n=15)
    if ranked:
        df = pd.DataFrame([{
            "Event Type":        e.event_type,
            "County":            e.county,
            "Year":              e.start_date.year,
            "Severity":          f"{e.severity_score:.0f}",
            "Downstream Events": count,
            "Damage":            fmt_damage(e.damage_property),
        } for e, count in ranked])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No cascade relationships found with current filters.")

# ── event search ──────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### Search Events")
search_cols = st.columns([2, 2, 2])
with search_cols[0]:
    s_type   = st.selectbox("Type", ["(any)"] + sorted(COLORS.keys()), key="s_type")
with search_cols[1]:
    s_county = st.text_input("County (partial)", key="s_county")
with search_cols[2]:
    s_year   = st.number_input("Year (0 = any)", 0, 2030, 0, key="s_year")

results = g.search_events(
    event_type   = None if s_type == "(any)" else s_type,
    county       = s_county or None,
    year         = int(s_year) if s_year else None,
    min_severity = min_severity,
)

if results:
    r_cols = st.columns(3)
    for i, evt in enumerate(results[:12]):
        with r_cols[i % 3]:
            c = color(evt.event_type)
            deaths = evt.deaths_direct + evt.deaths_indirect
            st.markdown(f"""
            <div class='event-card' style='border-left-color:{c}'>
                <div class='event-type' style='color:{c}'>{evt.event_type}</div>
                <div style='font-weight:600;margin:4px 0'>{evt.county} County</div>
                <div style='color:#6b7280;font-size:0.78rem'>
                    {evt.start_date.strftime('%b %d, %Y')} — {evt.end_date.strftime('%b %d, %Y')}
                </div>
                <div style='margin-top:8px;font-size:0.8rem;display:flex;gap:12px'>
                    <span>Severity {evt.severity_score:.0f}</span>
                    <span>Deaths {deaths}</span>
                    <span>{fmt_damage(evt.damage_property)}</span>
                </div>
            </div>""", unsafe_allow_html=True)
elif s_type != "(any)" or s_county or s_year:
    st.info("No events match your search.")
