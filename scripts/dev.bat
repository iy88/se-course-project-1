@echo off
setlocal
if exist "%~dp0..\backend\.venv\Scripts\python.exe" (
  "%~dp0..\backend\.venv\Scripts\python.exe" "%~dp0dev_services.py" %*
) else (
  uv run --project "%~dp0..\backend" --frozen python "%~dp0dev_services.py" %*
)
exit /b %errorlevel%
