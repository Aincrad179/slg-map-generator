@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

REM ---- find a Python 3 interpreter ----
set "PY="
REM prefer the official Windows launcher (it selects Python 3 even if PATH was not set)
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
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
)

%PY% "fhlc_gen.py" random
if errorlevel 1 (
  echo.
  echo [ERROR] Generation failed. Please send the messages above to the maintainer.
  echo.
  pause
  exit /b 1
)
start "" "output\preview.png"
echo.
echo Done. Press any key to close.
pause >nul
