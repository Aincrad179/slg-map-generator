@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ---- find a Python 3 interpreter ----
set "PY="
set "PYW="
REM prefer the official Windows launcher (it selects Python 3 even if PATH was not set)
py -3 --version >nul 2>nul && ( set "PY=py -3" & set "PYW=pyw -3" )
if not defined PY (
  where python >nul 2>nul && ( set "PY=python" & set "PYW=pythonw" )
)
if not defined PY (
  echo.
  echo [ERROR] Python 3 not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo During setup, check "Add python.exe to PATH". Then run this again.
  echo.
  pause
  exit /b 1
)

REM ---- require Python 3.10+ ----
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] This tool needs Python 3.10 or newer. The version found is:
  %PY% --version
  echo Install Python 3.10+ from https://www.python.org/downloads/ and retry.
  echo.
  pause
  exit /b 1
)

REM ---- ensure Pillow is installed ----
%PY% -c "import PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing missing dependency: Pillow ...
  %PY% -m pip install pillow
  %PY% -c "import PIL" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install Pillow. Run manually:  %PY% -m pip install pillow
    echo.
    pause
    exit /b 1
  )
)

REM ---- launch GUI (no console window) ----
start "" %PYW% "gui.pyw"
