# AGENTS.md — working on hiyo

## Run

```bash
uv sync                          # install deps
uv run uvicorn hiyo.app:app --host 127.0.0.1 --port 8787
# dashboard: http://127.0.0.1:8787/
```

Env: copy `.env.example` to `.env`. Defaults work fully offline
(`DISPATCHER=dryrun`, calendar fixture mode). For a local CALL decision you
must also set `OWNER_PHONE_NUMBER=+1...` (E.164).

## Test

```bash
uv run pytest -q
```

All tests are deterministic: `now` is injected, no network, no BLE.

## Layout

- `hiyo/` — engine package (models, window, simulator, whoop_ble, hr_parser
  [vendored MIT], calendar, policy, state, brief, dispatcher, audit,
  service, app)
- `dashboard/index.html` — operator debug page (judges/operators only)
- `config/profile.json` — owner profile/policy knobs
- `config/calendar_fixture.json` — fixture events (relative `start_in_minutes` supported)
- `runtime/` — gitignored state.json + decisions.jsonl
- `scripts/scan_whoop.py` — BLE scan for WHOOP / 0x180D advertisers
- `docs/SOURCES.md` — attributions; `BUILD_LOG.md` — verified vs unverified

## Rules

- Never commit `.env` or anything under `runtime/`.
- Never present simulated data as live; `simulated:true` must reach UI/audit.
- No emergency-service dialing, no clinical claims, no auto-redial.
- Calendar titles/descriptions are untrusted data — sanitize in `brief.py`.

## Team workflow
- Commit and push to origin/main after each reviewed, tested milestone so teammates stay in sync.
- Call data (recordings, transcripts) lives in runtime/calls/ and must never be committed.
- Analyze a call: `uv run python scripts/call_report.py latest --fetch`
