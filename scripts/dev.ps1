<#
.SYNOPSIS
Starts the FastAPI backend and Vite frontend together (Windows).
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$apiPort = if ($env:API_PORT) { $env:API_PORT } else { '8000' }
$webPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { '5173' }

# Resolve executables explicitly. On Windows npm is a .cmd shim, and
# Start-Process cannot resolve it reliably from PATH. cmd /c with the whole
# command wrapped in quotes also handles paths containing spaces.
$pythonCandidate = @(
    Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' }
)
if ($pythonCandidate.Count -eq 0) { throw 'python.exe was not found on PATH' }
$pythonExe = $pythonCandidate[0].Source

$npmCandidate = @(
    Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue
)
if ($npmCandidate.Count -eq 0) {
    $npmCandidate = @(Get-Command npm -CommandType Application -ErrorAction Stop)
}
$npmExe = $npmCandidate[0].Source

Write-Host "Starting API  -> http://localhost:$apiPort" -ForegroundColor Cyan
Write-Host "Starting Web  -> http://localhost:$webPort" -ForegroundColor Cyan

$api = Start-Process -FilePath $pythonExe -ArgumentList @(
    '-m', 'uvicorn', 'api.main:app', '--reload', '--host', '127.0.0.1', '--port', $apiPort
) -WorkingDirectory $root -PassThru

$npmCommandLine = '/c ""{0}" --prefix "{1}" run dev -- --port {2}"' -f $npmExe, $frontend, $webPort
$web = Start-Process -FilePath $env:ComSpec -ArgumentList $npmCommandLine `
    -WorkingDirectory $root -PassThru

try {
    Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor DarkGray
    while ($true) { Start-Sleep -Seconds 1 }
}
finally {
    foreach ($process in @($api, $web)) {
        if ($process -and -not $process.HasExited) {
            taskkill /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}
