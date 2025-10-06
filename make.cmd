@echo off
setlocal
set SCRIPT=%~dp0run-stack.ps1

if not exist "%SCRIPT%" (
  echo run-stack.ps1 not found next to make.cmd
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
