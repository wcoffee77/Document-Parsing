@echo off
rem doc2report web app - double-click to start (opens the browser automatically)
rem Uses the bundled runtime\python.exe when present (no Python/uv install, no PowerShell policy issues).
cd /d "%~dp0"
if exist "%~dp0runtime\python.exe" (
  if not defined DOC2REPORT_OUTPUT_DIR if not exist "%~dp0.git" set "DOC2REPORT_OUTPUT_DIR=%USERPROFILE%\Documents\doc2report"
  "%~dp0runtime\python.exe" -m doc2report web %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_webapp.ps1" %*
)
pause
