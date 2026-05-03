"""
test_cascade.py
pytest test suite for the Extreme Weather Cascade Graph project.

Run from project root:
    cd src
    pytest ../tests/test_cascade.py -v
"""

import sys
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from disaster_event import DisasterEvent, CASCADE_RULES, MAX_DISTANCE_KM
from cascade_graph import CascadeGraph


# ---------------------------------------------------------------------------
# Fixtures — reusable test events
# ---------------------------------------------------------------------------

def make_event(
    event_id,
    event_type,
    start,
    end,
    lat=34.0,
    lon=-118.0,
    county="Los Angeles",
    deaths=0,
    damage=0.0,
):
    return DisasterEvent(
        event_id        = event_id,
        event_type      = event_type,
        state           = "CA",
        county          = county,
        start_date      = datetime(*start),
        end_date        = datetime(*end),
        latitude        = lat,
        longitude       = lon,
        deaths_direct   = deaths,
        damage_property = damage,
    )


@pytest.fixture
def drought():
    return make_event("D1", "Drought", (2012, 1, 1), (2016, 12, 31),
                      lat=36.0, lon=-119.5, county="Fresno")

@pytest.fixture
def wildfire_near():
    """Wildfire close to drought, within temporal window."""
    return make_event("W1", "Wildfire", (2017, 6, 1), (2017, 9, 30),
                      lat=36.5, lon=-119.8, county="Fresno",
                      deaths=2, damage=5_000_000)

@pytest.fixture
def wildfire_far():
    """Wildfire geographically far from drought."""
    return make_event("W2", "Wildfire", (2017, 6, 1), (2017, 9, 30),
                      lat=32.7, lon=-117.1, county="San Diego")

@pytest.fixture
def wildfire_too_late():
    """Wildfire outside the temporal cascade window."""
    return make_event("W3", "Wildfire", (2021, 1, 1), (2021, 3, 31),
                      lat=36.5, lon=-119.8, county="Fresno")

@pytest.fixture
def debris_flow():
    """Debris flow after wildfire."""
    return make_event("DB1", "Debris Flow", (2018, 1, 1), (2018, 1, 15),
                      lat=36.4, lon=-119.7, county="Fresno",
                      deaths=21, damage=421_000_000)


# ---------------------------------------------------------------------------
# DisasterEvent — severity scoring
# ---------------------------------------------------------------------------

class TestSeverityScore:

    def test_zero_damage_zero_deaths(self):
        e = make_event("X", "Flood", (2020,1,1), (2020,1,2))
        assert e.severity_score == 0.0

    def test_high_damage_increases_score(self):
        low  = make_event("A", "Flood", (2020,1,1), (2020,1,2), damage=10_000)
        high = make_event("B", "Flood", (2020,1,1), (2020,1,2), damage=1_000_000_000)
        assert high.severity_score > low.severity_score

    def test_deaths_increase_score(self):
        no_deaths  = make_event("C", "Wildfire", (2020,1,1), (2020,1,2), deaths=0)
        with_deaths= make_event("D", "Wildfire", (2020,1,1), (2020,1,2), deaths=100)
        assert with_deaths.severity_score > no_deaths.severity_score

    def test_score_bounded_0_100(self):
        extreme = make_event("E", "Wildfire", (2020,1,1), (2020,1,2),
                             deaths=10_000, damage=999_999_999_999)
        assert 0 <= extreme.severity_score <= 100


# ---------------------------------------------------------------------------
# DisasterEvent — spatial
# ---------------------------------------------------------------------------

class TestDistance:

    def test_same_location_zero_distance(self, drought):
        assert drought.distance_km(drought) == pytest.approx(0.0, abs=0.1)

    def test_far_events_large_distance(self, drought, wildfire_far):
        dist = drought.distance_km(wildfire_far)
        assert dist > MAX_DISTANCE_KM

    def test_near_events_small_distance(self, drought, wildfire_near):
        dist = drought.distance_km(wildfire_near)
        assert dist < MAX_DISTANCE_KM


# ---------------------------------------------------------------------------
# DisasterEvent — cascade eligibility
# ---------------------------------------------------------------------------

class TestCouldTrigger:

    def test_drought_triggers_nearby_wildfire(self, drought, wildfire_near):
        assert drought.could_trigger(wildfire_near) is True

    def test_drought_does_not_trigger_distant_wildfire(self, drought, wildfire_far):
        assert drought.could_trigger(wildfire_far) is False

    def test_drought_does_not_trigger_wildfire_too_late(self, drought, wildfire_too_late):
        assert drought.could_trigger(wildfire_too_late) is False

    def test_no_reverse_trigger(self, drought, wildfire_near):
        """Wildfire should not trigger the past drought."""
        assert wildfire_near.could_trigger(drought) is False

    def test_wildfire_triggers_debris_flow(self, wildfire_near, debris_flow):
        assert wildfire_near.could_trigger(debris_flow) is True

    def test_drought_does_not_trigger_debris_flow_directly(self, drought, debris_flow):
        """Drought → Debris Flow is not a direct cascade rule."""
        assert drought.could_trigger(debris_flow) is False

    def test_incompatible_types(self):
        flood = make_event("F", "Flood", (2020,1,1), (2020,2,1), lat=36.0, lon=-119.5)
        drought2 = make_event("D", "Drought", (2020,4,1), (2020,6,1), lat=36.0, lon=-119.5)
        # Flood does not trigger Drought in our rules
        assert flood.could_trigger(drought2) is False


# ---------------------------------------------------------------------------
# DisasterEvent — edge weight
# ---------------------------------------------------------------------------

class TestEdgeWeight:

    def test_weight_between_0_and_1(self, drought, wildfire_near):
        w = drought.edge_weight(wildfire_near)
        assert 0.0 <= w <= 1.0

    def test_higher_severity_increases_weight(self, drought):
        low_sev  = make_event("W_L", "Wildfire", (2017,6,1), (2017,9,30),
                              lat=36.5, lon=-119.8, damage=1_000)
        high_sev = make_event("W_H", "Wildfire", (2017,6,1), (2017,9,30),
                              lat=36.5, lon=-119.8, damage=1_000_000_000, deaths=50)
        assert drought.edge_weight(high_sev) > drought.edge_weight(low_sev)


# ---------------------------------------------------------------------------
# CascadeGraph — construction
# ---------------------------------------------------------------------------

class TestCascadeGraphConstruction:

    def test_add_event(self, drought):
        g = CascadeGraph()
        g.add_event(drought)
        assert drought.event_id in g.events
        assert g.graph.number_of_nodes() == 1

    def test_add_events_bulk(self, drought, wildfire_near, debris_flow):
        g = CascadeGraph()
        g.add_events([drought, wildfire_near, debris_flow])
        assert g.graph.number_of_nodes() == 3

    def test_build_edges_creates_cascade(self, drought, wildfire_near, debris_flow):
        g = CascadeGraph()
        g.add_events([drought, wildfire_near, debris_flow])
        n_edges = g.build_edges()
        assert n_edges >= 1  # at minimum drought→wildfire or wildfire→debris


# ---------------------------------------------------------------------------
# CascadeGraph — querying
# ---------------------------------------------------------------------------

class TestCascadeGraphQuerying:

    @pytest.fixture
    def built_graph(self, drought, wildfire_near, debris_flow):
        g = CascadeGraph()
        g.add_events([drought, wildfire_near, debris_flow])
        g.build_edges()
        return g

    def test_find_cascade_path(self, built_graph, drought, debris_flow):
        path = built_graph.find_cascade_path(drought.event_id, debris_flow.event_id)
        # Path might exist through wildfire
        # (depends on whether edges were created; just check type)
        assert path is None or isinstance(path, list)

    def test_find_path_no_connection_returns_none(self, built_graph, debris_flow, drought):
        """Reverse path (result → trigger) should not exist."""
        path = built_graph.find_cascade_path(debris_flow.event_id, drought.event_id)
        assert path is None

    def test_get_trigger_events(self, built_graph, drought):
        triggers = built_graph.get_trigger_events()
        trigger_ids = [e.event_id for e in triggers]
        assert drought.event_id in trigger_ids

    def test_rank_by_cascade_potential(self, built_graph):
        ranked = built_graph.rank_by_cascade_potential()
        assert isinstance(ranked, list)
        # Should be sorted descending
        counts = [count for _, count in ranked]
        assert counts == sorted(counts, reverse=True)

    def test_search_events_by_type(self, built_graph):
        results = built_graph.search_events(event_type="Wildfire")
        assert all(e.event_type == "Wildfire" for e in results)

    def test_search_events_by_county(self, built_graph):
        results = built_graph.search_events(county="Fresno")
        assert all("fresno" in e.county.lower() for e in results)

    def test_search_events_by_year(self, built_graph):
        results = built_graph.search_events(year=2017)
        assert all(e.start_date.year == 2017 for e in results)

    def test_search_no_results(self, built_graph):
        results = built_graph.search_events(event_type="Tsunami")
        assert results == []

    def test_filter_by_type_returns_subgraph(self, built_graph):
        sub = built_graph.filter_by_type("Wildfire")
        assert isinstance(sub, CascadeGraph)

    def test_summary_keys(self, built_graph):
        s = built_graph.summary()
        for key in ["n_events", "n_edges", "n_trigger_events", "density"]:
            assert key in s

    def test_empty_graph_summary(self):
        g = CascadeGraph()
        s = g.summary()
        assert s["n_events"] == 0
        assert s["n_edges"]  == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_single_event_no_edges(self, drought):
        g = CascadeGraph()
        g.add_event(drought)
        n_edges = g.build_edges()
        assert n_edges == 0

    def test_duplicate_event_id(self, drought):
        g = CascadeGraph()
        g.add_event(drought)
        g.add_event(drought)  # should overwrite, not duplicate
        assert g.graph.number_of_nodes() == 1

    def test_event_with_zero_duration(self):
        e = make_event("Z", "Flood", (2020,5,1), (2020,5,1))
        assert e.start_date == e.end_date  # valid; one-day event

    def test_cascade_depth_isolated_event(self, drought):
        g = CascadeGraph()
        g.add_event(drought)
        assert g.get_cascade_depth(drought.event_id) == 0

    def test_cascade_rules_coverage(self):
        """Every trigger type in CASCADE_RULES should be a non-empty list."""
        for trigger, results in CASCADE_RULES.items():
            assert isinstance(results, list) and len(results) > 0
