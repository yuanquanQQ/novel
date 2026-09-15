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
    Write-Host 'Starting Novel Console...' -ForegroundColor Cyan
    Write-Host '[Backend] http://127.0.0.1:11452'
    Write-Host '[Frontend] http://localhost:11451'
    Write-Host 'Both services run in this window. Press Ctrl+C or close it to stop.'
    Write-Host ''

    $backend = Start-Process -FilePath $python -ArgumentList @(
        '-X', 'utf8', '-m', 'uvicorn', 'server.app:app',
        '--host', '127.0.0.1', '--port', '11452', '--reload'
    ) -WorkingDirectory $root -NoNewWindow -PassThru

    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        if ($backend.HasExited) {
            throw "Backend exited during startup with code $($backend.ExitCode)."
        }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:11452/docs' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch {
        }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) {
        throw 'Backend health check timed out. Review the log above.'
    }

    $frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList @(
        'run', 'dev', '--', '--host', 'localhost', '--port', '11451'
    ) -WorkingDirectory $web -NoNewWindow -PassThru

    Write-Host 'Services are ready. Open http://localhost:11451' -ForegroundColor Green
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
    }
    if ($backend.HasExited) {
        Write-Host "Backend exited with code $($backend.ExitCode)." -ForegroundColor Yellow
    }
    if ($frontend.HasExited) {
        Write-Host "Frontend exited with code $($frontend.ExitCode)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Stop-ChildTree $frontend
    Stop-ChildTree $backend
    Write-Host 'Frontend and backend processes have been stopped.'
}
