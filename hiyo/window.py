"""Rolling window over normalized sensor samples.

Tracks median BPM over the last N seconds, freshness, valid count,
sustained-elevation checks, and dedupe/replay rejection.
"""

from __future__ import annotations

import statistics
from collections import deque
from datetime import datetime, timedelta

from .models import SensorSample, WindowStats

MIN_PLAUSIBLE_BPM = 20
MAX_PLAUSIBLE_BPM = 240

# add() outcomes
OK = "ok"
DUPLICATE = "duplicate"
OUT_OF_ORDER = "out_of_order"
STALE = "stale"
INVALID = "invalid"


class SampleWindow:
    def __init__(
        self,
        window_seconds: int = 45,
        stale_seconds: float = 10.0,
        above_fraction: float = 0.8,
    ) -> None:
        self.window_seconds = window_seconds
        self.stale_seconds = stale_seconds
        self.above_fraction = above_fraction
        self.samples: deque[SensorSample] = deque()
        self._seen_ids: set[str] = set()
        self._last_observed: datetime | None = None
        self.last_rejection: str | None = None

    def add(self, sample: SensorSample, now: datetime) -> str:
        """Ingest a sample; returns a rejection code or OK."""
        result = OK
        if sample.bpm is None or not (MIN_PLAUSIBLE_BPM <= sample.bpm <= MAX_PLAUSIBLE_BPM):
            result = INVALID
        elif (now - sample.observed_at).total_seconds() > self.stale_seconds:
            result = STALE
        elif sample.event_id in self._seen_ids:
            result = DUPLICATE
        elif self._last_observed is not None and sample.observed_at <= self._last_observed:
            result = OUT_OF_ORDER

        self.last_rejection = result
        if result != OK:
            return result

        self.samples.append(sample)
        self._seen_ids.add(sample.event_id)
        self._last_observed = sample.observed_at
        self._evict(now)
        return OK

    def _evict(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self.samples and self.samples[0].observed_at < cutoff:
            self.samples.popleft()
        # bound the dedupe set
        if len(self._seen_ids) > 4096:
            live = {s.event_id for s in self.samples}
            self._seen_ids &= live | set(list(self._seen_ids)[-1024:])

    def clear(self) -> None:
        self.samples.clear()
        self._seen_ids.clear()
        self._last_observed = None

    def stats(
        self,
        now: datetime,
        baseline_bpm: int | None = None,
        delta_bpm: int | None = None,
        sensor_unavailable: bool = False,
    ) -> WindowStats:
        self._evict(now)
        newest_age = None
        if self.samples:
            newest_age = (now - self.samples[-1].observed_at).total_seconds()
        stale = newest_age is None or newest_age > self.stale_seconds

        bpms = [s.bpm for s in self.samples if s.bpm is not None]
        median = statistics.median(bpms) if bpms else None

        threshold = None
        frac_above = 0.0
        sustained = False
        if baseline_bpm is not None and delta_bpm is not None:
            threshold = float(baseline_bpm + delta_bpm)
            if bpms:
                frac_above = sum(1 for b in bpms if b >= threshold) / len(bpms)
                sustained = bool(median is not None and median >= threshold and frac_above >= self.above_fraction)

        return WindowStats(
            now=now,
            valid_count=len(bpms),
            median_bpm=median,
            newest_age_s=newest_age,
            stale=stale,
            fraction_above_threshold=frac_above,
            threshold_bpm=threshold,
            sustained_elevation=sustained,
            sensor_unavailable=sensor_unavailable,
            simulated=any(s.simulated for s in self.samples),
        )
