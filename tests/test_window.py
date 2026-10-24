"""Rolling window: freshness, dedupe, replay, medians (T09 extras)."""

from datetime import timedelta

from hiyo.models import SensorSample
from hiyo.window import SampleWindow

from conftest import NOW


def sample(bpm=90, seconds_ago=0, event_id=None, simulated=True) -> SensorSample:
    s = SensorSample(
        source="simulator",
        observed_at=NOW - timedelta(seconds=seconds_ago),
        bpm=bpm,
        simulated=simulated,
    )
    if event_id:
        s.event_id = event_id
    return s


def test_fresh_sample_accepted():
    w = SampleWindow()
    assert w.add(sample(), NOW) == "ok"


def test_stale_sample_rejected():
    w = SampleWindow(stale_seconds=10)
    assert w.add(sample(seconds_ago=30), NOW) == "stale"


def test_duplicate_event_id_rejected():
    w = SampleWindow()
    s = sample(event_id="dup-1")
    assert w.add(s, NOW) == "ok"
    again = s.model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    assert w.add(again, NOW) == "duplicate"


def test_out_of_order_rejected():
    w = SampleWindow()
    assert w.add(sample(), NOW) == "ok"
    old = sample(seconds_ago=5)
    assert w.add(old, NOW) == "out_of_order"


def test_invalid_bpm_rejected():
    w = SampleWindow()
    assert w.add(sample(bpm=None), NOW) == "invalid"
    assert w.add(sample(bpm=0), NOW) == "invalid"
    assert w.add(sample(bpm=500), NOW) == "invalid"


def test_stats_median_and_sustained():
    w = SampleWindow(window_seconds=45, stale_seconds=60)
    for i in range(29, -1, -1):  # ascending observed_at
        w.add(sample(bpm=95, seconds_ago=i), NOW)
    st = w.stats(NOW, baseline_bpm=70, delta_bpm=15)
    assert st.valid_count == 30
    assert st.median_bpm == 95
    assert st.stale is False
    assert st.sustained_elevation is True


def test_stats_stale_when_no_fresh():
    w = SampleWindow(stale_seconds=10)
    w.add(sample(bpm=95), NOW)
    w.add(sample(bpm=95), NOW + timedelta(seconds=1))
    later = NOW + timedelta(seconds=12)
    st = w.stats(later)
    assert st.stale is True
    assert st.newest_age_s == 12


def test_window_evicts_old_samples():
    w = SampleWindow(window_seconds=10)
    w.add(sample(seconds_ago=9), NOW)
    w.add(sample(seconds_ago=1), NOW)
    later = NOW + timedelta(seconds=5)
    st = w.stats(later)
    assert st.valid_count == 1
