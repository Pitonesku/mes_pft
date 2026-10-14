@echo off
rem Detached MES backend launcher (run via Task Scheduler so it survives shell sessions).
cd /d C:\Users\Maximusm\Documents\Python\mes_pft\backend
"C:\Users\Maximusm\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > uvicorn.out.log 2> uvicorn.err.log
