@echo off
setlocal enabledelayedexpansion
echo ===========================================================
echo   Universal Website Replication Engine  -  Installation
echo ===========================================================

REM --- Locate a suitable Python (3.12+) -----------------------------------
set "PY=py -3.14"
%PY% --version >nul 2>&1 || set "PY=py -3.12"
%PY% --version >nul 2>&1 || set "PY=py -3"
%PY% --version >nul 2>&1 || set "PY=python"
%PY% --version >nul 2>&1 || (
  echo [ERROR] Python 3.12+ was not found. Install it from https://python.org and retry.
  exit /b 1
)
echo Using Python:
%PY% --version

REM --- Check Node/npm ------------------------------------------------------
where npm >nul 2>&1 || (
  echo [ERROR] Node.js / npm was not found. Install Node 18+ from https://nodejs.org and retry.
  exit /b 1
)

REM --- Backend ------------------------------------------------------------
cd /d "%~dp0backend"

echo.
echo [1/5] Creating Python virtual environment...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || ( echo [ERROR] Could not create the virtual environment. & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

echo [2/5] Upgrading pip...
"%VPY%" -m pip install --upgrade pip

echo [3/5] Installing Python dependencies...
"%VPY%" -m pip install -r requirements.txt || ( echo [ERROR] pip install failed. & exit /b 1 )

echo [4/5] Installing Chromium for Playwright (may download on first run)...
"%VPY%" -m playwright install chromium || ( echo [ERROR] Playwright browser install failed. & exit /b 1 )

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created backend\.env from the example.
)

REM --- Frontend ----------------------------------------------------------
cd /d "%~dp0frontend"
echo.
echo [5/5] Installing and building the frontend...
call npm install || ( echo [ERROR] npm install failed. & exit /b 1 )
call npm run build || ( echo [ERROR] Frontend build failed. & exit /b 1 )

echo.
echo ===========================================================
echo   Installation complete.  Run  start.bat  to launch.
echo ===========================================================
endlocal
