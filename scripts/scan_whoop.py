"""Scan for nearby BLE devices advertising Heart Rate Service 0x180D
or with "WHOOP" in the name. macOS addresses are CoreBluetooth UUIDs.

Usage: uv run python scripts/scan_whoop.py [--timeout 10] [--broad]
"""

from __future__ import annotations

import argparse
import asyncio

import bleak

HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--broad", action="store_true", help="unfiltered scan (all devices)")
    args = ap.parse_args()

    def on_found(device, adv):
        name = device.name or adv.local_name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        interesting = HR_SERVICE in uuids or "whoop" in name.lower()
        tag = " <== CANDIDATE" if interesting else ""
        print(f"{device.address}  rssi={adv.rssi}  name={name!r} uuids={uuids}{tag}")

    kwargs = {} if args.broad else {"service_uuids": [HR_SERVICE]}
    scanner = bleak.BleakScanner(detection_callback=on_found, **kwargs)
    await scanner.start()
    print(f"scanning {args.timeout}s (broad={args.broad}) — macOS addresses are CoreBluetooth UUIDs")
    await asyncio.sleep(args.timeout)
    await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
