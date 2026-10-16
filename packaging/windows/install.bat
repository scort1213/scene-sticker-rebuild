@echo off
rem Double-click to install or update the scene-sticker-rebuild skill for Codex.
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if %errorlevel%==0 (
  py -3.12 install.py %*
) else (
  py -3 install.py %*
)
echo.
pause
