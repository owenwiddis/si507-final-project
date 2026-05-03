"""
noaa_fetcher.py
Downloads and parses NOAA Storm Events bulk CSVs into DisasterEvent objects.

NOAA distributes Storm Events as gzipped CSVs, one file per year:
  https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/

Each year has three file types:
  - details  : one row per event (the main file we use)
  - fatalities: fatality detail records
  - locations : additional location records

We only need the *details* files.
"""

import os
import gzip
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime
from pathlib import Path

from disaster_event import DisasterEvent

# NOAA bulk CSV base URL
BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

# NOAA event types we care about for California cascade modeling
TARGET_EVENT_TYPES = {
    "Drought",
    "Wildfire",
    "Flood",
    "Flash Flood",
    "Debris Flow",
    "Landslide",
    "Heat",
    "Excessive Heat",
    "High Wind",
    "Dust Storm",
    "Heavy Rain",
}

# Map NOAA's verbose type names → our simplified internal names
TYPE_NORMALIZATION = {
    "Flash Flood":    "Flood",
    "Excessive Heat": "Heat Wave",
    "Heat":           "Heat Wave",
}


class NOAADataFetcher:
    """
    Fetches NOAA Storm Events data for a given state and year range.

    Args:
        cache_dir (str): Local folder to store downloaded CSV files.
                         Avoids re-downloading on repeated runs.
        state (str): Two-letter state abbreviation, e.g. "CA".
    """

    # NOAA uses full state names in the STATE column, not abbreviations
    STATE_NAMES = {
        "CA": "CALIFORNIA", "TX": "TEXAS", "FL": "FLORIDA",
        "WA": "WASHINGTON", "OR": "OREGON", "AZ": "ARIZONA",
        "NV": "NEVADA", "CO": "COLORADO", "UT": "UTAH",
        "NM": "NEW MEXICO", "ID": "IDAHO", "MT": "MONTANA",
    }

    def __init__(self, cache_dir: str = "data/raw", state: str = "CA"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        abbrev = state.upper()
        self.state_abbrev = abbrev
        self.state = self.STATE_NAMES.get(abbrev, abbrev)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_events(
        self,
        start_year: int,
        end_year: int,
        event_types: set = None,
    ) -> list[DisasterEvent]:
        """
        Download (or load from cache) NOAA events for each year in range.

        Args:
            start_year: First year to include (inclusive).
            end_year:   Last year to include (inclusive).
            event_types: Set of event type strings to keep. Defaults to
                         TARGET_EVENT_TYPES if None.

        Returns:
            List of DisasterEvent objects, sorted by start_date.
        """
        if event_types is None:
            event_types = TARGET_EVENT_TYPES

        all_events = []
        for year in range(start_year, end_year + 1):
            print(f"  Loading {year}...")
            df = self._load_year(year)
            if df is None:
                print(f"    [!] No data found for {year}, skipping.")
                continue
            events = self._parse_dataframe(df, year, event_types)
            all_events.extend(events)
            print(f"    → {len(events)} events kept for {self.state}")

        all_events.sort(key=lambda e: e.start_date)
        print(f"\nTotal events loaded: {len(all_events)}")
        return all_events

    # ------------------------------------------------------------------
    # Download / caching
    # ------------------------------------------------------------------

    def _load_year(self, year: int) -> pd.DataFrame | None:
        """
        Return a DataFrame for the given year's details file.
        Uses local cache if available, otherwise downloads from NOAA.
        """
        cache_path = self.cache_dir / f"StormEvents_details_{year}.csv"

        if cache_path.exists():
            return pd.read_csv(cache_path, low_memory=False)

        url = self._find_url(year)
        if url is None:
            return None

        print(f"    Downloading {url} ...")
        response = requests.get(url, timeout=120)
        if response.status_code != 200:
            print(f"    [!] HTTP {response.status_code}")
            return None

        with gzip.open(BytesIO(response.content)) as f:
            df = pd.read_csv(f, low_memory=False)
        df.to_csv(cache_path, index=False)
        return df

    def _find_url(self, year: int) -> str | None:
        """
        Find the correct download URL by scraping the NOAA directory listing
        for the exact filename (which includes a changing date suffix).
        Filenames look like: StormEvents_details-ftp_v1.0_d2020_c20230927.csv.gz
        """
        import re as _re
        try:
            resp = requests.get(BASE_URL, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"    [!] Could not reach NOAA directory: {e}")
            return None

        # Try matching href attributes first (Apache directory listing)
        pattern = _re.compile(
            r'href="(StormEvents_details[^"]*_d' + str(year) + r'_[^"]+\.csv\.gz)"'
        )
        match = pattern.search(resp.text)
        if match:
            return BASE_URL + match.group(1)

        # Fallback: scan plain text lines for the filename token
        for line in resp.text.splitlines():
            if "details" in line and f"_d{year}_" in line and ".csv.gz" in line:
                for token in line.split():
                    clean = token.strip('"').strip("'")
                    if f"_d{year}_" in clean and clean.endswith(".csv.gz"):
                        return BASE_URL + clean

        print(f"    [!] Could not locate file for {year} in NOAA directory.")
        return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_dataframe(
        self,
        df: pd.DataFrame,
        year: int,
        event_types: set,
    ) -> list[DisasterEvent]:
        """
        Filter a raw NOAA DataFrame and convert rows → DisasterEvent objects.
        """
        # Filter by state (NOAA uses full state names e.g. "CALIFORNIA")
        df = df[df["STATE"].str.upper() == self.state].copy()

        # Filter by event type — also accept variants that normalize to our types
        all_target_types = set(event_types) | set(TYPE_NORMALIZATION.keys())
        df = df[df["EVENT_TYPE"].isin(all_target_types)].copy()

        events = []
        for _, row in df.iterrows():
            event = self._row_to_event(row, year)
            if event is not None:
                events.append(event)
        return events

    def _row_to_event(self, row: pd.Series, year: int) -> DisasterEvent | None:
        """Convert a single NOAA CSV row into a DisasterEvent."""
        try:
            start_date = self._parse_noaa_date(row.get("BEGIN_DATE_TIME", ""), year)
            end_date   = self._parse_noaa_date(row.get("END_DATE_TIME",   ""), year)
            if start_date is None or end_date is None:
                return None
            if end_date < start_date:
                end_date = start_date  # data quality guard

            event_type = str(row.get("EVENT_TYPE", "Unknown")).strip()
            event_type = TYPE_NORMALIZATION.get(event_type, event_type)

            lat = self._safe_float(row.get("BEGIN_LAT"))
            lon = self._safe_float(row.get("BEGIN_LON"))
            if lat is None or lon is None:
                # Fall back to county centroid (rough)
                lat, lon = self._county_centroid(str(row.get("CZ_NAME", "")))
            if lat is None:
                return None  # can't place event geographically

            event_id = f"{self.state}_{event_type.replace(' ','_').upper()}_{year}_{row.get('EVENT_ID', 'X')}"

            return DisasterEvent(
                event_id        = event_id,
                event_type      = event_type,
                state           = self.state,
                county          = str(row.get("CZ_NAME", "Unknown")).title(),
                start_date      = start_date,
                end_date        = end_date,
                latitude        = lat,
                longitude       = lon,
                deaths_direct   = int(self._safe_float(row.get("DEATHS_DIRECT"),   0)),
                deaths_indirect = int(self._safe_float(row.get("DEATHS_INDIRECT"), 0)),
                injuries_direct = int(self._safe_float(row.get("INJURIES_DIRECT"), 0)),
                damage_property = self._parse_damage(row.get("DAMAGE_PROPERTY", "")),
                damage_crops    = self._parse_damage(row.get("DAMAGE_CROPS",    "")),
                narrative       = str(row.get("EPISODE_NARRATIVE", "") or ""),
            )
        except Exception as e:
            # Skip malformed rows silently
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_noaa_date(self, date_str: str, year: int) -> datetime | None:
        """Parse NOAA date strings like '01-JAN-2020 00:00:00'."""
        if not date_str or pd.isna(date_str):
            return None
        formats = [
            "%d-%b-%Y %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str).strip(), fmt)
            except ValueError:
                continue
        return None

    def _parse_damage(self, value: str) -> float:
        """Convert NOAA damage strings like '1.5M', '500K', '250B' → float USD."""
        if not value or pd.isna(value):
            return 0.0
        s = str(value).strip().upper()
        multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
        if s and s[-1] in multipliers:
            try:
                return float(s[:-1]) * multipliers[s[-1]]
            except ValueError:
                return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _safe_float(self, value, default=None) -> float | None:
        """Convert to float, returning default on failure."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _county_centroid(self, county_name: str) -> tuple[float | None, float | None]:
        """
        Very rough California county centroid lookup as a fallback.
        Covers the most common CA counties in NOAA data.
        """
        CA_CENTROIDS = {
            "LOS ANGELES":   (34.32, -118.22),
            "SAN DIEGO":     (33.02, -116.77),
            "ORANGE":        (33.70, -117.75),
            "BUTTE":         (39.67, -121.60),
            "SANTA BARBARA": (34.74, -119.72),
            "VENTURA":       (34.45, -119.07),
            "SONOMA":        (38.52, -122.93),
            "SHASTA":        (40.76, -122.02),
            "NAPA":          (38.50, -122.33),
            "FRESNO":        (36.92, -119.75),
            "TULARE":        (36.21, -118.80),
            "KERN":          (35.34, -118.73),
            "MONTEREY":      (36.24, -121.31),
            "MENDOCINO":     (39.44, -123.37),
            "TRINITY":       (40.65, -123.10),
        }
        key = county_name.upper().replace(" (ZONE)", "").strip()
        return CA_CENTROIDS.get(key, (None, None))
