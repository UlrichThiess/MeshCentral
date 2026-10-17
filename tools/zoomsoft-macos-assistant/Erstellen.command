#!/bin/bash
set -euo pipefail
ZOOMSOFT_SOURCE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ZOOMSOFT_SOURCE/erstellen.py" "$@"
