"""Scenario-driven fake heart-rate samples. Every sample is simulated=True."""

from __future__ import annotations

import itertools
import random
from datetime import datetime

from .models import SensorSample

SCENARIOS = {
    "resting_normal": {"low": 60, "high": 68},
    "elevated_resting": {"low": 95, "high": 103},
    "elevated_moving": {"low": 112, "high": 124},
}

_rr = itertools.cycle([[640.0, 655.0], [], [672.0], []])


class Simulator:
    """Produces ~1 Hz fake SensorSamples for a named scenario."""

    def __init__(self, scenario: str = "resting_normal", seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self.set_scenario(scenario)

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}; choices: {sorted(SCENARIOS)}")
        self.scenario = name

    def tick(self, now: datetime) -> SensorSample:
        band = SCENARIOS[self.scenario]
        return SensorSample(
            source="simulator",
            device_model="simulator",
            observed_at=now,
            received_at=now,
            bpm=self._rng.randint(band["low"], band["high"]),
            rr_ms=list(next(_rr)),
            contact_detected=True,
            motion_state="unknown",
            simulated=True,
        )
