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
| `mean_length` / `sd_length` | `parameters.length.mean` / `.sd_samp` (mm) |
| `mean_weight` / `sd_weight` | `parameters.weight.mean` / `.sd_samp` × `report_scale` (g/100) |
| `mean_hardness` / `sd_hardness` | `parameters.hardness.mean` / `.sd_samp` (%) |
| `quality_status` (pass/warn/fail) | `run.status` |
| `tested_rods_count` | `rods_total` |
| `rejected_rods_count` | `rods_rejected` |
| `quality_notes` | `run.remarks` |

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

## Odoo -> MES push (MO created/confirmed)

Odoo pushes Manufacturing Orders to the MES through `POST /api/v2/odoo/mo-event`
(the `mes_integration` addon calls it on MO create/confirm and via a "Send to MES"
button). The MES:

1. Upserts the customer `PurchaseOrder` (po_number = `origin` or MO name).
2. Upserts `quality_specs` rows (scope `po`) from the parsed filter-rod spec.
3. Replaces `production_run_components` with the **filtered BOM** — only the four
   direct material groups (acetate tow, paper, triacetin, glue) are kept.

The webhook is idempotent by `mo_id` and HMAC-signed with `ODOO_WEBHOOK_SECRET`
(matching the Odoo system parameter `mes_pft.webhook_secret`).

The finished product's **Base Packaging** (`product.packaging` with
`is_base_packaging` checked) defines `box_type` — the rod capacity of one box
(`qty / product_uom_id.factor`, e.g. a Case of 7.75 in the "1000pcs" UoM →
7750 rods). Both the manual "Send to MES" action and the auto-push on confirm
guard that the product has exactly one Base Packaging (a `UserError` is raised
otherwise), and the payload carries top-level `box_type` + `base_packaging_name`.
The MES stores `box_type` on the `PurchaseOrder` and freezes it into the run's
`spec_snapshot` so the tablet pre-fills "Box Type".

## Human-in-the-loop report verification

Operator reports (`production_reports`) start as `verification_status = pending`.
A supervisor/admin approves or rejects them via `POST /api/reports/{id}/verify`
(`{"action": "approve" | "reject"}`). Editing a report resets it to `pending`;
only approved data is authoritative for Odoo sync. Verification is logged to the
immutable `report_audit_log`.

## Per-backorder quality control

`mrp.production` (via `mes_integration`) gains a **Quality Control** tab with
`mean_diameter`, `sd_diameter`, `mean_pd`, `sd_pd`, `mean_length`, `sd_length`,
`mean_weight`, `sd_weight`, `mean_hardness`, `sd_hardness`, `quality_status`,
`tested_rods_count`, `rejected_rods_count`, `quality_notes`. On shift close the
MES dispatcher writes these per run, posts partial completion (Odoo
auto-creates the backorder and returns its id, stored in
`production_runs.odoo_backorder_id`), and attaches a rendered quality
certificate PDF to the MO.


## Phase 0 hardening (completion, gating, webhook)

- **Completion** (`OdooClient.post_completion`): `button_mark_done` is called with the
  context flags `skip_consumption`, `skip_immediate`, `skip_backorder` and, for a partial
  quantity, `mo_ids_to_backorder`. A returned wizard action or a non-`done` state raises
  `OdooError` instead of failing silently. The backorder id is found through the
  procurement group (`find_backorder`).
- **Backorder chain** (`resolve_open_mo`): dispatch follows the chain to the currently open MO,
  so shift 2 posts to the backorder created by shift 1.
- **Verification gate** (`outbound.verified_produced_rods`): a run is only posted when its
  production report is `approved`; the quantity is the report's `produced_rods`, never the
  number of measured rods. Pending reports keep the outbox item `pending` (retry every
  10 min, no attempt consumed).
- **Retry safety**: quality fields, lots and the PDF are written first; the non-idempotent
  completion is last, and runs already `synced` are skipped.
- **Webhook**: signature is `HMAC(secret, "<X-Odoo-Timestamp>.<raw body>")`, max age 5 min.
  The legacy idempotency-key signature is still accepted until
  `ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true`. Deploy order: upgrade MES, upgrade the addon, then
  set the flag.
- **Addon**: QC fields are `copy=False`; the push runs after commit, on confirm and when
  quantity/BOM/product change (not on draft create).

Not yet verified against a live Odoo 18 instance: run the flow on a staging copy first.

## Phase 1: identity, sync mode, mapping (migration 0008)

- **Order identity** = root Odoo MO id (`purchase_orders.odoo_mo_id`). `po_number` is a display
  key only, so two MOs of one sales order no longer collide. `odoo_current_mo_id` tracks the
  open MO of the backorder chain and is advanced after each partial completion.
- **`purchase_orders.sync_mode`**: `full` posts completion to Odoo; `link_only` attaches
  quality data + PDF but never completes or consumes. All pre-existing orders are `link_only`;
  a new order arriving from an *open* Odoo MO is `full`. Change it with
  `PUT /api/v2/orders/{id}/sync-mode` (superadmin; `full` requires an Odoo link).
- **Cutover date**: `PUT /api/v2/odoo/sync-settings {"odoo_sync_from_date": "2026-10-15"}`.
  Runs that started before it are treated as `link_only`.
- **Run -> report link**: `production_runs.report_id`. Dispatch uses it first; otherwise the
  PO/machine/time heuristic is used and the link is stored when exactly one report matches.
- **Material mapping** (`services/odoo/mapping.py`): `GET /api/v2/odoo/material-mapping`
  (add `?suggest=true` for ranked Odoo product suggestions) and
  `POST /api/v2/odoo/material-mapping {material_id, odoo_product_id, odoo_uom_id, force}`.
  Suggestions are never applied automatically; changing or removing a link needs `force`.
  The inbound handler persists a link on its own only for an exact normalized-name match.

## Phase 3: shadow mode (migration 0009)

Set `ODOO_SHADOW_MODE=true` to rehearse the whole outbound flow against the real Odoo
without changing it:

- Every **read** (MO state, UoM factor, backorder chain, planned qty) goes to Odoo for real.
- Every **write** (quality fields, PDF attachment, `qty_producing` + `button_mark_done`) is
  recorded in `odoo_shadow_log.actions` and **not** sent. For completion the log shows the
  converted quantity, the planned quantity and whether a backorder is expected.
- MES-side side effects (run/order links, sync status, lots) run inside a savepoint that is
  rolled back, so a shadowed run stays unsynced and can be posted later.
- The verification gate behaves exactly as in live mode (pending reports keep the item pending).
- Shadowed outbox items get status `shadowed`.

Endpoints (superadmin): `GET /api/v2/odoo/shadow-log`, `POST /api/v2/odoo/shadow/requeue`.

**Going live:** review the shadow log against what the warehouse expects (quantities, which
MO, backorder yes/no) -> set `ODOO_SHADOW_MODE=false` and restart -> `POST /odoo/shadow/requeue`
(refused while shadow mode is still on) -> promote orders to `sync_mode=full` one at a time.

Limits: shadow mode cannot prove that Odoo accepts the write (access rules, locked periods,
lot/serial rules, unreserved components). The first live completion should be done on a
single low-risk MO while someone watches Odoo.

## Phase 2: inbound lifecycle and reconciliation (migration 0010)

- **State per order**: `purchase_orders.odoo_state` = `open | done | cancel | check | missing`,
  plus `odoo_synced_at` and `odoo_qty_drift` (Odoo chain total minus MES `target_qty`; shown
  for information, MES never overwrites the target).
- **Events**: the addon also pushes on `action_cancel` and `button_mark_done`. A `done` /
  `cancel` event only sets the order to `check` (a done root MO usually has an open backorder;
  one cancelled MO may be one of several). Spec and BOM are not touched, and unknown orders
  are ignored - nothing is created from a dead MO.
- **Reconciler** (`services/odoo/reconcile.py`, thread in `main.py`, every
  `ODOO_RECONCILE_MINUTES`, default 10, `0` disables): reads the whole procurement-group chain
  of every linked, unfinished order and sets `odoo_state`, the current open MO and the drift.
  A `done` or `cancel` chain downgrades `sync_mode` to `link_only`, so nothing is posted to a
  finished/dead MO. A missing MO is only flagged (`missing`), never unlinked.
  If Odoo is unreachable the worker logs and retries; MES keeps working standalone.
  Manual run: `POST /api/v2/odoo/reconcile`.
- **One-time cleanup of existing orders**: `GET /api/v2/odoo/unlinked-orders` proposes Odoo
  MOs (all states) by order number and reports ambiguous/unmatched ones. It writes nothing;
  confirm each pair with `POST /api/v2/odoo/link-order`. `link-order` now refuses to
  re-point an order that already has a link or to take an MO linked elsewhere, and never
  changes `sync_mode`.

## Component consumption write-back (Phase 3)

When an order is `sync_mode=full`, the dispatcher now writes the operator-reported
material consumption onto Odoo `stock.move` records before marking the MO done:

- Source: the approved report's `materials_json` (`acetate_list`, `paper_list`,
  `pva_list`, `hm_list`, `tri_list`), aggregated per type+batch by
  `services/odoo/consumption.py`.
- Matching: a report material is matched to the MO's raw move by normalized product
  name (`client._name_matches`). No name-based link is ever guessed silently.
- Units: kg items are written when the move's UoM category is Weight; paper bobbins
  are converted to metres using the bobbin length embedded in the type name
  (e.g. `Delfort 27mm/6000m` -> 6000m/bobbin) and written only when the move's UoM
  is a Length unit.
- Guardrails: lot/serial-tracked components, unit mismatches, missing matches and
  over-consumption (beyond the move's remaining demand) are SKIPPED and reported as
  `skipped` reasons - never written. These need manual handling in Odoo.
- Ordering: consumption is written after `qty_producing` and before
  `button_mark_done`, with `skip_consumption` in the context so Odoo does not
  recompute over it. In shadow mode the same plan is recorded in the shadow log.
- Non-direct components: any raw move *not* matched to a reported material (boxes,
  pallets, labels, ...) is auto-consumed proportionally to `produced_qty/planned_qty`
  (scaled from the move's reserved `product_uom_qty`), matching what Odoo would
  compute for the produced quantity. `manual_consumption` BOM lines and
  lot/serial-tracked products are skipped.
- Completion context now includes `skip_redirection` so `button_mark_done` returns
  `True` instead of a redirect action that XML-RPC cannot marshal; `post_completion`
  also tolerates a marshalling failure when the MO is already `done` (no double-post).

## UoM factor fix

`resolve_uom_ratio` used to return the UoM `factor` and `convert_rods` divided by it,
which inverts quantities for "bigger" units (Odoo stores `factor = 0.001` for
"1000 pcs"). It now returns `factor_inv` (falling back to `1/factor`), so
`qty = rods / factor_inv` matches Odoo's `qty / self.factor * to_unit.factor`.
This also affects the finished quantity posted with `post_completion`.

## Field-compatibility and quantity-range fixes (2026-10-08)

Two defects found while testing the Odoo -> MES push:

1. **`mrp.bom.line.alternative_product_ids` is Enterprise-only.** Building the MO
   payload raised `AttributeError` on Community, which broke both the automatic
   push (logged to the chatter) and the "Send to MES" button (raw RPC error). The
   addon now guards the field with `"alternative_product_ids" in line._fields`, so
   Community pushes the main component only. `action_send_to_mes` also raises a
   readable `UserError` instead of an RPC traceback.
2. **Rod quantities overflowed a 32-bit integer.** Odoo MOs are frequently
   expressed in a "1000pcs" unit (factor 0.001), so an MO of 10 000 000 x 1000pcs
   is 10 billion rods. Migration **0011** widens `purchase_orders.target_qty`,
   `purchase_orders.produced_qty`, `production_reports.produced_rods` and
   `production_reports.machine_counter` to `BIGINT` (non-destructive).

Verified end to end: pushing `WH/MO/00219` (10 000 000 x 1000pcs) stores
`target_qty = 10 000 000 000`, the filtered BOM components and the parsed
quality specs; the MO reports `mes_sync_status = synced`.

## UI audit fixes (2026-10-08)

Four findings from the Odoo Sync screen audit, all fixed:

1. **Auth headers were missing on Odoo GETs.** `fetchOdooMaterialMapping`,
   `fetchOdooShadowLog`, `fetchOdooUnlinkedOrders`, `fetchOdooSyncSettings` and
   `fetchOdooOrdersSync` called `_httpClient.get` without `headers: _authHeaders()`,
   so the backend answered 401 and the screens showed empty data ("0 of 0
   materials", shadow mode "OFF"). All GETs now send the bearer token, and every
   fetcher records `ApiService.lastApiStatus/lastApiDetail` so the UI shows the
   server's message instead of a silent empty list. Shadow mode is tri-state
   (ON / OFF / UNKNOWN) and never renders a false OFF.
2. **Mapping engine rebuilt on real data.** Suggestions now match on category keys
   (acetate grade, paper width+length, glue product code); `coldGlue`/`hotMelt`
   normalize to `glue`; unclassified junk (`del`) can no longer rank; no-match
   materials return an empty list instead of weak guesses; `fetch_candidate_products`
   orders by `name` (ordering by `display_name` raised on Odoo 18). A manual
   product picker (`GET /api/v2/odoo/products`, searchable, with UoM warnings)
   covers triacetin and other materials with no name match.
3. **Shadow mode is a runtime setting.** `PUT /api/v2/odoo/shadow-mode` stores it in
   `system_settings` (`.env` is only the initial default); the dispatcher, the
   shadow-log endpoint and the requeue guard all read the same value, so the UI
   toggle and the server can never disagree. `GET /api/v2/odoo/status` reports
   config, shadow state, Odoo reachability and outbox counts.
4. **Endpoint hardening.** The XML-RPC transport has a 20 s socket timeout;
   unreachable Odoo yields a 502 with a structured body instead of a bare 500;
   `unlinked-orders` returns `ok/matched/unmatched` and the material list always
   renders even when suggestions fail (`suggest_error` field).

## Legacy order matching (one-time cleanup)

Matching unlinked local orders to Odoo, per the real-data audit:

- **Code match first** on three fields: Source (`origin`), Production Order No.
  (`x_production_order_no`, from stock_cmr_packing) and MO name. Comparisons are
  case/whitespace-normalised; the custom field is skipped automatically when the
  addon is not installed on the Odoo instance.
- **Chains, not MOs.** Candidates are grouped by procurement group, so `F058` is
  ONE candidate (root `WH/MO/00155`, 18 MOs) instead of 17 ambiguous rows. The
  chain total quantity is compared in rods after UoM conversion
  (`client.to_rods`); a mismatch adds the `qty_mismatch` risk label.
- **Risk labels**: `open_chain` (do not promote to full without care),
  `done_history` (link-only, never posts), `qty_mismatch`.
- **Heuristic fallback**: when no code matches, candidates are offered only if the
  rod spec (diameter/length/PD) matches AND the Odoo production window overlaps
  the local report range within +-14 days. Labelled `heuristic:spec+date` and
  NEVER auto-selected. On the production data this surfaces candidates only for
  orders whose Odoo MO actually exists in that window.
- **Linking** (`POST /odoo/link-order`): any MO of a chain may be given; the root
  is resolved and stored, `odoo_state` is set from the chain, and `sync_mode`
  stays `link_only`. Never posts anything by itself.
- **Ignore** (`POST /orders/{id}/ignore-odoo`): marks test/junk orders
  (`odoo_state=ignored`) so they leave the review list; nothing is deleted.
- **UI**: the Reconcile tab opens a review dialog (Link / Browse / Ignore / Skip),
  and the Order Sync tab offers "Link to Odoo MO..." per unlinked order via a
  searchable chain picker (`GET /odoo/mos?q=`).

## Schema-compliance fixes for manual linking (2026-10-08)

Two defects fixed after the UI test:

1. `inbound.link_order` read `product_uom` from `mrp.production`, which does not
   exist in Odoo 18 (the field is `product_uom_id`) - every manual link failed
   with an RPC error. The field lists are now module-level constants
   (`inbound.MO_LINK_FIELDS`, `reconcile.MO_CHAIN_FIELDS`) covered by a regression
   test asserting `product_uom_id` is present and `product_uom` is not.
2. `_chain_rows` read `product_uom_id` but converted quantities with
   `m.get("product_uom")`, silently using ratio 1.0 - chain totals for
   "1000pcs" MOs were 1000x too small and `qty_mismatch` risk labels were wrong.
   Both now use `product_uom_id`.

Verified: linking H081 through the UI-equivalent API call returns 200 with root
`WH/MO/00190-001`, `odoo_state=done`, `sync_mode=link_only`; H081 leaves the
review list; H082 chain total now shows 11 609 000 rods, matching the local
11 609 000 target.
