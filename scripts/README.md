# scripts/

Operational and maintenance scripts for the **mes_pft** cigarette-filter MES.

All scripts are run from the repository root (e.g. `Documents\Python\mes_pft`).
The `.ps1` scripts require Windows (PowerShell); the `.sh` scripts run under
WSL / Linux, typically on the production server. Run PowerShell scripts with:

```
powershell -ExecutionPolicy Bypass -File scripts\<script>.ps1 [args]
```

---

## Deployment (production server)

### `install_server.ps1`
The **installer**. Copies the project to `C:\MES_System`, creates a fresh Python
virtual environment, installs `backend/requirements.txt`, and registers a
boot-time Windows Scheduled Task (`MES_Server`) that runs uvicorn as `SYSTEM`
(hidden, output routed to `C:\MES_System\logs\server.log`). Seeds `.env` from
the source (or `.env.example`) only if one does not already exist, and ships the
Flutter web console (`frontend\build\web`) if it is present.

- **Requires:** elevated PowerShell; Python on `PATH` (override with `-Python`).
- **Run from:** the development folder.

| Parameter | Default | Description |
| --- | --- | --- |
| `-TargetDir` | `C:\MES_System` | Production install directory. |
| `-TaskName` | `MES_Server` | Scheduled Task name. |
| `-Port` | `8000` | HTTP port the server listens on. |
| `-Python` | `python` | Base interpreter used to create the venv. |
| `-RunMigrations` | off | Also run `alembic upgrade head` before first start. |

```
powershell -ExecutionPolicy Bypass -File scripts\install_server.ps1
```

### `update_server.ps1`
The **updater**. Stops the `MES_Server` task, overwrites the updated files
(preserving the venv, `.env`, database files, logs and generated artefacts so
production data is never wiped), installs any new dependencies, applies Alembic
migrations (on by default) and restarts the service.

- **Requires:** elevated PowerShell; a prior `install_server.ps1`.
- **Run from:** the *updated* development folder.

| Parameter | Default | Description |
| --- | --- | --- |
| `-TargetDir` | `C:\MES_System` | Production install directory. |
| `-TaskName` | `MES_Server` | Scheduled Task name. |
| `-SkipMigrations` | off | Skip `alembic upgrade head`. |

```
powershell -ExecutionPolicy Bypass -File scripts\update_server.ps1
```

---

## Database (dump, restore, migrate)

### `dump_prod.sh`
Dumps the LIVE production database to a custom-format archive (`pg_dump -Fc`),
the format expected by `restore_test_db.*` and `run_migration.ps1`. Edit the
`DB_*` placeholders at the top of the file first.

- **Run:** inside WSL on the remote production server.
- **Output:** `production_log_db_dump` (or the first argument).

```
bash scripts/dump_prod.sh [output-file]
```

### `restore_test_db.ps1` / `restore_test_db.sh`
Restores the custom-format production dump into the LOCAL test Postgres
container (`mes_db_test`, host port `5433`). Windows (`.ps1`) and WSL (`.sh`)
variants of the same job.

- **Requires:** `docker compose --profile test up -d db_test`.

```
powershell -ExecutionPolicy Bypass -File scripts\restore_test_db.ps1 [-Dump production_log_db_dump]
bash scripts/restore_test_db.sh [path/to/dump]
```

### `run_migration.ps1`
Full test pipeline: restores the production dump into an **isolated** test DB,
runs `alembic upgrade head`, backfills the unified quality tables from
`measurements.db`, then reports row counts. Use it to validate a migration
against production data before touching the live server.

- **Requires:** a running Postgres (Docker test container on `5433`, or any
  reachable server).

| Parameter | Default | Description |
| --- | --- | --- |
| `-Dump` | `production_log_db_dump` | Custom-format dump to restore. |
| `-Sqlite` | `measurements.db` | SQLite source for the ETL backfill. |
| `-DbHost` | `127.0.0.1` | Target Postgres host. |
| `-DbPort` | `5433` | Target Postgres port. |
| `-DbUser` | `postgres` | Target Postgres user. |
| `-DbPassword` | `test_password` | Target Postgres password. |
| `-DbName` | `mes_test_db` | Target database name. |
| `-PgBin` | *(empty)* | Optional path to the PostgreSQL `bin` dir. |

```
powershell -ExecutionPolicy Bypass -File scripts\run_migration.ps1
```

---

## Station agent (station / tablet PCs)

### `build_station_agent.ps1`
Builds the standalone Windows executable for the station push agent with
PyInstaller (`--onefile --noconsole`).

- **Requires:** `pip install pyinstaller`.
- **Output:** `backend\app\static\agent\station_push_agent.exe`.

```
powershell -ExecutionPolicy Bypass -File scripts\build_station_agent.ps1
```

### `deploy_station_agent.ps1`
Deploys the station push agent as a silent background service on a station PC:
writes `station_agent.ini` next to the exe and registers it to run at boot via
**NSSM** (default) or **Task Scheduler** (with `-UseTaskScheduler`).

| Parameter | Default | Description |
| --- | --- | --- |
| `-ExePath` | *(required)* | Path to `station_push_agent.exe`. |
| `-WatchDir` | *(required)* | Station output folder to watch. |
| `-MesBaseUrl` | *(required)* | MES server base URL. |
| `-StationKey` | *(required)* | Station ingest key. |
| `-ServiceName` | `StationIngest` | Service / task name. |
| `-UseTaskScheduler` | off | Use Task Scheduler instead of NSSM. |

```
powershell -ExecutionPolicy Bypass -File scripts\deploy_station_agent.ps1 `
  -ExePath "C:\StationAgent\station_push_agent.exe" `
  -WatchDir "C:\Station1\output" -MesBaseUrl "http://10.10.0.202:8000" `
  -StationKey "<KEY>" -UseTaskScheduler
```
