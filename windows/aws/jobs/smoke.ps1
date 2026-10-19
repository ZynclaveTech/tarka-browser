# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1: a headless smoke test of the last Windows build (the zip in C:\tw\build):
# version, a rendered screenshot of a page, and its DOM. The machine has no
# interactive desktop (SSM runs as SYSTEM), so this checks the engine runs,
# not the window frame.
param([string]$Bucket, [string]$Prefix, [string]$Url = 'https://gettarka.com/')
$ErrorActionPreference = 'Continue'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
shutdown.exe /a 2>$null | Out-Null
$out = 'C:\smoke'
$log = "$out\smoke.log"
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $out | Out-Null
function Upload($file, $key) {
  if (Test-Path $file) { Write-S3Object -BucketName $Bucket -Key "$Prefix/$key" -File $file -Region ap-south-1 }
}
try {
  $zip = Get-ChildItem 'C:\tw\build' -File -Filter '*_windows_x64.zip' | Select-Object -First 1
  Expand-Archive -Path $zip.FullName -DestinationPath "$out\app" -Force
  $exe = Get-ChildItem "$out\app" -Recurse -Filter 'chrome.exe' | Select-Object -First 1
  "exe $($exe.FullName)" | Add-Content $log
  (Get-Item $exe.FullName).VersionInfo | Format-List ProductName, ProductVersion, CompanyName, FileDescription | Out-String | Add-Content $log
  $common = @('--headless=new', "--user-data-dir=$out\profile", '--no-first-run', '--window-size=1280,900', '--disable-gpu')
  & $exe.FullName @common "--screenshot=$out\shot.png" $Url 2>&1 | Add-Content $log
  & $exe.FullName @common '--dump-dom' 'https://en.wikipedia.org/wiki/Taj_Mahal' 2>&1 | Select-Object -First 3 | Add-Content $log
  Get-ChildItem $exe.Directory.FullName -Recurse -Filter 'xlit-*.bin' | ForEach-Object { "xlit $($_.FullName) $($_.Length)" } | Add-Content $log
  Upload "$out\shot.png" 'shot.png'
} finally {
  Upload $log 'smoke.log'
  if (-not (Get-Process ninja, clang-cl, lld-link, python, python3, 7z -ErrorAction SilentlyContinue)) {
    shutdown.exe /s /t 120 /c "Tark builder: job done"
  }
}
