# frontend — mes_pft Flutter app

Operator tablet app + web console for the cigarette-filter MES. Single Flutter
codebase; the web build is served by the FastAPI backend at `/`.

## Structure

- `lib/main.dart`, `lib/models.dart`, `lib/api_service.dart` — app entry, shared
  models, HTTP client (bearer-token auth).
- `lib/core/` — hash navigation, app navigation, open_new_tab (web/stub
  conditional exports; see `.clinerules` invariant 6).
- `lib/dashboard/` — 24-column dashboard grid engine for the web console.
- `lib/screens/mobile/` — tablet (operator/admin) screens.
- `lib/screens/web/` — web console screens.
- `lib/features/pdf_export/` — platform-conditional PDF export.
- `lib/widgets/`, `lib/theme/`, `lib/utils/` — shared UI, theming, logging.

## Build

```bash
cd frontend
flutter pub get
flutter build web --release      # web console (served by the backend)
flutter build apk --release      # tablet APK (prod_log_v<version>_b<build>.apk)
```

## Run / analyze

```bash
flutter analyze
flutter test
```

The app talks to the MES backend: development server on `http://127.0.0.1:8001`
(production: 8000). See the root `README.md`, `docs/api.md` and
`docs/AUTHENTICATION.md`.
