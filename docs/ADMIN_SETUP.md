# SQLAdmin Setup Guide

## Overview
SQLAdmin has been integrated into the Production Log application, providing a professional web-based admin panel for managing all system data.

## 📍 Access the Admin Panel

**URL**: `http://localhost:8000/admin`

## 🌱 First-Startup Auto-Seed

On the **very first startup** with an empty database, the API automatically seeds:

| Item | Value | Source |
|---|---|---|
| Role | `admin` (all permissions enabled) | hardcoded |
| Username | `admin` | `ADMIN_USERNAME` env var |
| Password | `admin` | `ADMIN_PASSWORD` env var |
| Email | `admin@factory.local` | `ADMIN_EMAIL` env var |

> ⚠️ **Before going to production**: set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` in your `.env` file.
> A loud warning is printed at startup if default credentials are still in use.

The seed is **idempotent** — it is skipped automatically on every subsequent startup once any roles or users exist in the database.

---

## 🔐 Authentication

### Requirements
To access the admin panel, you need a user account with:
- **can_manage_users** permission enabled in their role, OR
- A role named "admin" (case-insensitive)

### Login Credentials
Use your existing Production Log user credentials:
- **Username**: Your registered username
- **Password**: Your account password

### Example Admin User Setup

```python
# You can create an admin user via the API or directly in the database

# Via API POST /api/users:
{
    "username": "admin",
    "email": "admin@example.com",
    "password": "your-secure-password",
    "role_id": 1  # Role with can_manage_users=True
}
```

## 🛠️ Features

### Available Models

The admin panel provides full CRUD (Create, Read, Update, Delete) access to:

1. **Roles** - Manage user roles and permissions
   - Create/edit/delete roles
   - Configure permissions (can_create_po, can_edit_po, etc.)
   - Filter by role name

2. **Users** - Manage system users
   - Create/edit/delete users
   - Assign roles
   - Deactivate users (is_inactive)
   - Search by username/email

3. **Materials** - Manage material dictionary
   - Add material types and batches
   - Set categories (acetate, paper, PVA, etc.)
   - Hide/show materials from app

4. **Machines** - Manage production machines
   - Create/edit machine list
   - Add remarks/notes
   - Mark machines as inactive

5. **Shifts** - Manage production shifts
   - Define shift schedules


## 🔍 Features by Model

### Search & Filter
- **Global Search**: Available on User, Material, Machine, Purchase Order, Production Report models
- **Column Filtering**: Filter by specific fields (e.g., role, status, date range)
- **Sorting**: Click column headers to sort ascending/descending

### Batch Operations
- Create multiple records
- Edit records inline or via detail forms
- Soft-delete capability (use `is_hidden` or `is_inactive` flags)

### Data Validation
- Required fields are enforced
- Foreign key relationships maintained (e.g., User → Role)
- Timestamps auto-populated

## 🚀 Usage Examples

### Create a New Role

1. Navigate to `http://localhost:8000/admin`
2. Login with admin credentials
3. Click **Roles** in sidebar
4. Click **+ Create** button
5. Fill in:
   - Role Name: `Supervisor`
   - Permissions: Check `can_view_all_reports`, `can_edit_report`
6. Click **Save**

### Create a New User

1. Go to **Users** section
2. Click **+ Create**
3. Fill in:
   - Username: `operator1`
   - Email: `operator1@factory.com`
   - Password: (plaintext for MVP)
   - Role: Select from dropdown
4. Click **Save**

### Filter Production Reports by Date

1. Go to **Production Reports**


## 🔒 Security Considerations

### Current Implementation
- ✅ Authentication via existing User/Role system
- ✅ Session-based auth with secure cookies
- ⚠️ Passwords stored as plaintext (MVP)
- ✅ Role-based access control

### For Production Deployment
1. Implement bcrypt password hashing
2. Use HTTPS only
3. Set strong SECRET_KEY value
4. Configure appropriate session timeout
5. Enable database audit trails

## 🐛 Troubleshooting

### Login Fails
- Verify user exists in database
- Check user is not inactive: `is_inactive = False`
- Verify user has a role: `role_id IS NOT NULL`
- Verify role has can_manage_users permission

### Can't See Admin Panel
- Make sure you're logged in
- Check browser console for errors
- Clear cookies and try again

### Foreign Key Errors
- When creating users, ensure selected role exists
- Verify all related data exists before creating references

## 📚 Related Files

- `production_api/admin.py` - Admin configuration
- `production_api/main.py` - FastAPI app setup
- `requirements.txt` - Added sqladmin and wtforms

## 🔄 How It Works

1. Admin accesses `/admin` URL
2. SQLAdmin middleware intercepts request
3. User presented with login form
4. Credentials checked against User table
5. Role permissions verified (can_manage_users required)
6. If authenticated, session created
7. Admin panel displays based on database models
8. All changes saved to same database as API

## ✨ Next Steps

1. Create an admin role with can_manage_users=True
2. Create an admin user with that role
3. Access admin panel at `/admin`
4. Start managing your system data!

## 📖 More Info

- SQLAdmin Docs: https://aminalaee.dev/sqladmin/
- FastAPI Docs: https://fastapi.tiangolo.com/

2. Click **Filters** in toolbar
3. Select **report_date**
4. Choose date range
5. Click **Apply**

   - Set start/end times
   - Search by name

6. **Purchase Orders (PO)** - Manage production orders
   - Create/edit POs with technical specifications
   - Track target vs. produced quantities
   - Monitor material composition
   - Filter by PO number

7. **Production Reports** - View production data
   - View all submitted production reports
   - Filter by date, shift, machine, status
   - Search by PO number or operator

8. **Telegram Queue** - Monitor notifications
   - View pending/sent/failed telegram messages
   - Track delivery attempts and errors
   - Monitor notification status

## ⚙️ Configuration

### Environment Variables

Add to your `.env` file:

```env
# Session secret for admin panel authentication
SECRET_KEY=your-very-secure-random-key-here

# Keep existing settings
DB_USER=postgres
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=production_log
```

**Security Note**: Change `SECRET_KEY` to a strong random value in production!
