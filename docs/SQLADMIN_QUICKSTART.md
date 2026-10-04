# SQLAdmin Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

Newly added:
- `sqladmin==0.18.3` - Web admin panel
- `wtforms==3.1.1` - Form handling

### Step 2: Configure Environment
Add to your `.env` file (or copy from `.env.example`):
```env
SECRET_KEY=your-secure-random-key-here
```

Generate a secure key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 3: Create an Admin User
Use the existing API endpoint to create a user with admin role:

```bash
# First, create or get an admin role
curl -X POST http://localhost:8000/api/roles \
  -H "Content-Type: application/json" \
  -d {
    "role_name": "admin",
    "can_manage_users": true,
    "can_create_po": true,
    "can_edit_po": true,
    "can_edit_report": true,
    "can_setup_machines": true,
    "can_view_all_reports": true
  }

# Then create an admin user
curl -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d {
    "username": "admin",
    "email": "admin@factory.com",
    "password": "admin123",
    "role_id": 1
  }
```

### Step 4: Start the Server
```bash
python -m uvicorn production_api.main:app --reload
```

### Step 5: Access Admin Panel
Open your browser and navigate to:
```
http://localhost:8000/admin
```

**Login with:**
- Username: `admin`
- Password: `admin123`

## ✨ What You Can Now Do

### User Management
- Create/edit/delete users
- Assign roles and permissions
- Deactivate users

### System Configuration
- Manage production machines
- Define production shifts
- Configure material types and batches
- Set up purchase orders

### Data Management
- View production reports
- Monitor telegram notifications
- Track production metrics
- Manage PO fulfillment

## 🔐 Important Security Notes

⚠️ **For Development Only:**
- Passwords are stored in plaintext
- SECRET_KEY is a fallback value
- No HTTPS enforcement

✅ **For Production:**
1. Implement bcrypt password hashing
2. Set a strong SECRET_KEY
3. Use HTTPS only
4. Configure session timeout
5. Enable database audit logs
6. Restrict admin access by IP

## 📚 Full Documentation

See `ADMIN_SETUP.md` for comprehensive documentation including:
- Detailed feature descriptions
- Advanced configuration
- Security hardening
- Troubleshooting guide

## 🆘 Troubleshooting

### "Login failed"
- Verify user exists: `SELECT * FROM users WHERE username='admin'`
- Check user is active: `is_inactive = FALSE`
- Verify user has a role with can_manage_users permission

### "Module not found: sqladmin"
```bash
pip install sqladmin==0.18.3 wtforms==3.1.1
```

### Admin panel blank/white screen
- Check browser console for errors (F12)
- Clear cookies: `localStorage.clear()`
- Hard refresh: Ctrl+Shift+R (Cmd+Shift+R on Mac)

## 🔗 File Structure

```
production_log_dev/
├── production_api/
│   ├── admin.py              # NEW: Admin configuration
│   ├── main.py               # UPDATED: Added admin setup
│   ├── models.py             # SQLAlchemy models
│   └── ...
├── ADMIN_SETUP.md            # NEW: Full documentation
├── SQLADMIN_QUICKSTART.md    # NEW: This file
├── .env.example              # UPDATED: Added SECRET_KEY
└── requirements.txt          # UPDATED: Added sqladmin, wtforms
```

## ⚡ Next Steps

1. ✅ Install dependencies
2. ✅ Set SECRET_KEY in .env
3. ✅ Create admin role and user
4. ✅ Start server
5. ✅ Login to admin panel
6. ✅ Start managing your system!

Enjoy the new admin panel! 🎉
