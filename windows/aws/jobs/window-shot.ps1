# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1: screenshot Tark's real window in the `tarkdesk` desktop session
# (jobs/desktop-setup.ps1). Runs Tark from the last build's zip with a
# scratch profile, opens a few pages, and captures the whole screen.
#
# Folders: everything SYSTEM installs or runs (the app, the inner script) is
# in a folder only SYSTEM and Administrators can write; tarkdesk may read
# and run it. tarkdesk writes only to out\ (profile, screenshots), which
# SYSTEM never deletes recursively or re-permissions: it is removed with
# rmdir (which does not follow junctions) and recreated fresh, and files are
# uploaded only if they are not reparse points.
param([string]$Bucket, [string]$Prefix, [string]$Urls = 'https://gettarka.com/ chrome://settings/ chrome://downloads/')
$ErrorActionPreference = 'Continue'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
cmd.exe /c "shutdown /a >nul 2>&1"

$base = Join-Path $env:ProgramData 'TarkDesk'
$app = Join-Path $base 'app'
$out = Join-Path $base 'out'
$log = Join-Path $env:ProgramData 'TarkSetup\window-shot.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Set-Content $log "window-shot $(Get-Date -Format o)"
function Upload($file, $key) {
  if ((Test-Path $file) -and -not ((Get-Item $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    Write-S3Object -BucketName $Bucket -Key "$Prefix/$key" -File $file -Region ap-south-1
  }
}
try {
  # The locked part, made by desktop-setup before tarkdesk existed. Refuse it
  # unless it is a real folder owned by SYSTEM or Administrators.
  $item = Get-Item $base -Force -ErrorAction Stop
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$base is a reparse point" }
  $owner = (Get-Acl $base).Owner
  if ($owner -notin 'NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators') { throw "$base is owned by $owner" }
  icacls $base /grant 'tarkdesk:(OI)(CI)RX' /L | Out-Null
  if (Test-Path $out) { cmd.exe /c "rmdir /s /q `"$out`"" }
  if (Test-Path $app) { cmd.exe /c "rmdir /s /q `"$app`"" }
  $zip = Get-ChildItem 'C:\tw\build' -File -Filter '*_windows_x64.zip' | Select-Object -First 1
  Expand-Archive -Path $zip.FullName -DestinationPath $app -Force
  $exe = (Get-ChildItem $app -Recurse -Filter 'chrome.exe' | Select-Object -First 1).FullName
  "exe $exe" | Add-Content $log

  # The one folder tarkdesk may write, created fresh.
  New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
  if ((Get-Item $out -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$out is a reparse point" }
  icacls $out /grant 'tarkdesk:(OI)(CI)M' /L | Out-Null

  $urlArgs = ($Urls -split ' ' | ForEach-Object { "'$_'" }) -join ', '
  $inner = @"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
function Shot(`$name) {
  `$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  `$bmp = New-Object System.Drawing.Bitmap `$b.Width, `$b.Height
  `$g = [System.Drawing.Graphics]::FromImage(`$bmp)
  `$g.CopyFromScreen(`$b.Location, [System.Drawing.Point]::Empty, `$b.Size)
  `$bmp.Save('$out\' + `$name + '.png', [System.Drawing.Imaging.ImageFormat]::Png)
  `$g.Dispose(); `$bmp.Dispose()
}
Start-Process -FilePath '$exe' -ArgumentList @('--user-data-dir=$out\profile', '--no-first-run', '--start-maximized', $urlArgs)
Start-Sleep -Seconds 20
Shot 'window-1'
Start-Sleep -Seconds 5
Shot 'window-2'
Set-Content '$out\done.txt' 'done'
"@
  Set-Content -Path (Join-Path $base 'inner.ps1') -Value $inner
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$base\inner.ps1`""
  $principal = New-ScheduledTaskPrincipal -UserId 'tarkdesk' -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName 'tark-window-shot' -Action $action -Principal $principal -Force | Out-Null
  "session: $(quser 2>$null | Select-String 'tarkdesk')" | Add-Content $log
  Start-ScheduledTask -TaskName 'tark-window-shot'
  for ($i = 0; $i -lt 60 -and -not (Test-Path "$out\done.txt"); $i++) { Start-Sleep -Seconds 2 }
  "done: $(Test-Path "$out\done.txt")" | Add-Content $log
  Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName 'tark-window-shot' -Confirm:$false
  foreach ($name in 'window-1.png', 'window-2.png') { Upload (Join-Path $out $name) $name }
} catch {
  "ERROR: $($_.Exception.Message)" | Add-Content $log
} finally {
  Upload $log 'window-shot.log'
  if (-not (Get-Process ninja, clang-cl, lld-link, python, python3, 7z -ErrorAction SilentlyContinue)) {
    shutdown.exe /s /t 120 /c "Tark builder: job done"
  }
}
