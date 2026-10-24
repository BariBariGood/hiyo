"""Personal-baseline comparisons; explicit data gaps, source and simulation isolation."""

from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from .models import CoachProfile, Observation, SoulPolicy


def fresh(reading: Observation | None, now: datetime, policy: SoulPolicy) -> bool:
    return bool(reading and timedelta(0) <= now - reading.observed_at <= timedelta(hours=policy.freshness_hours))


def assess(readings: list[Observation], now: datetime, profile: CoachProfile, policy: SoulPolicy) -> dict:
    valid = [x for x in readings if x.observed_at <= now]
    if not valid:
        return {"status": "missing", "persistent": False, "signals": [], "baseline": {}}
    latest = max(valid, key=lambda x: x.observed_at)
    if not fresh(latest, now, policy):
        return {"status": "stale", "persistent": False, "signals": [], "baseline": {}}
    tz = ZoneInfo(profile.timezone)
    daily = {}
    for item in sorted(valid, key=lambda x: x.observed_at):
        # Never mix vendors' scores, or use fixtures as a baseline for real data.
        if item.source == latest.source and item.simulated == latest.simulated:
            daily[item.observed_at.astimezone(tz).date()] = item
    last_day = latest.observed_at.astimezone(tz).date()
    days = [last_day - timedelta(days=i) for i in range(policy.persistent_days)]
    start = min(days)
    prior = [x for day, x in daily.items() if start - timedelta(days=policy.baseline_days) <= day < start]
    baselines, signals, latest_deviations = {}, [], []
    thresholds = {"recovery_score": (-1, policy.recovery_drop_points),
                  "sleep_hours": (-1, policy.sleep_drop_hours),
                  "resting_hr": (1, policy.resting_hr_rise)}
    for metric, (direction, delta) in thresholds.items():
        samples = [getattr(x, metric) for x in prior if getattr(x, metric) is not None]
        if len(samples) < policy.minimum_baseline_days:
            continue
        base = median(samples)
        baselines[metric] = base
        value = getattr(latest, metric)
        if value is not None and direction * (value - base) >= delta:
            latest_deviations.append({"metric": metric, "baseline": base, "latest": value,
                                      "difference": value - base, "sustained": False})
        recent = [getattr(daily[day], metric) if day in daily else None for day in days]
        if all(value is not None and direction * (value - base) >= delta for value in recent):
            signals.append({"metric": metric, "baseline": base, "latest": getattr(latest, metric),
                            "consecutive_days": len(days)})
    return {"status": "persistent_change" if signals else "no_persistent_change" if baselines else "insufficient_history",
            "persistent": bool(signals), "signals": signals, "baseline": baselines,
            "latest_deviations": latest_deviations,
            "source": latest.source, "simulated": latest.simulated,
            "latest_observed_at": latest.observed_at.isoformat(),
            "heuristic": "product heuristic, not clinically validated"}
