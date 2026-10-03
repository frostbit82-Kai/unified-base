@echo off
rem Self-bootstrapping launcher for Unified Base on Windows.
rem Creates its own venv on first run - no admin rights, no prompts.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: creating venv...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Python 3 was not found. Install it, then run this again:
    echo     winget install -e --id Python.Python.3.13
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --no-input -r requirements.txt
if "%~1"=="--selftest" (
    ".venv\Scripts\python.exe" main.py --selftest
    pause
    exit /b
)
rem A console of its own, minimised: the app hides it once it is up, and every
rem module process shares it instead of opening a console window of its own.
start "Unified Base" /min ".venv\Scripts\python.exe" main.py %*
