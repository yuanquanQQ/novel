@echo off
REM 一键启动开发环境：后端(8300) + 前端(5173)
cd /d %~dp0\..
echo Starting backend (FastAPI :8300) ...
start "novel-backend" cmd /c "python -X utf8 -m uvicorn server.app:app --port 8300 --reload"
echo Starting frontend (Vite :5173) ...
cd web
start "novel-frontend" cmd /c "npm run dev"
echo.
echo Backend:  http://127.0.0.1:8300  (API)
echo Frontend: http://localhost:5173  (console)
echo.
echo Close this window's spawned windows to stop.
