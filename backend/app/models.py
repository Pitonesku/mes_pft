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
    
    target_qty = Column(Integer, nullable=False)
    produced_qty = Column(Integer, default=0)
    is_hidden = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

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
    machine_counter = Column(Integer, default=0)
    produced_rods = Column(Integer, default=0)
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
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN | CLOSED | VOID
    plant_tz = Column(String(50), nullable=False, default="Europe/Budapest")
    source = Column(String(20), nullable=False, default="tablet")  # tablet | auto | legacy
    client_shift_id = Column(String(64), nullable=True, unique=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    time_confidence = Column(String(20), nullable=True)  # exact | derived
    legacy_report_key = Column(String(100), nullable=True)


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
    odoo_mo_id = Column(Integer, nullable=True)


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


class ShiftQualityStat(Base):
    """One aggregated statistic for a shift/run version and parameter."""
    __tablename__ = "shift_quality_stats"
    id = Column(BigInteger, primary_key=True, index=True)
    shift_id = Column(BigInteger, ForeignKey("shift_sessions.id"), nullable=False, index=True)
    run_id = Column(BigInteger, ForeignKey("production_runs.id"), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    parameter = Column(String(30), nullable=False)
    n = Column(Integer, nullable=False, default=0)
    n_rejected = Column(Integer, nullable=False, default=0)
    mean = Column(Numeric, nullable=True)
    sd_samp = Column(Numeric, nullable=True)
    sd_pop = Column(Numeric, nullable=True)
    min = Column(Numeric, nullable=True)
    max = Column(Numeric, nullable=True)
    target = Column(Numeric, nullable=True)
    lsl = Column(Numeric, nullable=True)
    usl = Column(Numeric, nullable=True)
    n_out_of_spec = Column(Integer, nullable=False, default=0)
    pass_rate = Column(Numeric, nullable=True)
    status = Column(String(20), nullable=True)  # PASS | WARN | FAIL | NOT_MEASURED


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
