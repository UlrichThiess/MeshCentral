# Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
[CmdletBinding()]
param([string]$Ausgabe = (Join-Path ([IO.Path]::GetTempPath()) ('zoomsoft-windows-tests-' + [Guid]::NewGuid().ToString('N'))))
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Diese Integrationstests benötigen Windows.' }
$source = $PSScriptRoot
$compiler = Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
$Ausgabe = [IO.Path]::GetFullPath($Ausgabe)
[IO.Directory]::CreateDirectory($Ausgabe) | Out-Null

function Invoke-Compiler([string[]]$Arguments, [string]$Name) {
    $response = Join-Path $Ausgabe ($Name + '.rsp')
    [IO.File]::WriteAllLines($response, $Arguments, [Text.UTF8Encoding]::new($true))
    & $compiler ('@' + $response)
    if ($LASTEXITCODE -ne 0) { throw ('Kompilierung fehlgeschlagen: ' + $Name) }
}
$fixture = Join-Path $Ausgabe 'Test Agent.exe'
Invoke-Compiler @('/nologo', '/target:exe', '/platform:anycpu', '/warnaserror+', '/codepage:65001',
    "/out:`"$fixture`"", ('"' + (Join-Path $source 'tests\TestAgent.cs') + '"')) 'testagent'
$testProgram = Join-Path $Ausgabe 'Pruefungen.exe'
$logo = (Resolve-Path -LiteralPath (Join-Path $source '..\zoomsoft-macos\assets\ZOOMsoft.png')).Path
$arguments = @('/nologo', '/target:exe', '/main:Pruefungen', '/platform:anycpu', '/warnaserror+', '/codepage:65001',
    "/out:`"$testProgram`"", "/win32manifest:`"$(Join-Path $source 'app.manifest')`"", "/resource:`"$logo`",ZOOMsoft.png",
    '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll')
foreach ($file in @('Konfiguration.cs', 'Verbindungsstatus.cs', 'Sitzung.cs', 'Fernwartung.cs', 'tests\Pruefungen.cs')) {
    $arguments += '"' + (Join-Path $source $file) + '"'
}
Invoke-Compiler $arguments 'pruefungen'
& $testProgram $fixture $Ausgabe
if ($LASTEXITCODE -ne 0) { throw 'Die Windows-Prozessprüfungen sind fehlgeschlagen.' }

# Exercise the actual customer EXE builder with a synthetic PE/configuration.
# This fake template is only packaging input; it is never launched as an agent.
$template = Join-Path $Ausgabe 'Vorlage.faux'
& $testProgram --vorlage $template
if ($LASTEXITCODE -ne 0) { throw 'Die isolierte Testvorlage konnte nicht erstellt werden.' }
$built = Join-Path $Ausgabe 'Paket mit Leerzeichen ü'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $source 'Erstellen.ps1') -Vorlage $template -Ausgabe $built
if ($LASTEXITCODE -ne 0) { throw 'Die Paketierungsprüfung ist fehlgeschlagen.' }
$exe = Join-Path $built 'Ferwartung-ZOOMsoft-GmbH.exe'
$assembly = [Reflection.Assembly]::LoadFile($exe)
$resources = $assembly.GetManifestResourceNames()
foreach ($resource in @('meshagent.exe', 'meshagent.msh', 'ZOOMsoft.png', 'LICENSE.txt')) {
    if ($resources -notcontains $resource) { throw ('In der EXE fehlt ' + $resource) }
}
if ([Diagnostics.FileVersionInfo]::GetVersionInfo($exe).ProductName -ne 'Ferwartung | ZOOMsoft GmbH') {
    throw 'Der Windows-Produktname ist falsch.'
}
$actualHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not (Get-Content -LiteralPath (Join-Path $built 'SHA256.txt') -Raw).StartsWith($actualHash)) {
    throw 'Die Prüfsumme stimmt nicht.'
}
Write-Host 'OK: Einzel-EXE, Ressourcen, Produktname und Prüfsumme'
Write-Host ('Fenstervorschau: ' + (Join-Path $Ausgabe 'Fenstervorschau.png'))
