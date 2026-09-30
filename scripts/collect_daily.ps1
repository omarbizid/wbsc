# Daily collection until Airflow takes over (Milestone 5).
# Collects every active source into the raw store and loads it. If the database is down,
# the raw data is still saved; load it later with `jobintel replay --all`.
#
# Register once (runs every day at 07:00 as the current user):
#   schtasks /Create /SC DAILY /ST 07:00 /TN "jobintel-collect" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"<repo>\scripts\collect_daily.ps1\""
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
New-Item -ItemType Directory -Force -Path "$repo\logs" | Out-Null
$log = "$repo\logs\collect_$(Get-Date -Format yyyy-MM-dd).log"
$env:PYTHONIOENCODING = "utf-8"
# Make sure the database container is up (no-op if already running).
docker compose up -d postgres *>> $log
Start-Sleep -Seconds 5
& "$repo\.venv\Scripts\jobintel.exe" -v collect --all *>> $log
"exit code: $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log
exit $LASTEXITCODE
