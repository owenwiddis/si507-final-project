"""
cli.py  —  Extreme Weather Cascade Explorer (Command Line Interface)

Usage:
    python cli.py search   --type Wildfire --county Butte --year 2018
    python cli.py filter   --type Wildfire --min-severity 40
    python cli.py path     --from <event_id> --to <event_id>
    python cli.py rank     --top 10
    python cli.py summary
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from disaster_event import DisasterEvent
from cascade_graph import CascadeGraph
from noaa_fetcher import NOAADataFetcher


# ── data loading ───────────────────────────────────────────────────────────────

def build_graph() -> CascadeGraph:
    fetcher = NOAADataFetcher(cache_dir="data/raw", state="CA")
    events  = fetcher.fetch_events(start_year=2010, end_year=2025)
    g = CascadeGraph()
    g.add_events(events)
    g.build_edges()
    return g


# ── formatting helpers ─────────────────────────────────────────────────────────

def fmt_damage(v: float) -> str:
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    if v >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:.0f}"

def fmt_event(e: DisasterEvent, show_id: bool = False) -> str:
    deaths = e.deaths_direct + e.deaths_indirect
    dmg    = fmt_damage(e.damage_property + e.damage_crops)
    id_str = f"  id: {e.event_id}\n" if show_id else ""
    return (
        f"{id_str}"
        f"  {e.event_type:<14}  {e.county} County\n"
        f"  {e.start_date.strftime('%b %d, %Y')} — {e.end_date.strftime('%b %d, %Y')}\n"
        f"  Severity: {e.severity_score:.0f}/100   Deaths: {deaths}   Damage: {dmg}"
    )

def divider(width=60):
    print("─" * width)


# ── mode 1: search ─────────────────────────────────────────────────────────────

def cmd_search(g: CascadeGraph, args):
    results = g.search_events(
        event_type   = args.type,
        county       = args.county,
        year         = args.year,
        min_severity = args.min_severity,
    )

    filters = []
    if args.type:         filters.append(f"type={args.type}")
    if args.county:       filters.append(f"county~{args.county}")
    if args.year:         filters.append(f"year={args.year}")
    if args.min_severity: filters.append(f"min_severity={args.min_severity}")
    label = ", ".join(filters) if filters else "no filters (all events)"

    print(f"\nSEARCH  [{label}]")
    divider()

    if not results:
        print("No events matched your query.")
        return

    for i, e in enumerate(results, 1):
        print(f"[{i}]")
        print(fmt_event(e, show_id=True))
        print()

    print(f"{len(results)} event(s) found.")


# ── mode 2: filter ─────────────────────────────────────────────────────────────

def cmd_filter(g: CascadeGraph, args):
    results = g.search_events(
        event_type   = args.type,
        min_severity = args.min_severity,
    )

    label = f"type={args.type}" if args.type else "all types"
    if args.min_severity:
        label += f", severity >= {args.min_severity}"

    print(f"\nFILTER  [{label}]")
    divider()

    if not results:
        print("No events matched the filter.")
        return

    total_deaths = sum(e.deaths_direct + e.deaths_indirect for e in results)
    total_damage = sum(e.damage_property + e.damage_crops for e in results)
    avg_severity = sum(e.severity_score for e in results) / len(results)

    print(f"Events matched : {len(results)}")
    print(f"Avg severity   : {avg_severity:.1f}/100")
    print(f"Total deaths   : {total_deaths}")
    print(f"Total damage   : {fmt_damage(total_damage)}")
    print()

    from collections import Counter
    type_counts = Counter(e.event_type for e in results)
    print("Breakdown by type:")
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 40)
        print(f"  {etype:<16} {bar} ({count})")
    print()

    for e in results:
        print(fmt_event(e))
        print()


# ── mode 3: path ───────────────────────────────────────────────────────────────

def cmd_path(g: CascadeGraph, args):
    src_id = args.from_id
    dst_id = args.to_id

    if src_id not in g.events:
        print(f"\nError: event ID '{src_id}' not found. Run 'search' to list valid IDs.")
        return
    if dst_id not in g.events:
        print(f"\nError: event ID '{dst_id}' not found. Run 'search' to list valid IDs.")
        return

    print(f"\nPATH FINDER  [{src_id}  ->  {dst_id}]")
    divider()

    path = g.find_cascade_path(src_id, dst_id)

    if not path:
        print("No cascade path found between these two events.")
        print("They may not be causally connected within the graph.")
        return

    print(f"Cascade chain ({len(path)} steps):\n")
    for i, e in enumerate(path):
        print(f"Step {i+1}  --  {e.event_type.upper()}")
        print(fmt_event(e))
        if i < len(path) - 1:
            print("\n        v triggers\n")
    print()

    all_chains = g.get_all_cascades_from(src_id)
    if len(all_chains) > 1:
        print(f"Note: {src_id} has {len(all_chains)} total downstream cascade chains.")
        print(f"Longest chain depth: {g.get_cascade_depth(src_id)}")


# ── mode 4: rank ───────────────────────────────────────────────────────────────

def cmd_rank(g: CascadeGraph, args):
    top_n = args.top
    ranked = g.rank_by_cascade_potential(top_n=top_n)

    print(f"\nRANKINGS  [top {top_n} by cascade potential]")
    divider()

    if not ranked:
        print("No cascade relationships found in the graph.")
        return

    centrality = g.calculate_centrality()

    for rank, (e, downstream_count) in enumerate(ranked, 1):
        cent = centrality.get(e.event_id, 0)
        bar  = "█" * downstream_count if downstream_count <= 40 else "█" * 40 + f"+ ({downstream_count})"
        print(f"#{rank:<3} {e.event_type:<14} {e.county} ({e.start_date.year})")
        print(f"     Downstream: {bar or '(none)'}")
        print(f"     Severity: {e.severity_score:.0f}   Centrality: {cent:.4f}   Damage: {fmt_damage(e.damage_property)}")
        print()


# ── summary ────────────────────────────────────────────────────────────────────

def cmd_summary(g: CascadeGraph, args):
    s = g.summary()
    total_deaths = sum(e.deaths_direct + e.deaths_indirect for e in g.events.values())
    total_damage = sum(e.damage_property + e.damage_crops for e in g.events.values())

    print("\nGRAPH SUMMARY  [California Storm Events 2010–2025]")
    divider()
    print(f"Events (nodes)       : {s['n_events']}")
    print(f"Cascade links (edges): {s['n_edges']}")
    print(f"Chain origins        : {s['n_trigger_events']}")
    print(f"Graph density        : {s['density']:.5f}")
    print(f"Connected components : {s['n_components']}")
    print(f"Avg out-degree       : {s['avg_out_degree']}")
    print(f"Total deaths         : {total_deaths}")
    print(f"Total damage         : {fmt_damage(total_damage)}")
    print()
    print("Event type breakdown:")
    from collections import Counter
    counts = Counter(e.event_type for e in g.events.values())
    for etype, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {etype:<16} {count}")


# ── argument parser ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="Extreme Weather Cascade Explorer — California 2010–2025",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python cli.py summary
  python cli.py search --type Wildfire --county Butte
  python cli.py search --year 2018 --min-severity 30
  python cli.py filter --type Wildfire --min-severity 40
  python cli.py path --from <event_id> --to <event_id>
  python cli.py rank --top 10
        """
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser("search", help="Search events by type, county, year")
    p_search.add_argument("--type",         type=str,   default=None)
    p_search.add_argument("--county",       type=str,   default=None)
    p_search.add_argument("--year",         type=int,   default=None)
    p_search.add_argument("--min-severity", type=float, default=0, dest="min_severity")

    p_filter = subparsers.add_parser("filter", help="Filter by type/severity with aggregate stats")
    p_filter.add_argument("--type",         type=str,   default=None)
    p_filter.add_argument("--min-severity", type=float, default=0, dest="min_severity")

    p_path = subparsers.add_parser("path", help="Find cascade path between two events")
    p_path.add_argument("--from", dest="from_id", required=True)
    p_path.add_argument("--to",   dest="to_id",   required=True)

    p_rank = subparsers.add_parser("rank", help="Rank events by cascade potential")
    p_rank.add_argument("--top", type=int, default=10)

    subparsers.add_parser("summary", help="Print graph-level statistics")

    args = parser.parse_args()

    print("Loading NOAA data (cached after first run)...", flush=True)
    g = build_graph()

    dispatch = {
        "search":  cmd_search,
        "filter":  cmd_filter,
        "path":    cmd_path,
        "rank":    cmd_rank,
        "summary": cmd_summary,
    }
    dispatch[args.command](g, args)


if __name__ == "__main__":
    main()
