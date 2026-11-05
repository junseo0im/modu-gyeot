$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    docker compose up -d --build --wait db ocr
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and retry.' }
    Push-Location "$root\apps\api"
    try {
        uv sync --locked
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies failed.' }
        uv run python -m gyeot.migrate
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    } finally { Pop-Location }
    $log = Join-Path $root 'private\runtime'
    New-Item -ItemType Directory -Path $log -Force | Out-Null
    foreach ($port in 8766,3000) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $port already in use. Stop the known process before starting another instance."
        }
    }
    $pidFile = Join-Path $log 'processes.json'
    if (Test-Path -LiteralPath $pidFile) {
        $previous = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        foreach ($id in @($previous.api, $previous.worker, $previous.web)) {
            if (Get-Process -Id $id -ErrorAction SilentlyContinue) { throw 'A previous development process is still running. Stop it before restarting.' }
        }
    }
    $python = Join-Path $root 'apps\api\.venv\Scripts\python.exe'
    $api = Start-Process $python -ArgumentList '-B -m uvicorn gyeot.app:app --host 127.0.0.1 --port 8766 --no-access-log' -WorkingDirectory "$root\apps\api" -RedirectStandardOutput "$log\api.out.log" -RedirectStandardError "$log\api.err.log" -PassThru
    $worker = Start-Process $python -ArgumentList '-B -m gyeot.worker' -WorkingDirectory "$root\apps\api" -RedirectStandardOutput "$log\worker.out.log" -RedirectStandardError "$log\worker.err.log" -PassThru
    $env:NEXT_TELEMETRY_DISABLED='1'
    $web = Start-Process (Get-Command node).Source -ArgumentList 'node_modules/next/dist/bin/next start --hostname 127.0.0.1' -WorkingDirectory "$root\apps\web" -RedirectStandardOutput "$log\web.out.log" -RedirectStandardError "$log\web.err.log" -PassThru
    @{api=$api.Id;worker=$worker.Id;web=$web.Id} | ConvertTo-Json | Set-Content -LiteralPath $pidFile
    Write-Output 'Started local API, worker and web. Open http://localhost:3000 (not 127.0.0.1; origin is configured). Logs: private/runtime.'
} finally { Pop-Location }