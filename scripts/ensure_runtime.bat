@echo off
rem doc2report - makes sure runtime\ (Python + packages) exists in a git checkout. ASCII only (cmd code page).
rem Called by start_webapp.bat and doctor.bat. Needs: git, and access to the repository's remote (same as git pull).
rem The runtime lives on the repository's runtime-win64 branch (built by CI); it is cloned into runtime\ once and
rem refreshed only when scripts\onprem-requirements.txt changed (compared by git blob id, see packaging\build_runtime.ps1).
setlocal EnableDelayedExpansion
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

rem Zip bundle (no .git) or a runtime copied by hand (no runtime\.git): nothing to do.
if not exist "%ROOT%\.git" exit /b 0
if exist "%ROOT%\runtime\python.exe" if not exist "%ROOT%\runtime\.git" exit /b 0

where git >nul 2>nul
if errorlevel 1 (
  echo [doc2report] git was not found, so the Python runtime cannot be downloaded.
  echo   Install Git for Windows, or copy the runtime folder from the install zip here. See docs\team-setup.md
  exit /b 1
)

set "WANT="
for /f "delims=" %%H in ('git -C "%ROOT%" rev-parse HEAD:scripts/onprem-requirements.txt 2^>nul') do set "WANT=%%H"
set "HAVE="
if exist "%ROOT%\runtime\REQ_BLOB" set /p HAVE=<"%ROOT%\runtime\REQ_BLOB"
if exist "%ROOT%\runtime\python.exe" if /i "!HAVE!"=="!WANT!" exit /b 0

if exist "%ROOT%\runtime" if not exist "%ROOT%\runtime\.git" (
  echo [doc2report] The runtime folder exists but is incomplete. Delete it and run again.
  exit /b 1
)

set "URL="
for /f "delims=" %%U in ('git -C "%ROOT%" remote get-url origin 2^>nul') do set "URL=%%U"
if not defined URL (
  echo [doc2report] This folder has no git remote named origin, so the runtime cannot be downloaded.
  exit /b 1
)

echo.
echo [doc2report] Downloading the Python runtime. This happens once, and again only when packages change.
if exist "%ROOT%\runtime\.git" (
  git -c core.longpaths=true -C "%ROOT%\runtime" fetch --depth 1 origin runtime-win64
  if errorlevel 1 goto failed
  git -c core.longpaths=true -C "%ROOT%\runtime" reset --hard FETCH_HEAD
  if errorlevel 1 goto failed
) else (
  git -c core.longpaths=true -c core.autocrlf=false clone --depth 1 --single-branch --branch runtime-win64 "!URL!" "%ROOT%\runtime"
  if errorlevel 1 goto failed
)

set "HAVE="
if exist "%ROOT%\runtime\REQ_BLOB" set /p HAVE=<"%ROOT%\runtime\REQ_BLOB"
if /i not "!HAVE!"=="!WANT!" (
  echo [doc2report] Note: the runtime is older than this code, so some packages may be missing.
  echo   The maintainer's build may still be running. Try again in a few minutes. If it keeps happening, run doctor.bat.
)
exit /b 0

:failed
echo.
echo [doc2report] Could not download the Python runtime.
echo   - Check that this PC can reach the repository (git pull works?), then run this file again.
echo   - Or copy the runtime folder from the install zip into this folder. See docs\team-setup.md
exit /b 1
