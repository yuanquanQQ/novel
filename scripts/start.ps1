$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$web = Join-Path $root 'web'
$vite = Join-Path $web 'node_modules\vite\bin\vite.js'
$backend = $null
$frontend = $null
$exitCode = 0

function Stop-ChildTree([System.Diagnostics.Process] $process) {
    if ($null -eq $process -or $process.HasExited) { return }
    & taskkill.exe /PID $process.Id /T /F *> $null
}

try {
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
        throw "Vite was not found at $vite. Run npm install in the web directory."
    }

    Write-Host 'Starting Novel Console...' -ForegroundColor Cyan
    Write-Host '[Backend] http://127.0.0.1:11452'
    Write-Host '[Frontend] http://localhost:11451'
    Write-Host 'Both services run in this window. Press Q to exit; do not press Ctrl+C.'
    Write-Host ''

    $backend = Start-Process -FilePath $python -ArgumentList @(
        '-X', 'utf8', '-m', 'uvicorn', 'server.app:app',
        '--host', '127.0.0.1', '--port', '11452'
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

    $frontend = Start-Process -FilePath $node -ArgumentList @(
        $vite, '--host', 'localhost', '--port', '11451'
    ) -WorkingDirectory $web -NoNewWindow -PassThru

    Write-Host 'Services are ready. Open http://localhost:11451' -ForegroundColor Green
    Write-Host 'Press Q to exit.' -ForegroundColor Cyan
    while ($true) {
        if ($backend.HasExited) {
            Write-Host "Backend exited with code $($backend.ExitCode)." -ForegroundColor Yellow
            $exitCode = 1
            break
        }
        if ($frontend.HasExited) {
            Write-Host "Frontend exited with code $($frontend.ExitCode)." -ForegroundColor Yellow
            $exitCode = 1
            break
        }
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq [ConsoleKey]::Q) {
                Write-Host 'Stopping services...'
                break
            }
        }
        Start-Sleep -Milliseconds 100
    }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
} finally {
    Stop-ChildTree $frontend
    Stop-ChildTree $backend
    Write-Host 'Frontend and backend processes have been stopped.'
}

exit $exitCode
