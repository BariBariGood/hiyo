# Vendored from https://github.com/elsayed85/whoop
# File: whoop_ble/hr_parser.py
# Commit: b6f5c3aa194c21adaf341115c92c5be5798f1b52
# License: MIT (see docs/SOURCES.md). Copyright (c) 2026 WHOOP BLE Research Contributors.
# Vendored unmodified except for this attribution header.

"""Parse Bluetooth Heart Rate Measurement (0x2A37) payloads."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HeartRateMeasurement:
    bpm: int | None
    flags: int
    hr_is_16bit: bool
    sensor_contact_supported: bool
    sensor_contact_detected: bool | None
    energy_expended: int | None
    rr_intervals_ms: list[float] = field(default_factory=list)
    raw_hex: str = ""

    @property
    def has_rr(self) -> bool:
        return bool(self.rr_intervals_ms)


def parse_heart_rate(data: bytes | bytearray) -> HeartRateMeasurement:
    """
    Decode a Heart Rate Measurement notify per Bluetooth SIG spec.

    RR intervals are in units of 1/1024 second; returned values are milliseconds.
    """
    raw = bytes(data)
    if not raw:
        return HeartRateMeasurement(
            bpm=None,
            flags=0,
            hr_is_16bit=False,
            sensor_contact_supported=False,
            sensor_contact_detected=None,
            energy_expended=None,
            raw_hex="",
        )

    flags = raw[0]
    idx = 1
    hr_is_16bit = bool(flags & 0x01)

    bpm: int | None
    if hr_is_16bit:
        if len(raw) < 3:
            bpm = None
        else:
            bpm = int.from_bytes(raw[idx : idx + 2], "little")
            idx += 2
    else:
        if len(raw) < 2:
            bpm = None
        else:
            bpm = raw[idx]
            idx += 1

    contact_supported = bool(flags & 0x04)
    contact_detected: bool | None = bool(flags & 0x02) if contact_supported else None

    energy: int | None = None
    if flags & 0x08:
        if idx + 2 <= len(raw):
            energy = int.from_bytes(raw[idx : idx + 2], "little")
            idx += 2

    rr_ms: list[float] = []
    if flags & 0x10:
        while idx + 2 <= len(raw):
            rr_units = int.from_bytes(raw[idx : idx + 2], "little")
            rr_ms.append(round(rr_units / 1024.0 * 1000.0, 1))
            idx += 2

    return HeartRateMeasurement(
        bpm=bpm,
        flags=flags,
        hr_is_16bit=hr_is_16bit,
        sensor_contact_supported=contact_supported,
        sensor_contact_detected=contact_detected,
        energy_expended=energy,
        rr_intervals_ms=rr_ms,
        raw_hex=raw.hex(),
    )
