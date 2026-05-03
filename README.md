# Extreme Weather Cascade Explorer

A network-based tool for modeling how California climate disasters trigger one another — drought enabling wildfire, wildfire destabilizing hillsides for debris flows, floods following in the burn scar. Built on NOAA Storm Events data (2012–2023).

---

## The Problem

Traditional disaster databases — including NOAA's — store each event as an independent row. That structure makes it easy to count droughts or tally wildfire deaths, but it obscures the compounding dynamics that actually drive climate risk. A five-year drought doesn't just cause crop losses; it desiccates vegetation across millions of acres, setting the stage for the next wildfire season. A wildfire doesn't just burn — it strips hillside root systems, priming the slope for debris flows the following winter. Treating these events as independent severely underestimates cascading hazard.

This tool reframes the same NOAA data as a **directed graph**, where nodes are discrete disaster events and edges represent plausible causal links. The goal is to surface the hidden structure of climate cascades that emergency planners, researchers, and infrastructure managers need to see.

---

## How It Works

### Edge Criteria

An edge is drawn from event A to event B if all three conditions hold:

1. **Type compatibility** — B's event type appears in A's cascade rule set (e.g. Drought → Wildfire, Wildfire → Debris Flow). Rules are defined in `src/disaster_event.py`.
2. **Temporal ordering** — B starts after A ends (or after A begins, for persistent conditions like Drought and Heat Wave), within a type-specific maximum lag window (e.g. Wildfire → Debris Flow within 2 years).
3. **Geographic proximity** — the two event centroids are within 150 km of each other.

### Severity Score

Each event is assigned a severity score (0–100) derived from NOAA's reported deaths, injuries, and property/crop damage. Each component is log-scaled to compress outliers, then weighted: damage 50%, deaths 30%, injuries 20%.

### Network Analysis

The graph uses NetworkX under the hood. Cascade potential is measured by counting downstream descendants for each node. Betweenness centrality identifies "linchpin" events — those that sit on many cascade paths.

---

## Project Structure

```
cascade_project/
├── app.py                  # Streamlit dashboard
├── cli.py                  # Command line interface
├── requirements.txt
├── src/
│   ├── disaster_event.py   # DisasterEvent dataclass — node model, edge logic, severity scoring
│   ├── cascade_graph.py    # CascadeGraph — NetworkX wrapper, all queries and rankings
│   ├── noaa_fetcher.py     # NOAADataFetcher — downloads and parses NOAA bulk CSVs
│   └── narrative_generator.py  # (optional) Claude API integration for cascade storytelling
└── tests/
    └── test_cascade.py     # 35-test pytest suite
```

---

## Setup

```bash
pip install -r requirements.txt
```

The demo dataset (26 real California events) is hardcoded and works out of the box. To load real NOAA data for any year range, replace the `load_demo_graph()` function body in `app.py` or `cli.py` with:

```python
from src.noaa_fetcher import NOAADataFetcher
fetcher = NOAADataFetcher(cache_dir="data/raw", state="CA")
events  = fetcher.fetch_events(start_year=2010, end_year=2025)
g = CascadeGraph()
g.add_events(events)
g.build_edges()
```

NOAA data is downloaded as gzipped bulk CSVs and cached locally — no API key required for the bulk files.

---

## Running the Streamlit App

```bash
cd cascade_project
streamlit run app.py
```

Opens at `http://localhost:8501`. The app has four tabs:

- **Network** — force-directed graph of the full cascade network. Nodes are sized by severity score and colored by event type. Use the sidebar path finder to highlight a specific cascade chain in red.
- **Timeline** — Gantt-style view of all events with hover details.
- **Severity** — horizontal bar chart of the top 15 events by severity score.
- **Top Cascades** — table ranking events by how many downstream events they triggered.

Sidebar controls let you filter by event type, year range, and minimum severity. The **Cascade Path Finder** lets you select any two events and find the shortest cascade path between them.

---

## Running the CLI

```bash
cd cascade_project
python cli.py <command> [options]
```

### Commands

**`summary`** — print graph-level statistics

```bash
python cli.py summary
```

**`search`** — find events by type, county, and/or year

```bash
python cli.py search --type Wildfire --county Butte
python cli.py search --year 2018 --min-severity 30
python cli.py search --type Flood --year 2023
```

**`filter`** — filter by type and minimum severity, with aggregate stats and type breakdown

```bash
python cli.py filter --type Wildfire --min-severity 40
python cli.py filter --min-severity 60
```

**`path`** — find the shortest cascade chain between two events by event ID

```bash
python cli.py path --from CA_DROUGHT_2012 --to CA_WILD_2013_A
python cli.py path --from CA_WILD_2018_A --to CA_LAND_2019_A
```

Run `search` first to get valid event IDs.

**`rank`** — rank events by cascade potential (number of downstream events triggered)

```bash
python cli.py rank --top 10
```

---

## Running the Tests

```bash
cd cascade_project
PYTHONPATH=src pytest tests/test_cascade.py -v
```

35 tests covering:

- Severity scoring (zero inputs, damage scaling, death weighting, 0–100 bounds)
- Haversine distance (same location, near events, far events)
- Cascade eligibility — all three conditions tested independently (type compatibility, temporal ordering, geographic proximity)
- Edge weighting
- Graph construction (single events, bulk add, edge building)
- All four query modes (search, filter, path finding, rankings)
- Edge cases (isolated nodes, duplicate IDs, zero-duration events, empty graphs)

---

## Event IDs (Demo Dataset)

| ID | Type | County | Period |
|---|---|---|---|
| CA_DROUGHT_2012 | Drought | Fresno | 2012–2016 |
| CA_WILD_2013_A | Wildfire | Tuolumne | Aug–Oct 2013 |
| CA_WILD_2015_A | Wildfire | Lake | Jul–Oct 2015 |
| CA_WILD_2015_B | Wildfire | Trinity | Sep–Oct 2015 |
| CA_HEAT_2016 | Heat Wave | Fresno | Jul 2016 |
| CA_FLOOD_2017_A | Flood | Butte | Feb 2017 |
| CA_WILD_2017_A | Wildfire | Napa | Oct–Nov 2017 |
| CA_WILD_2017_B | Wildfire | Ventura | Dec 2017–Jan 2018 |
| CA_DEBRIS_2018A | Debris Flow | Santa Barbara | Jan 2018 |
| CA_WILD_2018_A | Wildfire | Butte | Nov 2018 (Camp Fire) |
| CA_FLOOD_2019_A | Flood | Butte | Feb–Mar 2019 |
| CA_LAND_2019_A | Landslide | Butte | Mar 2019 |
| CA_DROUGHT_2020 | Drought | Madera | 2020 |
| CA_HEAT_2020 | Heat Wave | Madera | Aug 2020 |
| CA_WILD_2020_A | Wildfire | Tehama | Aug–Nov 2020 |
| CA_WILD_2020_B | Wildfire | Santa Clara | Sep–Oct 2020 |
| CA_WILD_2020_C | Wildfire | Del Norte | Sep–Nov 2020 |
| CA_WILD_2021_A | Wildfire | Plumas | Jul–Oct 2021 (Dixie) |
| CA_WILD_2021_B | Wildfire | El Dorado | Aug–Sep 2021 (Caldor) |
| CA_DEBRIS_2021A | Debris Flow | Marin | Oct 2021 |
| CA_FLOOD_2021_A | Flood | Sonoma | Oct–Nov 2021 |
| CA_WIND_2021_A | High Wind | Sonoma | Oct 2021 |
| CA_FLOOD_2023_A | Flood | Monterey | Jan 2023 |
| CA_LAND_2023_A | Landslide | Monterey | Jan 2023 |
| CA_DEBRIS_2023A | Debris Flow | Los Angeles | Mar 2023 |
| CA_FLOOD_2023_B | Flood | Alameda | Mar 2023 |
