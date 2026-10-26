from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import date, datetime

# --- РОЛИ И ПРАВА ---
class RoleBase(BaseModel):
    role_name: str
    can_create_po: bool = False
    can_edit_po: bool = False
    can_edit_report: bool = False
    can_manage_users: bool = False
    can_setup_machines: bool = False
    can_view_all_reports: bool = False

class Role(RoleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- ПОЛЬЗОВАТЕЛИ ---
class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    role_id: Optional[int] = None
    is_inactive: bool = False
    can_use_ai: bool = False
    can_edit_report: bool = False
    can_create_po: bool = False
    can_edit_po: bool = False

class UserCreate(UserBase):
    password: str # При создании передаем чистый пароль, сервер его захэширует

class UserUpdate(UserBase):
    password: Optional[str] = None

class User(UserBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class LoginRequest(BaseModel):
    username: str
    password: Optional[str] = ""

class LoginResponse(BaseModel):
    status: str
    user_id: int
    username: str
    email: Optional[str] = None
    role_id: Optional[int] = None
    message: str

# --- МАТЕРИАЛЫ ---
class MaterialBase(BaseModel):
    category: str
    type_name: str
    default_batch: Optional[str] = None
    is_hidden: bool = False
    odoo_product_id: Optional[int] = None  # manual Odoo product mapping override

class Material(MaterialBase):
    id: int
    odoo_product_id: Optional[int] = None
    source: Optional[str] = "local"  # odoo | local
    model_config = ConfigDict(from_attributes=True)

class MachineBase(BaseModel):
    name: str
    remarks: Optional[str] = None
    is_inactive: bool = False

class Machine(MachineBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class ShiftBase(BaseModel):
    name: str
    start: str
    end: str

class Shift(ShiftBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- PURCHASE ORDERS (PO) ---
class POBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mo_number: str = Field(alias="po_number", serialization_alias="mo_number")  # Manufacturing Order number (legacy: po_number)
    diameter: float
    length: float
    pd: float
    cu: int
    weight: float
    box_type: int
    acetate_type: str
    paper_type: str
    pva_glue_type: str
    hm_glue_type: str
    triacetin_type: str
    target_qty: int
    produced_qty: int = 0
    is_hidden: bool = False
    is_archived: bool = False
    source: Optional[str] = "local"  # odoo | local
    allowed_materials: Optional[dict] = None  # category -> [{material_id, product_name, odoo_product_id}]
    odoo_mo_id: Optional[int] = None   # root mrp.production id
    odoo_mo_name: Optional[str] = None  # root MO name (e.g. WH/MO/00217)
    sync_mode: Optional[str] = None     # full | link_only
    odoo_state: Optional[str] = None    # open | done | cancel | check | missing

class POCreate(POBase):
    diameter_tolerance: Optional[float] = None  # ± tolerance override for diameter
    pd_tolerance: Optional[float] = None        # ± tolerance override for pressure drop
    triacetin: Optional[float] = None           # target triacetin content (%)
    triacetin_tolerance: Optional[float] = None # ± tolerance (percentage points)


class PO(POBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

# --- ОТЧЕТЫ (PRODUCTION REPORTS) ---
class ReportBase(BaseModel):
    # Обязательные базовые поля
    report_date: str
    shift_name: str
    machine_name: str
    operator_name: str
    po_number: str
    boxes_produced: int
    waste_kg: float
    
    # Client-generated idempotency key (UUID) to prevent duplicate submissions
    client_report_id: Optional[str] = None

    # One report per MO run: the tablet sends the active shift/run ids. Both are
    # optional (old APKs) and are validated / completed server-side.
    shift_id: Optional[int] = None
    run_id: Optional[int] = None

    # Timezone-aware submission
    timezone_offset: Optional[int] = None  # minutes from UTC (e.g., -420 for PDT)
    submitted_at_utc: Optional[datetime] = None  # absolute UTC timestamp of submission
    
    # Новые поля для Telegram и расчетов (делаем Optional, чтобы не было 422)
    shift_time_range: Optional[str] = ""
    
    # Технические параметры фильтра (из PO или ручного ввода)
    box_type: Optional[int] = 0
    diameter: Optional[float] = 0.0
    length: Optional[float] = 0.0
    pd: Optional[int] = 0
    weight: Optional[float] = 0.0
    
    # Показатели производства
    lot_number: Optional[str] = ""
    machine_counter: Optional[int] = 0
    produced_rods: Optional[int] = 0
    machine_efficiency: Optional[float] = 0.0
    difference: Optional[float] = 0.0
    diff_percent: Optional[str] = "0%"
    efficiency_box_min: Optional[float] = 0.0
    
    # Расход материалов (числовые значения)
    total_acetate: Optional[float] = 0.0
    total_paper: Optional[float] = 0.0
    total_pva: Optional[float] = 0.0
    total_hm: Optional[float] = 0.0
    total_triacetin: Optional[float] = 0.0

    # --- ТИПЫ МАТЕРИАЛОВ И БАТЧИ ДЛЯ КАЖДОЙ СМЕНЫ ---
    acetate_type: Optional[str] = ""
    acetate_batch: Optional[str] = "No Batch"
    
    paper_type: Optional[str] = ""
    paper_batch: Optional[str] = "No Batch"
    
    pva_glue_type: Optional[str] = ""
    pva_batch: Optional[str] = "No Batch"
    
    hm_glue_type: Optional[str] = ""
    hm_batch: Optional[str] = "No Batch"
    
    triacetin_type: Optional[str] = ""
    tri_batch: Optional[str] = "No Batch"

    acetate_list: Optional[List[dict]] = None
    paper_list: Optional[List[dict]] = None
    pva_list: Optional[List[dict]] = None
    hm_list: Optional[List[dict]] = None
    tri_list: Optional[List[dict]] = None
    # ------------------------------------------------

    # Системные поля истории изменений
    parent_report_id: Optional[int] = None
    edited_by: Optional[str] = None
    edited_at: Optional[datetime] = None
    status: Optional[str] = "original"
    
    # Прочее
    remarks: Optional[str] = ""
    is_modified_manually: Optional[bool] = False
    is_archived: Optional[bool] = False

    # Human-in-the-loop verification (operator -> supervisor approval)
    verification_status: Optional[str] = "pending"  # pending | approved | rejected
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    
class ReportCreate(ReportBase):
    pass

class Report(ReportBase):
    id: int
    sync_at: datetime
    status: str
    parent_report_id: Optional[int] = None
    edited_by: Optional[str] = None
    edited_at: Optional[datetime] = None
    is_archived: Optional[bool] = False
    model_config = ConfigDict(from_attributes=True)

class ReportSyncRequest(ReportCreate):
    """
    Extended report submission that includes an optional PDF payload (base64).
    Used by the Flutter app to send report data + PDF in a single call.
    """
    pdf_base64: Optional[str] = None
    pdf_filename: Optional[str] = None
# --- REPORT VERIFICATION (human-in-the-loop) ---

class ReportVerifyRequest(BaseModel):
    """Supervisor approval/rejection of operator-entered report data."""
    action: str  # "approve" | "reject"
    note: Optional[str] = None


# --- ODOO PUSH (MO created/confirmed in Odoo -> created in MES) ---

class OdooMoComponent(BaseModel):
    """One filtered BOM line (direct filter-rod material) from Odoo."""
    category: str = ""            # acetate | paper | triacetin | glue
    product_name: str = ""
    product_qty: float = 0.0
    product_uom: Optional[str] = None
    odoo_bom_line_id: Optional[int] = None
    odoo_product_id: Optional[int] = None


class OdooMoSpec(BaseModel):
    """Acceptance spec parsed in Odoo (diameter / length / PD / Cu / weight)."""
    parameter: str
    nominal: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    report_unit: str = ""
    report_scale: float = 1.0
    decimals: int = 3


class OdooMoEvent(BaseModel):
    """Payload pushed by Odoo when an MO is created/confirmed."""
    mo_id: int
    name: str = ""
    state: str = ""
    product_id: Optional[int] = None
    product_name: str = ""
    product_qty: float = 0.0
    product_uom_id: Optional[int] = None
    product_uom_name: str = ""
    origin: str = ""               # sale.order name (customer PO number)
    spec: Optional[dict] = None    # diameter/length/pd/cu/weight/tolerances
    box_type: Optional[int] = None   # rods per box (product's Base Packaging)
    base_packaging_name: str = ""    # e.g. "Case"
    bom: Optional[List[OdooMoComponent]] = None
    root_mo_id: Optional[int] = None    # root mrp.production id (backorders resolve to it)
    root_name: str = ""                 # root MO name
    idempotency_key: str = ""


class OdooMoRecall(BaseModel):
    """Payload for the safe MO recall endpoint (Odoo -> MES)."""
    mo_ref: Optional[str] = None   # e.g. "WH/MO/00218"
    mo_id: Optional[int] = None    # Odoo mrp.production id (alternative)


# --- AI ANALYSIS ---
class AIAnalysisRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # client-generated session UUID for multi-turn
    context_days: int = 30             # how many days of DB data to include as context
    source: Optional[str] = "web"      # 'web' | 'mobile' | 'telegram'

class AIAnalysisResponse(BaseModel):
    id: int
    question: str
    answer: str
    session_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AIAnalysisHistoryItem(BaseModel):
    id: int
    username: str
    question: str
    answer: Optional[str] = None
    source: Optional[str] = None
    session_id: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)