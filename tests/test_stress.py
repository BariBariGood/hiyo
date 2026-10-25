import math
from datetime import timedelta
from pathlib import Path

import pytest

import os
os.environ["HIYO_DISABLE_LOOPS"] = "1"
from fastapi.testclient import TestClient
from hiyo.app import app
from hiyo.models import SensorSample
from hiyo.stress import StressEstimator
from conftest import NOW


def smp(bpm, rr=None, sim=False):
    return SensorSample(bpm=bpm, source="test", simulated=sim, rr_ms=rr,
                        observed_at=NOW)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("HIYO_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DISPATCHER", "dryrun")
    monkeypatch.setenv("HIYO_DISABLE_LOOPS", "1")
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as c:
        yield c


def make(tmp_path):
    return StressEstimator(baseline_path=tmp_path / "b.json")


def feed(est, bpm, seconds=90, now=NOW, rr=None):
    t = now - timedelta(seconds=seconds)
    for i in range(seconds):
        est.add(smp(bpm, rr or [60000.0 / bpm]), t + timedelta(seconds=i))


def test_artifact_filtering(tmp_path):
    est = make(tmp_path)
    noisy = [746, 325, 1297.9, 634.8, 883, 1335.9, 347.7, 700, 720, 760]
    est.add(smp(78, noisy), NOW)  # 78bpm -> expected ~769ms
    accepted = [r[1] for r in est.rr]
    # 325 (>25% off + big jump), 1297.9, 883, 1335.9, 347.7 rejected
    assert 325 not in accepted and 347.7 not in accepted
    assert 1297.9 not in accepted and 1335.9 not in accepted
    assert len(accepted) < len(noisy)


def test_rmssd_known(tmp_path):
    est = make(tmp_path)
    rr = [800 + (10 if i % 2 else -10) for i in range(40)]
    # bypass cleaner: inject directly
    est.rr = [(NOW, float(v)) for v in rr]
    assert est._rmssd() == pytest.approx(20.0, abs=0.01)


def test_hr_score_calibration(tmp_path):
    est = make(tmp_path)
    feed(est, 100)
    out = est.estimate(NOW, rest=60, max_hr=190)
    assert out["hr_score"] == pytest.approx(2.1, abs=0.1)


def test_hrv_direction(tmp_path):
    est = make(tmp_path)
    feed(est, 70, rr=[math.exp(math.log(20))] * 40)  # ~20ms -> uniform fails successive diff? use direct
    e2 = make(tmp_path)
    # direct injection: low rmssd vs high rmssd
    low = [800.0] * 30; low[1::2] = [795.0] * 15  # rmssd 5
    hi = [800.0] * 30; hi[1::2] = [700.0] * 15    # rmssd 100
    e2.rr = [(NOW, v) for v in low]
    s_low = e2._hrv_score(e2._rmssd())[0]
    e2.rr = [(NOW, v) for v in hi]
    s_hi = e2._hrv_score(e2._rmssd())[0]
    assert s_low > s_hi  # lower HRV vs baseline -> higher stress score


def test_insufficient_rr_hr_only(tmp_path):
    est = make(tmp_path)
    feed(est, 90, seconds=70, rr=[999999])  # all rejected
    out = est.estimate(NOW, rest=60, max_hr=190)
    assert out["hrv_available"] is False and out["score"] is not None


def test_baseline_switches_personal(tmp_path):
    est = make(tmp_path)
    est.rr = [(NOW, v) for v in [800.0, 780.0] * 20]
    for i in range(15):
        est._record_baseline_minute(50.0, NOW - timedelta(minutes=15 - i))
    _, tag = est._hrv_score(50.0)
    assert tag.startswith("personal")


def test_exertion_not_scored(tmp_path):
    est = make(tmp_path)
    feed(est, 100)
    out = est.estimate(NOW, rest=60, max_hr=190, activity="moving")
    assert out["score"] is None and "exertion" in out["reason"]


def test_policy_does_not_import_stress():
    import hiyo.policy, inspect
    src = inspect.getsource(hiyo.policy)
    assert "import" not in [l.split()[0] for l in src.splitlines() if "stress" in l and "import" in l]
    import re
    assert not re.search(r"from .stress|import stress", src)


def test_status_includes_stress(client):
    r = client.get("/api/status")
    assert r.status_code == 200 and "stress" in r.json()
