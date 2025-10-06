@echo off
setlocal enabledelayedexpansion

set "SCRIPT=%~dp0make.ps1"

rem Prefer PowerShell Core (pwsh) if available
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
  exit /b !errorlevel!
)

rem Fallback to Windows PowerShell
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %errorlevel%
