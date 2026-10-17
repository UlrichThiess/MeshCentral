export PATH='/usr/bin:/bin:/usr/sbin:/sbin'
umask 022
if [ "$(id -u)" -ne 0 ]; then
  echo "$PRODUCT_NAME: Für diesen Vorgang sind Administratorrechte erforderlich." >&2
  exit 1
fi
if [ -n "${3:-}" ] && [ "$3" != '/' ]; then
  echo "$PRODUCT_NAME: Dieser Vorgang ist nur auf dem laufenden Startvolume möglich." >&2
  exit 1
fi

GUI_UIDS="$(/bin/ps -axo uid= | /usr/bin/awk '$1 >= 500 {print $1}' | /usr/bin/sort -nu)"

als_gui_benutzer() {
  GUI_RUN_UID="$1"
  shift
  /bin/launchctl asuser "$GUI_RUN_UID" /usr/bin/sudo -u "#$GUI_RUN_UID" "$@"
}

dienste_stoppen() {
  for GUI_UID in $GUI_UIDS; do
    /bin/launchctl bootout "gui/$GUI_UID/$GUI_LABEL" >/dev/null 2>&1 || true
  done
  /bin/launchctl bootout "system/$SERVICE_LABEL" >/dev/null 2>&1 || true
}
