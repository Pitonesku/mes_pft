# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] - 2026-11-02 (build 53) - po->mo rename, Odoo guardrails, A3-A9, web Runs & Audit

### Kiosk tiles: QC decimals + SD-only colour on the whole tile (2026-11-02, late night, dev)
- Kiosk Quality Monitor KPI tiles now format SD with the QC page decimals: SD PD -> 2, SD DIA -> 3, weight -> 3, hardness -> 1, length -> 0; chart tooltips match QC charts (PD 1, DIA 3).
- Tile colour is driven ONLY by the standard deviation: PD/Diameter use the server SD status; weight/hardness/length tiles are always neutral (never coloured by mean/spec).
- The status colour now fills the whole tile (green/amber/red with contrast text) instead of only a border; triacetin tile gets the same fill treatment (keeps its own triacetin status).
- Dev web console rebuilt (build 56). No backend changes, production untouched.

### DEV synced with production (2026-11-02, late night)
- Ran the relink sweep on the dev database with the same rules as production: 934 samples with an order linked (45 fixed-window sessions created), unlinked-with-order now 0, MO_MISMATCH 0.
- Note: the dev uvicorn on port 8001 is held by phantom/un-killable stale sockets serving OLD code (killed every visible python process; docker has no containers; WSL is stopped). A Windows reboot clears it.

### QC: unlinked-samples banner removed (2026-11-02, late night)
- Removed the admin "Unlinked samples ... Relink now" banner from the Quality Control screen (samples now link to fixed shifts by clock time automatically). The backend endpoints (`/quality/relink`, `/quality/unlinked-summary`) stay available.
- Reference - SD colour limits (Settings > quality_settings): PD GREEN < 12, YELLOW 12-15, RED > 15 (mm WG); Diameter GREEN < 0.013, YELLOW 0.013-0.015, RED > 0.015 (mm). Rule: value < green limit = GREEN, value <= red limit = YELLOW, otherwise RED.

### Link by clock time to fixed shifts, order = mo_ref OR Sample ID (2026-11-02, late night)
- **Root cause of unlinked order samples:** the station leaves `mo_ref` empty and the operator types the order number into the Sample ID field (e.g. `2610/110`); the earlier "has an order" test looked at `mo_ref` only (reported 0, really 953 on prod). A sample now has an order when `mo_ref` is set OR its Sample ID equals an existing order number (`shift_resolver.sample_order_ref`); ingest fills an empty `mo_ref` from it (additive).
- **Linking by time needs no opened session:** when no session covers a measurement, the resolver maps its timestamp to the fixed window (06-14 / 14-22 / 22-06) and links to that window's session; if none exists a closed session covering exactly that window is synthesized (`source='fixed-window'`, no operator), reused afterwards, never duplicated. The fixed window now wins over the 15-minute post-close grace window (a rod at 14:10 is Shift 2, not Shift 1).
- Synthesized sessions are hidden from the Runs & Audit timeline and carry no runs (nothing is pushed to Odoo).
- A sample linked by clock to a run-less synthesized session is never flagged MO_MISMATCH; relink repairs such statuses (`status_repaired`).
- QC PO filter also matches rods by order label, so rods without a production run still show under their order.
- Production relink: 953 samples with an order linked (49 window sessions created), 905 mislabeled MO_MISMATCH repaired, unlinked-with-order = 0. PO 2610/110 now shows Shift 1: 400, Shift 2: 580, Shift 3: 150 rods (entire PO 1140). 425 backend tests OK.

### QC "No data from server" fix + order-only relink (2026-11-02, night)
- **Root cause of "No data from server" whenever a PO was selected:** every /api/v2/quality request computed the certificate-style `report` payload (`compute_order_summary`, ~13.5 s for PO 2610/110) even though only Print Report uses it, so the 30 s client timeout / superseded requests left the screen empty. The payload is now computed ONLY with `include_report=1` / `include_raw=1` (Print Report), plus a fingerprinted 120 s cache (invalidated by any new rod). PO-filtered views dropped from ~13.5 s to 0.06-0.22 s on production (1050 rods for 2610/110 in 0.22 s).
- Frontend: stale out-of-order responses are ignored (request sequence guard), client timeout raised to 60 s, Print Report requests the heavy payload explicitly.
- **Relink processes only samples that carry an order (mo_ref).** Order-less samples are never auto-linked by the sweep and are reported separately (`without_order`). New `GET /api/v2/quality/unlinked-summary` returns the true totals; the QC card shows "N with an order, M without an order" instead of the capped list length (production: 0 with order, 10,434 without).
- 419 backend tests OK. Deployed to production.

### Fixed-window linking + 4-entry shift dropdown + report-sync FK guard (2026-11-02, evening)
- **Relink now links by fixed shift windows:** samples falling in the gap between sessions (e.g. M2 2026-11-02, Shift 1 auto-closed 14:00 local, Shift 2 re-opened 20:23) now link to the session of the fixed shift their timestamp belongs to (`shift_resolver` FIXED_WINDOW fallback, used by both ingest and the relink sweep). Prod relink run: 140 samples linked, including all 22 gap samples -> Shift 2 session 524.
- **QC Shift dropdown is exactly 4 entries:** All shifts / Current shift / the two other fixed windows. Session entries (and the machine-labeled rows) are gone.
- **Relink message** now explains remaining samples.
- **Critical fix:** POST /api/reports and /api/reports/sync no longer fail with production_reports_run_id_fkey when a tablet sends a stale run_id/shift_id - the ids are validated and nulled before insert (link_report_to_run re-resolves). Stops the report-loss retry loop seen in the prod log.
- Full backend suite: 414 tests OK. Deployed to production.

### Fixed shift windows + bug reporting (2026-11-02, build 56)
- UPDATE (2026-11-02, evening): re-applied to production with the QC filter UI redesigned as a single compact Shift dropdown (Machine -> PO -> Shift) that unifies fixed factory windows (Current / Shift 1 / Shift 2 / Shift 3) and session history - the scattered top-bar chips are gone. Time-anchoring hardened with new tests (off-schedule session at 20:30, full-day tiling with no gaps). Verified on prod: Shift 2 (14:00-22:00) shows 580 rods.
- NOTE (2026-11-02): this release was REVERTED ON PRODUCTION at the request of the user. Production was rolled back to the previous state: backend + web console = hotfix state (commit 46c0895, web build 55), DB migration 0031 downgraded (bug_reports tables dropped), and the b56 APK removed from the production apk_releases (auto-update serves build 55). The code remains intact on master for a future redeploy.

- **QC by fixed shifts:** the web Quality Control screen now defaults to fixed plant shifts (06:00-14:00 / 14:00-22:00 / 22:00-06:00) computed from each measurement's timestamp, independent of fragile tablet sessions. Opening a shift late (e.g. 21:00), re-logins or app updates can no longer hide measurements - everything measured inside a window always shows under it (`/api/v2/quality?fixed_shift=...`, new `fixed_shifts` in `/quality/filters`; pure window math in `services/shift_windows.py`).
- **Tablet shift resume:** when a machine already has an open shift, the operator can now RESUME it (re-attach via the new `GET /api/v2/machines/{id}/active-shift`) instead of fragmenting the day into extra sessions.
- **Bug report button:** new "Report a bug" button in the web console sidebar (under the menu) and in the tablet operator top bar. Reports carry user name, date/time, text (<= 2000 chars) and up to 3 image attachments; stored server-side (migration 0031, `bug_reports` + `bug_report_attachments`). Managers/admins review and resolve them in the new web "Bug Reports" section.
- Full backend suite: 408 tests OK. Deployed to production; tablets auto-update to build 56.

### Hotfix: reports invisible (500 on /api/reports) - po_number/mo_number alias (2026-11-02)
- Fixed: after migration 0030 (po_number -> mo_number rename), GET /api/reports failed with 500 on dev AND production because the endpoints build response dicts from raw table columns (mo_number) while schemas.Report still required po_number. Reports were invisible in the web console and on tablets.
- The four report endpoints that serialize column dicts (list, by-id, deleted, last-by-machine) now always include BOTH po_number (legacy clients + schema) and mo_number (new clients). schemas.Report gained an optional mo_number field. This also fixed the restored "copy from previous report" flow, whose PO lookup reads po_number from last-by-machine.
- Regression tests added (test_reports_po_mo_alias.py); full suite 398 tests OK. Hotfix deployed to production.

### Production updated to 2.2.0 b55 (2026-11-02)
- Deployed the full v2.2.0 build to the production MES server (backend, migrations 0028-0030, web console b55) via scripts/update_server.ps1.
- Tablet auto-update now serves build 55 on production: the backend's APK directory is `<backend>/app/apk_releases` (main.py resolves a relative APK_RELEASES_DIR against the app dir, not the service CWD). update_server.ps1 now mirrors the dev apk_releases/ folder into that location on every deploy.

### Web console update banner fixed (2026-11-02)
- Fixed the stuck "New version available on the server - reload to update." banner: it compared the running web build against the newest **APK** on the server, so any APK-only release (b54/b55) made it appear forever - pressing Reload re-downloaded the same stale web bundle and nothing changed.
- The banner now compares the running web build against the **served web bundle** (`/version.json`, same origin, new `ApiService.fetchServedWebVersion()`). It only appears when the server's web bundle is genuinely newer, so Reload always actually updates. APK-only releases no longer trigger it; the APK build number stays visible on the About card (`latestBuild`).
- Rebuilt the web console to 2.2.0+55 (it had been stuck on b53), so the served bundle now matches the current release.

### "Copy from previous report" restored (2026-11-02, build 55)
- Restored the lost feature: after a shift starts on a machine (or the MO switches), the operator is offered the previous shift's report ("Previous Report Found") and can copy the PO + lot plus the last bale of each material with **stop -> start** (acetate, paper, PVA glue, HM glue, triacetin). Draft restore takes priority and suppresses the offer.
- Fixed a backend bug this exposed: `/api/reports/last-by-machine` was shadowed by the dynamic `/api/reports/{report_id}` route (422) - the static route is now registered first. Verified live on dev (returns `materials_json` lists with `start`/`stop`).
- Tablet APK rebuilt as `prod_log_v2.2.0_b55.apk` (b54 was already published in this working tree, so the build number was bumped to keep the auto-update chain intact).

### Tablet APK rebuild with offline login (2026-11-02, build 54)
- Rebuilt the Android APK (`prod_log_v2.2.0_b54.apk`, published to `apk_releases/`) so the tablet build ships the offline-login flow and the new server-settings entry points. Version stays `2.2.0`; the build number was bumped (53 -> 54) so already-updated tablets receive the new APK via the auto-update flow.

### Server settings always reachable (2026-11-02)
- New "Server Settings" icon on the login screen (next to About/Force-Update) opens `ServerConfigScreen(editMode: true)` - wrong server addresses are no longer a lockout.
- Login failures with an unreachable server show a "Server" action button; tapping the login logo 5 times opens the same screen as a hidden escape hatch. The config screen gained a **Test Connection** button.

### Offline login + offline history (2026-11-02)
- **Device-bound offline login** (`core/offline_auth.dart`): every successful online login stores a PBKDF2-HMAC-SHA256 verifier of the password (random salt, 10k iterations) plus the profile. When the server is unreachable, login verifies the password locally and enters the app with the orange OFFLINE banner - no hardcoded/passwordless fallback, only users who logged in on that device.
- **Offline history**: the Server tab caches the last fetched reports (`cache_server_reports`) and shows them with an "Offline - showing cached reports" badge when the server is down; new reports/QC checks keep queueing via SyncManager as before.
- `ApiService` gained `isServerReachable()` / `testConnectionUrl()`. New dependency: `crypto`.

### Version visibility (web console + backend)
- `GET /api/version` now returns `app_version` (backend software version, single source `backend/app/version.py`) and `data_version` alongside the legacy counts-based `version` key.
- Web console shows the running build in the sidebar footer ("Web 2.2.0+53 · API 2.2.0"), a full About/Versions card on the Profile screen (web, backend, data version, server URL) and an orange "New version available — Reload" banner when the server publishes a newer build (reload via the new `core/reload_app` conditional export). Android keeps its existing install-based update flow.

### po_number -> mo_number DB rename (migration 0030, build 53)
- Renamed `purchase_orders.po_number` and `production_reports.po_number` to `mo_number` (migration 0030); the BI views `v_quality_rods` / `v_run_stats` were recreated against the new column.
- Every code/tests reference swept to `.mo_number`; legacy API output keeps `po_number` keys and the ORM keeps a compat `po_number` property, so old tablet APKs keep working until they auto-update to 2.2.0+53.

### A5: legacy `/api/*` routes extracted from main.py (2026-10-29)
- `main.py` shrank from ~2700 to ~510 lines: the whole legacy compatibility surface (users, login, reports CRUD, purchase orders, materials/machines/shifts, PDF upload, APK endpoints, PO audit) moved into the new `app/legacy_routes.py` (decorators keep their `/api` paths), together with its `_is_admin_user`, login-throttle helpers and `shift_lifecycle_svc_link`.
- `main.py` now only holds the app factory concerns: env/paths, lifespan (seed, watcher, Telegram bot, workers), CORS/auth-reads middleware, SQLAdmin, router registration and the Flutter SPA mount. Dead imports removed. `test_po_partial_update` now imports from `app.legacy_routes`.
- 393 tests green; dev MES verified serving legacy + v2 endpoints from the split modules.

### A7: stale-shift-summary recompute worker (2026-10-29)
- `services/aggregation.py` now owns the summary builders (`build_shift_summary`, `manual_check_dict`, `manual_checks_summary`, `overall_verdict` — moved out of `v2_routes`, which delegates) and adds `recompute_stale_summaries(db)`: rebuilds every summary flagged stale (e.g. after a run reassign) as a NEW version, clears the flags and returns the fresh rows.
- New `shift_summary_recompute_worker` (7th background worker) rebuilds stale summaries every 5 minutes and re-enqueues their Odoo sync, so the ERP always converges after supervisor corrections.

### A9: tablet naive timestamps are plant-local (2026-10-29)
- Naive `started_at`/`ended_at` from tablets were stored as UTC, shifting every shift interval by the plant offset. New `_naive_as_plant_local` interprets naive datetimes in the shift's `plant_tz` (Europe/Budapest default) on `open_shift` and `close_shift`; aware datetimes pass through. 5 new tests in `backend/tests/test_shift_tz_and_summary_recompute_db.py`.

### Flutter analyzer cleanup (2026-10-29)
- **0 errors / 0 warnings** on `lib/` (from 8 warnings + 5 deprecations): fixed dead-code `_saving ? null :` patterns (dialogs now guard inside the handlers, `_saving` moved to State fields), unused `ok`/`_loading` locals, dead null-aware expressions, `Table.fromTextArray` → `TableHelper.fromTextArray`, null-aware map elements, dangling library comments, and suppressed the intentional web-only `dart:html` lints. 44 info-level lints remain (pre-existing `use_build_context_synchronously` style).

### Duplicate runtime dirs consolidated (2026-10-29)
- `resolve_universal_path` now resolves relative env values against the app dir (no more CWD-dependent `.\pdf_archive`); `.env` points `LOCAL_PDF_ARCHIVE_PATH` at `backend/pdf_archive` absolutely.
- Kept one canonical `apk_releases` (repo root, 22 APKs) and one `pdf_archive` (`backend/pdf_archive`); the stale `backend/apk_releases`, `backend/app/apk_releases`, `pdf_archive/` and `backend/app/pdf_archive/` copies are removed.

### po→mo rename: compatibility step complete (2026-10-29)
- Verified the API accepts BOTH `mo_number` and `po_number` on input and serializes `mo_number` (Pydantic `populate_by_name` + alias); the Flutter `PurchaseOrder` reads `mo_number ?? po_number` and has a `moNumber` getter. The DB column rename (`purchase_orders`/`production_reports` `po_number` → `mo_number`) stays scheduled for the next major version per the roadmap plan (schema intact until then).

### Production Odoo addon deployment (2026-10-29)
- New `scripts/deploy_odoo_addon_prod.ps1` (run ON the production server, elevated): copies the tested `mes_integration` from `C:\Odoodev` into the production addons folder, runs `-u mes_integration --stop-after-init` with a service stop/start around it, and prints the follow-up steps (`ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true` in `C:\mes_system\.env` + restart `MES_Server`; later `REQUIRE_AUTH_READS=true`). Production is never touched from the dev machine.

### Odoo addon: MO recall guardrails + timestamp-signed webhooks (2026-10-29, addon 18.0.1.4.0)
- **`unlink()` blocked** for MOs already sent to MES (`mes_sync_status in (synced, error)`) — "Cannot delete: ... Use 'Cancel / Recall from MES' instead." An MO the MES references can no longer be deleted out from under it.
- **`action_cancel()` guarded** the same way; a direct cancel of a synced MO is refused.
- **New "Cancel / Recall from MES" button + `action_recall_from_mes()`**: HMAC-signed `POST /api/v2/odoo/mo-recall`; a MES `409` (MO open on a machine / has production data) surfaces the reason in a `UserError` and aborts the cancel; on `200` the MO is marked `mes_sync_status='recalled'` (new selection value) and cancelled normally.
- **Recalled MOs can never be re-pushed**: `_push_to_mes` / `_schedule_mes_push` / `button_mark_done` skip `recalled` MOs.
- **Timestamp-signed webhooks**: all addon → MES calls send `X-Odoo-Timestamp` + `HMAC(secret, "<ts>.<body>")`; the MES verifier rejects stamps older than 300 s. `.env.example` now defaults `ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true` (enable in production once the addon is deployed there).
- Dev smoke test `backend/scripts/smoke_test_mo_recall_guardrails.py` verifies version/selection/unlink/cancel guards against the DEV Odoo (127.0.0.1:8070) — never 8069.

### MO_MISMATCH relink UI (2026-10-29)
- New admin endpoint `GET /api/v2/quality/unlinked-samples`: samples with no shift plus `MO_MISMATCH` rows (machine, MO, link status, rod count) for review; `POST /api/v2/quality/relink` now enforces superadmin.
- Web console Quality Control gains an admin-only **"Unlinked / mismatched samples"** card with a **Relink now** button (`fetchUnlinkedSamples` / `relinkUnlinkedSamples` in `ApiService`).

### Optional read-endpoint auth (`REQUIRE_AUTH_READS`, 2026-10-29)
- New `app/require_auth_reads.py` middleware: when `REQUIRE_AUTH_READS=true`, every API request needs a valid bearer token or station key (401 otherwise) — legacy unauthenticated reads are closed in one switch. Public: non-API paths, `/api/auth/login`, `/api/version`, and the self-authenticating endpoints (Odoo webhooks, order-summary PDF, station ingest). Off by default for old tablet APK compatibility; enable once field APKs are retired. 9 new tests in `backend/tests/test_require_auth_reads.py`.

### Runs & Audit web screen (2026-10-29)
- New web console section **"Runs & Audit"** (`#/runs`, `screens/web/runs_screen.dart`): shift timeline with Active/Auto-closed/Closed filters, per-shift run list (MO, machine, counters, timestamps), per-run change/audit log (`run_change_log`), per-run manual QC checks and a supervisor **Reassign** dialog (reason mandatory) backed by `POST /api/v2/runs/{id}/reassign`.
- `ApiService` gained `fetchV2Shifts`, `fetchRunChanges`, `fetchRunManualChecks` and `reassignRun`.

### A4: background workers as a standalone process (2026-10-29)
- The six polling workers (Telegram queue/outbox, GDrive upload, Odoo dispatcher + reconciler, shift auto-close) moved out of `main.py` import-time threads into `backend/app/workers.py`.
- The web process starts them in its lifespan unless `MES_RUN_BACKGROUND_WORKERS=0`; `python -m app.workers` runs only the workers in a dedicated process (pair with the env flag on the web service). The station watcher and interactive Telegram bot stay in the web process.

### A3: Alembic-only schema management at startup (2026-10-29, migration 0029)
- Removed `models.Base.metadata.create_all()` (import time) and the lifespan calls to the frozen `migrate_db.migrate_roles_and_users` / `migrate_report_idempotency`; both effects moved into Alembic migration `0029_startup_legacy_migrations.py` (raw SQL, idempotent).
- Deliberate change: the legacy startup auto-reset of plain-text passwords to `1111` was NOT replicated — plain-text hashes are rejected by the bcrypt-only verifier and remediation stays with the explicit `app/scripts/fix_plaintext_passwords.py`.
- Fresh databases are now created with `alembic upgrade head`; `migrate_db.py` remains frozen but is never executed.

### S1: shift ownership on close/stop (2026-10-29)
- **Close/stop are no longer open to any authenticated user**: `POST /api/v2/shifts/{id}/close` and `POST /api/v2/shifts/{id}/stop` now require the shift's own operator (`shift_sessions.operator_id`) or a supervisor/admin (`_require_shift_operator_or_supervisor`) and return `403` otherwise — closing/stopping another operator's shift used to corrupt its runs, summary and certificate.
- The already-`CLOSED` idempotent replay of `close` stays ungated, so offline retries from any device still return the stored summary instead of erroring.
- **Resume transfers ownership**: re-opening (resuming) an `AUTO_CLOSED` shift sets `operator_id` to the resuming operator, so the new operator can close/stop their own resumed shift (the previous operator is locked out).
- Covered by 9 new tests in `backend/tests/test_shift_ownership_db.py` (owner/supervisor/manager close+stop, 403 for others, idempotent replay, resume ownership).

### Quality management: NCR + quarantine ledger (2026-10-28, build 52, migration 0028)
- **Quarantine boxes** (`production_reports.quarantine_boxes`): finished boxes isolated pending engineering inspection; excluded from `boxes_produced` and `waste_kg` until resolved.
- **Quarantine resolutions** (`quarantine_resolutions`, `services/quarantine.py`): SCRAP or RELEASE against one order's quarantine balance (`boxes <= remaining balance`, 422 otherwise). RELEASE on an Odoo-linked order enqueues an inventory-adjustment task in `odoo_outbox` (`aggregate_type='quarantine_release'`) — the closed MO is never touched. Admin soft-void; a RELEASE already synced to Odoo cannot be voided (409).
- **Non-conformity reports** (`non_conformity_reports` + `ncr_status_logs`): lifecycle OPEN → IN_PROGRESS → CLOSED with an immutable audit trail, auto numbering `NCR-{MO}-{seq:04d}`, mandatory `closing_remarks` on close.
- **RBAC**: `roles.users.can_manage_quality` (+ per-user override); all write endpoints under `/api/v2/quality/*` require the grant (admins always pass).
- **Order finalize** writes immutable `final_quarantine_boxes` / `final_scrap_boxes` / `final_scrap_kg` snapshots; post-close resolutions never mutate them.
- **Web console**: new "Quality Management" screen (`screens/web/quality/quality_management_screen.dart`) with NCR list/create/close and quarantine resolution.

### Odoo addon `mes_quarantine_release` (2026-10-28)
- `mes_integration` gains `mrp.production.mes_quarantine_release(boxes, reference)`: creates an `is_inventory` stock move that recovers the released boxes into stock without changing the closed MO state; rejects `boxes <= 0` and tracks `x_quarantine_released_boxes`.
- Dev smoke test `backend/scripts/smoke_test_quarantine_release.py` verifies the method against the **DEV** Odoo (127.0.0.1:8070, db `test`) — never 8069.

### Dead-man's switch manual QC reminders (2026-10-28, builds 50–51, migrations 0026–0027)
- Per-machine **manual test config** (migration 0026): visibility/required flags per manual QC parameter (weight, length, hardness, glue seam, cut quality, visual cleanness, triacetin) + operator manual triacetin fallback columns (wet/dry weight, rods, computed %).
- Per-machine **reminder interval** (migration 0027, `machines.reminder_interval_minutes`): the tablet raises a loud "dead man's switch" alarm when a manual QC test is due.
- Flutter `DeadManSwitch`: foreground full-screen overlay with looping alarm sound + haptics, and an exact OS-scheduled notification (`flutter_local_notifications` / AlarmManager) for backgrounded/killed apps. New deps: `audioplayers`, `flutter_local_notifications`, `timezone`; asset `assets/sounds/alarm_beep.wav`.

### Development / production environment split (2026-10-28)
- Development now uses a dedicated environment: **MES dev on port 8001**, **Odoo dev on 8070** (db `test`), custom addons at `C:\Odoodev` (esp. `mes_integration`). Production remains MES `C:\mes_system` (port 8000) and Odoo on 8069. Never edit production files or production Odoo addons directly — test on dev first, then push.
- Docs housekeeping: Grafana references removed from README/architecture/data-lifecycle (the Postgres views are now documented as BI/reporting/export); "Odoo (future)" sections rewritten as implemented; `.clinerules` and `ROADMAP.md` refreshed; `.env.example` production paths updated to `C:\mes_system`.

### Session/logout security fix + offline-data banner (2026-10-27, build 49)
- **Logout now actually clears the session**: the tablet logout buttons (operator + admin) previously only navigated to the login screen, leaving the bearer token and saved user in `SharedPreferences`; killing and reopening the app silently restored the session without credentials. Both handlers now call `ApiService.clearSession()` (removes `auth_token` + `auth_user`) before navigating.
- **Session restore re-validates + syncs**: `SessionGate._restore()` now runs `AppData.loadDataFromServer()` on a restored session and only re-enters the shell if the token survives server re-validation (a 401 clears the session and returns to login). This also fixes the stale fallback/demo data (`PO-2026-001`, demo users) previously shown after auto-login.
- **Offline/fallback data is now flagged**: added `AppData.usingFallbackData` and an orange "OFFLINE — limited data shown" banner (`OfflineBannerBar` / `AppStatusBanner`) on the tablet operator + admin screens, so demo/fallback data can no longer masquerade as a live session.
- App version bumped to `2.1.1+49` and the release APK was deployed to the auto-update folder (`apk_releases`).

### Triacetin target/tolerance + dry-batch measurement (2026-10-22, migration 0025)
- **Triacetin, % as a first-class quality parameter**: added `triacetin` / `triacetin_tolerance` to `quality_settings` (factory defaults `8.0` / `0.5`, used only for locally-created MOs) and to `purchase_orders` (per-item target). `_apply_po_tolerance_specs` and the Odoo inbound `_upsert_po_specs` now upsert a `quality_specs` row `parameter='triacetin'` (unit `%`, 2 decimals); the certificate matrix (`CERTIFICATE_PARAMS`, `_PARAM_META`, Flutter report tables) renders the new row.
- **Odoo MO flow**: for Odoo-pushed MOs the effective triacetin target/tolerance come from the Odoo product spec (overridable in the Odoo MO "Quality" tab) via `spec.triacetin` / `spec.triacetin_tolerance` — MES Settings are *not* applied to Odoo orders.
- **Dry-batch detection**: `quality_samples.is_triacetin` marks a station batch as "without triacetin" when `Sample ID` / `Batch Description` / `Comments` contains "Triacetin" (case-insensitive), set at ingest and in the station watcher.
- **Measurement + pairing** (`quality_stats.triacetin_measurements`, pure): a dry batch is paired with the nearest regular batch with the same rod count within ±5 minutes (before or after, whichever is closer). `triacetin % = (regular − dry) / dry × 100`.
- **Dry batches excluded from every statistic** (PD/diameter/weight/etc.) in `load_rods`, `compute_order_summary` and the shift summary; the computed triacetin % is injected into the certificate row + `parameters`.
- **Quality report**: the shift/order quality report gains a "Triacetin" table (`# / Time / Triacetin % / Regular wt / Dry wt / Rods`) in `pdf_generator.py` and the Flutter `quality_report_dialog.dart`.
- **Web UI**: PO form "Tech Specs" gains `Triacetin %` + `Triacetin Tol ± (%)` (prefilled from Settings); Settings → Quality & Tolerances gains `Triacetin Target (%)` + `Triacetin Tolerance ± (%)`; the PO detail Filter Specs and the quality summary card show the triacetin row.

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
