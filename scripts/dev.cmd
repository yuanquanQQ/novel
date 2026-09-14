@echo off
REM 一键启动开发环境：后端(11452) + 前端(11451)
cd /d %~dp0\..
echo Starting backend (FastAPI :11452) ...
start "novel-backend" cmd /c "python -X utf8 -m uvicorn server.app:app --port 11452 --reload"
echo Starting frontend (Vite :11451) ...
cd web
start "novel-frontend" cmd /c "npm run dev"
echo.
echo Backend:  http://127.0.0.1:11452  (API)
echo Frontend: http://localhost:11451  (console)
echo.
echo Close this window's spawned windows to stop.
