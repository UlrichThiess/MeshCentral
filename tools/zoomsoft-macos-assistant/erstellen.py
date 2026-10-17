#!/usr/bin/env python3
"""Erstellt den separaten macOS-Assistant und eine signierte, notarisierte DMG."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PRODUCT = "Fernwartung | ZOOMsoft GmbH"
APP_NAME = PRODUCT + " Assistant.app"
BUNDLE_ID = "de.zoomsoft.fernwartung.assistant"
VOLUME = "ZOOMsoft Fernwartung"
VERSION = "1.0"
NETWORK_KEYS = {
    "MeshName", "MeshType", "MeshID", "ServerID", "MeshServer",
    "WebProxy", "autoproxy", "ignoreProxyFile",
}
spec = importlib.util.spec_from_file_location("zoomsoft_package_build", ROOT.parent / "zoomsoft-macos/erstellen.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def connection_settings(source):
    """Import connection/trust data only; service and update settings are excluded."""
    settings = {}
    for line in source.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in NETWORK_KEYS:
            continue
        if key in settings:
            raise ValueError("Mehrdeutige Verbindungseinstellung: " + key)
        settings[key] = value
    for key in ("MeshType", "MeshID", "ServerID", "MeshServer"):
        if not settings.get(key):
            raise ValueError("In der Vorlage fehlt die Verbindungseinstellung " + key + ".")
    if settings["MeshType"] != "2":
        raise ValueError("Die Vorlage muss zu einer MeshCentral-Agentengerätegruppe gehören (MeshType=2).")
    server = urlsplit(settings["MeshServer"])
    if server.scheme != "wss" or not server.hostname or server.username or server.password:
        raise ValueError("Die Vorlage benötigt eine vollständige, verschlüsselte MeshServer-Adresse (wss://…).")
    settings.update({"disableUpdate": "1", "controlChannelDebug": "1", "displayName": PRODUCT})
    return "".join(key + "=" + value + "\n" for key, value in settings.items())


def sources(args, working):
    if args.agent or args.konfiguration:
        if not args.agent or not args.konfiguration:
            raise ValueError("--agent und --konfiguration müssen zusammen angegeben werden.")
        return args.agent.resolve(strict=True), args.konfiguration.resolve(strict=True)
    source = args.vorlage.resolve(strict=True)
    expanded = working / "vorlage"
    shared.run("/usr/sbin/pkgutil", "--expand-full", source, expanded)
    agents = [p for p in expanded.rglob("meshagent") if p.is_file()]
    configurations = [p for p in expanded.rglob("meshagent.msh") if p.is_file()]
    if len(agents) != 1 or len(configurations) != 1:
        raise ValueError("Die Vorlage muss genau einen MeshAgent und eine meshagent.msh enthalten.")
    return agents[0], configurations[0]


def minimum_versions(agent):
    data = agent.read_bytes()
    for feature in (b"configUsesCWD", b"disableUpdate", b"controlChannelDebug"):
        if feature not in data:
            raise ValueError("Der Agent unterstützt eine benötigte Funktion nicht: " + feature.decode())
    minimums = {}
    for arch in ("x86_64", "arm64"):
        metadata = shared.run("/usr/bin/xcrun", "vtool", "-arch", arch, "-show-build", agent, capture=True)
        match = re.search(r"\bminos\s+([0-9.]+)", metadata)
        if not match:
            raise ValueError("Die macOS-Mindestversion für " + arch + " fehlt.")
        minimums[arch] = match.group(1)
    return minimums


def app_info(minimums):
    info = shared.app_info(BUNDLE_ID, "Fernwartung", minimums, display_name=PRODUCT + " Assistant")
    info.update({
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "LSMultipleInstancesProhibited": True,
        "NSSupportsAutomaticTermination": False,
        "NSSupportsSuddenTermination": False,
        "NSHumanReadableCopyright": "Copyright © 2026 ZOOMsoft GmbH. Apache-2.0.",
        "NSDesktopFolderUsageDescription": PRODUCT + " benötigt Zugriff auf Dateien für die angeforderte Fernwartung.",
        "NSDocumentsFolderUsageDescription": PRODUCT + " benötigt Zugriff auf Dateien für die angeforderte Fernwartung.",
        "NSDownloadsFolderUsageDescription": PRODUCT + " benötigt Zugriff auf Dateien für die angeforderte Fernwartung.",
    })
    return info


def sign_binary(binary, identity, identifier):
    shared.run("/usr/bin/codesign", "--force", "--options", "runtime", "--timestamp",
               "--identifier", identifier, "--sign", identity, binary)
    shared.run("/usr/bin/codesign", "--verify", "--strict", "--all-architectures", binary)


def as_string(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def finder_layout(mount):
    folder = as_string(mount)
    background = as_string(mount / ".background/Anleitung.png")
    name = as_string(APP_NAME)
    return f'''tell application "Finder"
    set imageFolder to (POSIX file {folder}) as alias
    open imageFolder
    set imageWindow to container window of imageFolder
    set current view of imageWindow to icon view
    set toolbar visible of imageWindow to false
    set statusbar visible of imageWindow to false
    set bounds of imageWindow to {{180, 140, 900, 604}}
    set viewOptions to icon view options of imageWindow
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 88
    set text size of viewOptions to 12
    set background picture of viewOptions to (POSIX file {background}) as alias
    set position of item {name} of imageFolder to {{180, 210}}
    set position of item "Programme" of imageFolder to {{540, 210}}
    update imageFolder without registering applications
    delay 1
    close imageWindow
end tell
'''


def make_dmg(app, working, output, identity):
    stage = working / "dmg-inhalt"
    stage.mkdir()
    shared.run("/usr/bin/ditto", app, stage / APP_NAME)
    (stage / "Programme").symlink_to("/Applications", target_is_directory=True)
    (stage / ".background").mkdir()
    renderer = working / "DMGHintergrund"
    shared.run("/usr/bin/xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa",
               "-Wall", "-Wextra", ROOT / "DMGHintergrund.m", "-o", renderer)
    shared.run(renderer, shared.ASSETS / "ZOOMsoft.png", stage / ".background/Anleitung.png")
    rw = working / "assistant-beschreibbar.dmg"
    shared.run("/usr/bin/hdiutil", "create", "-srcfolder", stage, "-volname", VOLUME,
               "-fs", "HFS+", "-format", "UDRW", rw)
    mount = working / "laufwerk"
    mount.mkdir()
    shared.run("/usr/bin/hdiutil", "attach", rw, "-readwrite", "-nobrowse", "-noautoopen",
               "-mountpoint", mount)
    try:
        subprocess.run(["/usr/bin/osascript", "-"], input=finder_layout(mount),
                       text=True, check=True, timeout=45)
    finally:
        shared.run("/usr/bin/hdiutil", "detach", mount)
    shared.run("/usr/bin/hdiutil", "convert", rw, "-format", "UDZO",
               "-imagekey", "zlib-level=9", "-o", output)
    shared.run("/usr/bin/codesign", "--force", "--timestamp", "--sign", identity,
               "--identifier", BUNDLE_ID + ".dmg", output)
    shared.run("/usr/bin/codesign", "--verify", "--strict", output)


def notarize_dmg(image, working, profile):
    raw = shared.run("/usr/bin/xcrun", "notarytool", "submit", image,
                     "--keychain-profile", profile, "--wait", "--output-format", "json", capture=True)
    shared.write(working / "apple-dmg.json", raw)
    status = json.loads(raw)
    if status.get("status") != "Accepted":
        if status.get("id"):
            shared.run("/usr/bin/xcrun", "notarytool", "log", status["id"],
                       "--keychain-profile", profile, working / "apple-dmg-fehler.json")
        raise ValueError("Apple hat die DMG nicht akzeptiert. Details: " + str(working))
    shared.run("/usr/bin/xcrun", "stapler", "staple", image)
    shared.run("/usr/bin/xcrun", "stapler", "validate", image)
    shared.run("/usr/sbin/spctl", "--assess", "--type", "open", "--context",
               "context:primary-signature", "--verbose=2", image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vorlage", type=Path, default=Path.home() / "Downloads/MeshAgent-Fernwartung-signed.pkg")
    parser.add_argument("--agent", type=Path, help="Alternativ: vorhandener Universal-Agent")
    parser.add_argument("--konfiguration", type=Path, help="Zugehörige meshagent.msh bei --agent")
    parser.add_argument("--ausgabe", type=Path, default=Path.home() / "Downloads/ZOOMsoft-Assistant-Ergebnis")
    parser.add_argument("--app-zertifikat", default=shared.APP_IDENTITY)
    parser.add_argument("--notarprofil", default="meshcentral-notary")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise ValueError("Der Assistant muss auf deinem Mac mit den Developer-ID-Zertifikaten erstellt werden.")
    args.ausgabe = args.ausgabe.expanduser().resolve()
    if args.ausgabe.exists():
        raise ValueError("Der Ausgabeordner existiert bereits. Bitte --ausgabe mit einem neuen Ordnernamen verwenden.")
    os.umask(0o022)
    for tool in ("clang", "notarytool", "vtool"):
        shared.run("/usr/bin/xcrun", "--find", tool, capture=True)
    working = Path(tempfile.mkdtemp(prefix="zoomsoft-assistant-", dir=str(Path.home() / "Downloads")))
    print("Arbeitsverzeichnis:", working, flush=True)
    agent, configuration = sources(args, working)
    settings = connection_settings(configuration.read_text(encoding="utf-8-sig"))
    minimums = minimum_versions(agent)
    print("Mindestversionen des Agenten:", minimums, flush=True)
    app = working / "app" / APP_NAME
    executable = app / "Contents/MacOS"
    resources = app / "Contents/Resources"
    executable.mkdir(parents=True)
    resources.mkdir()
    shutil.copy2(agent, executable / "meshagent")
    (executable / "meshagent").chmod(0o755)
    shared.write(resources / "meshagent.msh", settings)
    shutil.copy2(shared.icon(working), resources / "AppIcon.icns")
    shared.plist(app / "Contents/Info.plist", app_info(minimums))
    shared.write(resources / "de.lproj/InfoPlist.strings",
                 'CFBundleDisplayName = "' + PRODUCT + ' Assistant";\n')
    license_path = ROOT.parent.parent / "LICENSE"
    if license_path.is_file():
        shutil.copy2(license_path, resources / "LICENSE.txt")
    universal = ["/usr/bin/xcrun", "clang", "-arch", "x86_64", "-arch", "arm64",
                 "-mmacosx-version-min=15.0", "-O2", "-Wall", "-Wextra"]
    shared.run(*(universal + ["-std=c11", "-Werror", ROOT / "Sitzungswaechter.c",
                              "-o", executable / "Sitzungswaechter"]))
    shared.run(*(universal + ["-fobjc-arc", "-fblocks", "-framework", "Cocoa",
                              "-framework", "ApplicationServices", "-framework", "CoreGraphics",
                              ROOT / "Assistant.m", "-o", executable / "Fernwartung"]))
    sign_binary(executable / "meshagent", args.app_zertifikat, BUNDLE_ID + ".meshagent")
    sign_binary(executable / "Sitzungswaechter", args.app_zertifikat, BUNDLE_ID + ".sitzung")
    shared.sign_app(app, args.app_zertifikat)
    # Staple the copied app itself for offline launches after dragging out of the DMG.
    shared.notarize([app], working, args.notarprofil, "Assistant-App")
    image = working / "Fernwartung-ZOOMsoft-GmbH-Assistant.dmg"
    make_dmg(app, working, image, args.app_zertifikat)
    notarize_dmg(image, working, args.notarprofil)
    args.ausgabe.mkdir(parents=True)
    target = args.ausgabe / image.name
    shutil.copy2(image, target)
    shared.write(args.ausgabe / "SHA256.txt", hashlib.sha256(target.read_bytes()).hexdigest() + "  " + target.name + "\n")
    shared.write(args.ausgabe / "Erstellungsbericht.json", json.dumps({
        "produkt": PRODUCT, "bundle_id": BUNDLE_ID, "version": VERSION,
        "mindestversionen": minimums,
        "agent_quelle_sha256": hashlib.sha256(agent.read_bytes()).hexdigest(),
        "datenverzeichnis": "~/Library/Application Support/" + BUNDLE_ID,
        "agent_modus": "connect --configUsesCWD=1 --disableUpdate=1 --controlChannelDebug=1",
    }, ensure_ascii=False, indent=2) + "\n")
    print("\n" + PRODUCT + ": Assistant-DMG erstellt und notarisiert.", flush=True)
    print("Kundendownload:", target)
    print("Auf dem Test-Mac: in Programme ziehen, starten, Freigaben bestätigen und Fernzugriff testen.")
    print("Fenster schließen, ⌘Q und sofortiges Beenden müssen die Verbindung beenden.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("\nErstellung abgebrochen:", error, file=sys.stderr)
        sys.exit(1)
