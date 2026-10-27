"""Deduplication: merge reports of the same real-world issue into one case.

Algorithm (online, one report at a time, in arrival order per category):

1. Candidates are open cases of the same category whose centroid is within the category's
   radius (``dedup_radius_m``) of the new report.
2. A candidate must still be "active": its last report is at most ``dedup_window_hours``
   before this one (sliding window), and the case is not older than
   ``MAX_SPAN_WINDOWS`` windows in total. The cap stops a permanent hotspot (a spot where
   people park illegally every day) from collapsing weeks of separate offences into one.
3. The nearest candidate wins; with none, the report opens a new case.

Radius and window are per category because issues differ: a parked car is gone in hours
and is exactly where it was reported, a pothole stays for weeks, noise is heard from
150 m away. Trade-offs: two genuinely different issues close together merge (lower
precision); a report with poor GPS can miss its case (lower recall). Both are measured
against the generator's ground truth.

The spatial search runs in PostGIS; the decision rule below is plain Python so it can be
unit-tested without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_SPAN_WINDOWS = 4


@dataclass(frozen=True)
class Candidate:
    case_id: uuid.UUID
    distance_m: float
    first_reported_at: datetime
    last_reported_at: datetime


def choose_case(
    candidates: list[Candidate],
    received_at: datetime,
    radius_m: float,
    window: timedelta,
) -> uuid.UUID | None:
    active = [
        c
        for c in candidates
        if c.distance_m <= radius_m
        and abs(received_at - c.last_reported_at) <= window
        and received_at - c.first_reported_at <= window * MAX_SPAN_WINDOWS
    ]
    if not active:
        return None
    return min(active, key=lambda c: (c.distance_m, c.last_reported_at)).case_id
