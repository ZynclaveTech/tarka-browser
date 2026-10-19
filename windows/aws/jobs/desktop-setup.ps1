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
# an LSA secret, not in the registry). The machine still has no inbound
# ports; the session is only reachable from this machine itself.
param([string]$Bucket, [string]$Prefix)
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
shutdown.exe /a 2>$null | Out-Null
$log = 'C:\tark-logs\desktop-setup.log'
New-Item -ItemType Directory -Force -Path 'C:\tark-logs', 'C:\tark-setup' | Out-Null
try {
  Add-Type -AssemblyName System.Web
  $plain = [System.Web.Security.Membership]::GeneratePassword(32, 6)
  $secure = ConvertTo-SecureString $plain -AsPlainText -Force
  if (Get-LocalUser -Name 'tarkdesk' -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name 'tarkdesk' -Password $secure
  } else {
    New-LocalUser -Name 'tarkdesk' -Password $secure -PasswordNeverExpires -AccountNeverExpires `
      -Description 'Tark build machine desktop session for window screenshots' | Out-Null
    Add-LocalGroupMember -Group 'Users' -Member 'tarkdesk'
  }
  'user tarkdesk ready' | Add-Content $log

  $zip = 'C:\tark-setup\AutoLogon.zip'
  Invoke-WebRequest -Uri 'https://download.sysinternals.com/files/AutoLogon.zip' -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath 'C:\tark-setup\autologon' -Force
  $sig = Get-AuthenticodeSignature 'C:\tark-setup\autologon\Autologon64.exe'
  if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw "Autologon64.exe signature not valid Microsoft: $($sig.Status)"
  }
  $p = Start-Process -FilePath 'C:\tark-setup\autologon\Autologon64.exe' `
    -ArgumentList @('/accepteula', 'tarkdesk', $env:COMPUTERNAME, $plain) -PassThru -Wait -WindowStyle Hidden
  $plain = $null
  "autologon exit $($p.ExitCode)" | Add-Content $log
  # No lock screen or screensaver in that session.
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Name NoLockScreen `
    -Value 1 -PropertyType DWORD -Force -ErrorAction SilentlyContinue | Out-Null
  'rebooting into the desktop session' | Add-Content $log
} finally {
  Write-S3Object -BucketName $Bucket -Key "$Prefix/desktop-setup.log" -File $log -Region ap-south-1
}
shutdown.exe /r /t 15 /c "Tark builder: sign in the desktop session"
