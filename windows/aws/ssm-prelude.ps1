# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Run first by every winbuild.sh job (sent base64-encoded, so no quoting is
# lost): the job script goes into a folder only SYSTEM and Administrators
# can write, never a path a signed-in user could change, then runs.
# __BUCKET__, __KEY__ and __ARGS__ are filled in by winbuild.sh.
$d = Join-Path $env:ProgramData 'TarkSetup'
New-Item -ItemType Directory -Force -Path $d | Out-Null
if ((Get-Item $d -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$d is a reparse point" }
icacls $d /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' | Out-Null
$job = Join-Path $d 'tark-job.ps1'
Read-S3Object -BucketName '__BUCKET__' -Key '__KEY__' -File $job -Region ap-south-1 | Out-Null
# The idle watchdog (bootstrap.ps1) treats a running job as busy.
$marker = Join-Path $d 'job.running'
Set-Content $marker (Get-Date -Format o)
try {
  powershell -NoProfile -ExecutionPolicy Bypass -File $job __ARGS__
} finally {
  Remove-Item -Force $marker -ErrorAction SilentlyContinue
}
