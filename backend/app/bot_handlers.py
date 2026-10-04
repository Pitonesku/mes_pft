"""
Telegram Bot Handlers — aiogram 3.x Router with FSM-based flows.
===============================================================
- /start command with role-based inline keyboard
- Admin flow: Settings → User Management → Add / Edit / Delete user / User List
- User flow: browse active orders, view stats, generate PDFs
- User flow: browse recent reports, view Digital/PDF options
- /ai <question> — AI-powered production data analysis (admin or can_use_ai users)
- /analyze — alias for /ai
"""

import json
import os
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import importlib
if __package__:
    models = importlib.import_module(f"{__package__}.models")
    database_mod = importlib.import_module(f"{__package__}.database")

    ai_svc = importlib.import_module(f"{__package__}.ai_service")
else:
    import models
    from database import SessionLocal
    from pdf_generator import PDFReportGenerator

    import ai_service as ai_svc

# Resolve SessionLocal via database module when running as package
if __package__:
    SessionLocal = database_mod.SessionLocal
    PDFReportGenerator = importlib.import_module(f"{__package__}.pdf_generator").PDFReportGenerator
else:
    from database import SessionLocal
    from pdf_generator import PDFReportGenerator


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = Router()


# ---------------------------------------------------------------------------
# FSM — Admin Add-User Flow (TG ID → Role → AI Access → Confirm)
# ---------------------------------------------------------------------------
class AddUserState(StatesGroup):
    waiting_for_tg_id = State()
    waiting_for_role = State()
    waiting_for_ai_access = State()
    confirm = State()


# ---------------------------------------------------------------------------
# FSM — Admin Delete-User Flow
# ---------------------------------------------------------------------------
class DelUserState(StatesGroup):
    confirm = State()


# ---------------------------------------------------------------------------
# FSM — Admin Edit-User Flow
# ---------------------------------------------------------------------------
class EditUserState(StatesGroup):
    waiting_for_field = State()
    waiting_for_role = State()
    confirm_delete = State()


# ---------------------------------------------------------------------------
# FSM — AI Chat Mode (direct conversation, no /ai prefix needed)
# ---------------------------------------------------------------------------
class AiChatState(StatesGroup):
    waiting_for_question = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_superadmin(user: models.User, kwargs: dict) -> bool:
    """Check if this TG user is the INIT_ADMIN_TG_ID superadmin."""
    init_tg = os.getenv("INIT_ADMIN_TG_ID", "").strip()
    if init_tg and str(user.telegram_id) == init_tg:
        return True
    return False


def _can_manage_users(kwargs: dict) -> bool:
    """Check if this TG user has admin access (can manage users)."""
    return (kwargs.get("user_role") or "user") == "admin"


def _can_use_ai(db_user: dict, kwargs: dict) -> bool:
    """Check if user is allowed to use the /ai command."""
    # Superadmin always can
    tg_id = str(db_user.get("telegram_id", ""))
    init_tg = os.getenv("INIT_ADMIN_TG_ID", "").strip()
    if init_tg and tg_id == init_tg:
        return True
    # Admin role can
    if (kwargs.get("user_role") or "user") == "admin":
        return True
    # Explicit DB flag
    return db_user.get("can_use_ai", False) == True


def build_main_keyboard(db_user: dict, kwargs: dict) -> InlineKeyboardMarkup:
    """Build the main menu keyboard, role-aware."""
    buttons = [
        [InlineKeyboardButton(text="📦 Orders", callback_data="orders")],
        [InlineKeyboardButton(text="📊 Reports", callback_data="reports")],
    ]
    if _can_use_ai(db_user, kwargs):
        buttons.append(
            [InlineKeyboardButton(text="🤖 AI Analysis", callback_data="ai_menu")]
        )
    if _can_manage_users(kwargs):
        buttons.append(
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="settings")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# Helper: generate PDF and send as document
# ---------------------------------------------------------------------------
async def generate_and_send_pdf(
    report_data: dict,
    chat_id: int,
    bot: Bot,
) -> None:
    """Generate a PDF from report_data, save locally, and send via Telegram."""
    try:
        generator = PDFReportGenerator()
        result = generator.generate_pdf(report_data)

        if not result.get("success"):
            await bot.send_message(
                chat_id=chat_id,
                text=f"PDF generation error: {result.get('error', 'Unknown error')}",
            )
            return

        pdf_path = result["path"]
        if not os.path.isfile(pdf_path):
            await bot.send_message(
                chat_id=chat_id,
                text="PDF file was not created on server.",
            )
            return

        document = FSInputFile(pdf_path)
        await bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=f"Report: {result.get('filename', 'report.pdf')}",
        )
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Error sending PDF: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Helper: build the Telegram-format digital report text
# ---------------------------------------------------------------------------
def build_digital_report_text(report: models.ProductionReport, po: models.PurchaseOrder = None) -> str:
    """Build the same formatted text sent during report submission."""
    shift_display = (
        f"{report.shift_name} ({report.shift_time_range})"
        if report.shift_time_range
        else datetime.now().strftime("%H:%M:%S")
    )

    if report.parent_report_id or report.edited_by:
        text = (
            f"Edited report from {report.report_date}/{report.shift_name}/{report.operator_name}/{report.machine_name}\n"
            f"Edited by: {report.edited_by or report.operator_name}\n"
            f"Date: {report.report_date}\n"
            f"Time: {shift_display}\n"
            f"Operator: {report.operator_name}\n"
            f"Machine #: {report.machine_name}\n\n"
        )
    else:
        text = (
            f"Production report submitted\n"
            f"Date: {report.report_date}\n"
            f"Time: {shift_display}\n"
            f"Operator: {report.operator_name}\n"
            f"Machine #: {report.machine_name}\n\n"
        )

    # Build diff_percent display
    raw_diff_pct_str = str(report.diff_percent or "0").replace('%', '').strip()
    try:
        diff_pct_val = float(raw_diff_pct_str)
    except ValueError:
        diff_pct_val = 0.0

    if diff_pct_val < 0 and abs(diff_pct_val) > 0.5:
        diff_marker = "🔴"
    elif abs(diff_pct_val) > 2.0:
        diff_marker = "🟠⚠"
    elif abs(diff_pct_val) > 1.0:
        diff_marker = "⚠️"
    else:
        diff_marker = ""

    cu_val = getattr(report, 'cu', 0) or 0

    text += (
        f"PO #: {report.po_number}\n"
        f"Lot #: {report.lot_number or ''}\n"
        f"Box type: {report.box_type}\n"
        f"Diameter (mm): {report.diameter}\n"
        f"Length (mm): {report.length}\n"
        f"PD (mmWg): {report.pd}\n"
        f"CU (Porosity): {cu_val}\n"
        f"Weight (mg): {report.weight}\n\n"

        f"Box produced: {report.boxes_produced}\n"
        f"Produced rods: {report.produced_rods}\n"
        f"Machine counter: {report.machine_counter}\n"
        f"Difference: {report.difference}\n"
        f"Diff,%: {raw_diff_pct_str} {diff_marker}\n"
        f"Waste (kg): {report.waste_kg}\n"
        f"Machine efficiency %: {report.machine_efficiency}\n\n"

        f"Remarks: {report.remarks or 'No comments.'}"
    )

    # Total materials used
    if report.total_acetate or report.total_paper or report.total_pva or report.total_hm or report.total_triacetin:
        text += "\n\nTotal used:\n"
        text += f"Acetate: {report.total_acetate} kg | "
        text += f"Paper: {report.total_paper} Bob | "
        text += f"PVA Glue: {report.total_pva} kg | "
        text += f"Hot Melt Glue: {report.total_hm} kg | "
        text += f"Triacetin: {report.total_triacetin} kg"

    # Add PO totals if available
    if po:
        remaining = po.target_qty - po.produced_qty
        text += (
            f"\n\nTotal PO Produced: {po.produced_qty}\n"
            f"Remaining to produce: {remaining}"
        )

    return text


# ===========================================================================
# /start COMMAND
# ===========================================================================
@router.message(Command("start"))
async def cmd_start(message: Message, **kwargs):
    """Entry point — show role-aware main menu."""
    db_user = kwargs.get("db_user") or {}
    user_role = kwargs.get("user_role") or "user"

    greeting = (
        f"Welcome, {db_user.get('username', 'operator')}!\n\n"
        "Select action:"
    )
    keyboard = build_main_keyboard(db_user, kwargs)
    await message.answer(greeting, reply_markup=keyboard)


# ===========================================================================
# MAIN MENU CALLBACKS
# ===========================================================================

# --- Back to main menu ---
@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, **kwargs):
    db_user = kwargs.get("db_user") or {}
    greeting = (
        f"Welcome, {db_user.get('username', 'operator')}!\n\n"
        "Select action:"
    )
    await callback.message.edit_text(greeting, reply_markup=build_main_keyboard(db_user, kwargs))
    await callback.answer()


# ===========================================================================
# AI ANALYSIS MENU (accessible if can_use_ai or admin)
# ===========================================================================

_AI_HELP = (
    "🤖 *Production AI Analyst*\n\n"
    "Usage: `/ai <your question>`\n\n"
    "_Example:_ `/ai Which machine had the highest waste last week?`"
)

_AI_EXAMPLES = [
    "Which machine had the highest efficiency last month?",
    "What is the total waste and how does it compare per shift?",
    "Which operator produced the most boxes this week?",
    "Show me the completion status of all active purchase orders.",
    "Are there any concerning trends in production output?",
]


@router.callback_query(F.data == "ai_menu")
async def cb_ai_menu(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Enter AI chat mode — user can ask questions directly without /ai prefix."""
    db_user = kwargs.get("db_user") or {}
    if not _can_use_ai(db_user, kwargs):
        await callback.answer("⛔ AI analysis is not available for your account.", show_alert=True)
        return

    await state.set_state(AiChatState.waiting_for_question)

    text = (
        "🤖 *AI Chat Mode*\n\n"
        "Ask anything about production data — no /ai prefix needed.\n"
        "_Example: Which machine had the highest waste last week?_"
    )

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔚 End AI Chat", callback_data="end_ai_chat")],
            ]
        ),
    )
    await callback.answer()


# --- Handle chat messages in AI mode ---
@router.message(AiChatState.waiting_for_question)
async def ai_chat_message(message: Message, state: FSMContext, **kwargs):
    """Process a question typed in AI chat mode."""
    question = (message.text or "").strip()
    if not question:
        await message.answer(
            "Please type your question about production data.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔚 End AI Chat", callback_data="end_ai_chat")],
                ]
            ),
        )
        return

    db_user = kwargs.get("db_user") or {}

    if not _can_use_ai(db_user, kwargs):
        await message.answer("⛔ AI analysis is not available for your account.")
        return

    await message.answer("🔍 Analysing production data, please wait…")

    db = SessionLocal()
    try:
        db_context = ai_svc.build_db_context(db, days=30)
        answer = await ai_svc.query_ai(question=question, db_context=db_context)

        log = models.AIAnalysisLog(
            username=db_user.get("username", f"tg:{message.from_user.id}"),
            question=question,
            answer=answer,
            source="telegram",
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        answer = f"❌ Error: {exc}"
    finally:
        db.close()

    # Send answer with "End AI Chat" button
    for i in range(0, len(answer), 4000):
        chunk = answer[i:i + 4000]
        if i + 4000 < len(answer):
            await message.answer(chunk)
        else:
            await message.answer(
                chunk,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔚 End AI Chat", callback_data="end_ai_chat")],
                    ]
                ),
            )


# --- End AI Chat callback ---
@router.callback_query(F.data == "end_ai_chat")
async def cb_end_ai_chat(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Exit AI chat mode and return to main menu."""
    await state.clear()
    db_user = kwargs.get("db_user") or {}
    greeting = (
        f"Welcome, {db_user.get('username', 'operator')}!\n\n"
        "Select action:"
    )
    await callback.message.edit_text(greeting, reply_markup=build_main_keyboard(db_user, kwargs))
    await callback.answer("AI chat ended.")


# ===========================================================================
# ADMIN FLOW — "⚙️ Settings"
# ===========================================================================

@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery, **kwargs):
    """Admin settings menu."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.message.edit_text(
        "⚙️ *Settings*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👥 User Management", callback_data="user_mgmt")],
                [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")],
            ]
        ),
    )
    await callback.answer()


# --- User Management submenu ---
@router.callback_query(F.data == "user_mgmt")
async def cb_user_mgmt(callback: CallbackQuery, **kwargs):
    """User management: Add / Edit / Delete user / User List."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.message.edit_text(
        "👥 *User Management*\nSelect action:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 User List", callback_data="user_list")],
                [InlineKeyboardButton(text="➕ Add User", callback_data="add_user")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="settings")],
            ]
        ),
    )
    await callback.answer()


# ===========================================================================
# USER LIST — View all bot users
# ===========================================================================

@router.callback_query(F.data == "user_list")
async def cb_user_list(callback: CallbackQuery, **kwargs):
    """Show list of all Telegram bot users."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    db = SessionLocal()
    try:
        users = (
            db.query(models.User)
            .filter(models.User.telegram_id.isnot(None))
            .order_by(models.User.id.asc())
            .all()
        )

        if not users:
            await callback.message.edit_text(
                "👥 *User List*\n\nNo bot users found.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            await callback.answer()
            return

        text_lines = ["👥 *Bot Users:*\n"]
        buttons = []
        for u in users:
            tg_id = u.telegram_id
            init_tg = os.getenv("INIT_ADMIN_TG_ID", "").strip()
            is_super = bool(init_tg and str(tg_id) == init_tg)
            ai_mark = "✅" if u.can_use_ai else "❌"
            role_label = "🔧 Admin" if u.tg_role == "admin" else "👤 User"
            lock = " 🔒" if is_super else ""

            text_lines.append(
                f"• *{u.username}*{lock} | TG: `{tg_id}` | {role_label} | AI: {ai_mark}"
            )
            buttons.append(
                [InlineKeyboardButton(
                    text=f"{u.username} ({u.tg_role})",
                    callback_data=f"edituser_{u.id}"
                )]
            )

        buttons.append(
            [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
        )

        await callback.message.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        db.close()
    await callback.answer()


# ===========================================================================
# EDIT USER FLOW — change role, toggle AI, delete
# ===========================================================================

@router.callback_query(F.data.startswith("edituser_"))
async def cb_edit_user(callback: CallbackQuery, **kwargs):
    """Show edit user screen with current settings."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid user ID")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.telegram_id.isnot(None),
        ).first()

        if not user:
            await callback.answer("User not found")
            return

        is_super = _is_superadmin(user, kwargs)
        role_label = "🔧 Admin" if user.tg_role == "admin" else "👤 User"
        ai_label = "✅ Allowed" if user.can_use_ai else "❌ Denied"
        lock_text = " 🔒 Superadmin (cannot be edited)" if is_super else ""

        text = (
            f"✏️ *Edit User*\n\n"
            f"Username: `{user.username}`\n"
            f"Telegram ID: `{user.telegram_id}`\n"
            f"Role: *{role_label}*\n"
            f"AI Access: *{ai_label}*\n"
            f"{lock_text}\n\n"
            "Select action:"
        )

        kb = []
        if not is_super:
            kb.append([InlineKeyboardButton(
                text="🔀 Toggle Role (Admin ↔ User)",
                callback_data=f"togglerole_{user.id}"
            )])
            kb.append([InlineKeyboardButton(
                text="🤖 Toggle AI Access",
                callback_data=f"toggleai_{user.id}"
            )])
            kb.append([InlineKeyboardButton(
                text="🗑 Delete User",
                callback_data=f"deluser_{user.id}"
            )])
        kb.append([InlineKeyboardButton(text="🔙 User List", callback_data="user_list")])

        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        )
    finally:
        db.close()
    await callback.answer()


# --- Toggle Role ---
@router.callback_query(F.data.startswith("togglerole_"))
async def cb_toggle_role(callback: CallbackQuery, **kwargs):
    """Toggle a user's tg_role between admin and user."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid user ID")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.telegram_id.isnot(None),
        ).first()

        if not user:
            await callback.answer("User not found")
            return

        if _is_superadmin(user, kwargs):
            await callback.answer("Cannot edit superadmin.", show_alert=True)
            return

        # Guard: cannot demote the last admin
        if user.tg_role == "admin":
            admin_count = (
                db.query(models.User)
                .filter(models.User.tg_role == "admin", models.User.telegram_id.isnot(None))
                .count()
            )
            if admin_count <= 1:
                await callback.answer(
                    "Cannot demote last admin. Promote another user first.",
                    show_alert=True,
                )
                return

        new_role = "user" if user.tg_role == "admin" else "admin"
        user.tg_role = new_role
        db.commit()

        await callback.answer(f"Role changed to {'Admin' if new_role == 'admin' else 'User'}.")
        # Refresh the edit view
        await cb_edit_user(callback, **kwargs)
    finally:
        db.close()


# --- Toggle AI Access ---
@router.callback_query(F.data.startswith("toggleai_"))
async def cb_toggle_ai(callback: CallbackQuery, **kwargs):
    """Toggle a user's can_use_ai flag."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid user ID")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.telegram_id.isnot(None),
        ).first()

        if not user:
            await callback.answer("User not found")
            return

        if _is_superadmin(user, kwargs):
            await callback.answer("Cannot edit superadmin.", show_alert=True)
            return

        user.can_use_ai = not user.can_use_ai
        db.commit()

        label = "Allowed" if user.can_use_ai else "Denied"
        await callback.answer(f"AI access: {label}")
        await cb_edit_user(callback, **kwargs)
    finally:
        db.close()


# ===========================================================================
# ADMIN FLOW — "➕ Add User"
# ===========================================================================

@router.callback_query(F.data == "add_user")
async def cb_add_user_start(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Admin tapped 'Add User' — ask for Telegram ID."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.message.edit_text(
        "🔑 Enter Telegram ID of the new user (digits only):\n\n"
        "Example: 123456789",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")]
            ]
        ),
    )
    await state.set_state(AddUserState.waiting_for_tg_id)
    await callback.answer()


@router.message(AddUserState.waiting_for_tg_id)
async def fsm_tg_id_received(message: Message, state: FSMContext):
    """Validate the typed Telegram ID (digits only)."""
    raw = message.text.strip() if message.text else ""

    if not raw.isdigit():
        await message.answer(
            "Telegram ID must contain only digits. Try again:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")]
                ]
            ),
        )
        return

    tg_id = int(raw)
    await state.update_data(new_tg_id=tg_id)

    # Ask for role
    await message.answer(
        f"Telegram ID: `{tg_id}`\n\nSelect role for the new user:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👤 User", callback_data="role_user")],
                [InlineKeyboardButton(text="🔧 Admin", callback_data="role_admin")],
                [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")],
            ]
        ),
    )
    await state.set_state(AddUserState.waiting_for_role)


@router.callback_query(AddUserState.waiting_for_role, F.data.in_({"role_user", "role_admin"}))
async def fsm_role_selected(callback: CallbackQuery, state: FSMContext):
    """Role selected — ask for AI access."""
    role_raw = callback.data  # "role_user" or "role_admin"
    role_value = "user" if role_raw == "role_user" else "admin"

    await state.update_data(new_role=role_value)

    await callback.message.edit_text(
        f"Role set to *{'User' if role_value == 'user' else 'Admin'}*\n\n"
        "Allow this user to use AI analysis (/ai command)?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Allow AI", callback_data="ai_yes")],
                [InlineKeyboardButton(text="❌ Deny AI", callback_data="ai_no")],
                [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")],
            ]
        ),
    )
    await state.set_state(AddUserState.waiting_for_ai_access)
    await callback.answer()


@router.callback_query(AddUserState.waiting_for_ai_access, F.data.in_({"ai_yes", "ai_no"}))
async def fsm_ai_access_selected(callback: CallbackQuery, state: FSMContext):
    """AI access selected — show confirmation."""
    ai_allowed = callback.data == "ai_yes"
    await state.update_data(new_ai_access=ai_allowed)

    data = await state.get_data()
    tg_id = data.get("new_tg_id")
    role_value = data.get("new_role", "user")
    role_label = "Admin" if role_value == "admin" else "User"
    ai_label = "✅ Allowed" if ai_allowed else "❌ Denied"

    confirm_text = (
        "*Confirm new user*\n\n"
        f"Telegram ID: `{tg_id}`\n"
        f"Role: *{role_label}*\n"
        f"AI Access: *{ai_label}*\n\n"
        "Confirm creation?"
    )
    await callback.message.edit_text(
        confirm_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Confirm", callback_data="confirm_add")],
                [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")],
            ]
        ),
    )
    await state.set_state(AddUserState.confirm)
    await callback.answer()


@router.callback_query(AddUserState.confirm, F.data == "confirm_add")
async def fsm_confirm_add(callback: CallbackQuery, state: FSMContext):
    """Final confirmation — save to database."""
    fsm_data = await state.get_data()
    tg_id = fsm_data.get("new_tg_id")
    role_value = fsm_data.get("new_role", "user")
    ai_access = fsm_data.get("new_ai_access", False)

    db = SessionLocal()
    try:
        # Check for duplicate
        existing = db.query(models.User).filter(
            models.User.telegram_id == tg_id
        ).first()
        if existing:
            await callback.message.edit_text(
                f"User with Telegram ID `{tg_id}` already exists.\n"
                f"Username: {existing.username}, role: {existing.tg_role or 'user'}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            await state.clear()
            await callback.answer()
            return

        # Create a system-generated username for the bot user
        username = f"tg_{tg_id}"
        counter = 1
        while db.query(models.User).filter(models.User.username == username).first():
            username = f"tg_{tg_id}_{counter}"
            counter += 1

        new_user = models.User(
            username=username,
            email="",
            password_hash="",  # Bot users don't have passwords
            telegram_id=tg_id,
            tg_role=role_value,
            can_use_ai=ai_access,
            is_inactive=False,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        role_label = "Admin" if role_value == "admin" else "User"
        ai_label = "✅ Allowed" if ai_access else "❌ Denied"
        await callback.message.edit_text(
            f"*User created successfully!*\n\n"
            f"Telegram ID: `{tg_id}`\n"
            f"System name: `{username}`\n"
            f"Role: *{role_label}*\n"
            f"AI Access: *{ai_label}*\n\n"
            f"The user can start using the bot by sending /start",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                ]
            ),
        )
    except Exception as e:
        db.rollback()
        await callback.message.edit_text(
            f"Error creating user: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                ]
            ),
        )
    finally:
        db.close()

    await state.clear()
    await callback.answer()


# ===========================================================================
# ADMIN FLOW — "🗑 Delete User"
# ===========================================================================

@router.callback_query(F.data == "del_user")
async def cb_del_user_start(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Admin tapped 'Delete User' — show list of bot users to choose from."""
    if not _can_manage_users(kwargs):
        await callback.answer("Access denied.", show_alert=True)
        return

    db = SessionLocal()
    try:
        users = (
            db.query(models.User)
            .filter(models.User.telegram_id.isnot(None))
            .order_by(models.User.id.asc())
            .all()
        )

        if not users:
            await callback.message.edit_text(
                "🗑 No bot users found.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            await callback.answer()
            return

        buttons = []
        for u in users:
            role_label = u.tg_role or "user"
            label = f"{u.username} [{role_label}] — TG: {u.telegram_id}"
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"deluser_{u.id}")]
            )
        buttons.append(
            [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")]
        )

        await callback.message.edit_text(
            "🗑 *Select user to delete:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        db.close()
    await callback.answer()


@router.callback_query(F.data.startswith("deluser_"))
async def cb_deluser_selected(callback: CallbackQuery, state: FSMContext, **kwargs):
    """User tapped a user to delete — show confirmation."""
    try:
        user_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid user ID")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.id == user_id
        ).first()

        if not user:
            await callback.message.edit_text(
                "User not found.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            await callback.answer()
            return

        # Guard: cannot delete superadmin
        if _is_superadmin(user, kwargs):
            await callback.answer("Cannot delete superadmin.", show_alert=True)
            await callback.message.edit_text(
                "⚠️ This user is the initial admin configured in .env and cannot be deleted.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            return

        # Guard: cannot delete the last remaining admin
        if user.tg_role == "admin":
            admin_count = (
                db.query(models.User)
                .filter(models.User.tg_role == "admin", models.User.telegram_id.isnot(None))
                .count()
            )
            if admin_count <= 1:
                await callback.answer("Cannot delete last admin.", show_alert=True)
                return

        tg_id = user.telegram_id
        role_label = user.tg_role or "user"

        await state.update_data(del_tg_id=tg_id, del_username=user.username, del_role=role_label)

        await callback.message.edit_text(
            f"*Confirm deletion*\n\n"
            f"Telegram ID: `{tg_id}`\n"
            f"Username: *{user.username}*\n"
            f"Role: *{role_label}*\n\n"
            f"Are you sure you want to delete this user?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Confirm Delete", callback_data="confirm_delete_user")],
                    [InlineKeyboardButton(text="Cancel", callback_data="user_mgmt")],
                ]
            ),
        )
        await state.set_state(DelUserState.confirm)
    finally:
        db.close()
    await callback.answer()


@router.callback_query(DelUserState.confirm, F.data == "confirm_delete_user")
async def fsm_confirm_delete_user(callback: CallbackQuery, state: FSMContext):
    """Delete the user from database."""
    fsm_data = await state.get_data()
    tg_id = fsm_data.get("del_tg_id")
    username = fsm_data.get("del_username", "unknown")

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.telegram_id == tg_id
        ).first()

        if not user:
            await callback.message.edit_text(
                f"User with Telegram ID `{tg_id}` no longer exists.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                    ]
                ),
            )
            await state.clear()
            await callback.answer()
            return

        db.delete(user)
        db.commit()

        await callback.message.edit_text(
            f"*User deleted successfully!*\n\n"
            f"Username: `{username}`\n"
            f"Telegram ID: `{tg_id}`\n\n"
            f"This user will no longer have access to the bot.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                ]
            ),
        )
    except Exception as e:
        db.rollback()
        await callback.message.edit_text(
            f"Error deleting user: {str(e)}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 User Management", callback_data="user_mgmt")]
                ]
            ),
        )
    finally:
        db.close()

    await state.clear()
    await callback.answer()


# ===========================================================================
# USER FLOW — "📦 Orders"
# ===========================================================================

@router.callback_query(F.data == "orders")
async def cb_orders_list(callback: CallbackQuery):
    """Redirect to paginated orders (active only, page 0)."""
    await cb_orders_paginated(callback, offset=0, filter_mode="active")
    await callback.answer()


# --- Paginated orders with active/all filter ---
async def cb_orders_paginated(callback: CallbackQuery, offset: int = 0, filter_mode: str = "active"):
    """Show orders with pagination (10 per page) and active/all filter."""
    page_size = 10

    db = SessionLocal()
    try:
        query = db.query(models.PurchaseOrder)
        if filter_mode == "active":
            query = query.filter(models.PurchaseOrder.is_archived == False)

        total = query.count()
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        orders = (
            query.order_by(models.PurchaseOrder.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        header = "*Active Orders:*" if filter_mode == "active" else "*All Orders:*"
        header += f"\nPage {offset // page_size + 1}/{total_pages}"

        if not orders:
            await callback.message.edit_text(
                f"📦 {header}\nNo orders found.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
                    ]
                ),
            )
            return

        buttons = []
        for po in orders:
            dia = f"{(po.diameter or 0):.2f}"
            length = int(po.length or 0)
            pd_val = int(po.pd or 0)
            cu_val = int(po.cu or 0)
            pcs_per_1000 = (po.target_qty or 0) / 1000

            if po.target_qty and po.target_qty % 1000 == 0:
                qty_label = f"{int(pcs_per_1000)}k pcs"
            else:
                qty_label = f"{pcs_per_1000:.1f}k pcs"

            label = (
                f"{po.po_number} — {dia}*{length} PD {pd_val} CU {cu_val} — {qty_label}"
            )
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"order_{po.id}")]
            )

        # Filter toggle row
        toggle_row = []
        if filter_mode == "active":
            toggle_row.append(
                InlineKeyboardButton(text="📋 Show All", callback_data="orders_p0_all")
            )
        else:
            toggle_row.append(
                InlineKeyboardButton(text="🟢 Active Only", callback_data="orders_p0_active")
            )
        buttons.append(toggle_row)

        # Pagination row
        pag_row = []
        if offset > 0:
            prev_offset = max(0, offset - page_size)
            pag_row.append(
                InlineKeyboardButton(
                    text="⬅ Prev 10", callback_data=f"orders_p{prev_offset}_{filter_mode}"
                )
            )
        if offset + page_size < total:
            next_offset = offset + page_size
            pag_row.append(
                InlineKeyboardButton(
                    text="Next 10 ➡", callback_data=f"orders_p{next_offset}_{filter_mode}"
                )
            )
        if pag_row:
            buttons.append(pag_row)

        buttons.append(
            [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
        )

        await callback.message.edit_text(
            header + "\nSelect an order to view:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        db.close()


# Handler for paginated orders callbacks
@router.callback_query(F.data.startswith("orders_p"))
async def handle_orders_paginated(callback: CallbackQuery):
    """Parse orders_p{offset}_{filter} callback."""
    try:
        parts = callback.data.replace("orders_p", "").split("_", 1)
        offset = int(parts[0])
        filter_mode = parts[1] if len(parts) > 1 else "active"
    except (ValueError, IndexError):
        offset = 0
        filter_mode = "active"

    await cb_orders_paginated(callback, offset=offset, filter_mode=filter_mode)
    await callback.answer()


# --- Single order detail ---
@router.callback_query(F.data.startswith("order_"))
async def cb_order_detail(callback: CallbackQuery):
    """Show order detail card with options."""
    try:
        po_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid order ID")
        return

    db = SessionLocal()
    try:
        po = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.id == po_id
        ).first()

        if not po:
            await callback.answer("Order not found")
            return

        report_count = (
            db.query(models.ProductionReport)
            .filter(models.ProductionReport.po_number == po.po_number)
            .count()
        )

        dia = f"{(po.diameter or 0):.2f}"
        length = int(po.length or 0)
        pd_val = int(po.pd or 0)
        cu_val = int(po.cu or 0)

        detail_text = (
            f"📦 *Order {po.po_number}*\n\n"
            f"Specification: {dia}×{length} PD {pd_val} CU {cu_val}\n\n"
            f"Target qty: {po.target_qty} pcs\n"
            f"Produced: {po.produced_qty} pcs\n"
            f"Diameter: {dia} mm\n"
            f"Length: {length} mm\n"
            f"PD: {pd_val} mmWg\n"
            f"CU: {cu_val}\n"
            f"Weight: {po.weight} mg\n"
            f"Box type: {po.box_type}\n"
            f"Reports: {report_count}\n"
            f"{'🔒 Archived' if po.is_archived else '🟢 Active'}"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Statistics", callback_data=f"stats_{po.id}")],
                [InlineKeyboardButton(text="📄 Reports", callback_data=f"reports_{po.id}")],
                [InlineKeyboardButton(text="⬅ Back to Orders", callback_data="orders")],
            ]
        )

        await callback.message.edit_text(
            detail_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    finally:
        db.close()
    await callback.answer()


# ===========================================================================
# STATISTICS — simplified digital format
# ===========================================================================

_stats_cache = {}


@router.callback_query(F.data.startswith("stats_"))
async def cb_po_stats(callback: CallbackQuery):
    """Show simplified statistics for a purchase order (digital format)."""
    try:
        po_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid order ID")
        return

    db = SessionLocal()
    try:
        po = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.id == po_id
        ).first()
        if not po:
            await callback.answer("Order not found")
            return

        reports = (
            db.query(models.ProductionReport)
            .filter(models.ProductionReport.po_number == po.po_number)
            .order_by(models.ProductionReport.id.asc())
            .all()
        )

        total_rods = 0
        total_machine_counter = 0
        total_waste = 0.0

        total_acetate = 0.0
        total_paper = 0.0
        total_pva = 0.0
        total_hm = 0.0
        total_tri = 0.0

        for r in reports:
            total_rods += r.produced_rods or 0
            total_machine_counter += r.machine_counter or 0
            total_waste += r.waste_kg or 0.0
            total_acetate += r.total_acetate or 0.0
            total_paper += r.total_paper or 0.0
            total_pva += r.total_pva or 0.0
            total_hm += r.total_hm or 0.0
            total_tri += r.total_triacetin or 0.0

        diff_pcs = total_machine_counter - total_rods
        diff_pct_summary = (diff_pcs / total_machine_counter * 100) if total_machine_counter > 0 else 0.0
        remaining = po.target_qty - total_rods

        if diff_pct_summary < 0 and abs(diff_pct_summary) > 0.5:
            diff_marker = "🔴"
        elif abs(diff_pct_summary) > 2.0:
            diff_marker = "🟠⚠"
        elif abs(diff_pct_summary) > 1.0:
            diff_marker = "⚠️"
        else:
            diff_marker = ""

        dia = f"{(po.diameter or 0):.2f}"
        length = int(po.length or 0)
        pd_val = int(po.pd or 0)
        cu_val = int(po.cu or 0)

        stats_text = (
            f"*Statistic {po.po_number}*\n"
            f"Specification: {dia}×{length} PD {pd_val} CU {cu_val}\n\n"
            f"Target rods: {po.target_qty}\n"
            f"Rods produced: {total_rods}\n"
            f"Machine counter: {total_machine_counter}\n"
            f"Difference: {diff_pcs} ({diff_pct_summary:.1f}%) {diff_marker}\n"
            f"*Remains to be produced: {remaining}*\n"
            f"Scrap: {total_waste:.2f} kg"
        )

        mats_used = (
            total_acetate > 0 or total_paper > 0 or total_pva > 0
            or total_hm > 0 or total_tri > 0
        )
        if mats_used:
            stats_text += (
                f"\n\n*Material Consumption Details:*\n"
                f"• Acetate: {total_acetate:.2f} kg\n"
                f"• Paper: {total_paper:.2f} Bob\n"
                f"• PVA Glue: {total_pva:.2f} kg\n"
                f"• Hot Melt Glue: {total_hm:.2f} kg\n"
                f"• Triacetin: {total_tri:.2f} kg"
            )

        _stats_cache[po_id] = {
            "po": po,
            "reports": reports,
            "timestamp": datetime.now(),
        }

        await callback.message.edit_text(
            stats_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📄 Download PDF (Audit)", callback_data=f"auditpdf_{po.id}")],
                    [InlineKeyboardButton(text="⬅ Back to Order", callback_data=f"order_{po.id}")],
                    [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")],
                ]
            ),
        )
    finally:
        db.close()
    await callback.answer()


# --- Audit PDF for a PO ---
@router.callback_query(F.data.startswith("auditpdf_"))
async def cb_audit_pdf(callback: CallbackQuery, bot: Bot):
    """Generate and send audit PDF for a purchase order."""
    try:
        po_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid order ID")
        return

    cached = _stats_cache.get(po_id)
    if not cached or (datetime.now() - cached["timestamp"]).total_seconds() > 300:
        await callback.answer("Data expired. Please open statistics again.", show_alert=True)
        return

    po = cached["po"]
    reports = cached["reports"]

    await callback.answer("Generating PDF audit...")

    try:
        generator = PDFReportGenerator()
        result = generator.generate_audit_pdf(po, reports)

        if not result.get("success"):
            await callback.message.answer(
                f"PDF generation error: {result.get('error', 'Unknown error')}",
            )
            return

        pdf_path = result["path"]
        if not os.path.isfile(pdf_path):
            await callback.message.answer("PDF file was not created on server.")
            return

        document = FSInputFile(pdf_path)
        await bot.send_document(
            chat_id=callback.message.chat.id,
            document=document,
            caption=f"Audit: {po.po_number}",
        )

        db_user = {}
        await callback.message.answer(
            "PDF sent. Select action:",
            reply_markup=build_main_keyboard(db_user, {}),
        )
    except Exception as e:
        await callback.message.answer(f"Error generating PDF: {str(e)}")

    await callback.answer()


# --- Reports list for a specific PO ---
@router.callback_query(F.data.startswith("reports_"))
async def cb_po_reports(callback: CallbackQuery):
    """List reports for a specific purchase order — tap for Digital/PDF options."""
    try:
        po_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid order ID")
        return

    db = SessionLocal()
    try:
        po = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.id == po_id
        ).first()
        if not po:
            await callback.answer("Order not found")
            return

        reports = (
            db.query(models.ProductionReport)
            .filter(models.ProductionReport.po_number == po.po_number)
            .order_by(models.ProductionReport.id.desc())
            .limit(15)
            .all()
        )

        if not reports:
            await callback.message.edit_text(
                f"No reports for order {po.po_number}.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅ Back to Order", callback_data=f"order_{po.id}")]
                    ]
                ),
            )
            await callback.answer()
            return

        buttons = []
        for r in reports:
            label = (
                f"{r.report_date} | {r.machine_name} | {r.shift_name} | "
                f"{r.produced_rods} pcs"
            )
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"reportopt_{r.id}")]
            )
        buttons.append(
            [InlineKeyboardButton(text="⬅ Back to Order", callback_data=f"order_{po.id}")]
        )

        await callback.message.edit_text(
            f"*Reports for order {po.po_number}:*\n"
            "Tap a report to choose format (Digital / PDF):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        db.close()
    await callback.answer()


# ===========================================================================
# USER FLOW — "📊 Reports"
# ===========================================================================

@router.callback_query(F.data == "reports")
async def cb_reports_list(callback: CallbackQuery):
    """Redirect to paginated reports (today, page 0)."""
    await cb_reports_paginated(callback, offset=0, filter_mode="today")
    await callback.answer()


async def cb_reports_paginated(callback: CallbackQuery, offset: int = 0, filter_mode: str = "today"):
    """Show reports with pagination (10 per page) and date filter."""
    page_size = 10
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    yesterday_start = today_start - timedelta(days=1)

    db = SessionLocal()
    try:
        query = db.query(models.ProductionReport)

        if filter_mode == "today":
            query = query.filter(models.ProductionReport.sync_at >= today_start)
            header = "*Today's Reports:*"
        elif filter_mode == "yesterday":
            query = query.filter(
                models.ProductionReport.sync_at >= yesterday_start,
                models.ProductionReport.sync_at < today_start,
            )
            header = "*Yesterday's Reports:*"
        else:
            header = "*All Reports:*"

        total = query.count()
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        reports = (
            query.order_by(models.ProductionReport.id.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        header += f"\nPage {offset // page_size + 1}/{total_pages}"

        if not reports:
            await callback.message.edit_text(
                f"📊 {header}\nNo reports found.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
                    ]
                ),
            )
            return

        buttons = []
        for r in reports:
            label = f"{r.report_date} | {r.machine_name} | {r.shift_name}"
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"reportopt_{r.id}")]
            )

        toggle_row = []
        if filter_mode == "today":
            toggle_row.append(InlineKeyboardButton(text="📅 Yesterday", callback_data="rptlist_p0_yesterday"))
            toggle_row.append(InlineKeyboardButton(text="📊 All Reports", callback_data="rptlist_p0_all"))
        elif filter_mode == "yesterday":
            toggle_row.append(InlineKeyboardButton(text="📅 Today", callback_data="rptlist_p0_today"))
            toggle_row.append(InlineKeyboardButton(text="📊 All Reports", callback_data="rptlist_p0_all"))
        else:
            toggle_row.append(InlineKeyboardButton(text="📅 Today", callback_data="rptlist_p0_today"))
            toggle_row.append(InlineKeyboardButton(text="📅 Yesterday", callback_data="rptlist_p0_yesterday"))
        buttons.append(toggle_row)

        pag_row = []
        if offset > 0:
            prev_offset = max(0, offset - page_size)
            pag_row.append(
                InlineKeyboardButton(text="⬅ Prev 10", callback_data=f"rptlist_p{prev_offset}_{filter_mode}")
            )
        if offset + page_size < total:
            next_offset = offset + page_size
            pag_row.append(
                InlineKeyboardButton(text="Next 10 ➡", callback_data=f"rptlist_p{next_offset}_{filter_mode}")
            )
        if pag_row:
            buttons.append(pag_row)

        buttons.append(
            [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
        )

        await callback.message.edit_text(
            header + "\nTap a report to choose format (Digital / PDF):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith("rptlist_p"))
async def handle_reports_paginated(callback: CallbackQuery):
    """Parse rptlist_p{offset}_{filter} callback."""
    try:
        tail = callback.data.replace("rptlist_p", "")
        if "_" in tail:
            parts = tail.split("_", 1)
            offset = int(parts[0])
            filter_mode = parts[1]
        else:
            offset = int(tail)
            filter_mode = "today"
    except (ValueError, IndexError):
        offset = 0
        filter_mode = "today"

    await cb_reports_paginated(callback, offset=offset, filter_mode=filter_mode)
    await callback.answer()


# ===========================================================================
# REPORT OPTIONS — Digital / PDF choice
# ===========================================================================

@router.callback_query(F.data.startswith("reportopt_"))
async def cb_report_options(callback: CallbackQuery):
    """Show Digital / PDF choice for a report."""
    try:
        report_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid report ID")
        return

    await callback.message.edit_text(
        "*Select report format:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Digital (text)", callback_data=f"digital_{report_id}")],
                [InlineKeyboardButton(text="📄 PDF", callback_data=f"genpdf_{report_id}")],
                [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("digital_"))
async def cb_digital_report(callback: CallbackQuery):
    """Send the report as text in the same format as the submission message."""
    try:
        report_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid report ID")
        return

    await callback.answer("Loading report...")

    db = SessionLocal()
    try:
        report = db.query(models.ProductionReport).filter(
            models.ProductionReport.id == report_id
        ).first()

        if not report:
            await callback.message.answer("Report not found in database.")
            return

        po = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.po_number == report.po_number
        ).first()

        text = build_digital_report_text(report, po)

        await callback.message.answer(text, parse_mode=None)
        await callback.message.answer(
            "Select action:",
            reply_markup=build_main_keyboard({}, {}),
        )
    finally:
        db.close()
    await callback.answer()


# ===========================================================================
# PDF GENERATION
# ===========================================================================

@router.callback_query(F.data.startswith("genpdf_"))
async def cb_generate_pdf(callback: CallbackQuery, bot: Bot):
    """Generate PDF for a specific report and send it to the user."""
    try:
        report_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid report ID")
        return

    await callback.answer("Generating PDF...")

    db = SessionLocal()
    try:
        report = db.query(models.ProductionReport).filter(
            models.ProductionReport.id == report_id
        ).first()

        if not report:
            await callback.message.answer("Report not found in database.")
            return

        report_data = {
            "report_date": report.report_date or "",
            "shift_name": report.shift_name or "",
            "machine_name": report.machine_name or "",
            "operator_name": report.operator_name or "",
            "po_number": report.po_number or "",
            "lot_number": report.lot_number or "",
            "shift_time_range": report.shift_time_range or "",
            "box_type": report.box_type or 0,
            "diameter": report.diameter or 0,
            "length": report.length or 0,
            "pd": report.pd or 0,
            "cu": getattr(report, 'cu', 0) or 0,
            "weight": report.weight or 0,
            "boxes_produced": report.boxes_produced or 0,
            "produced_rods": report.produced_rods or 0,
            "machine_counter": report.machine_counter or 0,
            "difference": report.difference or 0,
            "diff_percent": report.diff_percent or "0%",
            "waste_kg": report.waste_kg or 0,
            "machine_efficiency": report.machine_efficiency or 0,
            "total_acetate": report.total_acetate or 0,
            "total_paper": report.total_paper or 0,
            "total_pva": report.total_pva or 0,
            "total_hm": report.total_hm or 0,
            "total_triacetin": report.total_triacetin or 0,
            "remarks": report.remarks or "",
        }

        try:
            if report.materials_json:
                parsed = json.loads(report.materials_json)
                report_data["acetate_list"] = parsed.get("acetate_list", [])
                report_data["paper_list"] = parsed.get("paper_list", [])
                report_data["pva_list"] = parsed.get("pva_list", [])
                report_data["hm_list"] = parsed.get("hm_list", [])
                report_data["tri_list"] = parsed.get("tri_list", [])
            else:
                report_data["acetate_list"] = []
                report_data["paper_list"] = []
                report_data["pva_list"] = []
                report_data["hm_list"] = []
                report_data["tri_list"] = []
        except Exception:
            report_data["acetate_list"] = []
            report_data["paper_list"] = []
            report_data["pva_list"] = []
            report_data["hm_list"] = []
            report_data["tri_list"] = []

        await generate_and_send_pdf(report_data, callback.message.chat.id, bot)

        await callback.message.answer(
            "PDF sent. Select action:",
            reply_markup=build_main_keyboard({}, {}),
        )

    except Exception as e:
        await callback.message.answer(f"Error generating PDF: {str(e)}")
    finally:
        db.close()


# ===========================================================================
# /ai COMMAND — AI-powered production data analysis
# ===========================================================================

@router.message(Command("ai"))
async def cmd_ai(message: Message, **kwargs):
    """Answer a natural-language question about production data using AI.
    Allowed if tg_role='admin' OR can_use_ai=True OR is superadmin."""
    db_user = kwargs.get("db_user") or {}

    if not _can_use_ai(db_user, kwargs):
        await message.answer("⛔ AI analysis is not available for your account.\n"
                             "Contact an administrator to enable AI access.")
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(_AI_HELP, parse_mode="Markdown")
        return

    question = parts[1].strip()

    await message.answer("🔍 Analysing production data, please wait…")

    db = SessionLocal()
    try:
        db_context = ai_svc.build_db_context(db, days=30)
        answer = await ai_svc.query_ai(question=question, db_context=db_context)

        log = models.AIAnalysisLog(
            username=db_user.get("username", f"tg:{message.from_user.id}"),
            question=question,
            answer=answer,
            source="telegram",
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        answer = f"❌ Error: {exc}"
    finally:
        db.close()

    for i in range(0, len(answer), 4000):
        await message.answer(answer[i:i + 4000])


@router.message(Command("analyze"))
async def cmd_analyze(message: Message, **kwargs):
    """Alias for /ai."""
    await cmd_ai(message, **kwargs)