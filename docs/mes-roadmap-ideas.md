# MES review: status and improvement ideas

Working document - edit freely. Written 2026-10-10 after the shift / machine / MO review.
Decisions taken: **Option 2** (machine lives on the run), **one report per MO run**,
manual QC weight = **grams per 10 rods**, corrections = **supervisor only**, dead code removed.

## 1. Model (implemented)

```
ShiftSession (operator session)            who / when
  └─ ProductionRun (machine + MO + interval, end_counter)   where / what
       ├─ QualityMeasurement   (run_id)
       ├─ ManualQualityCheck   (run_id, machine/po/mo snapshot, verdict, void)
       └─ ProductionReport     (run_id + shift_id, one per MO run)
RunChangeLog = audit of every MO switch / machine change / supervisor correction
```

* `shift_sessions.machine_id` = the machine the shift is on **right now**; `production_runs.machine_id`
  is the history. Rods resolve to the run active on that machine at the rod's time.
* `POST /v2/shifts/{id}/switch-mo`, `POST /v2/shifts/{id}/change-machine` (shift stays open).
* `POST /v2/runs/{id}/reassign` (manager/admin; reason mandatory; cascades to QC checks + reports,
  marks the shift summary stale, audited; admin-only once the run is synced to Odoo).
* QC checks are bound **server-side** to the open run; the tablet's `mo_id` is ignored.

## 2. Defect register - status

| ID | Finding | Status |
|---|---|---|
| D1 | switch-mo hard-coded `seq=1` | fixed (`max(seq)+1`), tested |
| D2 | new run started at shift start | fixed (starts now) |
| D3 | runs left OPEN after close/stop/takeover/auto-close | fixed + migration 0018 repairs 6 phantom runs |
| D4 | overnight early-open got an end time in the past | fixed (Dart) + server guard in auto-close, tested |
| D5 | flat spec snapshot gave no limits | fixed (`load_run_specs` falls through, new runs write `parameters`) |
| D6 | MO switch silently dropped form data | fixed (draft saved first, new report identity) |
| D7 | `end_counter` never sent | fixed (dialog asks for the final counter) |
| Q1-Q4,Q6,Q7 | QC not in summary, client-bound MO, verdict not stored, default-OK toggles, no offline queue, no void | fixed |
| Q5 | weight units | resolved: g per 10 rods (spec per-100-rods converted) |
| L1 | live ingest dropped `MO_MISMATCH` | fixed (kept as `link_status`) |
| L4/L5 | reports not linked to shift/run | fixed (`production_reports.run_id/shift_id`, server re-validates by MO) |
| S2,S3,S4 | open-shift race, unvalidated `ended_at`, same-MO switch | fixed |
| P3 | `ShiftQualityStat`, `_cats.py`, `_t.txt`, `[DEBUG]` prints, `/api/debug/last-report`, widget_test | removed |

### Still open (not done in this pass)

* **S1** any authenticated user can still stop/close another operator's shift.
* **A3** `create_all()` + frozen `migrate_db.py` still run at startup (invariant 3).
* **A4** background workers are threads in the web process (duplicate with `--workers > 1`).
* **A5** `main.py` / `v2_routes.py` monoliths. **A7** summary recompute job. **A9** tablet time zone.
* Read endpoints without auth (`/api/reports`, `/v2/shifts`, `/v2/quality*`, dashboard), CORS `*` + credentials,
  `_require_superadmin` username check.
* Web console has no screen yet for: run timeline, QC checks per run, reassign, audit log.
* Only `quality_samples`/`measurements` are re-pointed by `/quality/relink`; there is no UI for `MO_MISMATCH`.
* `Table.fromTextArray` deprecations and pre-existing analyzer warnings in the Flutter app.

## 3. MO Deletion / Cancellation Guardrails (Odoo ↔ MES)

**Status: backend recall route IMPLEMENTED; Odoo addon override OUTLINED (to implement later).**

### Problem
An MO can be pushed to MES, then deleted/cancelled in Odoo after an operator started
working on it → orphaned records, tablet UI crashes, data corruption.

### Backend (DONE)
- `POST /api/v2/odoo/mo-recall` (HMAC-protected, same `_verify_odoo_webhook` as `mo-event`).
- Payload: `{ "mo_ref": "WH/MO/00218" }` (or `mo_id`).
- Logic in `services/odoo/recall.py::recall_mo`:
  1. `409` — MO has an open run (`ended_at IS NULL`): "MO is currently open on machine [M1/M2]…".
  2. `409` — production data exists (`end_counter > 0`, `manual_quality_checks`, or `quality_measurements`).
  3. `200` — archive/hide the unstarted order (`is_archived`, `is_hidden`, `odoo_state='recalled'`, `sync_mode='link_only'`) — **never delete** (invariant #2).

### Odoo addon override (OUTLINED — `mes_integration/models/mrp_production.py`)
1. **Block unlink** — override `unlink()` on `mrp.production`:
   - If `mes_sync_status in ('synced', 'error')` (i.e. already sent to MES) → raise `UserError`
     ("Cannot delete: this MO was sent to MES. Use 'Cancel / Recall from MES' instead.").
   - Never delete an MO that the MES may still reference.
2. **"Cancel / Recall from MES" action** — a button/action that `POST`s `{mo_ref}` to
   `/api/v2/odoo/mo-recall` with the same HMAC signature as `_push_to_mes`:
   - `200` → set `mes_sync_status = 'recalled'` (new selection value) and proceed with
     the normal `action_cancel()`.
   - `409` → surface the MES rejection reason (the `detail` string) to the office user via
     `UserError` / chatter, and **abort** the cancellation.
3. Add `'recalled'` to the `mes_sync_status` selection, and guard `action_cancel()` /
   `button_mark_done()` so a recalled MO cannot be re-pushed to MES.
