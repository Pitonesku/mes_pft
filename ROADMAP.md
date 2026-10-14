# Roadmap & Technical Debt

Future improvements and refactoring backlog for mes_pft.

## Future Technical Improvements / Refactoring

### Refactor `po_number` to `mo_number` across Data Layer & APIs
- **Status:** Backlog (Low / Non-blocking)
- **Context:** The UI and reports have been aligned to "Manufacturing Order" (MO),
  but the internal database columns, Pydantic schemas, and local SQLite models still
  rely on the legacy `po_number` keys for backward compatibility.
- **Action Plan:**
  1. **API Backward Compatibility:** Add Pydantic field aliases
     (`validation_alias='mo_number' | 'po_number'`) to accept both keys during
     ingestion and webhook handling.
  2. **DB Migration:** Alembic migration (`ALTER TABLE ... RENAME COLUMN po_number
     TO mo_number`) with backward-compatible views/aliases if needed.
  3. **Local Tablet SQLite:** Automated schema migration for tablet SQLite offline
     databases on startup.
  4. **Codebase Cleanup:** Replace legacy `po_number` identifiers with `mo_number`
     throughout backend models, services, and frontend Dart models.
- **Priority:** Low / Non-blocking technical debt. Keep current schema intact until a
  scheduled major version bump.

<!-- Template for future entries:
### <Title>
- **Status:** Backlog (Low / Non-blocking)
- **Context:** ...
- **Action Plan:** 1. ... 2. ... 3. ...
- **Priority:** ...
-->
