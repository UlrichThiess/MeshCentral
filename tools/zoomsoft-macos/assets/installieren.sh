echo "$PRODUCT_NAME: Die Installation wird abgeschlossen."
mkdir -p "$DATA_DIR"
chown root:wheel "$DATA_DIR" "$DATA_DIR/meshagent.msh" "$DAEMON_PLIST" "$GUI_PLIST"
chmod 755 '/usr/local/mesh_services' '/usr/local/mesh_services/meshagent' "$DATA_DIR"
chmod 644 "$DATA_DIR/meshagent.msh" "$DAEMON_PLIST" "$GUI_PLIST"
if [ -f "$DATA_DIR/meshagent.db" ]; then
  chown root:wheel "$DATA_DIR/meshagent.db"
  chmod 600 "$DATA_DIR/meshagent.db"
fi

# Eine beschädigte App darf nicht als erfolgreich installiert gemeldet werden.
/usr/bin/codesign --verify --strict --all-architectures "$APP_PATH"

LSREGISTER='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
/bin/launchctl bootstrap system "$DAEMON_PLIST"
for GUI_UID in $GUI_UIDS; do
  if /bin/launchctl print "gui/$GUI_UID" >/dev/null 2>&1; then
    if [ -x "$LSREGISTER" ]; then
      als_gui_benutzer "$GUI_UID" "$LSREGISTER" -f "$APP_PATH" >/dev/null 2>&1 || true
    fi
    /bin/launchctl bootstrap "gui/$GUI_UID" "$GUI_PLIST"
  fi
done
rm -f "$DATA_DIR/meshagent"

echo "$PRODUCT_NAME: Installation abgeschlossen."
