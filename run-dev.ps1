# Start both backend and frontend for local dev
$root = Split-Path -Parent $PSCommandPath

# Kill existing processes on ports 8000 and 3000
$pythonProcs = Get-NetTCPConnection -LocalPort 8000,3000 -ErrorAction SilentlyContinue | Select-Object OwningProcess -Unique
foreach ($p in $pythonProcs) {
    if ($p.OwningProcess) { Stop-Process -Id $p.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Start-Sleep 2

# Start backend with in-memory mode (no DATABASE_URL)
$backendEnv = @{
    ENVIRONMENT = "development"
    OPENAI_API_KEY = $env:OPENAI_API_KEY
    MOONSHOT_API_KEY = $env:MOONSHOT_API_KEY
}

Write-Host "Starting backend (port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .venv\Scripts\python.exe -m uvicorn arena.main:app --port 8000"

Start-Sleep 3

Write-Host "Starting frontend (port 3000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host ""
Write-Host "Backend: http://localhost:8000" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "Note: In local dev mode, magic links print to backend console instead of email." -ForegroundColor Yellow