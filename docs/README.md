# Production Log

Production tracking system for factory operators and managers. Operators submit
shift production reports from a Flutter mobile app; the FastAPI backend stores
them in PostgreSQL, notifies managers via Telegram, generates PDFs, and uploads
them to Google Drive.

## Repository layout (monorepo)

```
production_log/
├── production_api/          # FastAPI backend (source of truth)
│   ├── main.py              # API routes + background workers + lifespan
│   ├── auth.py              # Bearer-token authentication
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas
│   ├── bot_handlers.py      # Telegram bot (aiogram)
│   ├── bot_middleware.py    # Telegram DB auth middleware
│   ├── ai_routes.py         # AI analysis endpoints
│   ├── ai_service.py        # AI provider integration
│   ├── pdf_generator.py     # PDF generation + Google Drive upload
│   ├── database.py          # DB engine / sessions
│   ├── admin.py             # SQLAdmin admin panel
│   ├── migrate_db.py        # Startup schema migrations
│   ├── seed.py              # First-startup admin seeding
│   └── web/                 # Compiled Flutter web build (GENERATED, gitignored)
├── production_app/          # Flutter app source (Android / iOS / web / desktop)
├── .env.example             # Environment template
├── AUTHENTICATION.md        # Auth documentation
├── SECURITY_NOTES.md        # Security actions
├── BUILD_DEPLOY.md          # Build & deploy guide
└── CHANGELOG.md
```

## Branches

- `main` → **production** (deployed on the server)
- `development` → **development** (new work)

Workflow: `development` → (merge) → `main`.

## Backend

```bash
cd production_api
python -m venv .venv
# activate the venv
pip install -r requirements.txt
cp ../.env.example .env   # then fill in real values

python -m uvicorn production_api.main:app --host 0.0.0.0 --port 8000
# or, in this deployment, the WSL start script:
#   wsl -d Ubuntu -u administrator bash -lic "cd /mnt/c/src/production_log/production_api && uvicorn main:app --host 0.0.0.0 --port 8000"
```

On startup the backend creates missing tables, runs schema migrations, seeds the
initial admin/Telegram admin, starts the Telegram bot, and starts the delivery
workers.

Admin panel (SQLAdmin): `http://localhost:8000/admin`.

## Frontend (Flutter)

```bash
cd production_app
flutter pub get
flutter run
flutter build apk     # Android release
flutter build web     # web release (deploy to production_api/web/)
```

See [`BUILD_DEPLOY.md`](BUILD_DEPLOY.md) for the full build + deploy + signing
workflow.

## Authentication

API authentication uses signed bearer tokens. See
[`AUTHENTICATION.md`](AUTHENTICATION.md).

## Offline sync & duplicate prevention

Each report submission carries a client-generated `client_report_id` (UUID). The
server stores it with a partial unique index, and both `POST /api/reports` and
`POST /api/reports/sync` return the existing report instead of inserting a
duplicate when the id is already present. This makes retries (timeouts, the
60-second background sync) safe.

## Security

See [`SECURITY_NOTES.md`](SECURITY_NOTES.md) for credential-rotation steps and
the list of files that must never be committed.
