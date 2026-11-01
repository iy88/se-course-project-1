$pythonExe = Join-Path $PSScriptRoot '../backend/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $pythonExe) {
    & $pythonExe "$PSScriptRoot/init_database.py" @args
} else {
    & uv run --project "$PSScriptRoot/../backend" --frozen python "$PSScriptRoot/init_database.py" @args
}
exit $LASTEXITCODE
