# Architecture

## Shift resolution

Every incoming measurement is resolved to a shift with this algorithm
(`backend/app/services/shift_resolver.py`):

1. **Machine.** A station identifier (`maker`, `team`, or `instrument_id`, default
   `maker`) is mapped to a `machines.id` via `machine_aliases`. No match →
   `UNRESOLVED_MACHINE`, the sample is stored unlinked and queued for review.
2. **Clock skew.** A `produced_at` more than a few minutes in the future is flagged
   `CLOCK_SKEW`.
3. **Non-production.** Calibration / maintenance samples (by configured rules on
   `sample_id`/comments) are stored with `shift_id = NULL`.
4. **Exact containment.** The shift whose `[started_at, ended_at)` contains the
   timestamp is chosen; an open shift has `ended_at = NULL` (open interval). A
   partial-unique index enforces one open shift per machine.
5. **Grace window.** QC samples pulled just after close fall back to the most
   recently closed shift within `grace_minutes` (default 15).
6. **No match → `NO_SHIFT`.** `shift_id = NULL`; the row stays eligible for a later
   relink sweep (triggered when a shift is created/backfilled/closed).

Within a shift, the **production run** (one Manufacturing Order) is resolved by an
explicit `mo_ref` (from `Batch Description`/`Comments`) when present, otherwise by
the run active at the timestamp.

Late binding: tablets work offline, so a shift may reach the server after its
measurements. When a shift is created/closed, the resolver re-runs over the
machine's unlinked samples (`shift_id IS NULL`) in the same transaction.

## Data lifecycle

```
Quantum Neo CSV/XML
   └─ StationWatcher (poll, stable-file check, SHA-256 + MD5 dedup)
        └─ QuantumCsvParser -> ParsedSample
             └─ shift_resolver (machine -> shift -> run)
                  └─ quality_samples + quality_measurements  (shift_id NULLable)
                       ├─ Grafana reads Postgres views (v_quality_rods, v_run_stats)
                       └─ aggregation.quality_stats -> shift_quality_stats
                            └─ shift_summaries (versioned JSON)
                                 └─ odoo_outbox (future Odoo sync)
```

Files are processed transactionally: parse → resolve → insert → record
`ingestion_files` → commit → move to archive (or errors folder).

## Quality statistics methodology

Implemented in `app/quality_stats.py` (pure, unit-tested) and orchestrated by
`app/services/aggregation.py`.

- **Limits** are stored per parameter as `nominal`, `lower_limit`, `upper_limit`
  (asymmetric allowed; either bound may be NULL, e.g. hardness has only a lower
  limit). The customer certificate confirms pressure drop is 310..350 around 325
  (−15/+25), so a single `±tol` is not sufficient.
- **Rod rejection** (from the Grafana dashboard): a rod outside
  `nominal − m×(nominal−lower) .. nominal + m×(upper−nominal)` with `m=3` is
  rejected and excluded from every statistic; rejected rods are only counted.
- **Out-of-spec** (outside `[lower, upper]` but inside the rejection band) rods
  remain in mean/SD and lower the pass rate.
- **Standard deviation** is reported as **sample SD (n−1)** by default, matching
  the instrument and the certificate; population SD is also stored. The old
  Grafana panel used population SD (≈0.5% difference at n=100).
- **Weight** is measured per rod but certified per 100 rods (`report_scale=100`).
- **Hardness and length are not measured** by the station and are entered manually
  per MO; `certificate_rows` uses a manual value only when nothing was measured.

Statistics are computed **per production run (MO)**, never pooled across MOs.

## Certificate

The certificate mirrors the customer quality certificate layout: a header (item,
spec, production order, lot, quantity, materials), a parameter table
(nominal / lower / upper / mean / SD), and a rod-level appendix. It is generated
at shift close from `aggregation.certificate_rows`, re-issued with a new version
if late-linked measurements make the summary stale, and rendered via
`pdf_generator.py` (reusing the existing Telegram + Google Drive delivery path).

## Odoo sync (future)

`odoo_outbox` is the idempotent outbound queue. Community 18 uses the XML-RPC
`/xmlrpc/2` endpoint with an API key, behind a transport adapter so moving to
JSON-2 (Odoo 19+) is a swap. Each run maps to an `mrp.production`; the shift maps
to `mrp.workorder` records. Quality data needs a small custom addon in Community
(`quality.check` is Enterprise-only).
