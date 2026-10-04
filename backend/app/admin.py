"""
SQLAdmin Configuration for Production Log System
Provides web-based admin interface with authentication using existing User/Role system.

Compatible with sqladmin 0.24+.
column_filters must use sqladmin.filters objects (BooleanFilter,
AllUniqueStringValuesFilter, StaticValuesFilter) -- raw model attributes
or plain strings are NOT valid column_filters in sqladmin >= 0.14.
"""
import os
import bcrypt
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
import importlib

# Try to import filters - they may not exist in all versions
try:
    from sqladmin.filters import BooleanFilter, AllUniqueStringValuesFilter, StaticValuesFilter
    HAS_FILTERS = True
except ImportError:
    HAS_FILTERS = False
    BooleanFilter = None
    AllUniqueStringValuesFilter = None
    StaticValuesFilter = None

if __package__:
    models = importlib.import_module(f"{__package__}.models")
    database_mod = importlib.import_module(f"{__package__}.database")
    security_config = importlib.import_module(f"{__package__}.security_config")
    SessionLocal = database_mod.SessionLocal
else:
    import models
    import security_config
    from database import SessionLocal, engine as _engine
    class _DB:
        engine = _engine
    database_mod = _DB()


def _verify_sqladmin_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a bcrypt hash for SQLAdmin login.
    Falls back to direct comparison for legacy plain-text hashes."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'), hashed_password.encode('utf-8')
        )
    except (ValueError, TypeError):
        return plain_password == hashed_password


class AdminAuthentication(AuthenticationBackend):
    """Checks credentials against User/Role table.
    Access requires can_manage_users=True OR role_name == 'admin' (case-insensitive).

    AuthenticationBackend registers its own SessionMiddleware automatically with
    the secret_key passed here. Do NOT add a second SessionMiddleware in main.py --
    two layers sign cookies with different keys and break the login redirect.
    """

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        db = SessionLocal()
        try:
            user = db.query(models.User).filter(
                models.User.username == username,
                models.User.is_inactive == False
            ).first()
            if user and _verify_sqladmin_password(password, user.password_hash) and user.role:
                if user.role.can_manage_users or user.role.role_name.lower() in ("admin", "superadmin"):
                    request.session["user"] = {
                        "user_id": user.id,
                        "username": user.username,
                        "role_id": user.role_id,
                    }
                    return True
            return False
        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Return True if a valid session exists, False to redirect to login."""
        return bool(request.session.get("user"))


# ---------------------------------------------------------------------------
# Model Views
# ---------------------------------------------------------------------------

class RoleAdmin(ModelView, model=models.Role):
    column_list = [
        models.Role.id, models.Role.role_name, models.Role.can_create_po,
        models.Role.can_edit_po, models.Role.can_edit_report,
        models.Role.can_manage_users, models.Role.can_setup_machines,
        models.Role.can_view_all_reports,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.Role.role_name, title="Role Name"),
    ] if HAS_FILTERS else []
    column_sortable_list = [models.Role.role_name]
    name = "Role"
    name_plural = "Roles"
    icon = "fa-solid fa-shield"


class UserAdmin(ModelView, model=models.User):
    column_list = [
        models.User.id, models.User.username, models.User.email,
        models.User.role, models.User.is_inactive, models.User.created_at,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.User.username, title="Username"),
        BooleanFilter(models.User.is_inactive, title="Inactive"),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.User.username, models.User.email]
    column_sortable_list = [models.User.username, models.User.created_at]
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"

class MaterialDictionaryAdmin(ModelView, model=models.MaterialDictionary):
    column_list = [
        models.MaterialDictionary.id, models.MaterialDictionary.category,
        models.MaterialDictionary.type_name, models.MaterialDictionary.default_batch,
        models.MaterialDictionary.is_hidden, models.MaterialDictionary.created_at,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.MaterialDictionary.category, title="Category"),
        BooleanFilter(models.MaterialDictionary.is_hidden, title="Hidden"),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.MaterialDictionary.type_name, models.MaterialDictionary.category]
    column_sortable_list = [models.MaterialDictionary.category, models.MaterialDictionary.type_name]
    name = "Material"
    name_plural = "Materials"
    icon = "fa-solid fa-flask"


class MachineAdmin(ModelView, model=models.Machine):
    column_list = [
        models.Machine.id, models.Machine.name,
        models.Machine.remarks, models.Machine.is_inactive,
    ]
    column_filters = [
        BooleanFilter(models.Machine.is_inactive, title="Inactive"),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.Machine.name]
    column_sortable_list = [models.Machine.name]
    name = "Machine"
    name_plural = "Machines"
    icon = "fa-solid fa-gears"


class ShiftAdmin(ModelView, model=models.Shift):
    column_list = [models.Shift.id, models.Shift.name, models.Shift.start_time, models.Shift.end_time]
    column_searchable_list = [models.Shift.name]
    column_sortable_list = [models.Shift.name]
    name = "Shift"
    name_plural = "Shifts"
    icon = "fa-solid fa-clock"


class PurchaseOrderAdmin(ModelView, model=models.PurchaseOrder):
    column_list = [
        models.PurchaseOrder.id, models.PurchaseOrder.po_number,
        models.PurchaseOrder.target_qty, models.PurchaseOrder.produced_qty,
        models.PurchaseOrder.diameter, models.PurchaseOrder.length,
        models.PurchaseOrder.is_hidden, models.PurchaseOrder.created_at,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.PurchaseOrder.po_number, title="PO Number"),
        BooleanFilter(models.PurchaseOrder.is_hidden, title="Hidden"),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.PurchaseOrder.po_number]
    column_sortable_list = [
        models.PurchaseOrder.po_number,
        models.PurchaseOrder.created_at,
        models.PurchaseOrder.produced_qty,
    ]
    name = "Purchase Order"
    name_plural = "Purchase Orders"
    icon = "fa-solid fa-receipt"

class ProductionReportAdmin(ModelView, model=models.ProductionReport):
    column_list = [
        models.ProductionReport.id, models.ProductionReport.report_date,
        models.ProductionReport.shift_name, models.ProductionReport.machine_name,
        models.ProductionReport.operator_name, models.ProductionReport.po_number,
        models.ProductionReport.produced_rods, models.ProductionReport.boxes_produced,
        models.ProductionReport.waste_kg, models.ProductionReport.status,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.ProductionReport.report_date, title="Date"),
        AllUniqueStringValuesFilter(models.ProductionReport.shift_name, title="Shift"),
        AllUniqueStringValuesFilter(models.ProductionReport.machine_name, title="Machine"),
        StaticValuesFilter(
            models.ProductionReport.status,
            title="Status",
            values=[("original", "Original"), ("edited", "Edited"), ("obsolete", "Obsolete")],
        ),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.ProductionReport.po_number, models.ProductionReport.operator_name]
    column_sortable_list = [models.ProductionReport.report_date, models.ProductionReport.produced_rods]
    column_default_sort = [(models.ProductionReport.report_date, True)]
    name = "Production Report"
    name_plural = "Production Reports"
    icon = "fa-solid fa-chart-line"
    can_delete = False


class TelegramQueueAdmin(ModelView, model=models.TelegramQueue):
    column_list = [
        models.TelegramQueue.id, models.TelegramQueue.report_id,
        models.TelegramQueue.status, models.TelegramQueue.attempts,
        models.TelegramQueue.last_error, models.TelegramQueue.created_at,
    ]
    column_filters = [
        StaticValuesFilter(
            models.TelegramQueue.status,
            title="Status",
            values=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        ),
    ] if HAS_FILTERS else []
    column_sortable_list = [models.TelegramQueue.created_at, models.TelegramQueue.status]
    column_default_sort = [(models.TelegramQueue.created_at, True)]
    name = "Telegram Queue"
    name_plural = "Telegram Queues"
    icon = "fa-solid fa-paper-plane"
    can_delete = False


class ReportEditLogAdmin(ModelView, model=models.ReportEditLog):
    column_list = [
        models.ReportEditLog.id, models.ReportEditLog.report_id,
        models.ReportEditLog.username, models.ReportEditLog.changed_fields,
        models.ReportEditLog.edited_at,
    ]
    column_searchable_list = [models.ReportEditLog.username]
    column_sortable_list = [
        models.ReportEditLog.edited_at,
        models.ReportEditLog.report_id,
    ]
    column_default_sort = [(models.ReportEditLog.edited_at, True)]
    name = "Report Edit Log"
    name_plural = "Report Edit Logs"
    icon = "fa-solid fa-pen-to-square"
    can_delete = False
    can_create = False
    can_edit = False


class ReportAuditLogAdmin(ModelView, model=models.ReportAuditLog):
    column_list = [
        models.ReportAuditLog.id, models.ReportAuditLog.report_id,
        models.ReportAuditLog.action, models.ReportAuditLog.username,
        models.ReportAuditLog.changed_fields, models.ReportAuditLog.created_at,
    ]
    column_filters = [
        StaticValuesFilter(
            models.ReportAuditLog.action,
            title="Action",
            values=[
                ("CREATED", "Created"),
                ("EDITED", "Edited"),
                ("DELETED", "Deleted"),
                ("RESTORED", "Restored"),
            ],
        ),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.ReportAuditLog.username]
    column_sortable_list = [
        models.ReportAuditLog.created_at,
        models.ReportAuditLog.report_id,
    ]
    column_default_sort = [(models.ReportAuditLog.created_at, True)]
    name = "Report Audit Log"
    name_plural = "Report Audit Logs"
    icon = "fa-solid fa-clock-rotate-left"
    can_delete = False
    can_create = False
    can_edit = False


class AIAnalysisLogAdmin(ModelView, model=models.AIAnalysisLog):
    column_list = [
        models.AIAnalysisLog.id, models.AIAnalysisLog.username,
        models.AIAnalysisLog.source, models.AIAnalysisLog.question,
        models.AIAnalysisLog.session_id, models.AIAnalysisLog.created_at,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(models.AIAnalysisLog.username, title="User"),
        StaticValuesFilter(
            models.AIAnalysisLog.source,
            title="Source",
            values=[("web", "Web"), ("mobile", "Mobile"), ("telegram", "Telegram")],
        ),
    ] if HAS_FILTERS else []
    column_searchable_list = [models.AIAnalysisLog.username, models.AIAnalysisLog.question]
    column_sortable_list = [models.AIAnalysisLog.created_at]
    column_default_sort = [(models.AIAnalysisLog.created_at, True)]
    name = "AI Analysis Log"
    name_plural = "AI Analysis Logs"
    icon = "fa-solid fa-robot"
    can_delete = False
    can_create = False
    can_edit = False


def setup_admin(app):
    """Initialize SQLAdmin and mount it onto the FastAPI app."""
    auth = AdminAuthentication(secret_key=security_config.get_secret_key())
    admin = Admin(
        app=app,
        engine=database_mod.engine,
        authentication_backend=auth,
        title="Production Log Admin",
    )
    admin.add_view(RoleAdmin)
    admin.add_view(UserAdmin)
    admin.add_view(MaterialDictionaryAdmin)
    admin.add_view(MachineAdmin)
    admin.add_view(ShiftAdmin)
    admin.add_view(PurchaseOrderAdmin)
    admin.add_view(ProductionReportAdmin)
    admin.add_view(TelegramQueueAdmin)
    admin.add_view(ReportEditLogAdmin)
    admin.add_view(ReportAuditLogAdmin)
    admin.add_view(AIAnalysisLogAdmin)
    return admin
