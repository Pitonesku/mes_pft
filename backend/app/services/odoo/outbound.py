"""Outbound MES -> Odoo: idempotent dispatch of shift summaries queued in
``odoo_outbox``. Modeled on the StationWatcher / report_outbox worker pattern."""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.services import aggregation
from app.services.odoo.client import OdooClient, OdooConfig, OdooError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # legacy default; runtime value via max_attempts()

SHADOW_SETTING_KEY = "odoo_shadow_mode"
VERIFY_WAIT_SETTING_KEY = "odoo_verification_wait_minutes"
ERROR_RETRY_SETTING_KEY = "odoo_error_retry_minutes"
MAX_ATTEMPTS_SETTING_KEY = "odoo_max_attempts"
POLL_SECONDS_SETTING_KEY = "odoo_poll_seconds"
RECONCILE_MINUTES_SETTING_KEY = "odoo_reconcile_minutes"

DEFAULT_VERIFY_WAIT_MINUTES = 10
DEFAULT_ERROR_RETRY_MINUTES = 5
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_POLL_SECONDS = 30
DEFAULT_RECONCILE_MINUTES = 10


def _int_setting(session: Session, key: str, default: int, minimum: int = 0) -> int:
    """Read an integer ``{"value": n}`` setting, falling back to ``default``."""
    row = session.get(models.SystemSetting, key)
    raw = (row.value or {}).get("value") if row is not None else None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def verification_wait_minutes(session: Session) -> int:
    return _int_setting(session, VERIFY_WAIT_SETTING_KEY, DEFAULT_VERIFY_WAIT_MINUTES)


def error_retry_minutes(session: Session) -> int:
    return _int_setting(session, ERROR_RETRY_SETTING_KEY, DEFAULT_ERROR_RETRY_MINUTES)


def max_attempts(session: Session) -> int:
    return _int_setting(session, MAX_ATTEMPTS_SETTING_KEY, DEFAULT_MAX_ATTEMPTS, minimum=1)


def poll_seconds(session: Session) -> int:
    return _int_setting(session, POLL_SECONDS_SETTING_KEY, DEFAULT_POLL_SECONDS, minimum=1)


def reconcile_minutes(session: Session) -> int:
    return _int_setting(session, RECONCILE_MINUTES_SETTING_KEY, DEFAULT_RECONCILE_MINUTES)


def shadow_enabled(session: Session) -> bool:
    """Single source of truth for shadow mode (env is only the initial default).

    The web UI toggles this at runtime via ``PUT /api/v2/odoo/shadow-mode``, so
    the dispatcher, the shadow-log endpoint and the requeue guard must all read
    it from here instead of the environment.
    """
    row = session.get(models.SystemSetting, SHADOW_SETTING_KEY)
    if row is None:
        return bool(OdooConfig.from_env().shadow)
    value = row.value or {}
    return bool(value.get("enabled", True))


def set_shadow_enabled(session: Session, enabled: bool) -> bool:
    row = session.get(models.SystemSetting, SHADOW_SETTING_KEY)
    if row is None:
        row = models.SystemSetting(key=SHADOW_SETTING_KEY, value={})
        session.add(row)
    row.value = {"enabled": bool(enabled)}
    session.commit()
    return bool(enabled)


def enabled(config: Optional[OdooConfig] = None) -> bool:
    cfg = config or OdooConfig.from_env()
    return bool(cfg.enabled and cfg.valid())


def enqueue_shift_summary(
    session: Session,
    shift_id: int,
    version: int,
    payload: Dict[str, Any],
    config: Optional[OdooConfig] = None,
) -> Optional[models.OdooOutbox]:
    """Queue a shift summary for Odoo dispatch (no-op when Odoo is disabled)."""
    if not enabled(config):
        return None
    key = payload.get("idempotency_key") or f"mes:shift:{shift_id}:v{version}"
    existing = (
        session.query(models.OdooOutbox)
        .filter(models.OdooOutbox.idempotency_key == key)
        .first()
    )
    if existing is not None:
        return existing
    item = models.OdooOutbox(
        aggregate_type="shift",
        aggregate_id=shift_id,
        shift_summary_version=version,
        idempotency_key=key,
        payload=payload,
        payload_hash=aggregation.fingerprint(payload),
        status="pending",
    )
    session.add(item)
    return item


def enqueue_run_dispatch(
    session: Session,
    run_id: int,
    config: Optional[OdooConfig] = None,
) -> Optional[models.OdooOutbox]:
    """Queue a single run for Odoo dispatch immediately after its report is approved.

    Unlike the shift-close flow, this posts a run while the shift is still open, so a
    multi-order shift can sync each order as soon as its report is approved.
    Idempotent: returns the existing item when one is already queued or already synced.
    """
    if not enabled(config):
        return None
    db_run = session.get(models.ProductionRun, run_id)
    if db_run is None or db_run.odoo_sync_status == "synced":
        return None
    key = f"mes:run:{run_id}"
    existing = (
        session.query(models.OdooOutbox)
        .filter(models.OdooOutbox.idempotency_key == key)
        .first()
    )
    if existing is not None:
        return existing
    summary = aggregation.compute_run_summary(session, db_run)
    payload = {"runs": [summary]}
    item = models.OdooOutbox(
        aggregate_type="run",
        aggregate_id=run_id,
        idempotency_key=key,
        payload=payload,
        payload_hash=aggregation.fingerprint(payload),
        status="pending",
    )
    session.add(item)
    return item


def dispatch_pending(
    session_factory, config: OdooConfig, limit: int = 20, shadow: Optional[bool] = None
) -> int:
    """Process up to ``limit`` pending outbox items. Returns count dispatched.

    ``shadow`` overrides ``config.shadow``; callers that can read the runtime
    setting should pass ``shadow_enabled(session)`` so the UI toggle and the
    dispatcher agree.
    """
    if shadow is None:
        shadow = config.shadow
    session: Session = session_factory()
    dispatched = 0
    client: Optional[OdooClient] = None
    try:
        # Claim rows one at a time with FOR UPDATE SKIP LOCKED so a concurrent
        # manual POST /api/v2/odoo/dispatch and the background worker can never
        # pick up and double-process the same outbox row. Claiming the next row
        # only after the previous one committed keeps the lock window honest.
        for _ in range(limit):
            item = (
                session.query(models.OdooOutbox)
                .filter(
                    models.OdooOutbox.status == "pending",
                    (models.OdooOutbox.next_attempt_at.is_(None))
                    | (models.OdooOutbox.next_attempt_at <= datetime.now(timezone.utc)),
                )
                .order_by(models.OdooOutbox.id)
                .with_for_update(skip_locked=True)
                .limit(1)
                .first()
            )
            if item is None:
                break
            try:
                if client is None:
                    client = OdooClient(config)
                    client.connect()
                if shadow:
                    _shadow_item(session, client, item)
                else:
                    _dispatch_item(session, client, item)
                    item.status = "sent"
                item.last_error = None
                dispatched += 1
            except AwaitingVerification as wait:
                # Human-in-the-loop gate: keep pending, do not burn an attempt.
                item.last_error = f"awaiting verification: {wait}"
                item.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                    minutes=verification_wait_minutes(session)
                )
            except Exception as exc:  # noqa: BLE001
                item.attempts = (item.attempts or 0) + 1
                item.status = "failed" if item.attempts >= max_attempts(session) else "pending"
                item.last_error = str(exc)
                item.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                    minutes=error_retry_minutes(session)
                )
                logger.warning("Odoo dispatch failed for %s: %s", item.idempotency_key, exc)
            session.commit()
    finally:
        session.close()
    return dispatched


class AwaitingVerification(Exception):
    """Raised when a run has no approved production report yet.

    Not a failure: the outbox item stays ``pending`` and is retried later without
    consuming an attempt (human-in-the-loop gate, see docs/odoo-integration.md).
    """


def _utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _verified_reports(session: Session, db_run) -> List[Any]:
    """Return the approved operator report(s) for a run, or raise ``AwaitingVerification``.

    Direct ``report_id`` link first (Phase 1); the PO/machine/time heuristic is the
    legacy fallback. Pending reports always raise - never falls back to measured rods.
    """
    if getattr(db_run, "report_id", None):
        linked = session.get(models.ProductionReport, db_run.report_id)
        if linked is not None:
            status = linked.verification_status or "pending"
            if status == "approved":
                return [linked]
            raise AwaitingVerification(f"linked report {linked.id} is {status}")

    shift = session.get(models.ShiftSession, db_run.shift_id)
    if shift is None:
        raise AwaitingVerification("shift not found")
    po = session.get(models.PurchaseOrder, db_run.po_id) if db_run.po_id else None
    po_number = (po.po_number if po is not None else None) or db_run.mo_ref
    if not po_number:
        raise AwaitingVerification("run has no MO/PO number")
    machine = session.get(models.Machine, shift.machine_id)

    query = session.query(models.ProductionReport).filter(
        models.ProductionReport.po_number == po_number,
        models.ProductionReport.status != "obsolete",
        (models.ProductionReport.is_deleted.is_(None)) | (models.ProductionReport.is_deleted.is_(False)),
    )
    if machine is not None:
        query = query.filter(models.ProductionReport.machine_name == machine.name)
    start = _utc_naive(shift.started_at)
    if start is not None:
        query = query.filter(models.ProductionReport.submitted_at_utc >= start)
    end = _utc_naive(shift.ended_at)
    if end is not None:
        query = query.filter(models.ProductionReport.submitted_at_utc <= end + timedelta(hours=12))
    reports = query.all()

    if not reports:
        raise AwaitingVerification(f"no production report found for {po_number}")
    if any((r.verification_status or "pending") == "pending" for r in reports):
        raise AwaitingVerification(f"report for {po_number} awaits supervisor approval")
    approved = [r for r in reports if r.verification_status == "approved"]
    if not approved:
        raise AwaitingVerification(f"all reports for {po_number} were rejected")
    if len(reports) == 1 and getattr(db_run, "report_id", None) is None:
        db_run.report_id = reports[0].id  # unambiguous match -> persist the link
    return approved


def verified_produced_rods(session: Session, db_run) -> int:
    """Sum ``produced_rods`` of the approved operator report(s) for this run."""
    return sum(int(r.produced_rods or 0) for r in _verified_reports(session, db_run))


def _resolve_consumption_products(session: Session, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach ``material_id``/``odoo_product_id`` to each consumption item.

    Odoo matching is strictly by ID via the material dictionary; the name is
    never the primary key. Items without a material-dictionary match are left
    as-is (the client falls back to name matching only as a last resort).
    """
    names = {(item.get("type_name") or "").strip() for item in items}
    names.discard("")
    if not names:
        return items
    mats = (
        session.query(models.MaterialDictionary)
        .filter(models.MaterialDictionary.type_name.in_(names))
        .all()
    )
    by_name = {m.type_name.strip(): m for m in mats}
    for item in items:
        mat = by_name.get((item.get("type_name") or "").strip())
        if mat is not None:
            item["material_id"] = mat.id
            item["odoo_product_id"] = mat.odoo_product_id
    return items


def verified_consumption(session: Session, db_run) -> List[Dict[str, Any]]:
    """Aggregated per-material consumption of the approved report(s) for this run."""
    from app.services.odoo.consumption import aggregate_consumption
    return _resolve_consumption_products(session, aggregate_consumption(_verified_reports(session, db_run)))


def _shadow_item(session: Session, real_client: OdooClient, item: models.OdooOutbox) -> None:
    """Run the full dispatch flow with writes recorded instead of executed.

    All MES-side mutations made by the flow (run/order links, sync status, lots)
    happen inside a savepoint that is rolled back, so shadow mode leaves no trace
    other than ``odoo_shadow_log`` rows and the outbox status ``shadowed``.
    ``AwaitingVerification`` propagates exactly as in live mode (item stays pending).
    """
    from app.services.odoo.shadow import ShadowClient

    shadow = ShadowClient(real_client)
    records: list = []
    savepoint = session.begin_nested()
    try:
        _dispatch_item(session, shadow, item, sink=records)
    finally:
        savepoint.rollback()

    for rec in records:
        session.add(models.OdooShadowLog(
            outbox_id=item.id,
            run_id=rec["run_id"],
            odoo_mo_id=rec["odoo_mo_id"],
            link_only=rec["link_only"],
            actions=rec["actions"],
        ))
    if not records:
        session.add(models.OdooShadowLog(
            outbox_id=item.id, actions=[], note="nothing to post (no linked Odoo MO)",
        ))
    item.status = "shadowed"


def _dispatch_item(
    session: Session,
    client: OdooClient,
    item: models.OdooOutbox,
    sink: Optional[list] = None,
) -> None:
    payload = item.payload or {}
    for run in payload.get("runs", []):
        run_id = run.get("run_id")
        if not run_id:
            continue
        db_run = session.get(models.ProductionRun, run_id)
        if db_run is None:
            continue
        if db_run.odoo_sync_status == "synced":
            continue  # already dispatched on a previous attempt (idempotent retry)

        po = session.get(models.PurchaseOrder, db_run.po_id) if db_run.po_id else None
        start_mo = db_run.odoo_mo_id
        if po is not None:
            # Prefer the order's current open MO, then the root; the chain is
            # re-resolved against Odoo in _dispatch_run.
            start_mo = po.odoo_current_mo_id or po.odoo_mo_id or start_mo
        if start_mo is None:
            # Not linked to an Odoo MO (local order): nothing to post.
            continue
        link_only = (po is not None and (po.sync_mode or "link_only") != "full") or _before_cutover(
            session, db_run
        )
        if po is not None and not link_only:
            # Serialize full dispatch per order. Two runs of the SAME order (two
            # machines producing one Odoo MO) share one open-MO pointer; without
            # this lock a concurrent dispatcher could resolve the same MO and one
            # run's quantity would be silently skipped as "already done". The lock
            # makes resolve -> complete -> advance-pointer atomic per order.
            po = (
                session.query(models.PurchaseOrder)
                .filter(models.PurchaseOrder.id == po.id)
                .with_for_update()
                .first()
            )
        try:
            _dispatch_run(session, client, db_run, run, int(start_mo), link_only=link_only)
            if sink is not None:
                sink.append({
                    "run_id": db_run.id,
                    "odoo_mo_id": db_run.odoo_mo_id,
                    "link_only": link_only,
                    "actions": list(client.actions),
                })
                client.actions.clear()
        except AwaitingVerification:
            raise
        except Exception as exc:  # noqa: BLE001
            db_run.odoo_sync_status = "error"
            logger.warning("Run %s Odoo sync failed: %s", run_id, exc)
            raise


def _before_cutover(session: Session, db_run) -> bool:
    """True when the run started before the ``odoo_sync_from_date`` setting.

    Nothing before the cutover date may be posted to Odoo (stock double-count
    guard); such runs are handled as ``link_only``.
    """
    setting = session.get(models.SystemSetting, "odoo_sync_from_date")
    raw = ((setting.value or {}).get("date") if setting is not None else None) or None
    if not raw:
        return False
    try:
        cutoff = datetime.fromisoformat(str(raw))
    except ValueError:
        logger.warning("Invalid odoo_sync_from_date %r - treating as no cutover", raw)
        return False
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    started = db_run.started_at
    if started is None:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started < cutoff


def _dispatch_run(
    session: Session,
    client: OdooClient,
    db_run,
    run,
    start_mo_id: int,
    link_only: bool = False,
) -> None:
    # link_only: attach quality data + PDF only. Never complete/consume - the MO
    # may already be done in Odoo and posting again would double-count stock.
    if link_only:
        mo_id = start_mo_id
        client.write_mo_quality(mo_id, run)
        pdf_bytes = render_certificate_pdf(run)
        if pdf_bytes:
            client.attach_pdf(
                f"Quality_Report_{run.get('mo_ref') or mo_id}_run{db_run.id}.pdf",
                "mrp.production", mo_id, pdf_bytes,
            )
        db_run.odoo_mo_id = mo_id
        db_run.odoo_sync_status = "synced"
        return

    # 0. Authoritative quantity = approved operator report. Gate before any write.
    reports = _verified_reports(session, db_run)
    qty_rods = sum(int(r.produced_rods or 0) for r in reports)
    from app.services.odoo.consumption import aggregate_consumption
    consumption = _resolve_consumption_products(session, aggregate_consumption(reports))

    # Follow the backorder chain: earlier shifts may have closed the MO we hold.
    mo_id = client.resolve_open_mo(start_mo_id)
    if mo_id is None:
        logger.info("Run %s: Odoo MO chain from %s is closed; nothing to post", db_run.id, start_mo_id)
        db_run.odoo_sync_status = "synced"
        return
    db_run.odoo_mo_id = mo_id

    # Ordering matters for retries: every idempotent step runs first and the
    # non-idempotent completion (which spawns the backorder) runs LAST, so a
    # failure in an earlier step can never lead to a double completion.

    # 1. Structured quality fields on mrp.production (custom addon), not chatter.
    client.write_mo_quality(mo_id, run)

    # 2. Resolve raw-material lot ids (stock.lot) for later move-line creation.
    _resolve_material_lots(session, client, db_run)

    # 3. Attach the per-run quality certificate PDF to the MO (final report).
    #    Attached before completion so it stays on the MO that was measured.
    pdf_bytes = render_certificate_pdf(run)
    if pdf_bytes:
        name = f"Quality_Report_{run.get('mo_ref') or mo_id}_run{db_run.id}.pdf"
        client.attach_pdf(name, "mrp.production", mo_id, pdf_bytes)

    # 3b. Attach the operator's Production Report PDF(s) to the same MO (best effort).
    #     Prefer the Flutter-generated PDF (the MES design) uploaded with the report.
    try:
        import base64
        from app.pdf_generator import PDFReportGenerator, report_to_dict
        from app.services.odoo.legacy_push import safe_name
        safe = safe_name(run.get("mo_ref") or str(mo_id))
        generator = PDFReportGenerator()
        for report in reports:
            report_pdf = None
            filename = f"Production_Report_{safe}_#{report.id}.pdf"
            uploaded = (
                session.query(models.ReportOutbox)
                .filter(
                    models.ReportOutbox.report_id == report.id,
                    models.ReportOutbox.delivery_type == "pdf_gdrive",
                    models.ReportOutbox.payload_pdf_base64.isnot(None),
                )
                .order_by(models.ReportOutbox.id.desc())
                .first()
            )
            if uploaded and uploaded.payload_pdf_base64:
                try:
                    report_pdf = base64.b64decode(uploaded.payload_pdf_base64)
                    if uploaded.filename:
                        filename = uploaded.filename
                except Exception:
                    report_pdf = None
            if not report_pdf:
                report_pdf = generator.generate_pdf_bytes(report_to_dict(report))
            if report_pdf:
                client.attach_file(
                    filename, "mrp.production", mo_id, report_pdf, "application/pdf",
                )
    except Exception as exc:  # noqa: BLE001 - never block completion
        logger.warning("Run %s: production report PDF attach failed: %s", db_run.id, exc)

    # 4. Finished quantity: partial completion -> Odoo creates the backorder.
    if qty_rods:
        result = client.post_completion(mo_id, qty_rods, consumption=consumption)
        if result.get("skipped"):
            # post_completion skips an MO that is already done/cancelled. In live
            # mode that means the MO we resolved was closed out from under us (a
            # concurrent dispatch or an external Odoo action); marking the run
            # 'synced' would silently DROP its quantity. Fail instead so the
            # outbox retries and resolve_open_mo re-advances to the open MO.
            if not getattr(client, "is_shadow", False):
                raise OdooError(
                    f"MO {mo_id} completion skipped ({result.get('reason')}): "
                    f"{qty_rods} rods NOT posted to Odoo"
                )
        else:
            db_run.odoo_done_qty = result.get("qty")
            if result.get("backorder_id"):
                db_run.odoo_backorder_id = int(result["backorder_id"])
                # Advance the order to the new open MO for the next shift.
                po = session.get(models.PurchaseOrder, db_run.po_id) if db_run.po_id else None
                if po is not None:
                    po.odoo_current_mo_id = int(result["backorder_id"])

    db_run.odoo_sync_status = "synced"


def _resolve_material_lots(session: Session, client: OdooClient, db_run) -> None:
    logs = (
        session.query(models.MaterialLog)
        .filter(models.MaterialLog.shift_id == db_run.shift_id)
        .all()
    )
    for log in logs:
        if not log.odoo_lot_id and log.batch_no:
            lot = client.search_read(
                "stock.lot", [["name", "=", log.batch_no]], ["id"], limit=1
            )
            if lot:
                log.odoo_lot_id = int(lot[0]["id"])


def _produced_rods(run: Dict[str, Any]) -> float:
    for key in ("rods_used", "rods_total"):
        value = run.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def render_certificate_pdf(run: Dict[str, Any]) -> Optional[bytes]:
    """Render a simple quality certificate PDF for one production run.

    Pure-helper (no DB): consumes the already-computed run summary from the
    outbox payload and returns the PDF bytes, or ``None`` when there is no
    certificate data. reportlab is imported lazily so the Odoo service stays
    importable in tests without a heavy dependency.
    """
    rows = run.get("certificate") or []
    if not rows:
        return None

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except ImportError as exc:  # pragma: no cover - reportlab is a runtime dep
        logger.warning("reportlab unavailable, skipping certificate PDF: %s", exc)
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Quality Certificate")
    styles = getSampleStyleSheet()
    title = Paragraph(
        f"Quality Certificate — {run.get('mo_ref') or 'Production run'}",
        styles["Title"],
    )
    subtitle = Paragraph(
        "Automatic tests done for PD, length, weight "
        "(parameters taken from auto measurement station) · "
        f"Rods tested: {run.get('rods_total')} · Rods rejected: {run.get('rods_rejected')}",
        styles["Normal"],
    )

    from app.quality_stats import CERTIFICATE_PARAMS
    by_param = {str(r.get("parameter")): r for r in rows}
    header = ["Parameter", "Unit", "Nominal", "Lower", "Upper", "Mean", "SD", "N"]
    data = [header]
    for param, label, unit in CERTIFICATE_PARAMS:
        r = by_param.get(param) or {}
        data.append([
            label,
            unit,
            r.get("nominal"),
            r.get("lower"),
            r.get("upper"),
            r.get("mean"),
            r.get("sd"),
            r.get("n"),
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
    ]))

    story = [title, Spacer(1, 6), subtitle]
    remarks = (run.get("remarks") or "").strip()
    if remarks:
        story.append(Paragraph(f"Notes: {remarks}", styles["Normal"]))
        story.append(Spacer(1, 6))
    story.append(Spacer(1, 12))
    story.append(table)

    manual_rows = run.get("manual_checks") or []

    def _flag(v):
        return "-" if v is None else ("OK" if v else "FAIL")

    story.append(Spacer(1, 12))
    story.append(Paragraph("Manual measurements", styles["Heading2"]))
    mh = ["Run #", "Weight (mg)", "Length (mm)", "Hardness (%)",
          "Glue Seam (Glucim)", "Cut Quality", "Visual Cleanness", "Notes"]
    mrows = [mh]
    if not manual_rows:
        mrows.append(["", "No manual measurements recorded for this run",
                      "", "", "", "", "", ""])
    else:
        for c in manual_rows:
            mrows.append([
                c.get("seq") or "",
                c.get("weight_mg") or "",
                c.get("length_mm") or "",
                c.get("hardness") or "",
                _flag(c.get("glue_seam_ok")),
                _flag(c.get("cut_quality_ok")),
                _flag(c.get("visual_appearance_ok")),
                str(c.get("notes") or ""),
            ])
    mtable = Table(mrows, repeatRows=1)
    mtable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
    ]))
    story.append(mtable)

    doc.build(story)
    return buf.getvalue()
