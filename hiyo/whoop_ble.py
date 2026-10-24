"""WHOOP BLE heart-rate streamer.

Standard BLE Heart Rate Service (0x180D) / Heart Rate Measurement
characteristic (0x2A37) only — no proprietary protocol. Parses with the
vendored hr_parser. The notification callback only pushes onto an
asyncio.Queue (no I/O in callback). Reconnects with bounded exponential
backoff and emits SENSOR_UNAVAILABLE on drop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .hr_parser import parse_heart_rate
from .models import SensorSample

log = logging.getLogger("hiyo.ble")

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 30.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WhoopBleStreamer:
    """Connects to a WHOOP strap and streams SensorSamples into a queue.

    Queue items:
      {"type": "sample", "sample": SensorSample}
      {"type": "status", "status": "connected" | "unavailable", "detail": str}
    """

    def __init__(self, address: str, queue: asyncio.Queue) -> None:
        self.address = address
        self.queue = queue
        self._stop = asyncio.Event()

    def _on_disconnect(self, _client: object) -> None:
        # bleak calls this from its own context; emit is thread-safe enough
        # for put_nowait on a same-loop queue.
        self._emit({"type": "status", "status": "unavailable", "detail": "disconnected"})

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, item: dict) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            log.warning("BLE queue full; dropping %s", item.get("type"))

    async def run(self) -> None:
        """Async entry point; run as an asyncio task."""
        try:
            from bleak import BleakClient
            from bleak.exc import BleakError
        except ImportError:  # pragma: no cover
            log.error("bleak not installed")
            self._emit({"type": "status", "status": "unavailable", "detail": "bleak-missing"})
            return

        backoff = INITIAL_BACKOFF_S
        while not self._stop.is_set():
            client: BleakClient | None = None
            try:
                client = BleakClient(self.address, disconnected_callback=self._on_disconnect)
                await client.connect()
                self._emit({"type": "status", "status": "connected", "detail": self.address})
                backoff = INITIAL_BACKOFF_S

                def callback(_char: int, data: bytearray) -> None:
                    # No I/O here: parse + enqueue only.
                    m = parse_heart_rate(data)
                    now = utcnow()
                    self._emit(
                        {
                            "type": "sample",
                            "sample": SensorSample(
                                source="whoop_ble",
                                device_model="whoop_5",
                                observed_at=now,
                                received_at=now,
                                bpm=m.bpm,
                                rr_ms=list(m.rr_intervals_ms),
                                contact_detected=m.sensor_contact_detected,
                                motion_state="unknown",
                                simulated=False,
                            ),
                        }
                    )

                await client.start_notify(HR_MEASUREMENT_UUID, callback)
                while client.is_connected and not self._stop.is_set():
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # BleakError, timeouts, etc.
                log.info("BLE connect/stream failed: %s", exc)
                self._emit({"type": "status", "status": "unavailable", "detail": str(exc)})
            finally:
                if client is not None:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
            if not self._stop.is_set():
                self._emit({"type": "status", "status": "unavailable", "detail": "reconnecting"})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
