#!/usr/bin/env bash
# Manage local development services from any directory.
set -euo pipefail
exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/dev_services.py" "$@"
