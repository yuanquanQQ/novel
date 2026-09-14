@echo off
REM 一键启动开发环境：后端(11452) + 前端(114514)
cd /d %~dp0\..
echo Starting backend (FastAPI :11452) ...
start "novel-backend" cmd /c "python -X utf8 -m uvicorn server.app:app --port 11452 --reload"
echo Starting frontend (Vite :114514) ...
cd web
start "novel-frontend" cmd /c "npm run dev"
echo.
echo Backend:  http://127.0.0.1:11452  (API)
echo Frontend: http://localhost:114514  (console)
echo.
echo Close this window's spawned windows to stop.
