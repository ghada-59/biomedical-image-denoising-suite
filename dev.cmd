@echo off
rem Start, stop or check the API and the dashboard. Usage:  dev.cmd start | dev.cmd stop | dev.cmd status
rem Logic is in scripts\dev.ps1 (plain PowerShell, no extra dependencies). The execution-policy switch applies to this one call only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" %*
exit /b %ERRORLEVEL%
