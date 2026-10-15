import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, ForeignKey, DateTime, Date, Numeric, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import importlib
if __package__:
    database_mod = importlib.import_module(f"{__package__}.database")
    Base = database_mod.Base
else:
    from database import Base

# --- ПРАВА И ПОЛЬЗОВАТЕЛИ ---

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), unique=True, nullable=False)
    
    # Гибкие права доступа (те самые галочки в будущем)
    can_create_po = Column(Boolean, default=False)
    can_edit_po = Column(Boolean, default=False)
    can_edit_report = Column(Boolean, default=False)
    can_manage_users = Column(Boolean, default=False)
    can_setup_machines = Column(Boolean, default=False)
    can_view_all_reports = Column(Boolean, default=False)

    users = relationship("User", back_populates="role")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100))
    password_hash = Column(String(255), nullable=False)
    password_pin = Column(String(255), nullable=True)  # PBKDF2-SHA256 hash for offline mobile auth
    role_id = Column(Integer, ForeignKey("roles.id"))
    is_inactive = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Telegram Bot Integration
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=True)
    tg_role = Column(String, default="user")  # "user" or "admin" for Telegram bot access
    can_use_ai = Column(Boolean, default=False)  # whether this TG user can use /ai command

    # Per-user permission override (set by admin in user settings)
    can_edit_report = Column(Boolean, default=False)  # can edit/delete submitted reports
    can_create_po = Column(Boolean, default=False)     # per-user override: can create purchase orders
    can_edit_po = Column(Boolean, default=False)       # per-user override: can edit/delete purchase orders

    role = relationship("Role", back_populates="users")


# --- СПРАВОЧНИКИ (МАТЕРИАЛЫ, СТАНКИ, СМЕНЫ) ---

class MaterialDictionary(Base):
    __tablename__ = "material_dictionary"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False) # acetate, paper, etc.
    type_name = Column(String(100), nullable=False)
    default_batch = Column(String(50))
    is_hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Odoo integration: product.product / uom.uom ids for this material.
    odoo_product_id = Column(Integer, nullable=True)
    odoo_uom_id = Column(Integer, nullable=True)

    # Data origin: 'odoo' (synced) or 'local' (manually added on the shop floor).
    source = Column(String(20), nullable=False, default="local")

class Machine(Base):
    __tablename__ = "machines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    remarks = Column(Text)
    is_inactive = Column(Boolean, default=False)

    

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    start_time = Column("start_time", String(10), nullable=False)  # Существующая колонка БД
    end_time = Column("end_time", String(10), nullable=False)

    @property
    def start(self):
        if isinstance(self.start_time, datetime.time):
            return self.start_time.strftime("%H:%M:%S")
        return self.start_time

    @start.setter
    def start(self, value):
        if isinstance(value, datetime.time):
            self.start_time = value.strftime("%H:%M:%S")
        else:
            self.start_time = value

    @property
    def end(self):
        if isinstance(self.end_time, datetime.time):
            return self.end_time.strftime("%H:%M:%S")
        return self.end_time

    @end.setter
    def end(self, value):
        if isinstance(value, datetime.time):
            self.end_time = value.strftime("%H:%M:%S")
        else:
            self.end_time = value


# --- ПРОИЗВОДСТВО ---

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String(50), unique=True, nullable=False)
    
    # Технические параметры фильтра
    diameter = Column(Numeric(5, 2))
    length = Column(Numeric(5, 2))
    pd = Column(Numeric(6, 2))
    cu = Column(Integer)
    weight = Column(Numeric(6, 2))
    box_type = Column(Integer)
    
    # Состав материалов
    acetate_type = Column(String(100))
    paper_type = Column(String(100))
    pva_glue_type = Column(String(100))
    hm_glue_type = Column(String(100))
    triacetin_type = Column(String(100))
    
    # Rod quantities are BIGINT: an Odoo MO in a "1000pcs" unit easily exceeds
    # the 32-bit range once converted to single rods (e.g. 10 M x 1000pcs).
    target_qty = Column(BigInteger, nullable=False)
    produced_qty = Column(BigInteger, default=0)
    is_hidden = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Odoo integration: sale.order id for this customer PO (nullable; linked
    # non-destructively via inbound sync, never overwritten).
    odoo_id = Column(Integer, nullable=True)

    # Root Manufacturing Order link (resolved through the Odoo backorder
    # hierarchy; backorders are never imported as separate orders).
    odoo_mo_id = Column(Integer, nullable=True)          # root mrp.production id
    odoo_mo_name = Column(String(100), nullable=True)    # root MO name (e.g. WH/MO/00217)
    odoo_linked_at = Column(DateTime(timezone=True), nullable=True)
    # Currently open MO of the backorder chain (odoo_mo_id stays the root).
    odoo_current_mo_id = Column(Integer, nullable=True)
    # 'full' = post completion to Odoo; 'link_only' = link + quality data only.
    sync_mode = Column(String(20), nullable=False, default="link_only")
    # State of the Odoo MO chain: open | done | cancel | check | missing.
    odoo_state = Column(String(20), nullable=True)
    odoo_synced_at = Column(DateTime(timezone=True), nullable=True)
    odoo_qty_drift = Column(Numeric, nullable=True)  # Odoo root qty - target_qty (info only)

    # Explicit order lifecycle (distinct from odoo_state and the manual is_hidden
    # toggle). Set by POST /v2/orders/{id}/close or the Odoo 'done' reconcile hook.
    completion_status = Column(String(20), nullable=False, default="active")  # active | completed | cancelled
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by = Column(String(50), nullable=True)
    # Immutable cumulative snapshots written once at finalize.
    final_boxes = Column(BigInteger, nullable=True)
    final_rods = Column(BigInteger, nullable=True)
    final_waste_kg = Column(Numeric, nullable=True)
    final_materials = Column(JSONB, nullable=True)  # {acetate, paper, pva, hm, triacetin}
    final_quality = Column(JSONB, nullable=True)    # consolidated quality matrix + tested/rejected
    odoo_summary_attachment_id = Column(Integer, nullable=True)
    # Flutter-generated consolidated Order Summary PDF (primary source). The
    # ReportLab render_order_summary_pdf() remains only as a fallback when this
    # is NULL (backend-initiated finalize with no client in the loop).
    order_summary_pdf_base64 = Column(Text, nullable=True)
    order_summary_pdf_filename = Column(String(255), nullable=True)

    # Data origin: 'odoo' (synced MO) or 'local' (manually created MO).
    source = Column(String(20), nullable=False, default="local")

    # --- Manufacturing Order terminology (legacy DB column is po_number) -----
    @property
    def mo_number(self) -> str:
        """Manufacturing Order number (alias of the legacy ``po_number`` column)."""
        return self.po_number

    @mo_number.setter
    def mo_number(self, value: str) -> None:
        self.po_number = value

class ProductionReport(Base):
    __tablename__ = "production_reports"
    id = Column(Integer, primary_key=True, index=True)
    client_report_id = Column(String(64), nullable=True)
    report_date = Column(String)
    shift_name = Column(String)
    machine_name = Column(String)
    operator_name = Column(String)
    po_number = Column(String)
    boxes_produced = Column(Integer)
    waste_kg = Column(Float)

    acetate_type = Column(String(100), default="")
    acetate_batch = Column(String(100), default="No Batch")
    paper_type = Column(String(100), default="")
    paper_batch = Column(String(100), default="No Batch")
    pva_glue_type = Column(String(100), default="")
    pva_batch = Column(String(100), default="No Batch")
    hm_glue_type = Column(String(100), default="")
    hm_batch = Column(String(100), default="No Batch")
    triacetin_type = Column(String(100), default="")
    tri_batch = Column(String(100), default="No Batch")
    
    # --- ЭТИ ПОЛЯ НУЖНО ДОБАВИТЬ ---
    shift_time_range = Column(String, default="")
    
    box_type = Column(Integer, default=0)
    diameter = Column(Float, default=0.0)
    length = Column(Float, default=0.0)
    pd = Column(Integer, default=0)
    weight = Column(Float, default=0.0)
    
    lot_number = Column(String, nullable=True, default="")
    machine_counter = Column(BigInteger, default=0)
    produced_rods = Column(BigInteger, default=0)
    machine_efficiency = Column(Float, default=0.0)
    difference = Column(Float, default=0.0)
    diff_percent = Column(String, default="0%")
    efficiency_box_min = Column(Float, default=0.0)
    
    total_acetate = Column(Float, default=0.0)
    total_paper = Column(Float, default=0.0)
    total_pva = Column(Float, default=0.0)
    total_hm = Column(Float, default=0.0)
    total_triacetin = Column(Float, default=0.0)
    
    remarks = Column(String, default="")
    is_modified_manually = Column(Boolean, default=False)
    materials_json = Column(Text)
    sync_at = Column(DateTime, server_default=func.now())
    is_archived = Column(Boolean, default=False)
    
    # Timezone handling
    timezone_offset = Column(Integer, nullable=True)  # minutes from UTC (e.g., -420 for PDT)
    submitted_at_utc = Column(DateTime, nullable=True)  # absolute UTC timestamp of submission

    # Soft-delete (Bin) — deleted reports still count in statistics
    is_deleted = Column(Boolean, default=False)
    deleted_by = Column(String(50), nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    # Версионирование (Audit Trail)
    status = Column(String(20), default="original") # original, edited, obsolete
    parent_report_id = Column(Integer, ForeignKey("production_reports.id"))
    edited_by = Column(String(50))
    edited_at = Column(DateTime)

    # Human-in-the-loop verification: operator data stays "pending" until a
    # supervisor/admin approves it. Rejected reports are excluded from Odoo sync.
    verification_status = Column(String(20), default="pending")  # pending | approved | rejected
    verified_by = Column(String(50))
    verified_at = Column(DateTime)

    # One report per MO run: direct links to the shift session and the production
    # run (nullable - legacy reports are linked via production_runs.report_id).
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)

class TelegramQueue(Base):
    __tablename__ = "telegram_queue"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer)
    message_text = Column(Text, nullable=False)
    status = Column(String(20), default="pending") # pending, sent, failed
    attempts = Column(Integer, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

class ReportOutbox(Base):
    """
    Unified outbox for all delivery types: Telegram, PDF to GDrive, DB save.
    When a report is submitted offline, all deliveries are queued here.
    Background workers poll this table and process items when network is available.
    """
    __tablename__ = "report_outbox"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, nullable=False)
    delivery_type = Column(String(20), nullable=False)  # 'telegram', 'pdf_gdrive', 'db_save'
    status = Column(String(20), default="pending")       # pending, sent, failed
    payload_text = Column(Text)       # Telegram message text
    payload_pdf_base64 = Column(Text) # PDF as base64 string
    filename = Column(String(255))    # PDF filename
    attempts = Column(Integer, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
# --- AI ANALYSIS ---

class ReportEditLog(Base):
    """Immutable audit trail for inline edits to production reports.
    Each row records exactly what changed, who changed it, and when."""
    __tablename__ = "report_edit_log"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("production_reports.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(100), nullable=False)
    changed_fields = Column(Text, nullable=False)  # JSON list of field names
    old_values = Column(Text, nullable=False)       # JSON dict {field: old_value}
    new_values = Column(Text, nullable=False)       # JSON dict {field: new_value}
    edited_at = Column(DateTime, server_default=func.now())


class ReportAuditLog(Base):
    """Immutable high-level audit log for report lifecycle events.
    Records CREATED, EDITED, DELETED, RESTORED actions with JSON diff."""
    __tablename__ = "report_audit_log"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("production_reports.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(100), nullable=False)
    action = Column(String(20), nullable=False)  # CREATED, EDITED, DELETED, RESTORED
    changed_fields = Column(Text)  # JSON diff: {"field": {"old": val, "new": val}}
    created_at = Column(DateTime, server_default=func.now())

class AIAnalysisLog(Base):
    """Audit log for every AI query made through any client (web, mobile, Telegram)."""
    __tablename__ = "ai_analysis_log"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=False)
    session_id = Column(String(100), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    # source: 'web' | 'mobile' | 'telegram'
    source = Column(String(20), default="web")
    context_snapshot = Column(Text)   # first 2000 chars of DB context sent to AI
    created_at = Column(DateTime, server_default=func.now())


# =============================================================================
# UNIFIED MES DOMAIN (shift aggregate + quality + runs + specs)
# ``shift_sessions`` is the central entity, keyed by (machine_id, started_at,
# ended_at). It is "shifts" in the architecture docs; the table is named
# shift_sessions to avoid colliding with the legacy shift *template* table
# (models.Shift -> "shifts") that the tablet app still uses. A later migration
# renames the template to shift_templates and this table to shifts.
# =============================================================================


class ShiftSession(Base):
    """An actual opened/closed shift on one machine."""
    __tablename__ = "shift_sessions"
    id = Column(BigInteger, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)  # NULL = open
    status = Column(String(20), nullable=False, default="OPEN")  # IN_PROGRESS | AUTO_CLOSED | CLOSED | OPEN(legacy)
    plant_tz = Column(String(50), nullable=False, default="Europe/Budapest")
    source = Column(String(20), nullable=False, default="tablet")  # tablet | auto | legacy
    client_shift_id = Column(String(64), nullable=True, unique=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    time_confidence = Column(String(20), nullable=True)  # exact | derived
    legacy_report_key = Column(String(100), nullable=True)
    shift_name = Column(String(50), nullable=True)  # shift template label (e.g. "Shift 1")
    scheduled_end_at = Column(DateTime(timezone=True), nullable=True)  # for auto-close sweep


class ProductionRun(Base):
    """One Manufacturing Order / format run within a shift."""
    __tablename__ = "production_runs"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    mo_ref = Column(String(100), nullable=True)          # Manufacturing Order number
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="OPEN")
    spec_snapshot = Column(JSONB, nullable=False, default=dict)  # frozen limits
    end_counter = Column(Numeric, nullable=True)  # final machine counter at run split/close
    odoo_mo_id = Column(Integer, nullable=True)
    odoo_backorder_id = Column(Integer, nullable=True)  # mrp.production backorder id
    odoo_done_qty = Column(Numeric, nullable=True)      # last synced completion qty (product UoM)
    odoo_sync_status = Column(String(20), nullable=False, default="pending")  # pending | synced | error
    # Authoritative operator report for this run's produced quantity (nullable).
    report_id = Column(Integer, ForeignKey("production_reports.id"), nullable=True, index=True)
    # Machine this run produced on. A shift is an operator session that may span
    # several machines; the run is the "where/what/when" unit (Option 2 model).
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)


class ProductionRunComponent(Base):
    """One direct filter-rod material (filtered BOM line) for a production order.

    Populated from the Odoo MO push. Only the four direct material groups are
    kept (acetate tow, paper, triacetin, glue) — never the full BOM. The raw
    ``product_name`` is preserved verbatim and, when possible, matched to the
    local ``material_dictionary`` for Odoo lot tracking.

    ``po_id`` links the BOM to the order (available as soon as the MO is pushed);
    ``run_id`` is filled once a production run opens for that order.
    """
    __tablename__ = "production_run_components"
    id = Column(BigInteger, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)
    seq = Column(Integer, nullable=False, default=0)
    category = Column(String(50), nullable=False)  # acetate | paper | triacetin | glue
    product_name = Column(String(200), nullable=False)
    product_qty = Column(Numeric(14, 4), nullable=False, default=0)
    product_uom = Column(String(20), nullable=True)
    material_id = Column(Integer, ForeignKey("material_dictionary.id"), nullable=True)
    batch_no = Column(String(100), nullable=True)
    odoo_bom_line_id = Column(Integer, nullable=True)
    odoo_move_id = Column(Integer, nullable=True)


class ManualQualityCheck(Base):
    """An in-process manual QC log entry recorded by an operator during a shift.

    Quantitative (sample_weight, length_mm) and qualitative (glue seam, cut
    quality, visual appearance) checks, linked to the active shift and MO run.
    """
    __tablename__ = "manual_quality_checks"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    mo_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sample_weight = Column(Numeric, nullable=True)   # grams per ``sample_rods`` rods
    length_mm = Column(Numeric, nullable=True)        # millimetres
    hardness = Column(Numeric, nullable=True)         # percent (manual, not station)
    # Tri-state: True = OK, False = FAIL, NULL = not checked.
    glue_seam_ok = Column(Boolean, nullable=True)
    cut_quality_ok = Column(Boolean, nullable=True)
    visual_appearance_ok = Column(Boolean, nullable=True)
    notes = Column(Text, nullable=True)

    # Snapshot taken server-side at the time of the check (the tablet's cached
    # context is never trusted): machine / MO of the shift's open run.
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    mo_ref = Column(String(100), nullable=True)
    sample_rods = Column(Integer, nullable=False, default=10)  # weight is g per N rods
    verdicts = Column(JSONB, nullable=True)           # persisted pass/fail per parameter
    overall_status = Column(String(10), nullable=True)  # PASS | FAIL | NULL (no limits)
    measured_at = Column(DateTime(timezone=True), nullable=True)
    client_check_id = Column(String(64), nullable=True)  # offline-queue idempotency key
    voided_at = Column(DateTime(timezone=True), nullable=True)
    voided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    void_reason = Column(Text, nullable=True)


class RunChangeLog(Base):
    """Immutable audit trail for MO / machine changes and supervisor corrections."""
    __tablename__ = "run_change_log"
    id = Column(BigInteger, primary_key=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=False, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(30), nullable=False)  # SWITCH_MO | CHANGE_MACHINE | REASSIGN_MO | REASSIGN_MACHINE
    old_values = Column(JSONB, nullable=False, default=dict)
    new_values = Column(JSONB, nullable=False, default=dict)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    """Small key-value store for system toggles (e.g. Odoo integration mode)."""
    __tablename__ = "system_settings"
    key = Column(String(100), primary_key=True)
    value = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MachineAlias(Base):
    """Maps a station identifier (e.g. Maker=1) to a machine."""
    __tablename__ = "machine_aliases"
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    source = Column(String(50), nullable=False)          # 'quantum_neo'
    alias_field = Column(String(50), nullable=False)     # 'maker' | 'team' | 'instrument_id'
    alias_value = Column(String(100), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)


class StationProfile(Base):
    """Per-station parser profile: overrides the column/metadata mapping.

    A station may emit files with a different column order or a different set of
    parameters (e.g. no weight, hardness instead). Rows are keyed by a station
    identifier resolved from the file header (instrument_id -> maker -> team).
    """
    __tablename__ = "station_profiles"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)          # 'quantum_neo'
    match_key = Column(String(50), nullable=False)       # 'instrument_id' | 'maker' | 'team'
    match_value = Column(String(100), nullable=False)
    label = Column(String(100), nullable=True)           # human station name
    data_start_row = Column(Integer, nullable=True)
    encoding = Column(String(20), nullable=True)
    mo_field = Column(String(30), nullable=True)         # batch_description | comments | brand
    metadata_map = Column(JSONB, nullable=True)          # {field: csv key}
    column_map = Column(JSONB, nullable=True)            # {field: index or null}
    custom_fields = Column(JSONB, nullable=True)         # [{label, unit, index}, ...]
    delivery_mode = Column(String(10), nullable=False, default="push")  # push | pull
    watch_path = Column(String(500), nullable=True)      # pull-mode network folder
    station_key_id = Column(Integer, ForeignKey("station_keys.id"), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)


class StationKey(Base):
    """Long-lived API key for the station push agent (scoped to quality ingest).

    Only the SHA-256 hash of a key is stored, so the plaintext can be issued once
    and never recovered. Keys are revocable via ``is_active``.
    """
    __tablename__ = "station_keys"
    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256 hex
    label = Column(String(100), nullable=False)          # e.g. "Station 1 - Quantum Neo"
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class QualitySpec(Base):
    """Acceptance limits per parameter and scope. lower/upper stored explicitly."""
    __tablename__ = "quality_specs"
    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(20), nullable=False, default="default")  # default|machine|po|mo
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    parameter = Column(String(30), nullable=False)  # pd|diameter|weight|hardness|length|...
    nominal = Column(Numeric, nullable=True)
    lower_limit = Column(Numeric, nullable=True)    # may be NULL (hardness lower only)
    upper_limit = Column(Numeric, nullable=True)    # may be NULL
    reject_multiplier = Column(Numeric, nullable=False, default=3)
    rod_count = Column(Integer, nullable=False, default=100)
    report_unit = Column(String(20), nullable=False, default="")
    report_scale = Column(Numeric, nullable=False, default=1)
    decimals = Column(Integer, nullable=False, default=3)


class QualitySettings(Base):
    """Singleton row of factory-wide quality defaults (tolerances & SD limits)."""
    __tablename__ = "quality_settings"
    id = Column(Integer, primary_key=True, index=True)
    diameter_tolerance = Column(Numeric, nullable=False, default=0.03)
    pd_tolerance = Column(Numeric, nullable=False, default=20)
    pd_sd_warn = Column(Numeric, nullable=False, default=12)
    pd_sd_fail = Column(Numeric, nullable=False, default=15)
    dia_sd_warn = Column(Numeric, nullable=False, default=0.013)
    dia_sd_fail = Column(Numeric, nullable=False, default=0.015)


class QualitySample(Base):
    """One station output file (batch). shift_id/run_id are NULLable for calibration."""
    __tablename__ = "quality_samples"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    link_status = Column(String(30), nullable=False, default="NO_SHIFT")
    link_source = Column(String(20), nullable=False, default="auto")  # auto | manual
    kind = Column(String(20), nullable=False, default="PRODUCTION")   # PRODUCTION|CALIBRATION|MAINTENANCE
    source_instrument_id = Column(String(50), nullable=True)
    source_maker = Column(String(50), nullable=True)
    source_team = Column(String(50), nullable=True)
    sample_id = Column(String(100), nullable=True)
    mo_ref = Column(String(100), nullable=True)
    brand = Column(String(100), nullable=True)
    operator = Column(String(100), nullable=True)
    comments = Column(Text, nullable=True)
    produced_at = Column(DateTime(timezone=True), nullable=False)
    batch_started_at = Column(DateTime(timezone=True), nullable=True)
    batch_ended_at = Column(DateTime(timezone=True), nullable=True)
    rods_declared = Column(Integer, nullable=True)
    file_sha256 = Column(String(64), nullable=True, unique=True)
    file_md5 = Column(String(32), nullable=True)
    custom_metrics = Column(JSONB, nullable=True)        # {label: {n, mean, sd_samp, sd_pop, min, max, unit}}


class QualityMeasurement(Base):
    """One measured rod. shift_id/run_id are denormalized copies (NULLable)."""
    __tablename__ = "quality_measurements"
    id = Column(BigInteger, primary_key=True, index=True)
    sample_id = Column(BigInteger, ForeignKey("quality_samples.id"), nullable=False, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    measured_at = Column(DateTime(timezone=True), nullable=False)
    rod_no = Column(Integer, nullable=False)
    pd = Column(Numeric, nullable=True)
    weight = Column(Numeric, nullable=True)
    diameter = Column(Numeric, nullable=True)
    ovality = Column(Numeric, nullable=True)
    roundness = Column(Numeric, nullable=True)
    shape = Column(Numeric, nullable=True)
    hardness = Column(Numeric, nullable=True)  # not measured yet
    length = Column(Numeric, nullable=True)    # station-measured rod length (mm)


class MaterialLog(Base):
    """Material consumption attributed to a shift/run."""
    __tablename__ = "material_logs"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True)
    material_id = Column(Integer, ForeignKey("material_dictionary.id"), nullable=True)
    category = Column(String(50), nullable=False)
    batch_no = Column(String(100), nullable=True)
    qty_kg = Column(Numeric(12, 3), nullable=False, default=0)
    source = Column(String(30), nullable=False, default="legacy")  # legacy | materials_json

    # Odoo integration: stock.lot id for the batch/lot reference.
    odoo_lot_id = Column(Integer, nullable=True)


class ScrapLog(Base):
    """Waste/scrap attributed to a shift/run."""
    __tablename__ = "scrap_logs"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True)
    reason_code = Column(String(50), nullable=False, default="UNSPECIFIED")
    qty_kg = Column(Numeric(12, 3), nullable=False, default=0)
    recorded_at = Column(DateTime(timezone=True), nullable=True)


class IngestionFile(Base):
    """Ledger of processed station files (replaces Data_Bridge processed_files)."""
    __tablename__ = "ingestion_files"
    id = Column(BigInteger, primary_key=True, index=True)
    sha256 = Column(String(64), nullable=False, unique=True)
    md5 = Column(String(32), nullable=True)
    filename = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="processed")  # processed | error
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    sample_id = Column(BigInteger, ForeignKey("quality_samples.id"), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)


class ShiftSummary(Base):
    """Versioned, immutable shift summary (the final aggregated JSON)."""
    __tablename__ = "shift_summaries"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
    input_fingerprint = Column(String(100), nullable=True)
    is_stale = Column(Boolean, nullable=False, default=False)
    payload = Column(JSONB, nullable=False)


class OdooShadowLog(Base):
    """Odoo writes the dispatcher WOULD have made (ODOO_SHADOW_MODE), per run."""
    __tablename__ = "odoo_shadow_log"
    id = Column(BigInteger, primary_key=True, index=True)
    outbox_id = Column(BigInteger, ForeignKey("odoo_outbox.id", ondelete="SET NULL"), nullable=True, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    odoo_mo_id = Column(Integer, nullable=True)
    link_only = Column(Boolean, nullable=False, default=False)
    actions = Column(JSONB, nullable=False, default=list)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OdooOutbox(Base):
    """Idempotent outbound queue for Odoo dispatch (future phase)."""
    __tablename__ = "odoo_outbox"
    id = Column(BigInteger, primary_key=True, index=True)
    aggregate_type = Column(String(30), nullable=False)  # shift | run
    aggregate_id = Column(BigInteger, nullable=False)
    shift_summary_version = Column(Integer, nullable=True)
    idempotency_key = Column(String(100), nullable=False, unique=True)
    payload = Column(JSONB, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    odoo_model = Column(String(100), nullable=True)
    odoo_id = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
