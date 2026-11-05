@echo off
REM Development mode: backend (auto-serving API) + Vite dev server with hot reload.
REM Backend: http://127.0.0.1:8000   Frontend (open this): http://localhost:5173
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" ( call install.bat || exit /b 1 )

start "Replicator API" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe run.py"
start "Replicator UI"  cmd /k "cd /d %~dp0frontend && npm run dev"
start "" cmd /c "timeout /t 5 >nul & start http://localhost:5173"
echo Two windows launched (API + UI). Open http://localhost:5173
endlocal
