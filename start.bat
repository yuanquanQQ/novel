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

echo 正在启动小说创作控制台...
start "Novel Backend" /D "%ROOT%" cmd /k ""%PYTHON%" -X utf8 -m uvicorn server.app:app --host 127.0.0.1 --port 11452 --reload"
start "Novel Frontend" /D "%ROOT%web" cmd /k "npm run dev"

echo.
echo 后端：http://127.0.0.1:11452
echo 前端：http://localhost:114514
echo 关闭两个新窗口即可停止服务。
timeout /t 3 >nul
endlocal
