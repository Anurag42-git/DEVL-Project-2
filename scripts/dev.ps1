<#
.SYNOPSIS
Starts the FastAPI backend and Vite frontend together (Windows).
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting API  -> http://localhost:8000" -ForegroundColor Cyan
Write-Host "Starting Web  -> http://localhost:5173" -ForegroundColor Cyan

$api = Start-Process -FilePath python -ArgumentList @(
    '-m', 'uvicorn', 'api.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000'
) -WorkingDirectory $root -PassThru

$web = Start-Process -FilePath npm -ArgumentList @(
    '--prefix', $(Join-Path $root 'frontend'), 'run', 'dev'
) -WorkingDirectory $root -PassThru

try {
    Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor DarkGray
    while ($true) { Start-Sleep -Seconds 1 }
}
finally {
    foreach ($process in @($api, $web)) {
        if (-not $process.HasExited) { taskkill /PID $process.Id /T /F 2>$null | Out-Null }
    }
}
