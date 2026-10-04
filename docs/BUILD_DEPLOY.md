# Build & Deploy

## Prerequisites

- Flutter SDK (3.47.x) + Dart
- JDK 17
- Android SDK (platforms;android-36, build-tools;36.0.0, NDK 28.2.13676358, platform-tools)

## Signing the Android APK

Release APKs are signed using the keystore referenced by
`production_app/android/key.properties`:

```
storePassword=android
keyPassword=android
keyAlias=androiddebugkey
storeFile=C:/src/keys/user_debug.keystore
```

- `key.properties` and `*.jks`/`*.keystore` are **gitignored** (never commit them).
- The keystore must stay the same across every release, otherwise Android will
  refuse to update ("App not installed") because the signature changed.
- If you build on a different machine, copy the same keystore there and point
  `key.properties` at it.

## Build Android APK

```powershell
$env:JAVA_HOME='C:\src\tools\jdk17\jdk-17.0.20.1+1'
$env:ANDROID_HOME='C:\src\android-sdk'
$env:ANDROID_SDK_ROOT='C:\src\android-sdk'
$env:PATH = "$env:JAVA_HOME\bin;C:\Program Files\Git\cmd;C:\src\flutter\bin;" + $env:PATH
cd production_app
flutter build apk --release
```

Output: `production_app/build/app/outputs/apk/release/prod_log_v<version>_b<build>.apk`

Copy it to `production_api/apk_releases/` so the app's auto-update
(`GET /api/app/latest-version` + `GET /api/app/download`) serves it.

## Build Web

```powershell
cd production_app
flutter build web --release
# deploy into the folder FastAPI serves:
#   production_api/web/
```

`production_api/web/` is generated and gitignored.

## Restart the backend (this deployment runs under WSL)

```powershell
wsl -d Ubuntu -u administrator bash -lic "cd /mnt/c/src/production_log/production_api && uvicorn main:app --host 0.0.0.0 --port 8000"
```

## Git workflow

- `main` = production
- `development` = development

```bash
git checkout development
# ... make changes ...
git add -A
git commit -m "describe change"
git push origin development

# when ready to deploy:
git checkout main
git merge development
git push origin main
```
