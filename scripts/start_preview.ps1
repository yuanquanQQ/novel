$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
$occupied = Get-NetTCPConnection -LocalPort 11453,11454 -State Listen -ErrorAction SilentlyContinue
if ($occupied) { throw 'Preview ports 11453 or 11454 are occupied; existing processes were not changed.' }
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Start-HiddenLoggedProcess {
    param(
        [string]$executable,
        [string[]]$argumentList,
        [string]$workingDirectory,
        [string]$stdoutPath,
        [string]$stderrPath
    )
    # Windows PowerShell 5.1 fails when Start-Process inherits both Path and PATH.
    # ProcessStartInfo preserves the full environment; cmd only redirects logs.
    # Do not use -UseNewEnvironment because networking and crypto need user env data.
    $quotedArgs = foreach ($argument in $argumentList) {
        '"' + ($argument -replace '"', '\"') + '"'
    }
    $commandLine = '""' + $executable + '" ' + ($quotedArgs -join ' ') + ' 1>"' + $stdoutPath + '" 2>"' + $stderrPath + '""'
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $env:ComSpec
    $startInfo.Arguments = '/d /s /c ' + $commandLine
    $startInfo.WorkingDirectory = $workingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($startInfo)
}

$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$apiProcess = Start-HiddenLoggedProcess -executable $pythonPath -argumentList @(
    '-X', 'utf8', '-m', 'uvicorn', 'server.app:app', '--host', '127.0.0.1', '--port', '11454'
) -workingDirectory $projectRoot `
    -stdoutPath (Join-Path $runtimeDir 'preview-api.stdout.log') `
    -stderrPath (Join-Path $runtimeDir 'preview-api.stderr.log')

try {
    $nodePath = (Get-Command node.exe).Source
    $webProcess = Start-HiddenLoggedProcess -executable $nodePath -argumentList @(
        'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '11453',
        '--strictPort', '--mode', 'preview', '--configLoader', 'runner'
    ) -workingDirectory (Join-Path $projectRoot 'web') `
        -stdoutPath (Join-Path $runtimeDir 'preview-web.stdout.log') `
        -stderrPath (Join-Path $runtimeDir 'preview-web.stderr.log')
} catch {
    & taskkill.exe /PID $apiProcess.Id /T /F *> $null
    throw
}
[pscustomobject]@{
    BackendPid = $apiProcess.Id
    FrontendPid = $webProcess.Id
    Url = 'http://127.0.0.1:11453/novels/xinghai-zhumingshi/chapters'
} | ConvertTo-Json
