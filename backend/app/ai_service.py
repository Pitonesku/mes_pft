"""
AI Analysis Service

Supports two API formats, auto-detected from AI_API_BASE_URL:

  1. Anthropic  — https://api.anthropic.com
     Uses /v1/messages with x-api-key header and anthropic-version header.
     Default model: claude-3-5-haiku-20241022

  2. OpenAI-compatible — anything else (OpenAI, Groq, Azure OpenAI, Ollama, etc.)
     Uses /chat/completions with Authorization: Bearer header.
     Default model: gpt-4o-mini

Configuration via .env:
  AI_ENABLED        = true | false
  AI_API_KEY        = your key
  AI_API_BASE_URL   = https://api.anthropic.com          ← Anthropic
                      https://api.openai.com/v1          ← OpenAI
                      https://api.groq.com/openai/v1     ← Groq
                      http://localhost:11434/v1           ← Ollama
  AI_MODEL          = claude-3-5-haiku-20241022  (or any model your provider supports)
"""
import os
import importlib
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func

if __package__:
    models = importlib.import_module(f"{__package__}.models")
else:
    import models

# In-memory model override (set via POST /api/ai/model, cleared on restart)
_model_override: str | None = None

def set_model_override(model_name: str | None) -> None:
    """Set an in-memory model override that supersedes the AI_MODEL env var."""
    global _model_override
    _model_override = model_name

def get_model_override() -> str | None:
    return _model_override

def _is_anthropic() -> bool:
    return "anthropic.com" in os.getenv("AI_API_BASE_URL", "").lower()

def _effective_model() -> str:
    if _model_override:
        return _model_override
    model = os.getenv("AI_MODEL", "")
    if model:
        return model
    return "claude-3-5-haiku-20241022" if _is_anthropic() else "gpt-4o-mini"

_DB_SCHEMA = """## Database Schema (PostgreSQL)

### production_reports
- id (INTEGER PK), report_date (TEXT), shift_name (TEXT), machine_name (TEXT),
  operator_name (TEXT), po_number (TEXT), boxes_produced (INTEGER),
  produced_rods (INTEGER), waste_kg (FLOAT), machine_efficiency (FLOAT),
  machine_counter (INTEGER), difference (FLOAT), diff_percent (TEXT),
  status (TEXT: original/edited/obsolete), is_archived (BOOLEAN),
  sync_at (TIMESTAMP)

### purchase_orders
- id (INTEGER PK), po_number (TEXT UNIQUE), diameter (NUMERIC),
  length (NUMERIC), pd (NUMERIC), cu (INTEGER), weight (NUMERIC),
  box_type (INTEGER), target_qty (INTEGER), produced_qty (INTEGER),
  is_archived (BOOLEAN), is_hidden (BOOLEAN), created_at (TIMESTAMP)

### machines
- id (INTEGER PK), name (TEXT), is_inactive (BOOLEAN), remarks (TEXT)

### shifts
- id (INTEGER PK), name (TEXT), start_time (TEXT), end_time (TEXT)

### users
- id (INTEGER PK), username (TEXT), role_id (INTEGER FK→roles.id),
  is_inactive (BOOLEAN), created_at (TIMESTAMP)

### material_dictionary
- id (INTEGER PK), category (TEXT), type_name (TEXT),
  is_hidden (BOOLEAN), created_at (TIMESTAMP)

### ai_analysis_log
- id (INTEGER PK), username (TEXT), question (TEXT), answer (TEXT),
  source (TEXT: web/mobile/telegram), created_at (TIMESTAMP)
"""

_SYSTEM_PROMPT = f"""You are an expert production analyst for a cigarette filter manufacturing plant.
You have direct access to the production database via a read-only SQL tool.

{_DB_SCHEMA}

TOOL: execute_readonly_sql(sql_query: str) -> list of rows as JSON
- You MUST use this tool to answer data questions. NEVER guess numbers.
- Write standard PostgreSQL SELECT queries. You can use GROUP BY, ORDER BY, aggregates (SUM, AVG, COUNT, MIN, MAX), WHERE, HAVING, JOIN, LIMIT, subqueries.
- Always include LIMIT 50 unless the user asks for more.
- The tool returns rows as an array of JSON objects.

RULES:
- When comparing machines or shifts, highlight the best and worst performers.
- If a question cannot be answered from the available tables, say so clearly.
- Use bullet points for lists, format numbers with commas (e.g., 1,234,567).
- Keep answers under 400 words unless a longer breakdown is explicitly requested.
- When presenting tabular data, use Markdown tables.
"""

# ---------------------------------------------------------------------------
# Text-to-SQL guardrail — block any non-SELECT queries
# ---------------------------------------------------------------------------
import re

_FORBIDDEN_SQL = [
    r'\bDROP\b', r'\bDELETE\b', r'\bUPDATE\b', r'\bINSERT\b',
    r'\bALTER\b', r'\bGRANT\b', r'\bTRUNCATE\b', r'\bCREATE\b',
    r'\bEXEC\b', r'\bEXECUTE\b', r';\s*--', r'\bCOPY\b', r'\bVACUUM\b',
    r'\bREVOKE\b', r'\bSET\b', r'\bSHOW\b',
]
_FORBIDDEN_RE = re.compile('|'.join(_FORBIDDEN_SQL), re.IGNORECASE)
_SELECT_RE = re.compile(r'^\s*SELECT\b', re.IGNORECASE)

def _is_safe_sql(sql: str) -> bool:
    """Return True if the SQL looks like a safe read-only SELECT query."""
    if not _SELECT_RE.match(sql.strip()):
        return False
    if _FORBIDDEN_RE.search(sql):
        return False
    return True


def _execute_readonly_sql(sql: str) -> list[dict]:
    """Execute a read-only SQL query through the AI-only database session.
    Raises ValueError if the SQL is not safe or SessionAI is not configured."""
    from sqlalchemy import text

    if not _is_safe_sql(sql):
        raise ValueError(f"SQL query blocked by safety guardrail: {sql[:120]}")

    # Lazy-import to avoid circular dependency at module level
    if __package__:
        database_mod = importlib.import_module(f"{__package__}.database")
    else:
        import database as database_mod

    if database_mod.SessionAI is None:
        raise ValueError(
            "Text-to-SQL is disabled — AI read-only DB credentials are not configured. "
            "Set AI_DB_USER and AI_DB_PASSWORD in .env."
        )

    session = database_mod.SessionAI()
    try:
        result = session.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in rows]
    finally:
        session.close()


def build_db_context(db: Session, days: int = 30) -> str:
    """
    Query the DB for aggregated production stats and return them as a
    structured text block that will be injected into the AI prompt.

    Only aggregated/anonymized numeric data is sent — no raw report rows.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    parts: list[str] = [f"# Production DB Context (last {days} days, since {since})\n"]

    base_filter = [
        models.ProductionReport.report_date >= since,
        models.ProductionReport.is_archived == False,
        models.ProductionReport.status != "obsolete",
    ]

    try:
        # --- Overall summary ---
        row = db.query(
            func.count(models.ProductionReport.id).label("reports"),
            func.sum(models.ProductionReport.boxes_produced).label("boxes"),
            func.sum(models.ProductionReport.produced_rods).label("rods"),
            func.sum(models.ProductionReport.waste_kg).label("waste"),
            func.avg(models.ProductionReport.machine_efficiency).label("avg_eff"),
        ).filter(*base_filter).first()

        if row and row.reports:
            parts.append(
                f"## Overall Summary\n"
                f"- Reports: {row.reports}\n"
                f"- Total boxes produced: {int(row.boxes or 0):,}\n"
                f"- Total rods produced: {int(row.rods or 0):,}\n"
                f"- Total waste: {float(row.waste or 0):.2f} kg\n"
                f"- Avg machine efficiency: {float(row.avg_eff or 0):.1f}%\n"
            )

        # --- By machine ---
        by_machine = (
            db.query(
                models.ProductionReport.machine_name,
                func.count(models.ProductionReport.id).label("reports"),
                func.sum(models.ProductionReport.boxes_produced).label("boxes"),
                func.sum(models.ProductionReport.waste_kg).label("waste"),
                func.avg(models.ProductionReport.machine_efficiency).label("eff"),
            )
            .filter(*base_filter)
            .group_by(models.ProductionReport.machine_name)
            .order_by(func.sum(models.ProductionReport.boxes_produced).desc())
            .all()
        )
        if by_machine:
            parts.append("## Production by Machine")
            for r in by_machine:
                parts.append(
                    f"- {r.machine_name}: {int(r.boxes or 0):,} boxes, "
                    f"{float(r.waste or 0):.1f} kg waste, "
                    f"{float(r.eff or 0):.1f}% efficiency, "
                    f"{r.reports} shifts"
                )

        # --- By shift ---
        by_shift = (
            db.query(
                models.ProductionReport.shift_name,
                func.count(models.ProductionReport.id).label("reports"),
                func.sum(models.ProductionReport.boxes_produced).label("boxes"),
                func.avg(models.ProductionReport.machine_efficiency).label("eff"),
            )
            .filter(*base_filter)
            .group_by(models.ProductionReport.shift_name)
            .order_by(func.sum(models.ProductionReport.boxes_produced).desc())
            .all()
        )
        if by_shift:
            parts.append("\n## Production by Shift")
            for r in by_shift:
                parts.append(
                    f"- {r.shift_name}: {int(r.boxes or 0):,} boxes, "
                    f"{float(r.eff or 0):.1f}% avg efficiency, {r.reports} reports"
                )

        # --- Top 5 operators ---
        top_ops = (
            db.query(
                models.ProductionReport.operator_name,
                func.sum(models.ProductionReport.boxes_produced).label("boxes"),
                func.count(models.ProductionReport.id).label("shifts"),
            )
            .filter(*base_filter)
            .group_by(models.ProductionReport.operator_name)
            .order_by(func.sum(models.ProductionReport.boxes_produced).desc())
            .limit(5)
            .all()
        )
        if top_ops:
            parts.append("\n## Top 5 Operators (by output)")
            for r in top_ops:
                parts.append(
                    f"- {r.operator_name}: {int(r.boxes or 0):,} boxes in {r.shifts} shifts"
                )

        # --- Active Purchase Orders ---
        active_pos = (
            db.query(models.PurchaseOrder)
            .filter(
                models.PurchaseOrder.is_archived == False,
                models.PurchaseOrder.is_hidden == False,
            )
            .limit(15)
            .all()
        )
        if active_pos:
            parts.append("\n## Active Purchase Orders")
            for po in active_pos:
                pct = (po.produced_qty / po.target_qty * 100) if po.target_qty else 0
                parts.append(
                    f"- {po.po_number}: {int(po.produced_qty or 0):,}/{int(po.target_qty or 0):,} "
                    f"({pct:.1f}%) | Ø{po.diameter}×{po.length}mm"
                )

    except Exception as exc:
        parts.append(f"\n[Warning: partial data available — {exc}]")

    return "\n".join(parts)


async def query_ai(
    question: str,
    db_context: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Call the configured AI API with the production context and return the answer.

    Auto-detects Anthropic vs OpenAI-compatible based on AI_API_BASE_URL.
    conversation_history: list of {"role": "user"|"assistant", "content": "..."} dicts
                          for multi-turn sessions (last N pairs only).

    Raises ValueError on API errors so callers can return HTTP 502.
    """
    if not os.getenv("AI_ENABLED", "true").lower() == "true":
        return "AI analysis is disabled. Set AI_ENABLED=true in the server configuration."

    if not os.getenv("AI_API_KEY", ""):
        return (
            "AI API key is not configured. "
            "Please set AI_API_KEY in the server .env file."
        )

    user_content = (
        f"Current production database context:\n{db_context}\n\n"
        f"---\n\nQuestion: {question}"
    )

    # Build conversation turns (last 3 Q&A pairs max)
    history = list(conversation_history[-6:]) if conversation_history else []

    if _is_anthropic():
        return await _query_anthropic(user_content, history)
    else:
        return await _query_openai_compatible(user_content, history)


async def _query_anthropic(user_content: str, history: list[dict]) -> str:
    """Call Anthropic /v1/messages API."""
    messages = history + [{"role": "user", "content": user_content}]

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.getenv("AI_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": _effective_model(),
                "system": _SYSTEM_PROMPT,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.3,
            },
        )

    if response.status_code != 200:
        error_detail = response.text[:500]
        # Log the full error to the server console for debugging
        print(f"[AI Service] Anthropic API error ({response.status_code}): {error_detail}")
        raise ValueError(
            f"Anthropic API error {response.status_code}: {error_detail}"
        )

    data = response.json()
    return data["content"][0]["text"]


async def _query_openai_compatible(user_content: str, history: list[dict]) -> str:
    """Call any OpenAI-compatible /chat/completions API."""
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{os.getenv('AI_API_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('AI_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            json={
                "model": _effective_model(),
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.3,
            },
        )

    if response.status_code != 200:
        error_detail = response.text[:500]
        print(f"[AI Service] OpenAI-compatible API error ({response.status_code}): {error_detail}")
        raise ValueError(
            f"AI API error {response.status_code}: {error_detail}"
        )

    data = response.json()
    return data["choices"][0]["message"]["content"]


async def validate_api_key() -> dict:
    """
    Test whether the configured AI_API_KEY is valid by sending a minimal request.
    Returns a dict with keys:
      - valid: bool
      - error: str (if invalid)
      - provider: 'anthropic' | 'openai'
      - model: currently configured model name
    """
    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        return {"valid": False, "error": "AI_API_KEY is not set", "provider": "unknown", "model": _effective_model()}

    if _is_anthropic():
        return await _validate_anthropic_key()
    else:
        return await _validate_openai_key()


async def _validate_anthropic_key() -> dict:
    """Ping the Anthropic API with a minimal request to check key validity."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Use a very lightweight request with max_tokens=1 to minimize cost
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.getenv("AI_API_KEY", ""),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _effective_model(),
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
        if response.status_code == 200:
            return {"valid": True, "provider": "anthropic", "model": _effective_model()}
        else:
            return {"valid": False, "error": f"API error {response.status_code}: {response.text[:300]}", "provider": "anthropic", "model": _effective_model()}
    except Exception as e:
        return {"valid": False, "error": f"Connection error: {e}", "provider": "anthropic", "model": _effective_model()}


async def _validate_openai_key() -> dict:
    """Ping the OpenAI-compatible API to check key validity."""
    base_url = os.getenv("AI_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {os.getenv('AI_API_KEY', '')}",
                },
            )
        if response.status_code == 200:
            return {"valid": True, "provider": "openai", "model": _effective_model()}
        else:
            return {"valid": False, "error": f"API error {response.status_code}: {response.text[:300]}", "provider": "openai", "model": _effective_model()}
    except Exception as e:
        return {"valid": False, "error": f"Connection error: {e}", "provider": "openai", "model": _effective_model()}


async def fetch_available_models() -> dict:
    """
    Fetch the list of available models from the configured AI provider.
    Returns a dict with keys:
      - models: list of {"id": str, "display_name": str} (or just {"id": str} for OpenAI)
      - error: str (if failed)
      - provider: 'anthropic' | 'openai'
    """
    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        return {"models": [], "error": "AI_API_KEY is not set", "provider": "unknown"}

    if _is_anthropic():
        return await _fetch_anthropic_models()
    else:
        return await _fetch_openai_models()


async def _fetch_anthropic_models() -> dict:
    """Fetch available models from Anthropic's API."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": os.getenv("AI_API_KEY", ""),
                    "anthropic-version": "2023-06-01",
                },
            )
        if response.status_code == 200:
            data = response.json()
            models_list = [
                {"id": m["id"], "display_name": m.get("display_name", m["id"])}
                for m in data.get("data", [])
            ]
            # Sort: put claude models first
            models_list.sort(key=lambda m: (not m["id"].startswith("claude"), m["id"]))
            return {"models": models_list, "provider": "anthropic"}
        else:
            return {"models": [], "error": f"API error {response.status_code}: {response.text[:300]}", "provider": "anthropic"}
    except Exception as e:
        return {"models": [], "error": f"Connection error: {e}", "provider": "anthropic"}


async def _fetch_openai_models() -> dict:
    """Fetch available models from an OpenAI-compatible API."""
    base_url = os.getenv("AI_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {os.getenv('AI_API_KEY', '')}",
                },
            )
        if response.status_code == 200:
            data = response.json()
            models_list = [
                {"id": m["id"], "display_name": m.get("id", m["id"])}
                for m in data.get("data", [])
            ]
            # Sort alphabetically by id
            models_list.sort(key=lambda m: m["id"])
            return {"models": models_list, "provider": "openai"}
        else:
            return {"models": [], "error": f"API error {response.status_code}: {response.text[:300]}", "provider": "openai"}
    except Exception as e:
        return {"models": [], "error": f"Connection error: {e}", "provider": "openai"}


def query_ai_sync(
    question: str,
    db_context: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Synchronous wrapper around query_ai for use in non-async contexts
    (e.g., the Telegram bot thread).

    Creates a fresh event loop for the calling thread.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            query_ai(question, db_context, conversation_history)
        )
    finally:
        loop.close()
