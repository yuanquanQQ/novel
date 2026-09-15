@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [错误] 未找到虚拟环境：%ROOT%.venv
    echo 请先运行：python -m venv .venv
    pause
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 npm，请先安装 Node.js 并将 npm 加入 PATH。
    pause
    exit /b 1
)

if not exist "%ROOT%web\node_modules" (
    echo [错误] 前端依赖尚未安装。
    echo 请先运行：cd web ^&^& npm install
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start.ps1"
exit /b %errorlevel%
