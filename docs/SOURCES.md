# Sources & attributions

| Component | Source | License | Use |
|---|---|---|---|
| `hiyo/hr_parser.py` | [elsayed85/whoop](https://github.com/elsayed85/whoop) `whoop_ble/hr_parser.py`, commit `b6f5c3aa194c21adaf341115c92c5be5798f1b52` | MIT — Copyright (c) 2026 WHOOP BLE Research Contributors | Vendored unmodified except attribution header. Parses BLE Heart Rate Measurement (0x2A37). |
| `hiyo/whoop_ble.py`, `scripts/scan_whoop.py` | same repo (`tools/scan.py`, `tools/stream_hr.py`) | MIT | Original code; upstream used as reference for service/characteristic UUIDs and connect flow. |
| Design brief | `compiled16_whoop_ai_secretary_master_v1_1.md` (project-private) | n/a | Requirements source; not committed. |
| Alan Context | [Symbioose/alan-context](https://github.com/Symbioose/alan-context) | **No license declared** | Design reference only (decision linting, brief generation). **No code copied.** |
| Vapi | https://docs.vapi.ai | n/a | API docs for outbound call + webhooks. No code copied. |

MIT license text for vendored `hr_parser.py` is available upstream at
https://github.com/elsayed85/whoop/blob/b6f5c3aa194c21adaf341115c92c5be5798f1b52/LICENSE
