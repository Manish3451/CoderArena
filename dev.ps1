# Start both backend and frontend in separate terminals
# Run from the repo root: .\dev.ps1

$root = $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .\.venv\Scripts\uvicorn.exe arena.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host ""
Write-Host "Backend:  http://localhost:8000"
Write-Host "Frontend: http://localhost:3000"
Write-Host "API docs: http://localhost:8000/docs"
Write-Host ""
Write-Host "Before the backend will work, fill in .env:"
Write-Host "  DATABASE_URL  - Supabase pooler URL"
Write-Host "  RESEND_API_KEY - optional (dev mode prints links to console)"
