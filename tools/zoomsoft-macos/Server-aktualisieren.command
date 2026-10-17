#!/bin/bash
set -euo pipefail

MESH_RESULT_DIR="$(cd "$(dirname "$0")" && pwd)"
MESH_SERVER_AGENT="$MESH_RESULT_DIR/Server/meshagent_osx-universal-64"
if [ ! -s "$MESH_SERVER_AGENT" ]; then
  echo 'Zuerst die neuen Pakete mit Erstellen.command erstellen. Danach dieses Skript im Ergebnisordner starten.' >&2
  exit 1
fi
MESH_SERVER_USER='ulrich.thiess@assist.zoomsoft.dmz'
MESH_SERVER_STAGE=".zoomsoft-fernwartung-$(date +%Y%m%d-%H%M%S)-$$"
MESH_EXPECTED_HASH="$(/usr/bin/shasum -a 256 "$MESH_SERVER_AGENT" | /usr/bin/awk '{print $1}')"

echo 'Fernwartung | ZOOMsoft GmbH: Der neue signierte Agent wird auf den Server übertragen.'
/usr/bin/scp "$MESH_SERVER_AGENT" "$MESH_SERVER_USER:$MESH_SERVER_STAGE"

# Das Remote-Skript wird als Datei übertragen; sudo kann dadurch ein Passwort im Terminal abfragen.
MESH_LOCAL_UPDATE="$(mktemp -t zoomsoft-server-update)"
trap 'rm -f "$MESH_LOCAL_UPDATE"' EXIT
cat > "$MESH_LOCAL_UPDATE" <<'REMOTE'
#!/bin/bash
set -euo pipefail
MESH_SOURCE="$1"
MESH_HASH="$2"
MESH_TARGET='/opt/meshcentral/meshcentral-data/agents/meshagent_osx-universal-64'
MESH_DIRECTORY='/opt/meshcentral/meshcentral-data/agents'
MESH_ACTUAL_HASH="$(sha256sum "$MESH_SOURCE" | awk '{print $1}')"
if [ "$MESH_ACTUAL_HASH" != "$MESH_HASH" ]; then
  echo 'Die übertragene Datei stimmt nicht mit der signierten Originaldatei überein.' >&2
  exit 1
fi
sudo -u meshcentral mkdir -p "$MESH_DIRECTORY"
if sudo test -e "$MESH_TARGET"; then
  sudo cp -p "$MESH_TARGET" "$MESH_TARGET.bak-$(date +%Y%m%d-%H%M%S)"
fi
sudo install -o meshcentral -m 0755 "$MESH_SOURCE" "$MESH_TARGET.neu"
sudo cmp "$MESH_SOURCE" "$MESH_TARGET.neu"
sudo mv "$MESH_TARGET.neu" "$MESH_TARGET"
sudo systemctl restart meshcentral
sudo systemctl is-active meshcentral
rm -f "$MESH_SOURCE"
echo 'Fernwartung | ZOOMsoft GmbH: Der Server wurde aktualisiert.'
REMOTE

/usr/bin/scp "$MESH_LOCAL_UPDATE" "$MESH_SERVER_USER:$MESH_SERVER_STAGE.sh"
echo 'MeshCentral wird nun neu gestartet; bestehende Sitzungen werden kurz unterbrochen.'
/usr/bin/ssh -t "$MESH_SERVER_USER" \
  "/bin/bash '$MESH_SERVER_STAGE.sh' '$MESH_SERVER_STAGE' '$MESH_EXPECTED_HASH'"
/usr/bin/ssh "$MESH_SERVER_USER" "rm -f '$MESH_SERVER_STAGE.sh'"
