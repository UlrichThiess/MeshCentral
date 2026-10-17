#!/usr/bin/env python3
"""Erstellt die signierte und notarisierte Fernwartung für ZOOMsoft GmbH.

Benötigt macOS, Xcode, Python 3 sowie die bestehenden Developer-ID-Zertifikate.
Die Quelldatei mit den serverbezogenen Einstellungen wird ausschließlich lokal gelesen.
"""

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

PRODUCT = "Fernwartung | ZOOMsoft GmbH"
BUNDLE_ID = "de.zoomsoft.fernwartung"
VERSION = "1.1"
APP_PATH = "/Applications/" + PRODUCT + ".app"
DATA_DIR = "/usr/local/mesh_services/meshagent/meshagent"
SERVICE_LABEL = "meshagent"
GUI_LABEL = "meshagent-launchagent"
DAEMON_PLIST = "/Library/LaunchDaemons/meshagent.plist"
GUI_PLIST = "/Library/LaunchAgents/meshagent-launchagent.plist"
APP_IDENTITY = "Developer ID Application: msp informations technologie (2RAC2R2HDC)"
INSTALLER_IDENTITY = "Developer ID Installer: msp informations technologie (2RAC2R2HDC)"
ASSETS = Path(__file__).resolve().parent / "assets"


def run(*args, capture=False):
    result = subprocess.run([str(a) for a in args], check=True,
                            stdout=subprocess.PIPE if capture else None,
                            text=True)
    return result.stdout if capture else None


def write(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def plist(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(value, sort_keys=False))
    path.chmod(0o644)


def app_info(identifier, executable, minimums=None, display_name=PRODUCT):
    info = {
        "CFBundleIdentifier": identifier,
        "CFBundleName": display_name,
        "CFBundleDisplayName": display_name,
        "CFBundleSpokenName": display_name,
        "CFBundleExecutable": executable,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleIconFile": "AppIcon.icns",
        "CFBundleDevelopmentRegion": "de",
        "CFBundleLocalizations": ["de"],
        "NSHighResolutionCapable": True,
    }
    if minimums:
        info["LSMinimumSystemVersionByArchitecture"] = minimums
        info["LSMinimumSystemVersion"] = min(minimums.values(), key=version_tuple)
    return info


def version_tuple(value):
    return tuple(int(part) for part in value.split("."))


def service_plist(gui=False):
    info = {
        "Label": GUI_LABEL if gui else SERVICE_LABEL,
        "ProgramArguments": [APP_PATH + "/Contents/MacOS/meshagent",
                             "-kvmagent" if gui else "--configUsesCWD=1"],
        "WorkingDirectory": DATA_DIR,
        "AssociatedBundleIdentifiers": [BUNDLE_ID],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 3,
    }
    if gui:
        info["LimitLoadToSessionType"] = ["LoginWindow", "Aqua"]
    else:
        info["ProgramArguments"].append("--displayName=" + PRODUCT)
    return info


def render_script(name, minimums=None):
    values = {
        "PRODUCT_NAME": PRODUCT,
        "APP_PATH": APP_PATH,
        "BUNDLE_ID": BUNDLE_ID,
        "DATA_DIR": DATA_DIR,
        "SERVICE_LABEL": SERVICE_LABEL,
        "GUI_LABEL": GUI_LABEL,
        "DAEMON_PLIST": DAEMON_PLIST,
        "GUI_PLIST": GUI_PLIST,
        "MINIMUM_INTEL": (minimums or {}).get("x86_64", "15.0"),
        "MINIMUM_ARM": (minimums or {}).get("arm64", "26.0"),
    }
    header = "#!/bin/bash\nset -euo pipefail\n"
    header += "\n".join(key + "=" + shlex.quote(value) for key, value in values.items())
    return (header + "\n\n" + (ASSETS / "gemeinsam.sh").read_text(encoding="utf-8")
            + "\n" + (ASSETS / name).read_text(encoding="utf-8"))


def document(heading, paragraphs):
    return ("<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
            "<style>body{font:14px -apple-system,Helvetica,Arial;color:#333;margin:22px;}"
            "img{float:right;width:96px;height:96px;margin:0 0 12px 16px;}"
            "h1{font-size:21px;line-height:1.25;margin:0 0 16px;}"
            "h2{font-size:18px;}p{line-height:1.45;}</style></head><body>"
            '<img src="Logo.png" alt="ZOOMsoft GmbH">'
            + "<h1>" + html.escape(PRODUCT) + "</h1><h2>"
            + html.escape(heading) + "</h2>"
            + "".join("<p>" + html.escape(p) + "</p>" for p in paragraphs)
            + "</body></html>\n")


def distribution(root, operation, component_name, component_id):
    resources = root / (operation + "-ressourcen")
    resources.mkdir(parents=True, exist_ok=True)
    removing = operation == "deinstallation"
    welcome = document("Deinstallation" if removing else "Installation", [
        (PRODUCT + " wird für alle Benutzer dieses Macs entfernt. Dabei werden auch die lokalen Verbindungsdaten gelöscht.")
        if removing else (PRODUCT + " wird für alle Benutzer dieses Macs installiert."),
        "Für diesen Vorgang werden Administratorrechte benötigt.",
    ])
    conclusion = document("Deinstallation abgeschlossen" if removing else "Installation abgeschlossen", [
        (PRODUCT + " wurde für alle Benutzer dieses Macs entfernt.") if removing
        else (PRODUCT + " wurde für alle Benutzer dieses Macs installiert."),
        "" if removing else ("Erlauben Sie für " + PRODUCT
            + " unter Systemeinstellungen → Datenschutz & Sicherheit die Bildschirmaufnahme und Bedienung."),
    ])
    # Deutsche Ressourcen auch als Standard verwenden, falls macOS eine andere Sprache auswählt.
    for subdir in (resources, resources / "de.lproj"):
        write(subdir / "Willkommen.html", welcome)
        write(subdir / "Abschluss.html", conclusion)
    xml = ET.Element("installer-gui-script", {"minSpecVersion": "2"})
    ET.SubElement(xml, "title").text = PRODUCT
    ET.SubElement(xml, "options", {"customize": "never", "require-scripts": "false",
                                  "hostArchitectures": "arm64,x86_64"})
    ET.SubElement(xml, "domains", {"enable_anywhere": "false", "enable_currentUserHome": "false",
                                  "enable_localSystem": "true"})
    ET.SubElement(xml, "welcome", {"file": "Willkommen.html", "mime-type": "text/html"})
    ET.SubElement(xml, "conclusion", {"file": "Abschluss.html", "mime-type": "text/html"})
    outline = ET.SubElement(xml, "choices-outline")
    ET.SubElement(outline, "line", {"choice": "fernwartung"})
    choice = ET.SubElement(xml, "choice", {"id": "fernwartung", "title": PRODUCT, "visible": "false"})
    ET.SubElement(choice, "pkg-ref", {"id": component_id})
    ET.SubElement(xml, "pkg-ref", {"id": component_id, "version": VERSION, "auth": "Root"}).text = "#" + component_name
    result = root / (operation + ".xml")
    ET.ElementTree(xml).write(result, encoding="utf-8", xml_declaration=True)
    return result, resources


def icon(working):
    iconset = working / "ZOOMsoft.iconset"
    iconset.mkdir()
    for points in (16, 32, 128, 256, 512):
        for density in (1, 2):
            size = points * density
            suffix = "@2x" if density == 2 else ""
            run("/usr/bin/sips", "-z", size, size, ASSETS / "ZOOMsoft.png", "--out",
                iconset / ("icon_{}x{}{}.png".format(points, points, suffix)))
    target = working / "AppIcon.icns"
    run("/usr/bin/iconutil", "--convert", "icns", "--output", target, iconset)
    return target


def sign_app(path, identity):
    run("/usr/bin/codesign", "--force", "--options", "runtime", "--timestamp", "--sign", identity, path)
    run("/usr/bin/codesign", "--verify", "--strict", "--all-architectures", "--verbose=2", path)


def notarize(paths, working, profile, name):
    stage = working / ("apple-" + name)
    stage.mkdir()
    for path in paths:
        run("/usr/bin/ditto", path, stage / path.name)
    archive = working / ("apple-" + name + ".zip")
    run("/usr/bin/ditto", "-c", "-k", stage, archive)
    print("Apple prüft {}. Bitte warten …".format(name), flush=True)
    raw = run("/usr/bin/xcrun", "notarytool", "submit", archive,
              "--keychain-profile", profile, "--wait", "--output-format", "json", capture=True)
    write(working / ("apple-" + name + ".json"), raw)
    status = json.loads(raw)
    if status.get("status") != "Accepted":
        if status.get("id"):
            run("/usr/bin/xcrun", "notarytool", "log", status["id"],
                "--keychain-profile", profile, working / ("apple-" + name + "-fehler.json"))
        raise RuntimeError("Apple hat {} nicht akzeptiert. Details stehen im Arbeitsverzeichnis {}.".format(name, working))
    for path in paths:
        run("/usr/bin/xcrun", "stapler", "staple", path)
        run("/usr/bin/xcrun", "stapler", "validate", path)
        run("/usr/sbin/spctl", "--assess", "--type", "execute" if path.is_dir() else "install",
            "--verbose=2", path)


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vorlage", type=Path, default=Path.home() / "Downloads/MeshAgent-Fernwartung-signed.pkg")
    parser.add_argument("--ausgabe", type=Path, default=Path.home() / "Downloads/ZOOMsoft-Fernwartung-Ergebnis")
    parser.add_argument("--notarprofil", default="meshcentral-notary")
    parser.add_argument("--app-zertifikat", default=APP_IDENTITY)
    parser.add_argument("--paket-zertifikat", default=INSTALLER_IDENTITY)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Dieses Skript muss auf dem Mac mit den Developer-ID-Zertifikaten ausgeführt werden.")
    if not args.vorlage.is_file():
        raise RuntimeError("Die Paketvorlage fehlt: " + str(args.vorlage))
    if args.ausgabe.exists():
        raise RuntimeError("Der Ausgabeordner existiert bereits. Verwenden Sie --ausgabe mit einem neuen Ordnernamen: " + str(args.ausgabe))
    run("/usr/bin/xcrun", "--find", "clang", capture=True)
    run("/usr/bin/xcrun", "--find", "notarytool", capture=True)
    working = Path(tempfile.mkdtemp(prefix="zoomsoft-fernwartung-", dir=str(Path.home() / "Downloads")))
    print("Arbeitsverzeichnis:", working, flush=True)
    expanded = working / "vorlage"
    run("/usr/sbin/pkgutil", "--expand-full", args.vorlage.resolve(), expanded)
    candidates = [p for p in expanded.rglob("meshagent")
                  if p.is_file() and p.with_name("meshagent.msh").is_file()]
    if len(candidates) != 1:
        raise RuntimeError("Die Vorlage muss genau einen Agenten mit zugehöriger Konfigurationsdatei enthalten.")
    source_agent = candidates[0]
    if b"configUsesCWD" not in source_agent.read_bytes():
        raise RuntimeError("Dieser Agent unterstützt die benötigte Trennung von App und Verbindungsdaten nicht.")
    minimums = {}
    for arch in ("x86_64", "arm64"):
        metadata = run("/usr/bin/xcrun", "vtool", "-arch", arch, "-show-build", source_agent, capture=True)
        match = re.search(r"\bminos\s+([0-9.]+)", metadata)
        if not match:
            raise RuntimeError("Die macOS-Mindestversion für {} konnte nicht ermittelt werden.".format(arch))
        minimums[arch] = match.group(1)
    print("Mindestversionen des vorhandenen Agenten:", minimums, flush=True)

    payload = working / "payload"
    app = payload / APP_PATH.lstrip("/")
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True)
    (app / "Contents/MacOS").mkdir()
    shutil.copy2(source_agent, app / "Contents/MacOS/meshagent")
    (app / "Contents/MacOS/meshagent").chmod(0o755)
    app_icon = icon(working)
    shutil.copy2(app_icon, resources / "AppIcon.icns")
    (resources / "AppIcon.icns").chmod(0o644)
    info = app_info(BUNDLE_ID, "meshagent", minimums)
    info["LSUIElement"] = True
    for key, location in (("NSDesktopFolderUsageDescription", "Schreibtisch"),
                          ("NSDocumentsFolderUsageDescription", "Dokumente"),
                          ("NSDownloadsFolderUsageDescription", "Downloads")):
        info[key] = PRODUCT + " benötigt für die angeforderte Fernwartung Zugriff auf " + location + "."
    plist(app / "Contents/Info.plist", info)
    write(resources / "de.lproj/InfoPlist.strings",
          'CFBundleName = "' + PRODUCT + '";\nCFBundleDisplayName = "' + PRODUCT + '";\n')
    sign_app(app, args.app_zertifikat)

    data = payload / DATA_DIR.lstrip("/")
    data.mkdir(parents=True)
    msh_text = source_agent.with_name("meshagent.msh").read_text(encoding="utf-8-sig")
    # Nur den sichtbaren Namen ändern, die Server- und Gruppenzuordnung vollständig erhalten.
    msh_lines = [line for line in msh_text.splitlines()
                 if line.partition("=")[0].strip().lower() != "displayname"]
    write(data / "meshagent.msh", "\n".join(msh_lines) + "\ndisplayName=" + PRODUCT + "\n")
    plist(payload / DAEMON_PLIST.lstrip("/"), service_plist())
    plist(payload / GUI_PLIST.lstrip("/"), service_plist(gui=True))
    install_scripts = working / "installation-skripte"
    write(install_scripts / "preinstall", render_script("vorbereiten.sh", minimums), 0o755)
    write(install_scripts / "postinstall", render_script("installieren.sh", minimums), 0o755)
    uninstall_scripts = working / "deinstallation-skripte"
    write(uninstall_scripts / "postinstall", render_script("deinstallieren.sh"), 0o755)
    for folder, dirs, files in os.walk(payload):
        Path(folder).chmod(0o755)

    components = working / "komponenten.plist"
    run("/usr/bin/pkgbuild", "--analyze", "--root", payload, components)
    values = plistlib.loads(components.read_bytes())
    for value in values:
        value["BundleIsRelocatable"] = False
        value["BundleIsVersionChecked"] = False
    plist(components, values)
    packages = working / "pakete"
    packages.mkdir()
    final_pkgs = []
    for operation, script_dir in (("installation", install_scripts), ("deinstallation", uninstall_scripts)):
        component_id = BUNDLE_ID + "." + operation + ".pkg"
        component = operation + ".pkg"
        build = ["/usr/bin/pkgbuild", "--identifier", component_id, "--version", VERSION,
                 "--install-location", "/", "--scripts", script_dir]
        if operation == "installation":
            build += ["--root", payload, "--component-plist", components, "--ownership", "recommended"]
        else:
            build += ["--nopayload"]
        run(*(build + ["--sign", args.paket_zertifikat, "--timestamp", working / component]))
        dist, res = distribution(working, operation, component, component_id)
        run("/usr/bin/sips", "-z", "192", "192", ASSETS / "ZOOMsoft.png", "--out", res / "Logo.png")
        shutil.copy2(res / "Logo.png", res / "de.lproj/Logo.png")
        target = packages / ("Installieren.pkg" if operation == "installation" else "Deinstallieren.pkg")
        run("/usr/bin/productbuild", "--distribution", dist, "--resources", res,
            "--package-path", working, "--sign", args.paket_zertifikat, "--timestamp", target)
        final_pkgs.append(target)
    notarize(final_pkgs, working, args.notarprofil, "Pakete")

    executable = working / "Startprogramm"
    run("/usr/bin/xcrun", "clang", "-arch", "x86_64", "-arch", "arm64", "-mmacosx-version-min=15.0",
        "-fobjc-arc", "-fblocks", "-framework", "Cocoa", "-Wall", "-Wextra",
        ASSETS / "Startprogramm.m", "-o", executable)
    delivery = working / "download"
    delivery.mkdir()
    launchers = []
    for operation, package in zip(("installation", "deinstallation"), final_pkgs):
        app_name = PRODUCT + (" Installation" if operation == "installation" else " Deinstallation")
        launcher = delivery / (app_name + ".app")
        (launcher / "Contents/MacOS").mkdir(parents=True)
        (launcher / "Contents/Resources").mkdir()
        launcher_info = app_info(BUNDLE_ID + "." + operation, "Startprogramm",
                                 {"x86_64": "15.0", "arm64": "15.0"}, display_name=app_name)
        launcher_info["ZOOMsoftVorgang"] = operation
        launcher_info["ZOOMsoftMindestversionen"] = minimums
        plist(launcher / "Contents/Info.plist", launcher_info)
        shutil.copy2(executable, launcher / "Contents/MacOS/Startprogramm")
        (launcher / "Contents/MacOS/Startprogramm").chmod(0o755)
        shutil.copy2(package, launcher / "Contents/Resources/Vorgang.pkg")
        shutil.copy2(app_icon, launcher / "Contents/Resources/AppIcon.icns")
        (launcher / "Contents/Resources/Vorgang.pkg").chmod(0o644)
        (launcher / "Contents/Resources/AppIcon.icns").chmod(0o644)
        sign_app(launcher, args.app_zertifikat)
        launchers.append(launcher)
    notarize(launchers, working, args.notarprofil, "Startprogramme")

    args.ausgabe.mkdir(parents=True)
    write(args.ausgabe / "Anleitung.txt", PRODUCT + "\n\n"
          "Installation: Öffnen Sie „" + PRODUCT + " Installation.app“.\n"
          "Deinstallation: Öffnen Sie „" + PRODUCT + " Deinstallation.app“.\n\n"
          "Die Anwendung führt Sie mit deutschen Dialogen durch den gewählten Vorgang.\n"
          "Beide Vorgänge gelten für alle Benutzer dieses Macs und fordern Administratorrechte an.\n"
          "Bitte bestätigen Sie die Administratorabfrage von macOS.\n"
          "Das Kunden-ZIP enthält ausschließlich diese beiden Apps.\n"
          "Die benötigten signierten und notarisierten PKG-Dateien sind in den Apps eingebettet.\n\n"
          "Erlauben Sie unter Systemeinstellungen → Datenschutz & Sicherheit für " + PRODUCT
          + " die Bildschirmaufnahme und Bedienung. Diese Freigaben müssen Sie selbst bestätigen.\n\n"
          "Mindestversion: Intel macOS " + minimums["x86_64"] + "; Apple Silicon macOS " + minimums["arm64"] + ".\n")
    output_zip = args.ausgabe / "Fernwartung-ZOOMsoft-GmbH.zip"
    run("/usr/bin/ditto", "-c", "-k", delivery, output_zip)
    server = args.ausgabe / "Server"
    server.mkdir()
    raw_agent = server / "meshagent_osx-universal-64"
    shutil.copy2(app / "Contents/MacOS/meshagent", raw_agent)
    write(server / "SHA256.txt", hashlib.sha256(raw_agent.read_bytes()).hexdigest() + "  meshagent_osx-universal-64\n")
    shutil.copy2(Path(__file__).resolve().parent / "Server-aktualisieren.command", args.ausgabe / "Server-aktualisieren.command")
    (args.ausgabe / "Server-aktualisieren.command").chmod(0o755)
    print("\n" + PRODUCT + ": Erstellung abgeschlossen.", flush=True)
    print("Download:", output_zip)
    print("Vor der Installation den Server mit der beiliegenden Server-aktualisieren.command aktualisieren.")
    print("Danach die Namensanzeige, Freigaben, Fernsteuerung und Deinstallation auf einem Test-Mac prüfen.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as error:
        print("\nErstellung abgebrochen:", error, file=sys.stderr)
        sys.exit(1)
