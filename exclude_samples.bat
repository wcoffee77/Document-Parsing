@echo off
rem Hide test samples (samples\) from this PC's working folder. Repo is not changed; git pull still works.
rem Run once after git clone. To undo: git sparse-checkout disable
git sparse-checkout set --no-cone "/*" "!/samples/"
if errorlevel 1 (
  echo Failed. Check that git is installed and this is the project folder.
  exit /b 1
)
echo Done. The samples folder is hidden from this PC. git pull works as before.
