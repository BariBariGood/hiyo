"""Background engine: sensor loop + 5s decision loop + dispatch orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import audit
from .brief import build_brief
from .calendar import CalendarProvider
from .dispatcher import Dispatcher, make_dispatcher
from .models import (
    Action,
    ContextSnapshot,
    Decision,
    Profile,
    SensorSample,
    WindowStats,
)
from .policy import decide
from .simulator import Simulator
from .state import StateStore
from .window import SampleWindow

log = logging.getLogger("hiyo.service")

SENSOR_TICK_S = 1.0
DECISION_TICK_S = 5.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Service:
    def __init__(
        self,
        profile: Profile,
        state_store: StateStore,
        calendar: CalendarProvider,
        dispatcher: Dispatcher | None = None,
        window: SampleWindow | None = None,
        simulator: Simulator | None = None,
        owner_phone: str | None = None,
        autostart: bool = True,
    ) -> None:
        self.profile = profile
        self.store = state_store
        self.calendar = calendar
        self.owner_phone = owner_phone or os.environ.get("OWNER_PHONE_NUMBER")
        self.dispatcher = dispatcher or make_dispatcher(self.owner_phone)
        self.dispatcher_mode = "vapi" if os.environ.get("DISPATCHER", "").lower() == "vapi" else "dryrun"
        self.window = window or SampleWindow(window_seconds=profile.window_seconds)
        self.simulator = simulator or Simulator()
        self.autostart = autostart

        self.sensor_mode = "simulator"  # "simulator" | "ble"
        self.sensor_status = "ok"  # "ok" | "unavailable"
        self.activity = "unknown"
        self.activity_provenance: str | None = None

        self.latest_sample: SensorSample | None = None
        self.latest_decision: Decision | None = None
        self.latest_stats: WindowStats | None = None
        self.latest_context: ContextSnapshot | None = None
        self.recent_decisions: deque[Decision] = deque(maxlen=20)
        self.last_dispatch_error: str | None = None

        self._ble_queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._ble_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._last_logged_key: tuple | None = None

    # ----- lifecycle -----

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._sensor_loop(), name="sensor"))
        self._tasks.append(asyncio.create_task(self._decision_loop(), name="decision"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        all_tasks = list(self._tasks)
        if self._ble_task:
            self._ble_task.cancel()
            all_tasks.append(self._ble_task)
        await asyncio.gather(*all_tasks, return_exceptions=True)

    # ----- sensor -----

    async def _sensor_loop(self) -> None:
        while True:
            if self.sensor_mode == "simulator":
                sample = self.simulator.tick(utcnow())
                self.ingest_sample(sample)
            await asyncio.sleep(SENSOR_TICK_S)

    def ingest_sample(self, sample: SensorSample) -> str:
        res = self.window.add(sample, utcnow())
        if res == "ok":
            self.latest_sample = sample
        return res

    async def set_sensor_mode(self, mode: str) -> None:
        if mode not in ("simulator", "ble"):
            raise ValueError("mode must be 'simulator' or 'ble'")
        if mode == self.sensor_mode:
            return
        self.sensor_mode = mode
        if mode == "ble":
            self.sensor_status = "unavailable"
            address = os.environ.get("WHOOP_ADDR")
            if address and self._ble_task is None:
                from .whoop_ble import WhoopBleStreamer

                streamer = WhoopBleStreamer(address, self._ble_queue)
                self._ble_task = asyncio.create_task(self._ble_pump(streamer), name="ble")
        else:
            self.sensor_status = "ok"
            if self._ble_task:
                self._ble_task.cancel()
                self._ble_task = None

    async def _ble_pump(self, streamer) -> None:
        runner = asyncio.create_task(streamer.run())
        try:
            while True:
                item = await self._ble_queue.get()
                if item["type"] == "sample":
                    self.ingest_sample(item["sample"])
                elif item["type"] == "status":
                    self.sensor_status = "ok" if item["status"] == "connected" else "unavailable"
        finally:
            streamer.stop()
            runner.cancel()

    # ----- decision -----

    async def _decision_loop(self) -> None:
        while True:
            try:
                await self.evaluate_once()
            except Exception:
                log.exception("decision tick failed")
            await asyncio.sleep(DECISION_TICK_S)

    async def evaluate_once(self, now: datetime | None = None) -> Decision:
        now = now or utcnow()
        stats = self.window.stats(
            now,
            baseline_bpm=self.profile.baseline_bpm,
            delta_bpm=self.profile.delta_bpm,
            sensor_unavailable=(self.sensor_status == "unavailable"),
        )
        context = await self.calendar.snapshot(
            now, activity=self.activity, activity_provenance=self.activity_provenance
        )
        decision = decide(stats, context, self.profile, self.store.state, now,
                          owner_phone=self.owner_phone)
        self.latest_stats = stats
        self.latest_context = context
        self.latest_decision = decision
        self.recent_decisions.appendleft(decision)

        key = (decision.action, decision.reason_code, decision.candidate_id)
        if key != self._last_logged_key:
            audit.record("decision", {"decision": decision.model_dump(mode="json")})
            self._last_logged_key = key

        if decision.action == Action.CALL:
            await self._execute_dispatch(decision, context, now)
        return decision

    async def _execute_dispatch(self, decision: Decision, context: ContextSnapshot, now: datetime) -> None:
        try:
            self.store.record_dispatch_attempt(decision.candidate_id or "", now)
        except Exception:
            log.exception("state persist failed; refusing dispatch")
            audit.record("dispatch_failed", {"candidate_id": decision.candidate_id, "error": "state persist failed"})
            return
        brief = build_brief(context, now)
        try:
            result = await self.dispatcher.dispatch(self.owner_phone or "", brief)
        except Exception as exc:
            self.store.set_active_call(None)
            self.last_dispatch_error = str(exc)
            audit.record("dispatch_failed", {"candidate_id": decision.candidate_id, "error": str(exc)})
            return
        if result.ok:
            self.store.set_active_call(result.call_id)
            self.last_dispatch_error = None
            audit.record(
                "call_dispatched",
                {
                    "candidate_id": decision.candidate_id,
                    "call_id": result.call_id,
                    "dispatcher": self.dispatcher_mode,
                    "simulated_input": decision.simulated_input,
                    "number": self.owner_phone,
                },
            )
        else:
            # keep candidate locked, clear active call, no retry
            self.store.set_active_call(None)
            self.last_dispatch_error = result.error
            audit.record(
                "dispatch_failed",
                {"candidate_id": decision.candidate_id, "error": result.error, "dispatcher": self.dispatcher_mode},
            )

    def end_call(self, duration_minutes: float = 0.0) -> None:
        self.store.end_call()
        if duration_minutes > 0:
            self.store.add_spend_minutes(duration_minutes, utcnow())
        audit.record("call_ended", {"duration_minutes": round(duration_minutes, 3)})

    # ----- operator controls -----

    def set_activity(self, activity: str) -> None:
        if activity not in ("seated", "moving", "unknown"):
            raise ValueError("activity must be seated|moving|unknown")
        self.activity = activity
        self.activity_provenance = "manual_demo_flag"

    def set_scenario(self, name: str) -> None:
        self.simulator.set_scenario(name)

    def set_kill(self, on: bool) -> None:
        self.store.set_kill_switch(on)
        audit.record("kill_switch", {"on": on})

    def reset_demo(self) -> None:
        self.store.reset_demo(utcnow())
        self.window.clear()
        self.latest_sample = None
        self.latest_decision = None
        self.last_dispatch_error = None
        audit.record("demo_reset", {})
