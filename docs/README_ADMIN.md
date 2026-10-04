# Production Log Admin Panel (SQLAdmin)

## 🎉 What's New

Your Production Log system now includes a **professional web-based admin panel** powered by SQLAdmin!

## 🚀 Quick Access

**Admin Panel URL**: `http://localhost:8000/admin`

## 📖 Documentation

### For Quick Start (5 minutes)
👉 **Read**: `SQLADMIN_QUICKSTART.md`

### For Complete Setup
👉 **Read**: `ADMIN_SETUP.md`

### For Technical Details
👉 **Read**: `SQLADMIN_IMPLEMENTATION_SUMMARY.md`

## ✨ Features

- 8 management modules (Users, Roles, Materials, Machines, Shifts, POs, Reports, Telegrams)
- Search and filter capabilities
- Professional responsive web UI
- User/role-based access control
- Session-based authentication

## 🔐 Authentication

Login with a user account that has:
- `can_manage_users` permission enabled, OR
- Role name "admin"

## ⚙️ Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Update .env
```env
SECRET_KEY=your-secure-random-key-here
```

### 3. Create Admin User
```bash
curl -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d {
    "username": "admin",
    "password": "securepassword",
    "email": "admin@factory.com",
    "role_id": 1
  }
```

### 4. Start Server
```bash
python -m uvicorn production_api.main:app --reload
```

### 5. Access Admin
Navigate to: `http://localhost:8000/admin`

## 📁 Files Changed

### New Files
- `production_api/admin.py` - Admin configuration
- `ADMIN_SETUP.md` - Setup guide
- `SQLADMIN_QUICKSTART.md` - Quick start
- `SQLADMIN_IMPLEMENTATION_SUMMARY.md` - Technical details
- `test_admin_import.py` - Verification script

### Updated Files
- `requirements.txt` - Added sqladmin, wtforms
- `production_api/main.py` - Added admin setup
- `.env.example` - Added SECRET_KEY

## 🆘 Quick Troubleshooting

**Login fails?**
- Verify user has a role with can_manage_users=True
- Check password is correct

**Admin panel won't load?**
- Check sqladmin installed: `pip show sqladmin`
- Verify SECRET_KEY in .env
- Clear browser cookies

**Can't find admin module?**
- Run: `pip install -r requirements.txt`

## 📚 Documentation Files

1. `SQLADMIN_QUICKSTART.md` - 5-minute setup
2. `ADMIN_SETUP.md` - Complete guide
3. `SQLADMIN_IMPLEMENTATION_SUMMARY.md` - Technical details

## ✅ Checklist

- [ ] Dependencies installed
- [ ] SECRET_KEY in .env
- [ ] Admin user created
- [ ] Server running
- [ ] Admin accessible at /admin
- [ ] Ready to manage data!

---

**Status**: ✅ Ready to Use  
**Last Updated**: June 27, 2026
