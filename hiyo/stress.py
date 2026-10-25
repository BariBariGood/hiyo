"""Live stress estimate (0-3) from BLE heart rate + RR intervals.

Reimplements the method described in WHOOP patent application
US 2024/0188865 A1 (weighted cardiac contributions). Display only —
never feeds policy, prompts, or dispatch.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

WINDOW_S = 300
BASELINE_DAYS = 14
METHOD = ("hiyo approximation of WHOOP patent US20240188865A1 — "
          "not WHOOP's Stress Score, not medical")

_MU0 = math.log(42.0)
_SIG0 = 0.5
_SIG_FLOOR = 0.15


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


class StressEstimator:
    def __init__(self, baseline_path: Path | None = None, tz=None) -> None:
        self.samples: list[tuple[datetime, float, bool]] = []  # t, bpm, simulated
        self.rr: list[tuple[datetime, float]] = []
        self._last_rr: float | None = None
        self._minute_rmssd: list[tuple[str, float]] = []  # minute bucket -> ln rmssd
        self.path = baseline_path or Path(
            os.environ.get("HIYO_STRESS_BASELINE", "runtime/stress_baseline.json"))
        self._lock = threading.Lock()
        self.baseline: list[dict] = self._load_baseline()

    # ---------- ingest ----------

    def add(self, sample, now: datetime) -> None:
        with self._lock:
            self.samples.append((now, float(sample.bpm), bool(sample.simulated)))
            cut = now - timedelta(seconds=WINDOW_S)
            self.samples = [s for s in self.samples if s[0] >= cut]
            for rr in getattr(sample, "rr_ms", None) or []:
                self._accept_rr(float(rr), now)
            self.rr = [r for r in self.rr if r[0] >= cut]

    def _accept_rr(self, rr: float, now: datetime) -> bool:
        if not (300 <= rr <= 2000):
            return False
        bpm_ref = self.samples[-1][1] if self.samples else 60000 / rr
        expected = 60000 / bpm_ref
        if abs(rr - expected) > 0.25 * expected:
            return False
        if self._last_rr is not None and abs(rr - self._last_rr) > 0.20 * self._last_rr:
            return False
        self._last_rr = rr
        self.rr.append((now, rr))
        return True

    # ---------- hrv ----------

    def _rmssd(self) -> float | None:
        if len(self.rr) < 30:
            return None
        vals = [r[1] for r in self.rr]
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        return math.sqrt(sum(d * d for d in diffs) / len(diffs))

    def _hrv_score(self, rmssd: float) -> tuple[float, str]:
        ln = math.log(max(rmssd, 1e-6))
        if len(self.baseline) >= 15:
            mus = [b["v"] for b in self.baseline]
            mu = mean(mus)
            sig = max(pstdev(mus), _SIG_FLOOR)
            tag = f"personal ({len(self.baseline)} min)"
        else:
            mu, sig, tag = _MU0, _SIG0, "population default"
        z = (ln - mu) / sig
        return 3.0 * _phi(-z), tag

    def _record_baseline_minute(self, rmssd: float, now: datetime) -> None:
        bucket = now.replace(second=0, microsecond=0).isoformat()
        if self._minute_rmssd and self._minute_rmssd[-1][0] == bucket:
            return
        ln = math.log(max(rmssd, 1e-6))
        self._minute_rmssd.append((bucket, ln))
        self.baseline.append({"t": now.isoformat(), "v": ln})
        cutoff = (now - timedelta(days=BASELINE_DAYS)).isoformat()
        self.baseline = [b for b in self.baseline if b["t"] >= cutoff]
        self._save_baseline()

    # ---------- score ----------

    def estimate(self, now: datetime, rest: float, max_hr: float,
                 activity: str = "unknown") -> dict:
        with self._lock:
            if activity in ("moving", "exercise"):
                return {"score": None, "zone": None, "hrv_available": False,
                        "reason": "exertion — not scored", "method": METHOD,
                        "simulated": any(s[2] for s in self.samples)}
            hr_vals = [s[1] for s in self.samples]
            if not hr_vals or (now - self.samples[0][0]).total_seconds() < 60:
                return {"score": None, "zone": None, "hrv_available": False,
                        "reason": "insufficient data (<60s)", "method": METHOD,
                        "simulated": any(s[2] for s in self.samples)}
            hr_mean = mean(hr_vals)
            x = (hr_mean - rest) / max(max_hr - rest, 1e-9)
            hr_score = max(0.0, min(3.0, 3 / (1 + math.exp(-7.87 * (x - 0.2)))))
            rmssd = self._rmssd()
            w = 0.3 + 0.4 / (1 + math.exp((hr_mean - (rest + 10)) / 5))
            out = {"hr_score": round(hr_score, 2), "hrv_score": None,
                   "rmssd_ms": None, "hr_mean": round(hr_mean, 1),
                   "weight_hr": round(w, 2), "hrv_available": False,
                   "valid_rr": len(self.rr), "baseline": None,
                   "simulated": any(s[2] for s in self.samples),
                   "method": METHOD, "reason": None}
            if rmssd is None:
                score = hr_score
                out["reason"] = "HRV unavailable — HR only"
            else:
                hrv_score, tag = self._hrv_score(rmssd)
                self._record_baseline_minute(rmssd, now)
                score = w * hr_score + (1 - w) * hrv_score
                out.update(hrv_score=round(hrv_score, 2), rmssd_ms=round(rmssd, 1),
                           hrv_available=True, baseline=tag)
            score = max(0.0, min(3.0, score))
            out["score"] = round(score, 2)
            out["zone"] = "low" if score < 1 else ("medium" if score < 2 else "high")
            return out

    def clear(self) -> None:
        with self._lock:
            self.samples.clear()
            self.rr.clear()
            self._last_rr = None
            self._minute_rmssd.clear()

    # ---------- persistence ----------

    def _load_baseline(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return []

    def _save_baseline(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.baseline))
            tmp.replace(self.path)
        except Exception:
            pass
