"""
disaster_event.py
Represents a single extreme weather event node in the cascade graph.
"""

from dataclasses import dataclass, field
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2


# Cascade type compatibility: which event types can trigger which
CASCADE_RULES = {
    "Drought":   ["Wildfire", "Heat Wave", "Dust Storm"],
    "Wildfire":  ["Debris Flow", "Flood", "Landslide"],
    "Flood":     ["Landslide", "Debris Flow"],
    "Landslide": ["Flood", "Debris Flow"],
    "Heat Wave": ["Drought", "Wildfire"],
    "High Wind": ["Wildfire", "Dust Storm"],
    "Debris Flow": ["Flood"],
}

# Max days between end of trigger and start of result for a valid cascade edge
MAX_CASCADE_DAYS = {
    ("Drought",  "Wildfire"):     1095,  # drought effects persist ~3 years
    ("Wildfire", "Debris Flow"):   730,  # hillside instability lasts ~2 years
    ("Wildfire", "Landslide"):     730,
    ("Wildfire", "Flood"):         365,
    ("Flood",    "Landslide"):      90,
    ("Flood",    "Debris Flow"):    90,
    ("Heat Wave","Drought"):       365,
    ("Heat Wave","Wildfire"):      180,
    ("High Wind","Wildfire"):       30,
    "default":                     365,
}

MAX_DISTANCE_KM = 150  # geographic proximity cutoff


@dataclass
class DisasterEvent:
    """
    A single extreme weather event — one node in the cascade graph.

    Attributes are drawn directly from NOAA Storm Events CSV columns,
    plus a derived severity_score (0–100).
    """
    event_id:      str
    event_type:    str          # NOAA EVENT_TYPE field
    state:         str
    county:        str
    start_date:    datetime
    end_date:      datetime
    latitude:      float
    longitude:     float
    deaths_direct: int   = 0
    deaths_indirect: int = 0
    injuries_direct: int = 0
    damage_property: float = 0.0   # USD
    damage_crops:    float = 0.0   # USD
    narrative:     str   = ""      # NOAA episode/event narrative text
    severity_score: float = field(init=False)

    def __post_init__(self):
        self.severity_score = self._calculate_severity()

    # ------------------------------------------------------------------
    # Severity
    # ------------------------------------------------------------------

    def _calculate_severity(self) -> float:
        """
        Normalize deaths, injuries, and damage into a 0–100 score.
        Weights: damage 50%, deaths 30%, injuries 20%.
        Each component is log-scaled then normalized to [0,1].
        """
        import math

        def log_norm(value, scale):
            """Log-scale a value relative to a reference scale."""
            if value <= 0:
                return 0.0
            return min(math.log1p(value) / math.log1p(scale), 1.0)

        deaths    = self.deaths_direct + self.deaths_indirect
        damage    = self.damage_property + self.damage_crops

        d_score   = log_norm(deaths,    100)         # 100 deaths → max
        inj_score = log_norm(self.injuries_direct, 500)
        dmg_score = log_norm(damage,    1_000_000_000)  # $1B → max

        raw = 0.30 * d_score + 0.20 * inj_score + 0.50 * dmg_score
        return round(raw * 100, 2)

    # ------------------------------------------------------------------
    # Spatial helpers
    # ------------------------------------------------------------------

    def distance_km(self, other: "DisasterEvent") -> float:
        """Haversine distance between two event centroids (km)."""
        R = 6371.0
        lat1, lon1 = radians(self.latitude),  radians(self.longitude)
        lat2, lon2 = radians(other.latitude), radians(other.longitude)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))

    # ------------------------------------------------------------------
    # Cascade eligibility
    # ------------------------------------------------------------------

    def could_trigger(self, other: "DisasterEvent") -> bool:
        """
        Return True if this event could plausibly have triggered `other`.

        Three conditions must all hold:
          1. Type compatibility  — other.event_type is in this event's cascade rules
          2. Temporal ordering   — other starts after this ends, within max lag window
          3. Geographic overlap  — events are within MAX_DISTANCE_KM of each other
        """
        # 1. Type compatibility
        allowed_types = CASCADE_RULES.get(self.event_type, [])
        if other.event_type not in allowed_types:
            return False

        # 2. Temporal ordering
        # For persistent background conditions (Drought, Heat Wave), the downstream
        # event can begin *during* the trigger — drought enables concurrent wildfires.
        # We still measure the lag from trigger END (or other.start if it ends first)
        # to keep the window sensible.
        persistent_types = {"Drought", "Heat Wave"}
        if self.event_type in persistent_types:
            # Other event must start after trigger begins (not before)
            if other.start_date <= self.start_date:
                return False
            # Measure days gap from end of trigger (or start of other if trigger outlasts it)
            reference_start = min(self.end_date, other.start_date)
            days_gap = max((other.start_date - reference_start).days, 0)
        else:
            if other.start_date <= self.end_date:
                return False
            days_gap = (other.start_date - self.end_date).days
        key = (self.event_type, other.event_type)
        max_days = MAX_CASCADE_DAYS.get(key, MAX_CASCADE_DAYS["default"])
        if days_gap > max_days:
            return False

        # 3. Geographic proximity
        if self.distance_km(other) > MAX_DISTANCE_KM:
            return False

        return True

    def edge_weight(self, other: "DisasterEvent") -> float:
        """
        Compute a weight for the edge self → other.
        Higher weight = stronger cascade link.

        Weight = avg(severity scores) * proximity_factor * recency_factor
        """
        days_gap = max((other.start_date - self.end_date).days, 1)
        key = (self.event_type, other.event_type)
        max_days = MAX_CASCADE_DAYS.get(key, MAX_CASCADE_DAYS["default"])

        proximity_factor = 1 - (self.distance_km(other) / MAX_DISTANCE_KM)
        recency_factor   = 1 - (days_gap / max_days)

        avg_severity = (self.severity_score + other.severity_score) / 200  # normalize to [0,1]
        weight = avg_severity * proximity_factor * recency_factor
        return round(max(weight, 0.0), 4)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __repr__(self):
        return (
            f"DisasterEvent({self.event_id!r}, type={self.event_type!r}, "
            f"county={self.county!r}, {self.start_date.date()}, "
            f"severity={self.severity_score})"
        )
