# Station measurement delivery (push agent + pull watcher)

Measurements reach MES through two mechanisms:

- **Pull (primary, transparent)** — `StationWatcher` polls shared network folders
  (`STATION_WATCH_PATHS`, one subfolder per station).
- **Push (standalone backup for isolated stations)** — `station_push_agent.py`
  runs on the station PC, watches a **local** output folder, and POSTs files to
  `POST /api/v2/quality/ingest`. Files are kept locally until the server ACKs, so
  a network outage never loses a measurement.

The push agent authenticates with a **long-lived station API key** — no admin
credentials are ever stored on a station PC.

## 1. Server: create a station key

On the MES server (from `backend/`):

```powershell
# one-time: migrate + seed (migration 0013 + station_ingest account)
python -m alembic upgrade head

# create a key (prints it ONCE — copy it to the station config)
python -m app.scripts.create_station_key --label "Station 1 - Quantum Neo"

# manage keys
python -m app.scripts.create_station_key --list
python -m app.scripts.create_station_key --revoke 1
python -m app.scripts.create_station_key --activate 1
```

The plaintext is never stored — only its SHA-256 hash (`station_keys` table).
The key is **only** valid on `POST /api/v2/quality/ingest` (it cannot access
materials/orders/odoo/admin routes).

## 2. Station PC: configure the agent

Copy `backend/app/scripts/station_agent.ini.example` to `station_agent.ini`
next to the agent (or let the **Download Agent Bundle** button in
Settings → Quality Stations generate it for you), edit `watch_dir`,
`mes_base_url`, `station_key`, then run:

```powershell
python station_push_agent.py            # runs in the foreground (logs to console + file)
```

Settings precedence: **CLI flag > environment variable > `station_agent.ini` >
built-in default**.

| setting | env var | config key | default |
|---|---|---|---|
| watch folder | `STATION_AGENT_WATCH_DIR` | `watch_dir` | (required) |
| MES base URL | `MES_BASE_URL` | `mes_base_url` | `http://127.0.0.1:8000` |
| station key | `STATION_AGENT_KEY` | `station_key` | (required) |
| archive dir | `STATION_AGENT_ARCHIVE_DIR` | `archive_dir` | `<watch>/Archive` |
| error dir | `STATION_AGENT_ERROR_DIR` | `error_dir` | `<watch>/Errors` |
| scan interval | `STATION_AGENT_SCAN_INTERVAL` | `scan_interval` | `30` |
| ledger path | `STATION_AGENT_LEDGER` | `ledger` | `<archive>/ledger.json` |

## 3. Package to a standalone .exe

```powershell
pip install pyinstaller
.\scripts\build_station_agent.ps1   # -> backend/app/static/agent/station_push_agent.exe
```

`--noconsole` means no pop-up window; the agent writes to `station_push_agent.log`
in its own folder.

## 4. Run silently as a background service

On the station PC (admin PowerShell), copy the `.exe` + `station_agent.ini` to a
folder (e.g. `C:\StationAgent`), then:

```powershell
# Option A — NSSM (https://nssm.cc, add to PATH):
.\scripts\deploy_station_agent.ps1 -ExePath "C:\StationAgent\station_push_agent.exe" `
  -WatchDir "C:\Station1\output" -MesBaseUrl "http://10.10.0.202:8000" -StationKey "<KEY>"

# Option B — Task Scheduler (no extra tools):
.\scripts\deploy_station_agent.ps1 ... -UseTaskScheduler
```

The script writes `station_agent.ini`, then registers the agent to auto-start at
boot (hidden, restarts on failure). Logs: `C:\StationAgent\station_push_agent.log`.
