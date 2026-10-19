# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# W1, one time: give the build machine a signed-in desktop so Tark's real
# window can be screenshotted (jobs/window-shot.ps1). SSM commands run as
# SYSTEM in session 0, which has no screen.
#
# Creates a standard (non-admin) local user `tarkdesk` with a random
# password generated here and never printed or logged, and signs it in at
# boot with Sysinternals Autologon (which stores the password encrypted as
# an LSA secret). Everything this job downloads or writes lives in a folder
# only SYSTEM and Administrators can write, and Autologon must carry
# Microsoft's exact Authenticode signer. The machine has no inbound ports.
param([string]$Bucket, [string]$Prefix)
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
cmd.exe /c "shutdown /a >nul 2>&1"

function Lock-Folder($path) {
  New-Item -ItemType Directory -Force -Path $path | Out-Null
  if ((Get-Item $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "$path is a reparse point" }
  icacls $path /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' | Out-Null
}

$base = Join-Path $env:ProgramData 'TarkSetup'
Lock-Folder $base
$log = Join-Path $base 'desktop-setup.log'
Set-Content $log "desktop-setup $(Get-Date -Format o)"
$ok = $false
try {
  # Before any non-admin user exists: Windows' default ACL on C:\ lets any
  # signed-in user add files inside folders SYSTEM creates there, and modify
  # files SYSTEM creates at the root. Lock everything the build machine runs
  # from, so no planted module or script can run as SYSTEM.
  foreach ($dir in 'C:\tark-setup', 'C:\tark-logs', 'C:\tw', 'C:\tarka-browser', 'C:\ucw', 'C:\Python312') {
    if (Test-Path $dir) { Lock-Folder $dir; "locked $dir" | Add-Content $log }
  }
  Remove-Item -Force 'C:\tark-job.ps1', 'C:\bootstrap.ps1' -ErrorAction SilentlyContinue
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $plain = [Convert]::ToBase64String($bytes) + 'aA1!'
  $secure = ConvertTo-SecureString $plain -AsPlainText -Force
  if (Get-LocalUser -Name 'tarkdesk' -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name 'tarkdesk' -Password $secure
  } else {
    New-LocalUser -Name 'tarkdesk' -Password $secure -PasswordNeverExpires -AccountNeverExpires `
      -Description 'Tark build machine desktop session for window screenshots' | Out-Null
    Add-LocalGroupMember -Group 'Users' -Member 'tarkdesk'
  }
  'user tarkdesk ready' | Add-Content $log

  $zip = Join-Path $base 'AutoLogon.zip'
  Invoke-WebRequest -Uri 'https://download.sysinternals.com/files/AutoLogon.zip' -OutFile $zip -UseBasicParsing
  $dest = Join-Path $base 'autologon'
  Expand-Archive -Path $zip -DestinationPath $dest -Force
  $tool = Join-Path $dest 'Autologon64.exe'
  $sig = Get-AuthenticodeSignature $tool
  $signer = 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US'
  if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -ne $signer) {
    throw "Autologon64.exe: signature $($sig.Status), signer '$($sig.SignerCertificate.Subject)'"
  }
  'autologon signature verified' | Add-Content $log
  $p = Start-Process -FilePath $tool -ArgumentList @('/accepteula', 'tarkdesk', $env:COMPUTERNAME, $plain) `
    -PassThru -Wait -WindowStyle Hidden
  $plain = $null
  "autologon exit $($p.ExitCode)" | Add-Content $log
  if ($p.ExitCode -ne 0) { throw "Autologon exited $($p.ExitCode)" }
  New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Force | Out-Null
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Name NoLockScreen `
    -Value 1 -PropertyType DWORD -Force | Out-Null
  'rebooting into the desktop session' | Add-Content $log
  $ok = $true
} catch {
  "ERROR: $($_.Exception.Message) at $($_.InvocationInfo.PositionMessage)" | Add-Content $log
} finally {
  Write-S3Object -BucketName $Bucket -Key "$Prefix/desktop-setup.log" -File $log -Region ap-south-1
}
if ($ok) { shutdown.exe /r /t 15 /c "Tark builder: sign in the desktop session" }
