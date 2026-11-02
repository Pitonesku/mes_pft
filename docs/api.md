# API Documentation

The backend exposes the existing legacy routes (unchanged for old tablet APKs) plus
new unified routes. FastAPI serves the interactive OpenAPI docs at `/docs` in
development (disabled in production).

## Authentication

`POST /api/auth/login` issues a signed bearer token; send
`Authorization: Bearer <token>` on protected routes.

## Existing routes (compatibility)

- `GET /api/reports`, `POST /api/reports`, `POST /api/reports/sync`
- `GET /api/purchase-orders`, `POST /api/purchase-orders`, `PUT/DELETE /api/purchase-orders/{id}`
- `GET /api/materials`, `GET/POST/PUT/DELETE /api/machines`, `GET/POST /api/shifts` (legacy shift *templates*)
- `GET /api/users`, `POST /api/users`, `PUT /api/users/{id}`

## New unified routes (v2)

> These endpoints are defined against the unified models. This document lists the
> target contract; where a route diverges, the OpenAPI schema at `/docs`
> (development only) is authoritative.

### Shifts (the central aggregate)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/shifts` | List shifts (filter by machine, status, time range) |
| `POST` | `/api/v2/shifts` | Open a shift on a machine (409 if one is already open) |
| `POST` | `/api/v2/shifts/{id}/close` | Close a shift; runs aggregation + builds summary/certificate. **Only the shift's operator or a supervisor/admin** (403 otherwise; an already-closed replay returns the stored summary) |
| `GET` | `/api/v2/shifts/{id}` | Full shift record incl. runs, quality summary |
| `GET` | `/api/v2/shifts/{id}/summary` | Latest versioned `shift_summaries` payload |
| `POST` | `/api/v2/shifts/{id}/stop` | Stop without finalizing (`AUTO_CLOSED`). **Only the shift's operator or a supervisor/admin** |

`POST /api/v2/shifts` request:

```json
{ "machine_id": 1, "operator_id": 17, "started_at": "2026-05-06T04:00:00Z" }
```

`POST /api/v2/shifts/{id}/close` accepts `ended_at`, the report payload
(`ReportCreate` fields), `material_logs[]`, `scrap_logs[]`, `manual_quality`
(hardness/length), and an `Idempotency-Key` header. The response is the complete
shift record (see `ShiftSummary.payload`).

### Measurements

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v2/quality/ingest` | Ingest a station file (multipart) through the same pipeline |
| `GET` | `/api/v2/shifts/{id}/measurements` | Raw rod-level rows for a shift (JSON + CSV) |
| `GET` | `/api/v2/runs/{id}/measurements` | Raw rod-level rows for a run |
| `POST` | `/api/v2/quality/relink` | (admin) re-run resolution over unlinked samples |

### Quality summary / certificate

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/runs/{id}/quality` | Aggregated stats + certificate table for one run |
| `GET` | `/api/v2/shifts/{id}/quality` | Aggregated stats + certificate for all runs in a shift |
| `GET` | `/api/v2/runs/{id}/certificate.pdf` | Render the certificate PDF |

### Odoo outbox (admin)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/odoo-outbox` | List queued/failed dispatches |
| `POST` | `/api/v2/odoo-outbox/{id}/retry` | Re-enqueue a failed dispatch |

### Odoo inbound / webhooks / settings

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v2/odoo/mo-event` | Odoo addon webhook (HMAC-signed via `ODOO_WEBHOOK_SECRET`): MO created/updated/recalled |
| `POST` | `/api/v2/odoo/mo-recall` | HMAC-protected: archive/hide an MO that was recalled in Odoo (409 if open or has production data) |
| `POST` | `/api/v2/odoo/sync-inbound` | (admin) Pull open MOs from Odoo and upsert orders/specs |
| `POST` | `/api/v2/odoo/sync-orders` | (admin) Trigger the outbound dispatcher now |
| `POST` | `/api/v2/odoo/link-order` | (admin) Link a local order to an Odoo MO |
| `POST` | `/api/v2/odoo/reconcile` | (admin) Reconcile linked orders' state with Odoo |
| `GET` | `/api/v2/odoo/status` | Connector health (configured/reachable, shadow mode) |
| `GET/PUT` | `/api/v2/odoo/sync-settings` | Dispatch timing (verification wait, retry, max attempts, poll) |
| `PUT` | `/api/v2/odoo/shadow-mode` | Toggle shadow mode (rehearse writes) |
| `GET` | `/api/v2/odoo/shadow-log` | Shadowed write log |
| `POST` | `/api/v2/odoo/shadow/requeue` | Post shadowed items for real (refused while shadow mode is on) |

### Station profiles & push agent

| Method | Path | Purpose |
|---|---|---|
| `GET/POST` | `/api/v2/station-profiles` | List/create per-station profiles (pull watch folder / push agent) |
| `PUT/DELETE` | `/api/v2/station-profiles/{id}` | Edit/remove a profile |
| `POST` | `/api/v2/station-profiles/{id}/generate-key` | Create a station API key (prints once, SHA-256 stored) |
| `POST` | `/api/v2/station-profiles/{id}/revoke-key` | Revoke the profile's key |
| `GET` | `/api/v2/station-profiles/{id}/download-agent` | ZIP bundle: `station_push_agent.exe` + `station_agent.ini` |

### Manual quality checks

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v2/quality/manual-check` | Submit a manual QC check (bound server-side to the open run) |
| `GET` | `/api/v2/quality/manual-checks` | List checks (filters: `machine_id`, `shift_id`, `run_id`, `voided`) |
| `POST` | `/api/v2/quality/manual-checks/{id}/void` | Supervisor void with mandatory reason |

### Live quality & dashboard

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/machines/{machine_alias}/live-quality` | Live rod window stats + control limits per machine |
| `GET` | `/api/v2/dashboard/summary` | KPI cards for the web dashboard |
| `GET` | `/api/v2/quality` | Quality overview with machine/shift/PO windows |

### Quality management (NCR + quarantine)

Write actions (`POST`/`PATCH`) require the `can_manage_quality` grant
(role flag or per-user override; admins always pass). Quarantine boxes are
reported by operators as `quarantine_boxes` on the shift report and are
excluded from `boxes_produced` and `waste_kg` until resolved.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/quality/unlinked-samples` | (admin) Samples with no shift or `MO_MISMATCH` awaiting review |
| `POST` | `/api/v2/quality/relink` | (admin) Re-run shift/run resolution over unlinked samples |

#### Non-Conformity Reports (NCR)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v2/quality/ncrs` | Create (auto number `NCR-{MO}-NNNN`); body `{po_id, description, corrective_action?, severity?, machine_id?, run_id?}` |
| `GET` | `/api/v2/quality/ncrs` | List; filters `po_id`, `status`, `machine_id`, `open_only` |
| `GET` | `/api/v2/quality/ncrs/{id}` | Detail incl. status history |
| `PATCH` | `/api/v2/quality/ncrs/{id}` | Edit description/CAPA/severity or transition `OPEN`/`IN_PROGRESS` |
| `POST` | `/api/v2/quality/ncrs/{id}/close` | Close with mandatory `closing_remarks` |
| `POST` | `/api/v2/quality/ncrs/{id}/reopen` | `CLOSED -> IN_PROGRESS` |
| `GET` | `/api/v2/quality/ncrs/{id}/history` | Immutable transition log |

#### Quarantine resolutions (Scrap Act / Release)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v2/quality/quarantine-resolutions` | Resolve boxes; body `{po_id, kind: "scrap"\|"release", boxes, dry_weight_kg? (scrap), reason_code?, notes?, ncr_id?}`. Validates `boxes <= remaining quarantine balance` (422 otherwise). RELEASE on an Odoo-linked order enqueues an inventory-adjustment task in `odoo_outbox` (`aggregate_type='quarantine_release'`) — the closed MO is never touched |
| `GET` | `/api/v2/quality/quarantine-resolutions` | List; filters `po_id`, `kind`, `include_voided` |
| `POST` | `/api/v2/quality/quarantine-resolutions/{id}/void` | Admin soft-void; a RELEASE already synced to Odoo cannot be voided (409) |
| `GET` | `/api/v2/orders/{id}/quarantine` | Balance + resolution history for one order |
| `GET` | `/api/v2/orders/quality-flags` | Batch NCR/quarantine flags for the orders list (`po_ids` optional) |

## Shift summary payload (target shape)

```json
{
  "schema_version": "1.1",
  "idempotency_key": "mes:shift:<id>:v<n>",
  "shift": { "machine_id": 1, "started_at": "…Z", "ended_at": "…Z",
             "operator_id": 17, "plant_tz": "Europe/Budapest", "verdict": "PASS" },
  "runs": [{
    "seq": 1, "mo_ref": "E050", "po_number": "…",
    "qty": {"boxes": 0, "rods": 0},
    "components": [{"category": "acetate", "batch": "…", "qty_kg": 0}],
    "scrap": [{"reason_code": "UNSPECIFIED", "qty_kg": 0}],
    "spec": {"pd": {"nominal": 325, "lower": 310, "upper": 350},
             "diameter": {"nominal": 7.72, "lower": 7.69, "upper": 7.75}},
    "quality": {"status": "PASS", "rods_total": 0, "rods_rejected": 0,
                "parameters": {"pd": {"n": 0, "mean": null, "sd": null}}}
  }]
}
```
