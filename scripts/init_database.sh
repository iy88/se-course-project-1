#!/usr/bin/env bash
# Initialize PostgreSQL on Linux/macOS from any working directory.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
python="$repo_root/backend/.venv/bin/python"
# Git Bash/MSYS uses the native Windows virtual environment layout.
if [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]]; then
    python="$repo_root/backend/.venv/Scripts/python.exe"
fi
if [[ -x "$python" ]]; then
    exec "$python" "$script_dir/init_database.py" "$@"
fi
exec uv run --project "$repo_root/backend" --frozen python "$script_dir/init_database.py" "$@"
