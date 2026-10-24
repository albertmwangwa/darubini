#!/usr/bin/env bash
# Download Darubini datasets on macOS or Linux.
# Usage: scripts/get-data.sh [core|extended|large] [--accept-licences]
set -euo pipefail
tier="${1:-core}"
shift || true
cli=".venv/bin/darubini"
[[ -x "$cli" ]] || { echo "Run 'make setup' first." >&2; exit 1; }
"$cli" download --tier "$tier" "$@"
"$cli" verify
