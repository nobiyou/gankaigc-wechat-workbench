@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1"
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo start-dev.cmd failed. Check logs:
  echo   %~dp0.tmp\backend.err.log
  echo   %~dp0.tmp\frontend.err.log
  pause
)
exit /b %EXIT_CODE%
