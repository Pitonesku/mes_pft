# Odoo ERP integration

The MES backend connects to **Odoo 18 Community** over the XML-RPC API
(`/xmlrpc/2`), authenticated with an API key. The connector is deliberately
**non-destructive**: it only *links* local records to Odoo ids and never
deletes or overwrites existing production data.

## Components

| File | Responsibility |
|---|---|
| `app/services/odoo/client.py` | `OdooConfig`, `OdooTransport` (XML-RPC), `OdooClient` (search/read/write/attach), UoM conversion, MO quality-field mapping |
| `app/services/odoo/inbound.py` | Fetch open MOs → link `production_runs` / `purchase_orders` |
| `app/services/odoo/outbound.py` | Enqueue + dispatch shift summaries from `odoo_outbox` |
| `app/models.py` (`odoo_*` columns) | Nullable link fields on PO / material / run / material_log |

## Data model (nullable link fields)

- `purchase_orders.odoo_id` → `sale.order`
- `material_dictionary.odoo_product_id` / `odoo_uom_id` → `product.product` / `uom.uom`
- `material_logs.odoo_lot_id` → `stock.lot`
- `production_runs.odoo_mo_id` → `mrp.production`
- `production_runs.odoo_backorder_id` / `odoo_done_qty` / `odoo_sync_status`

All are `NULL` for existing rows (44 POs, 17 materials, 150k+ measurements);
linking is additive only.

## Outbound flow (shift close → Odoo)

1. `close_shift` writes a versioned `shift_summaries` row and enqueues an
   `odoo_outbox` item (idempotency key `mes:shift:<id>:v<n>`).
2. `odoo_dispatcher_worker` (background thread) polls `odoo_outbox` and, per run:
   - writes structured QC fields on `mrp.production`
   - posts partial completion (`qty_producing` + `button_mark_done` → backorder)
   - resolves raw-material `stock.lot` ids
3. The Certificate of Analysis PDF is attached via `ir.attachment`.

## Structured QC fields (written directly to the MO — not the chatter)

A small Odoo addon adds these fields to `mrp.production`:

| Odoo field | MES source (per run) |
|---|---|
| `mean_diameter` / `sd_diameter` | `parameters.diameter.mean` / `.sd_samp` |
| `mean_pd` / `sd_pd` | `parameters.pd.mean` / `.sd_samp` |
| `quality_status` (pass/warn/fail) | `run.status` |
| `tested_rods_count` | `rods_total` |
| `rejected_rods_count` | `rods_rejected` |

`NOT_MEASURED` / `NO_DATA` runs skip the QC write (no fabricated pass/fail).

## UoM conversion

Finished-rod quantities are converted to the MO's product UoM via
`resolve_uom_ratio` (reads `uom.uom.factor`; falls back to name matching):

```
qty = rods / ratio        # M pcs -> 1e6, k pcs -> 1e3, Pcs -> 1
```

## Configuration

```
ODOO_ENABLED=false
ODOO_URL=http://localhost:8069
ODOO_DB=odoo
ODOO_USER=mes_integration
ODOO_API_KEY=...
```

The connector stays fully inert until `ODOO_ENABLED=true` and the other values
are set. Admin endpoints: `POST /api/v2/odoo/sync-inbound` and
`POST /api/v2/odoo/dispatch`.

## Migration

`alembic/versions/0004_odoo_link_fields.py` adds the nullable `odoo_*` columns
(partial-unique index on `purchase_orders.odoo_id`).
