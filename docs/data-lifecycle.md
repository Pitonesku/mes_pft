# Data lifecycle

From the quality test station to the database, dashboards and Odoo.

## 1. Station output

Quantum Neo writes a CSV (or XML, in a future firmware) per measured batch into a
network share. The CSV has a metadata header (instrument, maker, team, shift,
sample id, produced-on, batch start/end, comments, batch description) followed by
the rod table (PD, weight, diameter, ovality, roundness, shape) and a footer with
Mean/Min/Max/SD/CofV.

## 2. Ingestion

`StationWatcher` polls the pull folders configured per station
(**Settings → Quality Stations**, `station_profiles.watch_path`; the legacy
`STATION_WATCH_PATH`/`STATION_WATCH_PATHS` env vars are static fallbacks only),
picks up only stable (non-zero size) `.csv`/`.xml` files, computes SHA-256 + MD5,
and skips any file already in `ingestion_files`. It parses via `QuantumCsvParser`,
resolves machine → shift → run, then inserts `quality_samples` +
`quality_measurements` in one transaction.

## 3. Storage (PostgreSQL)

- `quality_samples` — one row per file/batch (link status + machine + timestamps).
- `quality_measurements` — one row per rod; `shift_id`/`run_id` are denormalized
  copies and **nullable** (calibration/maintenance/no-shift).
- `shift_sessions` / `production_runs` — the operational aggregate and MO runs.
- `quality_specs` — per-parameter limits (nominal/lower/upper).
- `shift_quality_stats` / `shift_summaries` — aggregated, versioned results.

## 4. BI / reporting views

Read-only PostgreSQL views expose the same data to any BI or reporting tool
(created by migration `0002_quality_views.py`), replacing the old SQLite file
and ad-hoc SQL:

- `v_quality_rods` — rod-level rows with machine, shift, run and spec limits.
- `v_run_stats` — per-run mean/SD/min/max/out-of-spec for the live dashboard.
- `v_worker_status` — watcher heartbeat (replaces `worker_status` in SQLite).

Row order is `(measured_at, sample_id, rod_no)` (the old dashboard used `rowid`).

## 5. Aggregation + certificate

`aggregation.py` loads a run's rods, builds `ParamSpec`s from the frozen
`spec_snapshot`/`quality_specs`, and calls `quality_stats.compute_run_stats` +
`certificate_rows`. Results are written as `shift_quality_stats` and a versioned
`shift_summaries` JSON, which drives the PDF certificate and the Odoo payload.

## 6. Odoo

`odoo_outbox` stores the idempotent payload per shift/run. A background dispatcher
sends it to Odoo Community 18 via XML-RPC (API key), mapping runs to
`mrp.production`, the shift to `mrp.workorder`, and quality to the custom
`mes_integration` addon (`quality.check` is Enterprise-only). The connector also
handles inbound order linking, shadow-mode rehearsal, background reconciliation,
MO recall guardrails and quarantine-release inventory adjustments — see
`docs/odoo-integration.md`.
