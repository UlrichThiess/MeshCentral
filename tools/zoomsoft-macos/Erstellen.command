#!/bin/bash
set -eu
MESH_BUILD_SOURCE="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Zum Erstellen wird Python 3 benötigt (in den Xcode-Entwicklerwerkzeugen enthalten).'
  exit 1
fi
exec python3 "$MESH_BUILD_SOURCE/erstellen.py" "$@"
