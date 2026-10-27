# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1: build Tark for Windows from a commit of tarka-browser. The work
# folder C:\tw keeps build\ between runs: windows/layered_build.py keeps the
# base (Chromium, core and Windows patches, toolchains) as build\src-base and
# applies Tark's layer again, so a change to Tark's patches rebuilds only what
# it changed, as on Android. -Fresh makes a new base.
# Artifacts and the log go to the job's S3 prefix; the machine shuts down
# (stops) at the end, success or not.
param([string]$Bucket, [string]$Prefix, [string]$Ref = 'main', [switch]$Fresh, [switch]$PatchOnly)
$ErrorActionPreference = 'Continue'
# Windows PowerShell 5.1 redirects (*>>) as UTF-16; logs are read on the Mac.
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
# A job that just finished may have scheduled a shutdown; this one needs the machine.
cmd.exe /c "shutdown /a >nul 2>&1"
$repo = 'C:\tarka-browser'
$work = 'C:\tw'
$log = 'C:\tark-logs\tark-build.log'
New-Item -ItemType Directory -Force -Path 'C:\tark-logs' | Out-Null
Set-Content $log "tark-build $Ref $(Get-Date -Format o)"
$env:Path = 'C:\Python312;C:\Python312\Scripts;C:\Program Files\Git\cmd;C:\Program Files\Git\bin;C:\Program Files\7-Zip;' + $env:Path
$env:vs2022_install = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$env:GYP_MSVS_VERSION = '2022'
$env:WINDOWSSDKDIR = 'C:\Program Files (x86)\Windows Kits\10'

function Upload($file, $key) {
  if (Test-Path $file) { Write-S3Object -BucketName $Bucket -Key "$Prefix/$key" -File $file -Region ap-south-1 }
}

try {
  if (-not (Test-Path "$repo\.git")) {
    git clone --quiet https://github.com/ZynclaveTech/tarka-browser.git $repo *>> $log
  }
  # Byte for byte as in the repository (Git for Windows turns LF into CRLF by
  # default, which breaks the trust data's sha256s): once, the setting and a
  # checkout of every file again.
  if ((git -C $repo config core.autocrlf) -ne 'false') {
    git -C $repo config core.autocrlf false *>> $log
    git -C $repo rm -r --cached --quiet . *>> $log
  }
  git -C $repo fetch --quiet origin *>> $log
  git -C $repo checkout --quiet --force $Ref *>> $log
  git -C $repo reset --quiet --hard "origin/$Ref" *>> $log
  git -C $repo submodule update --init --depth 1 ungoogled-chromium *>> $log
  "commit $(git -C $repo rev-parse HEAD)" | Add-Content $log

  python3 "$repo\windows\prepare_workdir.py" $repo $work *>> $log
  # The last build's packages, so only this build's are uploaded.
  Get-ChildItem "$work\build" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.zip', '.exe' } | Remove-Item -Force
  # ONNX Runtime with the static C runtime for live captions (W2), built once
  # and kept on the machine's disk.
  if (-not (Test-Path 'C:\ort-out\lib\onnxruntime.dll')) {
    & "$repo\windows\ci\build_onnxruntime.ps1" -Out 'C:\ort-out' *>> $log
  }
  $env:TARK_ORT_DIR = 'C:\ort-out'
  # WinSparkle without OpenSSL, Tark's updater (W2), likewise built once.
  if (-not (Test-Path 'C:\winsparkle-out\WinSparkle.dll')) {
    & "$repo\windows\ci\build_winsparkle.ps1" -Out 'C:\winsparkle-out' *>> $log
  }
  $env:TARK_WINSPARKLE_DIR = 'C:\winsparkle-out'
  Set-Location $work
  $vcvars = "$env:vs2022_install\VC\Auxiliary\Build\vcvars64.bat"
  $layered = 'python3 layered_build.py . --jobs 64'
  if ($Fresh) { $layered += ' --fresh' }
  if ($PatchOnly) {
    # The base (if it changed) and Tark's layer, no ninja: the cheapest way to
    # see every patch conflict on the Windows stack.
    $layered += ' --patch-only'
    cmd.exe /c "call `"$vcvars`" && $layered" *>> $log
  } else {
    cmd.exe /c "call `"$vcvars`" && $layered && python3 package.py" *>> $log
  }
  "exit $LASTEXITCODE" | Add-Content $log
  # Only package.py's installer and zip, which sit directly in build\ (a
  # recursive search also picked up hundreds of tool files).
  Get-ChildItem "$work\build" -File -Filter 'Tark-*' | Where-Object { $_.Extension -in '.zip', '.exe' } |
    ForEach-Object { Upload $_.FullName $_.Name }
} finally {
  Upload $log 'tark-build.log'
  # Stop the machine unless another job is still building on it; the idle
  # watchdog (bootstrap.ps1) stops it after that one.
  if (-not (Get-Process ninja, clang-cl, lld-link, python, python3, 7z -ErrorAction SilentlyContinue)) {
    shutdown.exe /s /t 120 /c "Tark builder: job done"
  }
}
