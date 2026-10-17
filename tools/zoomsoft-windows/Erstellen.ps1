# Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
[CmdletBinding()]
param(
    [string]$Vorlage = (Join-Path $HOME 'Downloads\meshagent.exe'),
    [string]$Konfiguration,
    [string]$Ausgabe = (Join-Path $HOME 'Downloads\ZOOMsoft-Windows-Ergebnis-1.0'),
    [string]$ZertifikatThumbprint,
    [string]$ZeitstempelUrl = 'https://timestamp.digicert.com'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-ZoomsoftIcon([string]$Png, [string]$Target) {
    Add-Type -AssemblyName System.Drawing
    $original = [Drawing.Image]::FromFile($Png)
    $stream = [IO.File]::Create($Target)
    $writer = [IO.BinaryWriter]::new($stream)
    try {
        $images = @()
        foreach ($size in @(16, 32, 48, 256)) {
            $bitmap = [Drawing.Bitmap]::new($size, $size)
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            $memory = [IO.MemoryStream]::new()
            try {
                $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.DrawImage($original, 0, 0, $size, $size)
                $bitmap.Save($memory, [Drawing.Imaging.ImageFormat]::Png)
                $images += [pscustomobject]@{ Size = $size; Data = $memory.ToArray() }
            } finally { $graphics.Dispose(); $bitmap.Dispose(); $memory.Dispose() }
        }
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$images.Count)
        $offset = 6 + 16 * $images.Count
        foreach ($image in $images) {
            $dimension = if ($image.Size -eq 256) { 0 } else { $image.Size }
            $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
            $writer.Write([byte]0); $writer.Write([byte]0)
            $writer.Write([uint16]1); $writer.Write([uint16]32)
            $writer.Write([uint32]$image.Data.Length); $writer.Write([uint32]$offset)
            $offset += $image.Data.Length
        }
        foreach ($image in $images) { $writer.Write([byte[]]$image.Data) }
    } finally { $writer.Dispose(); $stream.Dispose(); $original.Dispose() }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Die Windows-App muss unter Windows erstellt werden.'
}
$source = $PSScriptRoot
$Vorlage = (Resolve-Path -LiteralPath $Vorlage).Path
$Ausgabe = [IO.Path]::GetFullPath($Ausgabe)
if (Test-Path -LiteralPath $Ausgabe) { throw 'Der Ausgabeordner existiert bereits. Bitte -Ausgabe mit einem neuen Ordnernamen angeben.' }
$compiler = Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Der C#-Compiler des .NET Frameworks fehlt. Benötigt wird .NET Framework 4.8.' }
if (-not ('ZOOMsoft.Fernwartung.Konfiguration' -as [type])) {
    Add-Type -TypeDefinition (Get-Content -LiteralPath (Join-Path $source 'Konfiguration.cs') -Raw -Encoding UTF8)
}
$engine = [IO.File]::ReadAllBytes($Vorlage)
$machine = [ZOOMsoft.Fernwartung.Konfiguration]::AgentPruefen($engine)
if ($Konfiguration) {
    $rawConfig = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $Konfiguration).Path, [Text.Encoding]::UTF8)
} else {
    $rawConfig = [ZOOMsoft.Fernwartung.Konfiguration]::EingebetteteEinstellungen($engine)
}
$settings = [ZOOMsoft.Fernwartung.Konfiguration]::Filtern($rawConfig)
$logo = Join-Path $source '..\zoomsoft-macos\assets\ZOOMsoft.png'
if (-not (Test-Path -LiteralPath $logo)) { throw 'Das ZOOMsoft-Logo fehlt. Bitte auch tools/zoomsoft-macos/assets aus dem Fork übernehmen.' }
$logo = (Resolve-Path -LiteralPath $logo).Path
$license = (Resolve-Path -LiteralPath (Join-Path $source '..\..\LICENSE')).Path
$working = Join-Path ([IO.Path]::GetTempPath()) ('zoomsoft-windows-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($working) | Out-Null
try {
    $enginePath = Join-Path $working 'meshagent.exe'
    $settingsPath = Join-Path $working 'meshagent.msh'
    $iconPath = Join-Path $working 'ZOOMsoft.ico'
    [IO.File]::WriteAllBytes($enginePath, $engine)
    [IO.File]::WriteAllText($settingsPath, $settings, [Text.UTF8Encoding]::new($false))
    New-ZoomsoftIcon $logo $iconPath
    $name = 'Ferwartung-ZOOMsoft-GmbH.exe'
    $program = Join-Path $working $name
    $arguments = @('/nologo', '/target:winexe', '/platform:anycpu', '/optimize+', '/warnaserror+', '/codepage:65001',
        "/out:`"$program`"", "/win32icon:`"$iconPath`"", "/win32manifest:`"$(Join-Path $source 'app.manifest')`"",
        '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll',
        "/resource:`"$enginePath`",meshagent.exe", "/resource:`"$settingsPath`",meshagent.msh", "/resource:`"$logo`",ZOOMsoft.png",
        "/resource:`"$license`",LICENSE.txt")
    foreach ($file in @('Konfiguration.cs', 'Verbindungsstatus.cs', 'Sitzung.cs', 'Fernwartung.cs')) {
        $arguments += '"' + (Join-Path $source $file) + '"'
    }
    $response = Join-Path $working 'erstellen.rsp'
    [IO.File]::WriteAllLines($response, $arguments, [Text.UTF8Encoding]::new($true))
    & $compiler ('@' + $response)
    if ($LASTEXITCODE -ne 0) { throw 'Die Windows-App konnte nicht kompiliert werden.' }
    if ($ZertifikatThumbprint) {
        $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $ZertifikatThumbprint)
        if (-not $certificate.HasPrivateKey) { throw 'Dem Signierzertifikat fehlt der private Schlüssel.' }
        $signature = Set-AuthenticodeSignature -LiteralPath $program -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer $ZeitstempelUrl
        if ($signature.Status -ne 'Valid') { throw ('Die Windows-Signierung ist fehlgeschlagen: ' + $signature.StatusMessage) }
    }
    [IO.Directory]::CreateDirectory($Ausgabe) | Out-Null
    Copy-Item -LiteralPath $program -Destination (Join-Path $Ausgabe $name)
    $hash = (Get-FileHash -LiteralPath (Join-Path $Ausgabe $name) -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $Ausgabe 'SHA256.txt'), "$hash  $name`r`n", [Text.UTF8Encoding]::new($false))
    [pscustomobject]@{
        produkt = [ZOOMsoft.Fernwartung.Konfiguration]::Produkt
        version = '1.0'
        agent_architektur = ('0x{0:X4}' -f $machine)
        agent_quelle_sha256 = [ZOOMsoft.Fernwartung.Konfiguration]::Hash($engine)
        modus = 'connect -nocertstore --configUsesCWD=1 --disableUpdate=1'
        signiert = [bool]$ZertifikatThumbprint
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Ausgabe 'Erstellungsbericht.json') -Encoding UTF8
    Write-Host "`nFerwartung | ZOOMsoft GmbH: Windows-App erstellt."
    Write-Host ('Kundendownload: ' + (Join-Path $Ausgabe $name))
    Write-Host 'EXE starten, Desktop testen und Fenster schließen: Verbindung und Geräteeintrag müssen enden.'
} finally {
    # Only this invocation's generated scratch files; never the source template.
    if (Test-Path -LiteralPath $working) { Remove-Item -LiteralPath $working -Recurse -Force }
}
