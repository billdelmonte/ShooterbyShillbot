# Shooter ShillBot bootstrap (Windows / PowerShell)
# Run from project root:
#   powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Close -Serve

param(
  [switch]$Close,
  [switch]$Serve
)

$ErrorActionPreference = "Stop"

Write-Host "== Shooter ShillBot bootstrap =="

if (!(Test-Path ".\.venv")) {
  Write-Host "Creating venv..."
  python -m venv .venv
}

$PY = ".\.venv\Scripts\python.exe"
if (!(Test-Path $PY)) { throw "venv python not found at $PY" }

Write-Host "Installing requirements..."
& $PY -m pip install --upgrade pip
& $PY -m pip install -r requirements.txt

Write-Host "Sanity check imports..."
& $PY -c "import shillbot.db as d; print('DB ok:', hasattr(d,'DB')); import shillbot.cli as c; print('CLI ok:', hasattr(c,'main'))"

Write-Host "Init DB..."
& $PY -m shillbot init-db

Write-Host "Ingest..."
& $PY -m shillbot ingest

if ($Close) {
  Write-Host "Close once..."
  & $PY -m shillbot close-once
}

if ($Serve) {
  Write-Host "Serving reports..."
  & $PY -m shillbot serve
}
