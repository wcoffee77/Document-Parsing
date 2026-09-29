@echo off
rem doc2report web app - double-click to start (opens the browser automatically)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_webapp.ps1" %*
pause
