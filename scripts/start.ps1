$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$web = Join-Path $root 'web'
$backend = $null
$frontend = $null

function Stop-ChildTree([System.Diagnostics.Process] $process) {
    if ($null -eq $process -or $process.HasExited) { return }
    & taskkill.exe /PID $process.Id /T /F *> $null
}

try {
    Write-Host '正在启动小说创作控制台...' -ForegroundColor Cyan
    Write-Host '[后端] http://127.0.0.1:11452'
    Write-Host '[前端] http://localhost:11451'
    Write-Host '两个服务将在当前窗口运行；按 Ctrl+C 或关闭窗口可停止全部服务。'
    Write-Host ''

    $backend = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'server.app:app', '--host', '127.0.0.1', '--port', '11452', '--reload') -WorkingDirectory $root -NoNewWindow -PassThru
    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        if ($backend.HasExited) { throw "后端启动失败，退出代码：$($backend.ExitCode)" }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:11452/docs' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $healthy = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) { throw '后端健康检查超时，请查看上方日志。' }

    $frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev', '--', '--host', 'localhost', '--port', '11451') -WorkingDirectory $web -NoNewWindow -PassThru
    Write-Host '服务已启动，浏览器打开 http://localhost:11451' -ForegroundColor Green
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
    }
    if ($backend.HasExited) { Write-Host "后端已退出（代码 $($backend.ExitCode)）。" -ForegroundColor Yellow }
    if ($frontend.HasExited) { Write-Host "前端已退出（代码 $($frontend.ExitCode)）。" -ForegroundColor Yellow }
} catch {
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Stop-ChildTree $frontend
    Stop-ChildTree $backend
    Write-Host '已清理前后端进程。'
}
