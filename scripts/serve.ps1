<#
.SYNOPSIS
Builds the React app and serves it together with the FastAPI backend on port 8000.
This is the single-process production deployment for Windows.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Building frontend..." -ForegroundColor Cyan
npm --prefix (Join-Path $root 'frontend') run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }

Write-Host "Starting production server at http://localhost:8000" -ForegroundColor Cyan
Set-Location $root
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
