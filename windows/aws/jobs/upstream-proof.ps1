# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1-1: build upstream ungoogled-chromium-windows unchanged at Tark's
# Chromium tag, to prove the build machine's toolchain before any Tark
# patch is involved. Artifacts and the log go to the job's S3 prefix; the
# machine shuts down (stops) at the end, success or not.
param([string]$Bucket, [string]$Prefix, [string]$Tag = '155.0.8059.39-1.1')
$ErrorActionPreference = 'Continue'
$root = 'C:\ucw'
$log = 'C:\tark-logs\upstream-proof.log'
New-Item -ItemType Directory -Force -Path 'C:\tark-logs' | Out-Null
$env:Path = 'C:\Python312;C:\Python312\Scripts;C:\Program Files\Git\cmd;C:\Program Files\7-Zip;' + $env:Path
$env:vs2022_install = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$env:GYP_MSVS_VERSION = '2022'
$env:WINDOWSSDKDIR = 'C:\Program Files (x86)\Windows Kits\10'

function Upload($file, $key) {
  if (Test-Path $file) { Write-S3Object -BucketName $Bucket -Key "$Prefix/$key" -File $file -Region ap-south-1 }
}

try {
  if (-not (Test-Path "$root\build.py")) {
    git clone --quiet --recurse-submodules --depth 1 --shallow-submodules --branch $Tag `
      https://github.com/ungoogled-software/ungoogled-chromium-windows.git $root *>> $log
  }
  Set-Location $root
  $vcvars = "$env:vs2022_install\VC\Auxiliary\Build\vcvars64.bat"
  cmd.exe /c "call `"$vcvars`" && python3 build.py --tarball -j 64 && python3 package.py" *>> $log
  "exit $LASTEXITCODE" | Add-Content $log
  Get-ChildItem "$root\build" -File -Filter *.zip | ForEach-Object { Upload $_.FullName $_.Name }
  Get-ChildItem "$root\build" -File -Filter *.exe | ForEach-Object { Upload $_.FullName $_.Name }
} finally {
  Upload $log 'upstream-proof.log'
  shutdown.exe /s /t 120 /c "Tark builder: job done"
}
