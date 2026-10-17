# Fernwartung | ZOOMsoft GmbH – macOS-Assistant

Dieser separate native macOS-Client verwendet den temporären `connect`-Modus des
MeshAgent. Beim Öffnen der App beginnt die Verbindung zum MeshCentral-Server aus
der Paketvorlage. Die Verbindung bleibt während der App-Laufzeit bestehen und
wird nach Netzunterbrechungen vom Agenten erneut aufgebaut.

Fenster schließen, „Fernwartung beenden“ oder ⌘Q beendet die Sitzung. Minimieren
oder ein Wechsel zu einer anderen App lässt sie weiterlaufen. Ein eigener
Sitzungswächter stoppt den Agenten und seine Prozessgruppe auch dann, wenn der
App-Prozess abstürzt oder sofort beendet wird.

Der Kunde erhält eine DMG mit:

- **Fernwartung | ZOOMsoft GmbH Assistant.app**
- einer Verknüpfung zu **Programme**
- einem deutschen Hintergrund: **Ziehen Sie die App in „Programme“.**

Nach dem Kopieren startet der Kunde die App aus „Programme“. Für den Betrieb
werden keine PKGs, Startdienste, Anmeldeobjekte oder Deinstallationsprogramme
eingerichtet. Die App arbeitet mit den Rechten des angemeldeten Benutzers.

## Erstellen

Im bereits geklonten Fork den Branch aktualisieren:

```bash
git switch zoomsoft/macos-fernwartung
git pull --ff-only
```

Aus dem Repository-Stamm auf dem Mac ausführen:

```bash
bash tools/zoomsoft-macos-assistant/Erstellen.command \
  --ausgabe "$HOME/Downloads/ZOOMsoft-Assistant-Ergebnis"
```

Bei einem weiteren Build einen neuen Ausgabeordner angeben. Standardvorlage ist
die bereits vorhandene Datei `~/Downloads/MeshAgent-Fernwartung-signed.pkg`.
Sie wird ausschließlich zum Auslesen des Universal-Agenten und der Verbindung
zu deinem Server und deiner Gerätegruppe verwendet.

Alternativ können Agent und Konfiguration direkt angegeben werden:

```bash
bash tools/zoomsoft-macos-assistant/Erstellen.command \
  --agent "/Pfad/zum/meshagent" \
  --konfiguration "/Pfad/zur/meshagent.msh" \
  --ausgabe "$HOME/Downloads/ZOOMsoft-Assistant-Ergebnis-2"
```

Benötigt werden macOS mit angemeldeter Finder-Sitzung, Xcode-Werkzeuge, Python 3,
dein vorhandenes **Developer ID Application**-Zertifikat und das funktionierende
Notarisierungsprofil **meshcentral-notary**. Beim Einrichten der DMG-Ansicht kann
macOS die Erlaubnis zum Steuern des Finders abfragen.

Das Skript kompiliert App und Sitzungswächter für Intel und Apple Silicon, übernimmt
das Logo aus dem benachbarten Verzeichnis `zoomsoft-macos`, signiert alle
ausführbaren Dateien und notarisiert App und DMG. Auch die kopierte App enthält
ein angeheftetes Notarisierungsticket für den Offline-Start.

Ergebnis:

```text
~/Downloads/ZOOMsoft-Assistant-Ergebnis/Fernwartung-ZOOMsoft-GmbH-Assistant.dmg
```

Zusätzlich entstehen eine SHA-256-Prüfsumme und ein Erstellungsbericht. Die
macOS-Mindestversion je Architektur wird aus dem verwendeten Agenten übernommen;
bei der bisherigen Vorlage sind dies Intel macOS 15 und Apple Silicon macOS 26.

Ein Abgleich über `Server-aktualisieren.command` ist für diesen Client nicht
erforderlich: Er startet als temporärer Agent mit deaktiviertem Austausch seiner
ausführbaren Datei. Das JavaScript-Modul für Fernsteuerung kommt weiterhin von
deinem MeshCentral-Server.

## Freigaben und Daten

Die App zeigt die Freigaben für **Bildschirmaufnahme** und **Bedienung** an und
öffnet auf Knopfdruck die passenden macOS-Einstellungen. macOS kann nach einer
neuen Bildschirmfreigabe einen Neustart der App verlangen. Diese Freigaben
müssen die jeweiligen Benutzer selbst bestätigen. Apple-eigene Dialoge folgen
der Systemsprache; die eigene Oberfläche ist Deutsch.

Verbindungseinstellungen und Agentdaten liegen getrennt von der signierten App
unter `~/Library/Application Support/de.zoomsoft.fernwartung.assistant/`. Sie
enthalten die eigene Geräteidentität dieses Clients und ermöglichen erneute
Verbindungen. Bei geschlossener App läuft dort kein Dienst. Zum vollständigen
Entfernen können die App und dieses persönliche Datenverzeichnis gelöscht werden.

Der temporäre Client hat eine eigene Bundle-ID und eine eigene Geräteidentität.
Ein bisher dauerhaft installierter Agent ist eine separate Verbindung; für den
Abschalttest muss dieser unabhängig beendet sein.

## Quellen und Prüfstand

| Datei | Aufgabe |
| --- | --- |
| `Assistant.m` | Native Oberfläche, Freigaben und App-Lebenszyklus |
| `Sitzungswaechter.c` | Start des Agenten, Elternüberwachung und Aufräumen der Sitzung |
| `DMGHintergrund.m` | Deutscher DMG-Hintergrund mit Logo und Pfeil |
| `erstellen.py` | Konfiguration, Universal-Build, Signatur, DMG-Ansicht und Notarisierung |
| `test_assistant.py` | Prozess- und Konfigurationstests ohne Netzwerk oder Installation |

Die Prozessprüfungen starten echte isolierte Testprogramme. Sie prüfen das Ende
von Agent und Kindprozess bei geschlossenem Steuerkanal, abgebrochenem Elternprozess,
beendetem Wächter und unerwartetem Agent-Ende. Auch ein Agent, der das reguläre
Stoppsignal ignoriert, wird beendet. Eine zweite Instanz übernimmt keine aktive
Sitzung; fremde Prozesse bleiben aktiv. Update- und Dienstparameter aus der
Vorlage werden nicht in die portable Konfiguration übernommen.

Auf Linux ausführbar:

```bash
python3 tools/zoomsoft-macos-assistant/test_assistant.py
```

**Noch auf dem Mac erforderlich:** Kompilierung der Cocoa-Oberfläche, Finder-Ansicht,
Apple-Signierung und Notarisierung sowie der vollständige Funktionstest mit dem
realen Agenten. Die Linux-Prüfungen bestätigen diese macOS-Funktionen nicht.

Vor dem Kundeneinsatz auf einem Test-Mac prüfen:

1. DMG öffnen: Logo, Anleitung und beide Symbole prüfen; App nach Programme ziehen.
2. App öffnen: auf dem Server muss der temporäre Client erscheinen.
3. Bildschirmaufnahme und Bedienung erlauben, gegebenenfalls App neu starten.
4. Bildschirm, Maus und Tastatur sowie Wiederverbindung nach Netzunterbrechung testen.
5. Fenster schließen: Sitzung und Serververbindung müssen enden.
6. Mit ⌘Q und „Sofort beenden“ wiederholen; anschließend darf kein Prozess dieser Sitzung laufen.
7. App erneut öffnen und nach einem Mac-Neustart prüfen: Verbindung entsteht erst beim Öffnen.

## Technische Grundlagen

- [MeshAgent-Konsole und temporärer Modus](https://github.com/Ylianst/MeshAgent/blob/26846b1c7f0841d71938f6bebc96eef5a947d217/meshconsole/main.c)
- [Konfiguration, Update-Sperre und Verbindungsstatus](https://github.com/Ylianst/MeshAgent/blob/26846b1c7f0841d71938f6bebc96eef5a947d217/meshcore/agentcore.c)
- [Apples Paketierung von Mac-Software](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)
- [Apples Notarisierungsablauf](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
