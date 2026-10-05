@echo off
rem Unified Base self-test: starts a small window, finds it, embeds it and
rem stops it, then says what this PC has for each kind of module.
"%~dp0runtime\python.exe" -E -s "%~dp0app\main.py" --selftest
echo.
pause
