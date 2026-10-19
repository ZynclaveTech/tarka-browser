# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1: screenshot Tark's real window in the `tarkdesk` desktop session
# (jobs/desktop-setup.ps1). Runs Tark from the last build's zip with a
# scratch profile, opens a few pages, and captures the whole screen a few
# times: the window frame, the one row, the Tark sheet's mark, a page.
param([string]$Bucket, [string]$Prefix, [string]$Urls = 'https://gettarka.com/ chrome://settings/ chrome://downloads/')
$ErrorActionPreference = 'Continue'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
shutdown.exe /a 2>$null | Out-Null
$dir = 'C:\desk'
$log = "$dir\window-shot.log"
Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dir | Out-Null
icacls $dir /grant 'tarkdesk:(OI)(CI)M' | Out-Null
function Upload($file, $key) {
  if (Test-Path $file) { Write-S3Object -BucketName $Bucket -Key "$Prefix/$key" -File $file -Region ap-south-1 }
}
try {
  $session = (quser 2>$null | Select-String 'tarkdesk')
  "session: $session" | Add-Content $log
  $zip = Get-ChildItem 'C:\tw\build' -File -Filter '*_windows_x64.zip' | Select-Object -First 1
  Expand-Archive -Path $zip.FullName -DestinationPath "$dir\app" -Force
  $exe = (Get-ChildItem "$dir\app" -Recurse -Filter 'chrome.exe' | Select-Object -First 1).FullName
  icacls "$dir\app" /grant 'tarkdesk:(OI)(CI)RX' /T | Out-Null

  # The script the desktop session runs: start Tark, wait, screenshot.
  $inner = @"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
function Shot(`$name) {
  `$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  `$bmp = New-Object System.Drawing.Bitmap `$b.Width, `$b.Height
  `$g = [System.Drawing.Graphics]::FromImage(`$bmp)
  `$g.CopyFromScreen(`$b.Location, [System.Drawing.Point]::Empty, `$b.Size)
  `$bmp.Save("$dir\`$name.png", [System.Drawing.Imaging.ImageFormat]::Png)
  `$g.Dispose(); `$bmp.Dispose()
}
Start-Process -FilePath '$exe' -ArgumentList @('--user-data-dir=$dir\profile', '--no-first-run', '--start-maximized', $(($Urls -split ' ' | ForEach-Object { "'$_'" }) -join ', '))
Start-Sleep -Seconds 20
Shot 'window-1'
Start-Sleep -Seconds 5
Add-Type -AssemblyName Microsoft.VisualBasic
[System.Windows.Forms.SendKeys]::SendWait('^1')
Start-Sleep -Seconds 3
Shot 'window-2'
Set-Content '$dir\done.txt' 'done'
"@
  Set-Content -Path "$dir\inner.ps1" -Value $inner
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $dir\inner.ps1"
  $principal = New-ScheduledTaskPrincipal -UserId 'tarkdesk' -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName 'tark-window-shot' -Action $action -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName 'tark-window-shot'
  for ($i = 0; $i -lt 60 -and -not (Test-Path "$dir\done.txt"); $i++) { Start-Sleep -Seconds 2 }
  "done: $(Test-Path "$dir\done.txt")" | Add-Content $log
  Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName 'tark-window-shot' -Confirm:$false
  Get-ChildItem $dir -Filter 'window-*.png' | ForEach-Object { Upload $_.FullName $_.Name }
} finally {
  Upload $log 'window-shot.log'
  if (-not (Get-Process ninja, clang-cl, lld-link, python, python3, 7z -ErrorAction SilentlyContinue)) {
    shutdown.exe /s /t 120 /c "Tark builder: job done"
  }
}
