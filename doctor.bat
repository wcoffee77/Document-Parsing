@echo off
rem doc2report - installation/environment check. Writes a report file you can send to the maintainer.
cd /d "%~dp0"
call "%~dp0scripts\ensure_runtime.bat"
if exist "%~dp0runtime\python.exe" (
  if not defined DOC2REPORT_OUTPUT_DIR if not exist "%~dp0.git" set "DOC2REPORT_OUTPUT_DIR=%USERPROFILE%\Documents\doc2report"
  "%~dp0runtime\python.exe" -m doc2report doctor --save
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_webapp.ps1" --doctor
)
pause
