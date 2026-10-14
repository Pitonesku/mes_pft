# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Configurable Odoo dispatch timing (2026-10-11)
- The previously hardcoded dispatcher timing is now configurable via `PUT /api/v2/odoo/sync-settings` (and the web "Odoo Integration" screen): `odoo_verification_wait_minutes` (default 10), `odoo_error_retry_minutes` (default 5), `odoo_max_attempts` (default 5) and `odoo_poll_seconds` (default 30). Stored in `system_settings`, read by `outbound.py` helpers and the dispatcher loop, with validation (ints, minimums).

### Odoo completion: fix double-backorder + auto-consume non-direct components (2026-10-11)
- Fixed a partial-completion bug where `button_mark_done` returned a redirect action containing `mo_ids_to_backorder=None`, which Odoo's XML-RPC marshaller (`allow_none=False`) couldn't serialize; the MES then retried and completed the *next* backorder, double-counting production. `plan_completion` now sends `skip_redirection` (so `button_mark_done` returns `True`), and `post_completion` verifies `read_mo_state == "done"` before failing so a retry can never double-post.
- Consumption write-back now also auto-consumes the remaining (non-direct) BOM components — boxes, pallets, labels, etc. — proportionally to `produced_qty / planned_qty` (the same scale Odoo would apply) instead of leaving them at 0. `plan_consumption` gained a `proportion` argument; `manual_consumption` lines and lot/serial-tracked products are still skipped.
- Consumption write-back now detects "already consumed" via the move's `picked` flag and caps against the full demand (`product_uom_qty`) instead of `quantity`: Odoo 18 pre-populates raw `stock.move.quantity` to the reserved demand, which was making every reserved material look "already consumed" and silently skipping the reported paper/glue/triacetin and the boxes/pallets.

### Base Packaging → box_type guard & payload (Odoo ↔ MES, 2026-10-11)
- `mes_integration`: "Send to MES" and the auto-push on confirm now hard-fail when the finished product has zero or multiple `is_base_packaging` packagings — `_validate_base_packaging` raises a `UserError` (the post-commit auto-push marks the MO `error` and posts to chatter). The payload now carries top-level `box_type` (rods/box, e.g. a Case of 7.75 in the "1000pcs" UoM → 7750) and `base_packaging_name`.
- MES `OdooMoEvent` accepts `box_type` / `base_packaging_name`; `handle_mo_event` stores the top-level `box_type` (falling back to `spec.box_type`) into `PurchaseOrder.box_type`, which the tablet pre-fills as "Box Type" via `build_spec_snapshot`.

### Safe MO recall guardrails (backend, 2026-10-11)
- New `POST /api/v2/odoo/mo-recall` (HMAC-protected, same `_verify_odoo_webhook` as `mo-event`): rejects with `409` when the MO is open on a machine or has production data (`end_counter`, manual QC checks, station measurements); otherwise archives/hides the unstarted order (`is_archived`, `is_hidden`, `odoo_state='recalled'`, `sync_mode='link_only'`) — never deletes. Logic in `services/odoo/recall.py` (pure, unit-tested). The Odoo `mrp.production` unlink/recall override is outlined in `docs/mes-roadmap-ideas.md` (to implement later).

### Shift Quality Report overhaul (2026-10-11)
- **Certificate-style shift quality report** in `pdf_generator.py` (`render_shift_quality_pdf`): header (PO + specification + **real machine name** + date + `DD.MM.YYYY HH:mm – HH:mm` shift interval + operator), the fixed **5-parameter matrix** (length `mm`, diameter `mm`, pressure drop `mm WG`, hardness `%`, weight `g/100`) with `Nominal / Lower SL / Upper SL / Mean / SD` (station data wins, manual fills gaps, SD only when n≥2, else dash), and a chronological **manual checks log table** (`# / Time / Length / Weight / Glue Seam / Cut Quality / Visual Cleanliness / Operator / Notes`), with a "No manual checks recorded for this shift" row when empty.
- **UTF-8 font**: bundles DejaVu Sans (regular + bold) and registers it with reportlab, so Ukrainian/Hungarian/Latin characters render without tofu boxes.
- `/shifts/{id}/certificate.pdf` now renders via the new report (machine binding fixed: `ShiftSession.machine_id → Machine.name`, fallback `ProductionReport.machine_name`).

### Shift + MO quality reports (2026-10-11)
- **Shift quality report**: the printable "Quality Report" is now a certificate-style document (English only) — header with `PO Number`, `Specification` (e.g. `7.72*108PD 380 CU 0`), machine/date/shift/operator, then the 5-parameter measurement table (length, diameter, pressure drop, hardness, weight) with `Nominal / Lower SL / Upper SL / Mean / SD`. Values come from the server's merged run/order summary, so the operator's manual length/hardness/weight appear.
- **MO quality report** = average of the shift reports (`compute_order_summary`); a new **"Print MO Quality Report"** action on the Orders statistics tab opens it.
- **Removed** the monitor-only `FINAL VERDICT` and the SD Yellow/Red threshold columns from the report — SD is shown as a plain value (yellow/red stays on the shop-floor monitor view).
- `/v2/quality` now returns a `report` block (spec string + certificate + manual measurements + remarks); `_shift_quality_summary` merges the shift's manual QC checks into the station stats.

### Manual measurements merged into station stats & Odoo QC (2026-10-11, migration 0020)
- **Hardness** added to manual QC checks (`manual_quality_checks.hardness`, migration 0020), the check payload/evaluation rules and the Flutter QC screen (percent).
- **Merge of manual + station measurements**: new pure helpers `quality_stats.manual_rods()` and `merge_manual_parameters()` convert operator checks into pseudo-rods (weight g/rod, length mm, hardness %) and fill any parameter the station did not measure — length and hardness always, weight only as a fallback — into the run/order `parameters`. A station measurement is never overwritten.
- **Run/order summaries** now carry `remarks` (joined check notes) and `manual_measurements` (count + per-parameter mean/SD).
- **Odoo QC tab** (`mes_integration` v18.0.1.1.0) gains `mean_length/sd_length`, `mean_weight/sd_weight` (g/100), `mean_hardness/sd_hardness` and `quality_notes`; the MES writes them from the merged summary (weight scaled to g/100). Diameter/PD/status/counts field names were already a match.
- App version bumped to `2.1.1+44`.

### Shift / machine / MO lifecycle (2026-10-10, migrations 0018-0019)
- **Machine lives on the production run** (`production_runs.machine_id`); a shift is an operator session. New `POST /api/v2/shifts/{id}/change-machine` keeps the shift open and starts a new run on the new machine.
- **Fixed MO switch**: `switch-mo` used a hard-coded `seq=1` (violating `UNIQUE (shift_id, seq)`), started the new run at the shift start and never recorded the final counter. Runs now get `max(seq)+1`, start now, store `end_counter` and are audited in `run_change_log`.
- **No phantom runs**: close / stop / takeover / auto-close close the shift's open runs; one open run per machine is DB-enforced (`one_open_run_per_machine`). Migration 0018 repairs existing phantom runs.
- **Manual QC checks** are bound server-side to the open run (machine + MO snapshot), weight is grams per N (default 10) rods, toggles are tri-state, verdicts are stored, checks can be voided and queued offline (`client_check_id`). They appear in each run of the shift summary (schema 1.2).
- **One report per MO run**: `production_reports.run_id/shift_id`; the server re-validates the link by MO number. MO / machine of a linked report change only through the supervisor endpoint `POST /api/v2/runs/{id}/reassign` (reason required, cascades, audited).
- **Fixes**: flat run spec snapshots gave no limits; overnight early-open produced an end time in the past (auto-close fired immediately); live ingest silently dropped `MO_MISMATCH`; `ended_at` was unvalidated.
- **Removed**: unused `shift_quality_stats` table/model, `backend/_cats.py`, `backend/_t.txt`, `[DEBUG]` prints in `create_report`, unauthenticated `/api/debug/last-report`, the stale Flutter counter widget test.
- Roadmap and remaining gaps: `docs/mes-roadmap-ideas.md`.

### Security & Reliability (2026-08-28 hardening)
- **Bearer-token authentication** (`auth.py`): replaced the spoofable `X-User-Id` header with HMAC-signed bearer tokens. `POST /api/auth/login` now returns `access_token`; report-submission, admin, and AI endpoints require `Authorization: Bearer <token>`.
- **Secrets hardening**: added `.gitignore` rules for `.env.txt`, `Gdrive_secret.json`, `token.json`, `nohup.out`, `*.jks`, `*.keystore`, `key.properties`.
- **Fixed missing Telegram worker**: added `telegram_outbox_worker` so offline/synced reports (`report_outbox` telegram queue) now send their Telegram notification.
- **Duplicate-report idempotency**: added `client_report_id` (column + partial unique index + endpoint guard) to `POST /api/reports` and `POST /api/reports/sync`.
- **Fixed PO counter race**: lock the `PurchaseOrder` row (`SELECT ... FOR UPDATE`) before recomputing `produced_qty`.
- **Telegram reliability**: removed fragile `parse_mode: "Markdown"`, added terminal `failed` state after 10 attempts, cleared `last_error` on success.
- **DB pool_pre_ping**: added `pool_pre_ping=True` to SQLAlchemy engines.
- App version bumped to `2.1.1+27`; release signing uses a persistent keystore (see `BUILD_DEPLOY.md`).

### Fixed
- **Operator screen compilation error**: Fixed bracket/parenthesis mismatch in `operator_screen.dart` around `Expanded` / `SingleChildScrollView` / `Column` nesting in the report preview dialog. Three closing brackets were missing after the `children` list, causing subsequent widgets (`Divider`, `Row`) to be incorrectly parsed as extra positional arguments.
- **Cross-platform path resolution for PDF archive & APK releases**: `LOCAL_PDF_ARCHIVE_PATH` and `APK_RELEASES_DIR` env vars containing Windows absolute paths (e.g. `C:\src\...`) no longer create malformed folder trees when running on Linux/Docker/WSL. A new `resolve_universal_path()` helper in `main.py` normalizes paths across native Windows, WSL Ubuntu, and Docker Linux containers, converting `C:\...` ↔ `/mnt/c/...` as needed, and falls back to the application directory when env vars are unset.

---

## [2.0.1] — Build 2 — 2026-06-30

### Added
- **Offline report with PDF storage**: When network is unavailable, submitted reports are stored locally in SQLite with full report data AND generated PDF (base64). The PDF is generated immediately in Flutter before saving, ensuring no data loss.
- **"Not sent" indicator**: Pending reports in the Local tab show an orange "Not sent" badge and a cloud-upload icon. The detail view displays a banner: *"This report has not been sent to the server yet. It will be sent automatically when the network is available."*
- **Report protection**: Pending reports (status='pending') are immutable — neither EDIT nor DELETE buttons appear. Only synced reports can be edited, and only drafts can be deleted. This matches server-side behavior for report integrity.
- **Server/Local tabs in History**: Two-tab view in Production History: **Server** (fetches from API) and **Local** (SQLite reports: pending + draft + synced). Each tab shares the same date-range filter.
- **Background GDrive PDF upload worker** (`gdrive_worker`): Server-side background thread that polls `report_outbox` for pending PDF uploads and sends them to Google Drive in the correct `YYYY/MM/` folder structure. Also saves a local archive copy.
- **Combined sync endpoint** (`POST /api/reports/sync`): Atomically saves report data to DB, updates PO counters, queues TG message, and queues PDF for GDrive upload — all in a single API call. Accepts `pdf_base64` and `pdf_filename` fields.
- **`ReportOutbox` model**: Unified delivery queue on the server for all report outbound actions (`telegram`, `pdf_gdrive`, `db_save`). Workers poll this table independently.
- **Periodic background sync**: A 60-second `Timer.periodic` in `main.dart` calls `SyncManager.syncReports()` and `AppData.syncPendingSetupChanges()`, so pending reports are sent as soon as the network becomes available.
- **Local DB schema v3**: Added `pdf_data`, `sync_attempts`, and `last_sync_error` columns to the local `reports` table for offline PDF storage and sync tracking.
- **`ApiService.syncReport()`**: New method that sends report + PDF base64 to `POST /api/reports/sync` in one call, replacing the old two-step (report first, then PDF).

### Fixed
- **PDF not uploaded for offline reports**: Previously, `SyncManager.syncReports()` only called `submitProductionReport()` (which sends report JSON only). PDF was never included. Now it calls `ApiService.syncReport()` with both report data and `pdf_base64`.
- **Telegram-only delivery**: Offline-submitted reports were only queued in `telegram_queue`. Now they go through `report_outbox` for all three delivery types.
- **No local "Not sent" visibility**: Operators couldn't tell which reports were pending. The Local tab and status badges now make this unambiguous.

### Changed
- **SyncManager** now uses `LocalDB.saveReportWithPdf()` / `markReportSynced()` / `incrementSyncAttempts()` for better tracking.
- **Operator screen** `_submitReport()` offline path now generates a full PDF before saving locally, instead of just saving JSON.
- **History screen** `_loadHistory()` supports server/local tab switching and injects `_local_status` metadata for UI indicators.
- **App startup** now triggers `SyncManager.syncReports()` + `AppData.syncPendingSetupChanges()` immediately and periodically every 60 seconds.

---

## [2.0.0] - 2026-06-28

### Added

#### Web Interface (Flutter Web)
- **Full web shell** (`web_shell.dart`): Dark navigation rail with role-based menu items. SuperAdmin sees all sections; Manager/Operator see Dashboard, Orders, Reports, Materials, My Profile.
- **Dashboard screen**: KPI cards (Total Reports, Rods Produced, Total Waste, Open POs) for the last 30 days. Recent Reports table with columns: Date | Shift | Machine | Operator | PO | Rods Produced | Submitted. Clicking any row opens a resizable side-panel with full report details.
- **Orders screen**: Full PO management — sortable/filterable table, resizable detail side-panel with progress bar, tech specs, materials, hide/show toggle, edit dialog, delete with confirmation. Statistics tab (audit) shows per-report breakdown, production summary, and materials consumed. Print/Save PDF button generates an audit PDF matching the Android version.
- **Reports screen**: Filterable table (Date | Shift | Machine | Operator | PO | Submitted | Status). Clicking a row opens the shared `ReportDetailPanel` side-panel.
- **Materials screen**: Full CRUD for the material dictionary — table with Material Type | Category | Default Batch | Hidden. Add/Edit dialog with category dropdown and hidden toggle.
- **Users screen** (superAdmin only): Full CRUD — table with Username | Email | Role | Can Modify PO | Status. Add/Edit dialog with role dropdown, password field, inactive toggle.
- **Machines & Shifts screen** (superAdmin only): Tabbed layout — Machines tab and Shifts tab, each with Add/Edit/Delete. Changes are queued and synced to the server (same logic as Android).
- **My Profile screen**: Avatar, role chip, editable name/email, change-password section (current + new + confirm). Saves via `ApiService.updateUser`.
- **Resizable panel layout** (`resizable_panel.dart`): Drag-to-resize side panel used across Dashboard, Orders, and Reports screens.
- **Shared ReportDetailPanel** (`report_detail_panel.dart`): Reusable widget showing all report fields — production numbers, filter specs, materials with batches and kg, remarks, manual-edit flag, submission timestamp. Used by Dashboard, Orders (audit), and Reports screens.

#### Backend (`production_api/`)
- **SQLAdmin web admin panel** (`admin.py`): Full browser-based CRUD for all database models (Users, Roles, PurchaseOrders, Reports, Machines, Shifts, Materials, etc.) accessible at `/admin`. Secured with HTTP Basic Auth using `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars.
- **`itsdangerous==2.1.2`** added to `requirements.txt` (required by sqladmin for session signing).

#### Flutter App
- **`dev_banner.dart`**: Reusable "DEVELOPING" banner widget controlled by `kIsDeveloping` in `config.dart`. Set to `false` for production builds.
- **`config.dart`**: Single-file production flag (`kIsDeveloping`). Now set to `false` for this release.
- **`file_logger.dart`**: Web-safe file logger — all methods are no-ops on web (`kIsWeb` guard), preventing `MissingPluginException` from `path_provider` on the browser platform.
- **PDF export refactored** into platform-conditional files: `pdf_export.dart` (interface), `pdf_export_android.dart` (saves to local storage + print dialog), `pdf_export_web.dart` (browser download), `pdf_export_stub.dart` (no-op for unsupported platforms), `pdf_layout_service.dart` (shared layout logic), `report_pdf_controller.dart` (controller).

### Fixed
- **Report Entries table in audit panel**: Replaced horizontal-scrolling `DataTable` with a `LayoutBuilder`-based `Table` that fills the panel width proportionally — no more horizontal scroll in the side panel.
- **Materials Consumption in audit panel**: Replaced tree/indented view with a flat table (Category | Material Type | Batch | Used). Type subtotal rows shown in bold blue-grey; category total rows shown in bold purple.
- **PDF audit report — Total rows**: Switched from `pw.Table.fromTextArray()` to a manually built `pw.Table` so Total rows (type-level and category-level) are rendered in bold with tinted backgrounds.
- **FileLogger on web**: `MissingPluginException` for `getApplicationDocumentsDirectory` no longer thrown when running as Flutter Web.

### Changed
- **`requirements.txt`**: Added `sqladmin==0.18.0`, `wtforms==3.1.1`, `itsdangerous==2.1.2`, `androguard==3.3.5`, `aiofiles==23.2.1`.
- **Dev banner**: `kIsDeveloping` set to `false` — the red "DEVELOPING" banner is no longer shown in production builds.

---

## [1.0.1] - 2026-06-15

### Added
- **Web UI -- Reports page**: Redesigned with correct columns (Date, Shift, Machine, Operator, PO, Submitted, Status). Clicking any row opens a slide-in detail panel showing all report fields (production numbers, filter specs, materials with batches and kg, remarks, manual-edit flag, submission timestamp). Columns use the same ApiService.fetchReports() as the mobile history screen.
- **Web UI -- Orders page**: Full PO management in the browser. Clickable rows open a side panel with: full PO details (general, tech specs, materials), progress bar, hide/show toggle, edit form (dialog with all fields), delete with confirmation, and a statistics tab (audit summary mirroring the Android AuditPage -- total rods, boxes, waste, materials consumed, and per-report breakdown). Create New PO button available in the toolbar.
- **First-startup auto-seed**: On first run with an empty database the API automatically creates an `admin` role (all permissions enabled) and a default admin user. Credentials are read from `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` env vars (defaults: `admin` / `admin` / `admin@factory.local`). A loud console warning is printed when defaults are in use so they are never left unchanged in production. The seed is fully idempotent and is skipped on every subsequent startup once any roles or users already exist.
- **Auto-update system**: App now checks for updates on startup. If a newer APK is available on the server, a dialog prompts the user to download and install it automatically.
- **`GET /api/app/latest-version`** endpoint: Returns the latest APK version info (version name, build number) by scanning the `apk_releases/` folder on the server. Uses `androguard` to extract version from APK metadata, with filename-based fallback (`prod_log_v1.0.3_b4.apk`).
- **`GET /api/app/download`** endpoint: Streams the latest APK file for direct download and installation on Android devices.
- **Auto-named APK builds**: `build.gradle.kts` updated so `flutter build apk --release` automatically outputs `prod_log_v<version>_b<build>.apk` (e.g. `prod_log_v1.0.0_b1.apk`).
- **`update_checker.dart`**: New Flutter utility class that compares current app version with server version and handles download + install flow.
- **`package_info_plus`** and **`url_launcher`** added to Flutter dependencies for version detection and APK install triggering.

### Fixed
- **Cross-device "copy from previous report"**: The "use data from previous report" dialog now queries the server API instead of only the local SQLite DB, so it works correctly across all tablets/devices.
- **Report submission time timezone**: `sync_at` timestamps are now returned from the API with a `Z` UTC suffix, and the Flutter history screen converts them to local time using `.toLocal()` before display.
- **Material delete/edit with special characters**: `PUT /api/materials/{old_name:path}` and `DELETE /api/materials/{material_name:path}` now use FastAPI's `:path` converter to handle material names containing `/`, `,`, and other special characters.
- **Machine name in "last report" API**: Changed `GET /api/reports/last-by-machine` to use a query parameter (`?machine_name=...`) instead of a path parameter, fixing issues with machine names containing `#` and spaces (e.g. `Machine #1`).

### Changed
- **Local DB cleanup**: Reports older than 5 days are automatically removed from the local SQLite database on each successful server sync (keeps `draft` and `pending` reports regardless of age).
- **`androguard==3.3.5`** and **`aiofiles==23.2.1`** added to `requirements.txt`.

---

## [1.0.0] - 2026-06-01

### Added
- Initial production release.
- Operator report submission with shift, machine, PO, lot, and material tracking.
- Admin dashboard with PO management, material dictionary, user management.
- Production history screen with date range filter.
- PDF report generation and Google Drive upload.
- Telegram notifications on report submission.
- Local SQLite offline queue with automatic sync.
- Audit screen for PO-level production statistics.
