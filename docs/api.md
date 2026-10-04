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

> These endpoints are defined against the unified models and are implemented
> incrementally; the routes are documented here as the target contract.

### Shifts (the central aggregate)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v2/shifts` | List shifts (filter by machine, status, time range) |
| `POST` | `/api/v2/shifts` | Open a shift on a machine (409 if one is already open) |
| `POST` | `/api/v2/shifts/{id}/close` | Close a shift; runs aggregation + builds summary/certificate |
| `GET` | `/api/v2/shifts/{id}` | Full shift record incl. runs, quality summary |
| `GET` | `/api/v2/shifts/{id}/summary` | Latest versioned `shift_summaries` payload |

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
