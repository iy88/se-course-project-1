$pythonExe = Join-Path $PSScriptRoot '../backend/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $pythonExe) {
    & $pythonExe "$PSScriptRoot/dev_services.py" @args
} else {
    & uv run --project "$PSScriptRoot/../backend" --frozen python "$PSScriptRoot/dev_services.py" @args
}
exit $LASTEXITCODE
