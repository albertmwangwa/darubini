# Darubini setup for Windows PowerShell (the Makefile equivalent of `make setup`).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "Python launcher 'py' not found. Install Python 3.10+ from https://www.python.org/downloads/ and tick 'Add to PATH'."
}

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,notebooks]"
.\.venv\Scripts\pre-commit.exe install

Write-Host ""
Write-Host "Setup complete. Next: scripts\get-data.ps1 (core datasets, about 6.5 GB)." -ForegroundColor Green
