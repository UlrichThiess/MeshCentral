# Die bisherigen Dienstbezeichnungen bleiben für das Erkennen des Dienstes erhalten.
# Die neue App übernimmt dieselbe Datenbank und damit die vorhandene Geräteidentität.
echo "$PRODUCT_NAME: Die Installation wird vorbereitet."
MESH_OS_REQUIRED="$MINIMUM_INTEL"
if [ "$(/usr/sbin/sysctl -in hw.optional.arm64 2>/dev/null || true)" = '1' ]; then
  MESH_OS_REQUIRED="$MINIMUM_ARM"
fi
MESH_OS_CURRENT="$(/usr/bin/sw_vers -productVersion)"
if ! /usr/bin/awk -v current="$MESH_OS_CURRENT" -v required="$MESH_OS_REQUIRED" 'BEGIN {
  split(current, c, "."); split(required, r, ".");
  for (i = 1; i <= 3; i++) {
    if ((c[i]+0) > (r[i]+0)) exit 0;
    if ((c[i]+0) < (r[i]+0)) exit 1;
  }
  exit 0;
}'; then
  echo "$PRODUCT_NAME: Mindestens macOS $MESH_OS_REQUIRED wird benötigt. Vorhanden ist macOS $MESH_OS_CURRENT." >&2
  exit 1
fi
if [ -e "$APP_PATH/Contents/Info.plist" ]; then
  EXISTING_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist")"
  if [ "$EXISTING_ID" != "$BUNDLE_ID" ]; then
    echo "$PRODUCT_NAME: Am Zielort liegt eine andere Anwendung. Die Installation wurde abgebrochen." >&2
    exit 1
  fi
fi
dienste_stoppen
