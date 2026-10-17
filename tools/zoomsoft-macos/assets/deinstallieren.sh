echo "$PRODUCT_NAME: Die Deinstallation wird vorbereitet."
if [ -e "$APP_PATH/Contents/Info.plist" ]; then
  EXISTING_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist")"
  if [ "$EXISTING_ID" != "$BUNDLE_ID" ]; then
    echo "$PRODUCT_NAME: Am Zielort liegt eine andere Anwendung. Die Deinstallation wurde abgebrochen." >&2
    exit 1
  fi
fi
dienste_stoppen

# Nur die zu diesem Agenten gehörenden Diagnosedienste entfernen.
for DIAGNOSTIC_LABEL in 'meshagentDiagnostic_periodicStart' 'meshagentDiagnostic'; do
  /bin/launchctl bootout "system/$DIAGNOSTIC_LABEL" >/dev/null 2>&1 || true
  rm -f "/Library/LaunchDaemons/$DIAGNOSTIC_LABEL.plist"
done

# Ausschließlich die Freigaben dieser App zurücksetzen, niemals sämtliche TCC-Freigaben.
LSREGISTER='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
for GUI_UID in $GUI_UIDS; do
  if /bin/launchctl print "gui/$GUI_UID" >/dev/null 2>&1; then
    als_gui_benutzer "$GUI_UID" /usr/bin/tccutil reset All "$BUNDLE_ID" >/dev/null 2>&1 || true
    if [ -d "$APP_PATH" ] && [ -x "$LSREGISTER" ]; then
      als_gui_benutzer "$GUI_UID" "$LSREGISTER" -u "$APP_PATH" >/dev/null 2>&1 || true
    fi
  fi
done

rm -f "$DAEMON_PLIST" "$GUI_PLIST"
# Feste, nicht vom Aufrufer veränderbare Pfade; die Agentdaten werden mit entfernt.
rm -rf -- "$APP_PATH" "$DATA_DIR"
rm -f '/usr/local/mesh_services/meshagentDiagnostic/meshagentDiagnostic'
rmdir '/usr/local/mesh_services/meshagentDiagnostic' 2>/dev/null || true
rmdir '/usr/local/mesh_services/meshagent' 2>/dev/null || true
rmdir '/usr/local/mesh_services' 2>/dev/null || true

/usr/sbin/pkgutil --forget 'de.zoomsoft.fernwartung.installation.pkg' >/dev/null 2>&1 || true
/usr/sbin/pkgutil --forget 'com.meshcentral.meshagent.pkg' >/dev/null 2>&1 || true

if [ -e "$APP_PATH" ] || [ -e "$DATA_DIR" ] || [ -e "$DAEMON_PLIST" ] || [ -e "$GUI_PLIST" ]; then
  echo "$PRODUCT_NAME: Die Deinstallation konnte nicht vollständig abgeschlossen werden." >&2
  exit 1
fi
echo "$PRODUCT_NAME: Deinstallation abgeschlossen."
