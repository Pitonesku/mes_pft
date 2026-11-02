# Roadmap & Technical Debt

Future improvements and refactoring backlog for mes_pft.
Keep this file up to date: mark items resolved when the change lands, add new
gaps as they are found. (`.clinerules`: consult this file before starting a task.)

## Environments (reference)

- **Dev**: MES on port 8001, Odoo on 8070 (db `test`), custom addons in `C:\Odoodev`.
- **Prod**: MES in `C:\mes_system` (port 8000), Odoo on 8069 (addons in Program Files).
- Never edit production directly — dev first, then push/copy (see `.clinerules`).

## Future Technical Improvements / Refactoring

### Refactor `po_number` to `mo_number` across Data Layer & APIs
- **Status:** RESOLVED (2026-10-29, migration 0030, released as 2.2.0+53).
  DB columns renamed (`purchase_orders.mo_number`, `production_reports.mo_number`),
  BI views recreated, all code/tests swept to `.mo_number`. Legacy API output keeps
  `po_number` keys + a compat ORM property so old tablet APKs work until they
  auto-update.
- **Context:** The UI and reports have been aligned to "Manufacturing Order" (MO),
  but the internal database columns, Pydantic schemas, and local SQLite models still
  rely on the legacy `po_number` keys for backward compatibility.
- **Action Plan:**
  1. ✅ **API Backward Compatibility:** the API accepts both `mo_number` and
     `po_number` on input and serializes `mo_number` (Pydantic alias +
     `populate_by_name`); the Flutter `PurchaseOrder` reads `mo_number ?? po_number`
     and exposes a `moNumber` getter.
  2. **DB Migration:** (deferred) `ALTER TABLE ... RENAME COLUMN po_number
     TO mo_number` with backward-compatible views/aliases if needed — scheduled for
     the next major version bump together with a full regression pass.
  3. **Local Tablet SQLite:** (deferred) automated schema migration for tablet
     SQLite offline databases on startup.
  4. **Codebase Cleanup:** (deferred) replace legacy `po_number` identifiers with
     `mo_number` throughout backend models, services, and frontend Dart models.
- **Priority:** Low / Non-blocking technical debt. Keep current schema intact until a
  scheduled major version bump.

### Remove `create_all()` + frozen `migrate_db.py` from startup (A3)
- **Status:** ✅ Resolved (2026-10-29, migration 0029).
- `models.Base.metadata.create_all(bind=engine)` removed from import; the lifespan
  no longer calls `migrate_db.migrate_roles_and_users` / `migrate_report_idempotency`.
  Both effects now live in Alembic migration `0029_startup_legacy_migrations.py`
  (raw SQL, idempotent). Deliberate change: the legacy auto-reset of plain-text
  passwords to `1111` was NOT replicated — use `app/scripts/fix_plaintext_passwords.py`
  explicitly instead. `migrate_db.py` stays frozen (invariant 3) but is no longer
  executed. Fresh databases are created with `alembic upgrade head`.

### Move background workers out of the web process (A4)
- **Status:** ✅ Resolved (2026-10-29). The six polling workers (Telegram queue,
  Telegram outbox, GDrive, Odoo dispatcher/reconciler, shift auto-close) moved from
  import-time threads in `main.py` to `app/workers.py`. The web process starts them
  in its lifespan unless `MES_RUN_BACKGROUND_WORKERS=0`; a dedicated process runs
  them alone with `python -m app.workers`. The station watcher and the interactive
  Telegram bot intentionally stay in the web process (async/interactive).
- **Action (ops):** for a multi-worker or split deployment set
  `MES_RUN_BACKGROUND_WORKERS=0` on the web service and run the worker task
  separately. Login throttle remains per-process (single web worker recommended).

### Break up the monoliths (A5)
- **Status:** Main win shipped (2026-10-29); continue incrementally.
- ✅ `main.py` 2700 → ~510 lines: legacy `/api/*` routes extracted to
  `app/legacy_routes.py`; summary builders moved earlier to `services/aggregation.py`.
  Remaining monoliths: `v2_routes.py` (~4.3k lines), `bot_handlers.py`, `pdf_generator.py`.
- **Action:** keep splitting v2_routes by domain (quality, shifts, odoo admin) when
  touching those areas; no big-bang rewrite.

### Translate legacy Russian comments/log strings to English
- **Status:** Open. `main.py` (legacy block), `init_db.py`, and section headers in
  `models.py`/`schemas.py` still contain Russian comments and console messages.
- **Action:** translate comments and log strings (keep user-facing Telegram messages
  as they are).

### Dead code + stray artifacts cleanup
- **Status:** ✅ Done (2026-10-29).
- ✅ `generate_offline_pin()` removed from `main.py` (offline auth uses bearer tokens now).
- ✅ `2026.10.04_prod_log_backup` moved to `backups/` (gitignored).
- ✅ Duplicate runtime dirs consolidated: one canonical `apk_releases` (repo root)
  and one `pdf_archive` (`backend/pdf_archive`); `resolve_universal_path` now
  resolves relative env values against the app dir (no CWD dependence).

### Restrict legacy read endpoints
- **Status:** ✅ Opt-in enforcement shipped (2026-10-29). Set
  `REQUIRE_AUTH_READS=true` (`app/require_auth_reads.py` middleware) to require a
  bearer token / station key on every API request; keep `false` while old tablet
  APKs are still in the field. Flip it once they are retired.

### Enable `ODOO_WEBHOOK_REQUIRE_TIMESTAMP`
- **Status:** ✅ Addon side done (2026-10-29); flip the env flag after deploying the
  upgraded addon to production. `mes_integration` >= 18.0.1.4.0 signs all webhooks
  (`mo-event`, `mo-recall`) as `HMAC(secret, "<timestamp>.<body>")` with an
  `X-Odoo-Timestamp` header; the MES verifier enforces a 300 s max age. Set
  `ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true` (already the `.env.example` default) once
  the production addon is upgraded.

### Remaining open items (from the 2026-10-10 review)
- **A7** — ✅ Resolved 2026-10-29: `aggregation.recompute_stale_summaries` +
  `shift_summary_recompute_worker` (7th worker, every 5 min, re-enqueues Odoo).
- **A9** — ✅ Resolved 2026-10-29: naive tablet timestamps are interpreted as
  plant-local (`_naive_as_plant_local`) on shift open/close; tested.
- **Web console gaps:** ✅ Runs & Audit screen landed 2026-10-29 (run timeline,
  QC checks per run, reassign dialog, change/audit log — `#/runs`).
- **MO_MISMATCH relink UI:** ✅ Landed 2026-10-29 — admin
  `GET /v2/quality/unlinked-samples` + "Relink now" card in the web Quality
  Control screen; `/quality/relink` enforces superadmin.
- **Flutter analyzer warnings:** ✅ Cleaned 2026-10-29 — 0 errors / 0 warnings
  on `lib/` (`Table.fromTextArray` → `TableHelper`, dead code, unused vars,
  null-aware fixes). 44 info-level lints remain for a rainy day.

### Resolved (since the review)
- ✅ CORS `*` + credentials → explicit origin allowlist, `allow_credentials=False`.
- ✅ `_require_superadmin` username-string check → role-based `_is_admin`.
- ✅ **S1 shift ownership (2026-10-29):** `close`/`stop` now require the shift's own
  operator or a supervisor/admin (`_require_shift_operator_or_supervisor`, 403
  otherwise); the already-CLOSED idempotent replay stays open to any authenticated
  user so offline retries keep working; resuming an AUTO_CLOSED shift transfers
  ownership to the resuming operator. Tested in `tests/test_shift_ownership_db.py`.
  (Follow-up idea: apply the same guard to `switch-mo` / `change-machine`.)
- ✅ **Odoo MO recall guardrails (2026-10-29, addon 18.0.1.4.0):** `unlink()` blocks
  MOs with `mes_sync_status in (synced, error)`; `action_cancel()` requires the new
  "Cancel / Recall from MES" action (`action_recall_from_mes`, HMAC-signed POST to
  `/api/v2/odoo/mo-recall`, surfaces MES 409 reasons); recalled MOs are never
  re-pushed. Webhooks always carry timestamp signatures. Verified by
  `backend/scripts/smoke_test_mo_recall_guardrails.py` against the dev Odoo (8070).
- ✅ NCR + quarantine ledger (migration 0028) and `mes_quarantine_release` addon
  method with dev smoke test.
- ✅ Dead-man's switch manual-QC reminders (migrations 0026–0027).
- ✅ Dev/prod environment split documented (8001 / 8070 / `C:\Odoodev` /
  `C:\mes_system`).

<!-- Template for future entries:
### <Title>
- **Status:** Backlog (Low / Non-blocking)
- **Context:** ...
- **Action Plan:** 1. ... 2. ... 3. ...
- **Priority:** ...
-->
