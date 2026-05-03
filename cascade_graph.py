"""
cascade_graph.py
Builds and queries the directed cascade network from DisasterEvent objects.
"""

import networkx as nx
from itertools import combinations
from disaster_event import DisasterEvent


class CascadeGraph:
    """
    Directed graph where nodes are DisasterEvents and edges represent
    plausible causal cascade links (trigger → result).

    Uses NetworkX DiGraph under the hood so all nx algorithms are available.
    """

    def __init__(self):
        self.graph  = nx.DiGraph()
        self.events: dict[str, DisasterEvent] = {}

    # ------------------------------------------------------------------
    # Building the graph
    # ------------------------------------------------------------------

    def add_event(self, event: DisasterEvent) -> None:
        """Add a single DisasterEvent as a node."""
        self.events[event.event_id] = event
        self.graph.add_node(
            event.event_id,
            event_type     = event.event_type,
            county         = event.county,
            start_date     = event.start_date,
            end_date       = event.end_date,
            severity_score = event.severity_score,
            lat            = event.latitude,
            lon            = event.longitude,
        )

    def add_events(self, events: list[DisasterEvent]) -> None:
        """Bulk-add a list of DisasterEvent objects."""
        for e in events:
            self.add_event(e)

    def build_edges(self, verbose: bool = False) -> int:
        """
        Evaluate all ordered pairs of events and add edges where
        event_a.could_trigger(event_b) is True.

        This is O(n²) — fine for California 2010–2025 (~thousands of events).
        Returns the number of edges added.
        """
        event_list = sorted(self.events.values(), key=lambda e: e.start_date)
        n = len(event_list)
        edges_added = 0

        for i in range(n):
            for j in range(i + 1, n):
                a = event_list[i]
                b = event_list[j]
                if a.could_trigger(b):
                    weight = a.edge_weight(b)
                    self.graph.add_edge(
                        a.event_id, b.event_id,
                        weight        = weight,
                        days_gap      = (b.start_date - a.end_date).days,
                        distance_km   = round(a.distance_km(b), 1),
                    )
                    edges_added += 1
                    if verbose:
                        print(f"  EDGE: {a.event_type} ({a.county}) → {b.event_type} ({b.county})")

        print(f"Built {edges_added} cascade edges across {n} events.")
        return edges_added

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def find_cascade_path(
        self,
        start_id: str,
        end_id:   str,
    ) -> list[DisasterEvent] | None:
        """
        Find the shortest cascade path between two events.
        Returns list of DisasterEvent objects, or None if no path exists.
        """
        try:
            path_ids = nx.shortest_path(self.graph, start_id, end_id)
            return [self.events[eid] for eid in path_ids]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_all_cascades_from(self, event_id: str) -> list[list[DisasterEvent]]:
        """
        Return all simple paths (cascade chains) originating from event_id.
        Paths are sorted by length (longest first).
        """
        if event_id not in self.graph:
            return []
        descendants = nx.descendants(self.graph, event_id)
        paths = []
        for desc_id in descendants:
            for path_ids in nx.all_simple_paths(self.graph, event_id, desc_id):
                paths.append([self.events[eid] for eid in path_ids])
        paths.sort(key=len, reverse=True)
        return paths

    def get_trigger_events(self) -> list[DisasterEvent]:
        """
        Return events with no incoming edges — cascade originators.
        These are the 'first dominoes' in the network.
        """
        return [
            self.events[nid]
            for nid in self.graph.nodes
            if self.graph.in_degree(nid) == 0
        ]

    def get_cascade_depth(self, event_id: str) -> int:
        """
        Count the longest downstream chain from this event.
        (Longest path to any reachable descendant.)
        """
        if event_id not in self.graph:
            return 0
        descendants = list(nx.descendants(self.graph, event_id))
        if not descendants:
            return 0
        try:
            return max(
                len(nx.shortest_path(self.graph, event_id, d)) - 1
                for d in descendants
            )
        except nx.NetworkXNoPath:
            return 0

    def rank_by_cascade_potential(self, top_n: int = 20) -> list[tuple[DisasterEvent, int]]:
        """
        Rank events by how many downstream events they (directly or indirectly) triggered.
        Returns list of (DisasterEvent, downstream_count) tuples, sorted descending.
        """
        scored = []
        for nid in self.graph.nodes:
            n_downstream = len(nx.descendants(self.graph, nid))
            scored.append((self.events[nid], n_downstream))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def filter_by_type(self, event_type: str) -> "CascadeGraph":
        """
        Return a new CascadeGraph containing only events of the given type
        AND their immediate cascade neighbors (for context).
        """
        subgraph = CascadeGraph()
        keep_ids = set()

        for nid, event in self.events.items():
            if event.event_type == event_type:
                keep_ids.add(nid)
                keep_ids.update(self.graph.predecessors(nid))
                keep_ids.update(self.graph.successors(nid))

        for nid in keep_ids:
            subgraph.add_event(self.events[nid])

        for u, v, data in self.graph.edges(data=True):
            if u in keep_ids and v in keep_ids:
                subgraph.graph.add_edge(u, v, **data)

        return subgraph

    def search_events(
        self,
        event_type: str = None,
        county:     str = None,
        year:       int = None,
        min_severity: float = 0,
    ) -> list[DisasterEvent]:
        """
        Search/filter events by type, county, year, and minimum severity.
        All filters are optional and combined with AND logic.
        """
        results = list(self.events.values())

        if event_type:
            results = [e for e in results if e.event_type.lower() == event_type.lower()]
        if county:
            results = [e for e in results if county.lower() in e.county.lower()]
        if year:
            results = [e for e in results if e.start_date.year == year]
        if min_severity > 0:
            results = [e for e in results if e.severity_score >= min_severity]

        return sorted(results, key=lambda e: e.start_date)

    # ------------------------------------------------------------------
    # Graph statistics
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a dict of key graph statistics."""
        return {
            "n_events":         self.graph.number_of_nodes(),
            "n_edges":          self.graph.number_of_edges(),
            "n_trigger_events": len(self.get_trigger_events()),
            "avg_out_degree":   round(
                sum(d for _, d in self.graph.out_degree()) / max(self.graph.number_of_nodes(), 1), 2
            ),
            "density":          round(nx.density(self.graph), 5),
            "n_components":     nx.number_weakly_connected_components(self.graph),
        }

    def calculate_centrality(self) -> dict[str, float]:
        """
        Return betweenness centrality scores for all events.
        High centrality = event sits on many cascade paths (a 'linchpin' disaster).
        """
        return nx.betweenness_centrality(self.graph, weight="weight")
