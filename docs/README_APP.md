# Production Log App

## Overview
A mobile-first production tracking system designed for factory operators and managers to submit, track, and analyze production reports in real-time.

## Purpose
The Production Log app enables:
- **Operators** to quickly submit shift production reports with material usage, machine counters, and quality metrics
- **Managers** to review reports, manage purchase orders, configure materials and shifts
- **Admins** to manage users, audit production data, and generate statistics

## Key Features

### 📱 Core Functionality
- **Production Report Submission** — Operators fill out shift reports with PO number, lot, materials used, production counts
- **Offline-First Architecture** — Works without internet; automatically syncs when connection is restored
- **Real-Time Sync** — Data syncs across all tablets/devices on the same network
- **Cross-Device Copy** — "Use data from previous report" works across all tablets, not just the one that submitted it

### 📊 Data Management
- **Material Tracking** — Track acetate, paper, PVA glue, hot melt glue, triacetin usage per shift
- **Purchase Order (PO) Management** — Create, edit, track PO fulfillment and remaining quantities
- **Production History** — View all submitted reports with date range filtering
- **Audit Reports** — Detailed PO-level statistics including material consumption, waste, machine efficiency

### 🔧 Admin Tools
- **User Management** — Create operators, managers, admins with role-based access
- **Material Dictionary** — Configure available material types and batches
- **Machine & Shift Setup** — Define production machines and shift schedules
- **Sync Manager** — Force data sync, view connection logs

### 📄 Reports & Notifications
- **PDF Generation** — Auto-generate professional PDF reports with all production details
- **Google Drive Upload** — Automatically upload PDFs to Google Drive (optional)
- **Telegram Notifications** — Receive shift report summaries via Telegram bot
- **Local Archive** — PDFs saved locally for offline access

### 🔄 Auto-Update System
- **Version Checking** — App checks for updates on startup
- **One-Click Install** — Download and install new APK directly from the app
- **Automatic Naming** — APK files auto-named with version and build number

## Current Version
**v1.0.0 (Build 1)**

## System Requirements
- **Android 5.0+** (API level 21+)
- **Internet connection** (for sync; app works offline)
- **Storage**: ~50 MB for app + local database

## Architecture

### Frontend (Flutter)
- **Language**: Dart
- **Database**: SQLite (local offline storage)
- **HTTP Client**: http package with custom logging
- **UI Framework**: Material Design 3

### Backend (FastAPI)
- **Language**: Python 3.11+
- **Database**: PostgreSQL (production) / SQLite (dev)
- **PDF Generation**: ReportLab
- **Cloud Storage**: Google Drive API
- **Notifications**: Telegram Bot API

## Recent Changes
See **CHANGELOG.md** for detailed version history and feature updates.

## Support & Contact
For issues, feature requests, or support:
- Check the **Info** screen in the app (ℹ️ button)
- Review **CHANGELOG.md** for recent fixes
- Contact your system administrator

---

**Last Updated**: June 19, 2026
