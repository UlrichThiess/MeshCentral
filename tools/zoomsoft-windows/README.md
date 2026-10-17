# Ferwartung | ZOOMsoft GmbH – Windows

Eine einzelne Windows-EXE mit dem Logo, Fenstertitel, Verbindungshinweis,
Rechnernamen und den beiden unteren Schaltflächen der macOS-App.

Öffnen startet die Fernwartung, Minimieren lässt sie weiterlaufen. Fenster
schließen, Alt+F4, Escape oder **Fernwartung beenden** beendet die Verbindung.
Der Agent startet mit `connect` als temporäres Gerät. MeshCentral löscht den
Geräteeintrag beim Verbindungsende. Es gibt keinen Hintergrunddienst, Autostart,
Installer oder Sitzungsprotokoll.

Windows besitzt für diesen Agenten keine macOS-Freigabedialoge. Die entsprechenden
Zeilen zeigen den verfügbaren Desktop und die Benutzer- bzw. Administratorrechte.
Für die Bedienung erhöhter Fenster und von Administratordialogen muss die App mit
passenden Administratorrechten gestartet werden; der normale Start fordert sie
nicht automatisch an. Der Zugriff auf den sicheren Desktop muss im realen Test
mit dem verwendeten Agenten und den Windows-Richtlinien geprüft werden.

## EXE auf Windows erstellen

Benötigt werden Windows 10 ab Version 1809 oder Windows 11 mit .NET Framework 4.8.
Der Builder verwendet dessen vorhandenen C#-Compiler, ohne Visual Studio, .NET SDK
oder zusätzliche NuGet-Pakete. Kundenseitig genügt diese Windows-Laufzeit ebenfalls.

1. In MeshCentral bei der gewünschten Gerätegruppe einen **nativen Windows-Agenten**
   herunterladen, z. B. Windows x64. Nicht `MeshCentralAssistant.exe` verwenden.
2. Den Fork auf Branch `zoomsoft/macos-fernwartung` unter Windows öffnen bzw.
   aktualisieren. Die Quelldateien in `tools/zoomsoft-windows` und das bestehende
   Logo in `tools/zoomsoft-macos/assets` müssen vorhanden sein.
3. In PowerShell aus dem Repository-Stamm ausführen:

```powershell
git pull --ff-only
.\tools\zoomsoft-windows\Erstellen.cmd `
  -Vorlage "$HOME\Downloads\meshagent.exe"
```

Den Vorlagennamen an den tatsächlichen Download anpassen. Server und Gerätegruppe
werden aus seiner eingebetteten Konfiguration gelesen. Die Originalvorlage und
die darin vorhandene Agentensignatur bleiben unverändert.

Falls der Fork bisher nur auf dem Mac liegt, unter Windows einmalig platzsparend
klonen:

```powershell
git clone --depth 1 --filter=blob:none --sparse --branch zoomsoft/macos-fernwartung `
  https://github.com/UlrichThiess/MeshCentral.git "$HOME\Downloads\MeshCentral-ZOOMsoft"
cd "$HOME\Downloads\MeshCentral-ZOOMsoft"
git sparse-checkout set tools/zoomsoft-windows tools/zoomsoft-macos/assets
```

Alternativ lässt sich eine separate `.msh` übergeben:

```powershell
.\tools\zoomsoft-windows\Erstellen.cmd `
  -Vorlage "C:\Pfad\MeshService64.exe" `
  -Konfiguration "C:\Pfad\meshagent.msh" `
  -Ausgabe "$HOME\Downloads\ZOOMsoft-Windows-Ergebnis-2"
```

Ergebnis:

```text
~/Downloads/ZOOMsoft-Windows-Ergebnis-1.0/Ferwartung-ZOOMsoft-GmbH.exe
```

Der Kunde erhält nur diese EXE. Das Zeichen `|` steht im Fenstertitel; in einem
Windows-Dateinamen ist es nicht erlaubt. Für einen weiteren Build einen neuen
Ausgabeordner angeben. Prüfsumme und Erstellungsbericht dienen der Build-Prüfung.
Der Apache-Lizenztext ist als Ressource in der EXE enthalten.

Für eine Authenticode-Signatur optional `-ZertifikatThumbprint "…"` hinzufügen.
Das zugehörige Windows-Codesignaturzertifikat mit privatem Schlüssel muss im
Zertifikatspeicher des aktuellen Benutzers liegen. Ohne diesen Parameter erzeugt
der Builder eine unsignierte EXE; das Apple-Developer-ID-Zertifikat kann sie nicht
als Windows-Anwendung signieren.

## Sitzung und Daten

Der Agent läuft mit dem Benutzerkonto und den Rechten der sichtbaren App. Ein
Windows-Jobobjekt besitzt alle zugehörigen Prozesse und beendet sie auch beim
Absturz oder beim Beenden der App über den Task-Manager. Die Zuordnung erfolgt
direkt bei der Prozesserzeugung. Fremde Agenten und Dienste werden nicht beendet.

Der Agent besitzt eine eigene, dateibasierte Geräteidentität (`-nocertstore`).
Sie wird nicht aus dem Windows-Zertifikatspeicher eines vorhandenen dauerhaften
Agenten übernommen. Verbindung und Agentdaten liegen in einem geschützten
Benutzerverzeichnis unter
`%LOCALAPPDATA%\ZOOMsoft\Fernwartung-Windows\<Server-und-Gruppenkennung>\`.
Der native Agent kann dort Datenbanken und bei Fehlern eigene Diagnosedaten
anlegen; die Oberfläche zeichnet kein Sitzungsprotokoll auf.

Es wird kein Dienst registriert. Der native Agent kann seine üblichen
Statuswerte unter `HKCU\Software\Open Source\ZOOMsoftFernwartung` hinterlegen.
Für das vollständige Entfernen reichen das Löschen der EXE, des genannten
Benutzerverzeichnisses und bei Bedarf dieses eigenen Statusschlüssels.

## Prüfungen

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\zoomsoft-windows\Pruefen.ps1
```

Die Windows-Prüfungen verwenden echte isolierte Testprozesse, keine
Serververbindung. Sie prüfen zeitnahe Statusausgaben ohne Zeilenende, Terminalcodes,
Serverbindung, separate Daten je Server/Gruppe, Prozessgruppenende bei regulärem
Schließen und Task-Manager-Ende, ignoriertes Stoppsignal, Agent-Absturz und
fehlgeschlagenen Prozessstart. Außerdem wird das Fenster in eine PNG gerendert
und der tatsächliche EXE-Builder mit einer synthetischen Vorlage ausgeführt.

Der echte MeshCentral-Disconnect-Handler lässt sich ohne Windows prüfen:

```bash
node --test tools/zoomsoft-windows/test_temporarer_agent.js
```

Die GitHub-Actions-Prüfung führt beides aus. Die erste Funktionsprüfung mit deinem
realen Agenten unter Windows bleibt erforderlich: Desktop, Maus und Tastatur,
Wiederverbindung nach Netzunterbrechung sowie das Verschwinden des Geräts nach
Fensterschließen, Alt+F4 und Task-Manager-Ende. Ein separat installierter dauerhafter
Agent ist eine eigenständige Verbindung und muss dabei unterschieden werden.

Quellen:

- [Windows-Agent und temporärer Modus](https://github.com/Ylianst/MeshAgent/blob/26846b1c7f0841d71938f6bebc96eef5a947d217/meshservice/ServiceMain.c)
- [Windows-Jobobjekte](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Prozesszuordnung bei der Erzeugung](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Windows-Pseudokonsole](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)
