@echo off
setlocal
cd /d "%~dp0"

REM --- First-run bootstrap ------------------------------------------------
if not exist "backend\.venv\Scripts\python.exe" (
  echo No virtual environment found - running installation first...
  call install.bat || exit /b 1
)

REM --- Make sure the UI is built so the backend can serve it --------------
if not exist "frontend\dist\index.html" (
  echo Building the frontend...
  pushd frontend
  if not exist "node_modules" ( call npm install )
  call npm run build
  popd
)

set "URL=http://127.0.0.1:8000"
echo.
echo ===========================================================
echo   Starting the Replication Engine at %URL%
echo   (press Ctrl+C in this window to stop)
echo ===========================================================

REM Open the browser a few seconds after the server starts (detached).
start "" cmd /c "timeout /t 3 >nul & start %URL%"

cd backend
".venv\Scripts\python.exe" run.py

endlocal
