# Fernwartung | ZOOMsoft GmbH

Dieses Verzeichnis enthält die vollständigen Quellen der angepassten macOS-Fassung.
Es übernimmt die bisherigen Erstellungsskripte einschließlich der zuletzt vereinbarten
App-Namen und des Kunden-ZIPs mit ausschließlich zwei Apps:

- `Fernwartung | ZOOMsoft GmbH Installation.app`
- `Fernwartung | ZOOMsoft GmbH Deinstallation.app`

Beide Apps verwenden das ZOOMsoft-Logo und dieselben kompakten deutschen Dialoge.
Sie installieren beziehungsweise deinstallieren für alle Benutzer des Macs und
fordern Administratorrechte an. Die Abschlussmeldungen lauten „Installation
abgeschlossen“ beziehungsweise „Deinstallation abgeschlossen“.

## Auf dem Mac erstellen

Vorausgesetzt werden die vorhandenen Xcode-Werkzeuge, Python 3, die beiden
Developer-ID-Zertifikate und das bereits eingerichtete Notarisierungsprofil
`meshcentral-notary`. Als Vorlage dient standardmäßig
`~/Downloads/MeshAgent-Fernwartung-signed.pkg` mit der bestehenden Server- und
Gerätegruppenzuordnung.

Den Fork klonen:

```bash
git clone --branch zoomsoft/macos-fernwartung \
  https://github.com/UlrichThiess/MeshCentral.git \
  "$HOME/Downloads/MeshCentral-ZOOMsoft"
```

Aus dem Stammverzeichnis dieses Klons erstellen:

```bash
bash tools/zoomsoft-macos/Erstellen.command \
  --ausgabe "$HOME/Downloads/ZOOMsoft-Fernwartung-Ergebnis-Repository"
```

Für jeden neuen Build einen neuen Ausgabeordner wählen. Das Skript signiert
Agent-App, Pakete und Startprogramme, reicht sie bei Apple ein und heftet die
Notarisierungstickets an. Die Pakete sind in die beiden Startprogramme eingebettet.

Im Ergebnisordner entstehen:

| Datei oder Ordner | Verwendung |
| --- | --- |
| `Fernwartung-ZOOMsoft-GmbH.zip` | Kundendownload mit den beiden Apps |
| `Anleitung.txt` | Separate Anleitung für den Betreiber |
| `Server/` | Signierter Universal-Agent mit SHA-256-Prüfsumme |
| `Server-aktualisieren.command` | Serverabgleich über `ulrich.thiess@assist.zoomsoft.dmz` |

Vor dem ersten Installationstest den Server mit dem Skript aus dem Ergebnisordner
aktualisieren:

```bash
bash "$HOME/Downloads/ZOOMsoft-Fernwartung-Ergebnis-Repository/Server-aktualisieren.command"
```

Der Agent wird unter `/Applications/Fernwartung | ZOOMsoft GmbH.app` installiert.
Verbindungsdaten und Geräteidentität bleiben außerhalb der signierten App.
Die Freigaben für Bildschirmaufnahme und Bedienung werden auf dem Mac bestätigt.

Weitere Parameter und Details stehen in [LIESMICH.txt](LIESMICH.txt).
Der allgemeine Fix für macOS-Verzeichnisrechte und seine Regressionstests liegen
in `macosinstaller.js` und `test/macosinstaller.test.js` im Repository-Stamm.

## Quellen und Prüfung

`erstellen.py` baut die Pakete und das Kunden-ZIP. `assets/Startprogramm.m` enthält
die Oberfläche. Die Shellskripte unter `assets/` übernehmen Installation,
Dienstverwaltung und Deinstallation; `assets/ZOOMsoft.png` ist das Logo.

Die übernommenen Quellen werden auf Python- und Shellsyntax geprüft; für den
Verzeichnisrechte-Fix wird die vorhandene Node.js-Testsuite ausgeführt.
Kompilierung, Signierung, Notarisierung und der vollständige Funktionstest dieser
Repository-Fassung erfolgen auf dem Mac.
