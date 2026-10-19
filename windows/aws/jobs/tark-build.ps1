# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1: build Tark for Windows from a commit of tarka-browser. The work
# folder C:\tw keeps build\ between runs (incremental). -Fresh wipes it.
# Artifacts and the log go to the job's S3 prefix; the machine shuts down
# (stops) at the end, success or not.
param([string]$Bucket, [string]$Prefix, [string]$Ref = 'main', [switch]$Fresh, [switch]$PatchOnly)
$ErrorActionPreference = 'Continue'
# Windows PowerShell 5.1 redirects (*>>) as UTF-16; logs are read on the Mac.
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
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
  git -C $repo fetch --quiet origin *>> $log
  git -C $repo checkout --quiet --force $Ref *>> $log
  git -C $repo reset --quiet --hard "origin/$Ref" *>> $log
  git -C $repo submodule update --init --depth 1 ungoogled-chromium *>> $log
  "commit $(git -C $repo rev-parse HEAD)" | Add-Content $log

  if ($Fresh -and (Test-Path "$work\build\src")) { Remove-Item -Recurse -Force "$work\build\src" }
  python3 "$repo\windows\prepare_workdir.py" $repo $work *>> $log
  Set-Location $work
  $vcvars = "$env:vs2022_install\VC\Auxiliary\Build\vcvars64.bat"
  if ($PatchOnly) {
    # Extract, patch and run Tark's steps, then stop before gn gen: the
    # cheapest way to see every patch conflict on the Windows stack.
    $env:TARK_STOP_BEFORE_GN = '1'
  }
  cmd.exe /c "call `"$vcvars`" && python3 build.py --tarball -j 64 && python3 package.py" *>> $log
  "exit $LASTEXITCODE" | Add-Content $log
  Get-ChildItem "$work\build" -File -Include *.zip, *.exe -Recurse -Depth 0 | ForEach-Object { Upload $_.FullName $_.Name }
} finally {
  Upload $log 'tark-build.log'
  # Stop the machine unless another job is still building on it; the idle
  # watchdog (bootstrap.ps1) stops it after that one.
  if (-not (Get-Process ninja, clang-cl, lld-link, python, python3, 7z -ErrorAction SilentlyContinue)) {
    shutdown.exe /s /t 120 /c "Tark builder: job done"
  }
}
