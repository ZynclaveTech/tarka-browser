# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Builds WinSparkle 0.9.4 (MIT), Tark's Windows updater (W2), for Windows x64
# into OUT: WinSparkle.dll, include\, COPYING (what windows/tark_post_patch.py
# installs). Built here rather than taken prebuilt because the release DLL
# links OpenSSL 1.0.2u (end of life since 2019) for the legacy DSA signature
# check. This build drops that path (winsparkle-patches\no-openssl.patch):
# updates must carry an EdDSA signature, and with no key set WinSparkle refuses
# them instead of installing them unsigned. The C runtime is linked statically
# (the project's Release setting).
#
#   windows\ci\build_winsparkle.ps1 -Out C:\winsparkle-out
#   windows\ci\build_winsparkle.ps1 -Out C:\winsparkle-out -CheckOnly

param([Parameter(Mandatory)][string]$Out, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$Version = '0.9.4'
# The release's source zip (submodules included), as GitHub lists its digest.
$Sha256 = 'CD77040F828DCE0ADCF8F0205F776238197DEB24F5108BF01A3E5623B703A3B9'

function Find-VsTool([string]$Pattern) {
  $vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -products * -latest -property installationPath
  $tool = Get-ChildItem "$vs\$Pattern" | Select-Object -First 1
  if (-not $tool) { throw "$Pattern not found" }
  $tool.FullName
}

if (-not $CheckOnly) {
  # git, nuget and MSBuild write progress to stderr, which Windows PowerShell
  # turns into errors when a job redirects it (*>>); their exit codes are checked.
  $ErrorActionPreference = 'Continue'
  $src = 'C:\winsparkle-src'
  if (Test-Path $src) { Remove-Item -Recurse -Force $src }
  $temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
  $zip = "$temp\WinSparkle-$Version-src.zip"
  Invoke-WebRequest -UseBasicParsing -OutFile $zip `
    -Uri "https://github.com/vslavik/winsparkle/releases/download/v$Version/WinSparkle-$Version-src.zip"
  if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $Sha256) { throw "WinSparkle-$Version-src.zip has the wrong SHA-256" }
  Expand-Archive $zip -DestinationPath $src -Force

  git -C $src apply --verbose -p1 "$PSScriptRoot\winsparkle-patches\no-openssl.patch"
  if ($LASTEXITCODE) { throw 'no-openssl.patch did not apply' }

  # The project file has CRLF endings (its .gitattributes): edit it here
  # rather than with a patch. Drop the libcrypto project and OpenSSL's headers.
  $proj = "$src\WinSparkle.vcxproj"
  $text = [IO.File]::ReadAllText($proj)
  $ref = '(?s)\s*<ProjectReference Include="3rdparty\\libcrypto\.vcxproj">.*?</ProjectReference>'
  if ($text -notmatch $ref) { throw 'libcrypto ProjectReference not found' }
  $text = $text -replace $ref, '' -replace '3rdparty\\openssl-win32;', ''
  [IO.File]::WriteAllText($proj, $text)

  # Gettext.Tools (the translations) and the WebView2 SDK (release notes),
  # at the versions packages.config pins.
  # GitHub's runners have nuget; Tark's build machine fetches it.
  $nuget = (Get-Command nuget -ErrorAction SilentlyContinue).Source
  if (-not $nuget) {
    $nuget = "$temp\nuget.exe"
    Invoke-WebRequest -UseBasicParsing -OutFile $nuget -Uri 'https://dist.nuget.org/win-x86-commandline/latest/nuget.exe'
  }
  & $nuget restore "$src\WinSparkle.sln" -PackagesDirectory "$src\packages" -NonInteractive
  if ($LASTEXITCODE) { throw 'nuget restore failed' }

  $msbuild = Find-VsTool 'MSBuild\Current\Bin\amd64\MSBuild.exe'
  & $msbuild $proj /m /nologo /v:minimal /p:Configuration=Release /p:Platform=x64
  if ($LASTEXITCODE) { throw 'WinSparkle build failed' }
  $ErrorActionPreference = 'Stop'

  New-Item -ItemType Directory -Force "$Out\include" | Out-Null
  Copy-Item "$src\x64\Release\WinSparkle.dll" $Out
  Copy-Item "$src\include\*.h" "$Out\include\"
  Copy-Item "$src\COPYING" $Out
  $Version | Out-File -Encoding ascii -NoNewline "$Out\VERSION"
}

# The DLL must load on any Windows 10 or 11 PC with no C runtime DLL, export
# what Tark calls, and hold no OpenSSL.
$dumpbin = Find-VsTool 'VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe'
$dll = "$Out\WinSparkle.dll"
$deps = (& $dumpbin /nologo /dependents $dll) -join "`n"
"WinSparkle.dll needs:`n$deps"
if ($deps -match '(?i)(msvcp\d+|vcruntime\d+|concrt\d+|ucrtbase|api-ms-win-crt-|libcrypto|libeay)') {
  throw "WinSparkle.dll needs $($Matches[0])"
}
$exports = (& $dumpbin /nologo /exports $dll) -join "`n"
foreach ($name in 'win_sparkle_init', 'win_sparkle_cleanup', 'win_sparkle_set_eddsa_public_key',
                  'win_sparkle_check_update_with_ui', 'win_sparkle_set_shutdown_request_callback') {
  if ($exports -notmatch "\b$name\b") { throw "WinSparkle.dll does not export $name" }
}
$bytes = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($dll))
# The release DLL holds these: OpenSSL's source paths (its assertions) and its
# PEM prompt.
foreach ($marker in '\openssl\crypto\', 'Enter PEM pass phrase:') {
  if ($bytes.Contains($marker)) { throw "WinSparkle.dll still holds OpenSSL ($marker)" }
}
if ((Get-Content "$Out\VERSION").Trim() -ne $Version) { throw "not WinSparkle $Version" }
"WinSparkle.dll: static C runtime, no OpenSSL, the API Tark calls exported"
