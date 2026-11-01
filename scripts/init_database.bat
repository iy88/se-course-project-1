@echo off
setlocal
if exist "%~dp0..\backend\.venv\Scripts\python.exe" (
  "%~dp0..\backend\.venv\Scripts\python.exe" "%~dp0init_database.py" %*
) else (
  uv run --project "%~dp0..\backend" --frozen python "%~dp0init_database.py" %*
)
exit /b %errorlevel%
