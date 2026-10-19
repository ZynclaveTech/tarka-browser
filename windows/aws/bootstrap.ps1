# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# One-time setup of the Windows build machine (W1), run over SSM by
# windows/aws/winbuild.sh. Installs what upstream ungoogled-chromium-windows
# builds with: Visual Studio 2022 Build Tools (C++ workload, ATL, MFC), the
# Windows SDK 10.0.28000 (upstream's CI version), Python 3.12, Git, 7-Zip;
# lifts MAX_PATH; adds an idle watchdog that shuts the machine down (which
# stops the instance) after 30 minutes with no build running.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$tmp = 'C:\tark-setup'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Get-File($url, $name) {
  $out = Join-Path $tmp $name
  if (-not (Test-Path $out)) { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing }
  return $out
}
function Run($file, $arguments) {
  $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru -Wait
  if ($p.ExitCode -notin 0, 3010) { throw "$file exited $($p.ExitCode)" }
}

# Long paths (upstream's build scripts need them).
New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force | Out-Null

# Python 3.12, for all users, on PATH, with python3.exe as upstream expects.
if (-not (Test-Path 'C:\Python312\python.exe')) {
  $py = Get-File 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'python.exe'
  Run $py '/quiet InstallAllUsers=1 PrependPath=1 TargetDir=C:\Python312 Include_test=0'
}
Copy-Item 'C:\Python312\python.exe' 'C:\Python312\python3.exe' -Force
& 'C:\Python312\python.exe' -m pip install --quiet httplib2==0.22.0 clang==21.1.7

# Git (also gives bash, which Tark's install_xlit.sh step uses) and 7-Zip.
if (-not (Test-Path 'C:\Program Files\Git\cmd\git.exe')) {
  $git = Get-File 'https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/Git-2.51.0-64-bit.exe' 'git.exe'
  Run $git '/VERYSILENT /NORESTART /NOCANCEL /SP- /COMPONENTS="gitlfs"'
}
if (-not (Test-Path 'C:\Program Files\7-Zip\7z.exe')) {
  $sz = Get-File 'https://www.7-zip.org/a/7z2501-x64.exe' '7z.exe'
  Run $sz '/S'
}

# Visual Studio 2022 Build Tools: the C++ desktop workload with ATL and MFC.
$vs = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
if (-not (Test-Path "$vs\VC\Auxiliary\Build\vcvars64.bat")) {
  $bt = Get-File 'https://aka.ms/vs/17/release/vs_buildtools.exe' 'vs_buildtools.exe'
  Run $bt ('--quiet --wait --norestart --nocache --installPath "' + $vs + '" ' +
    '--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended ' +
    '--add Microsoft.VisualStudio.Component.VC.ATL --add Microsoft.VisualStudio.Component.VC.ATLMFC')
}

# Windows SDK 10.0.28000 with the debuggers (upstream CI's exact installer).
if (-not (Test-Path 'C:\Program Files (x86)\Windows Kits\10\Include\10.0.28000.0')) {
  $sdk = Get-File 'https://download.microsoft.com/download/38ab8f6d-3676-4860-ae84-3361308b9d7f/KIT_BUNDLE_WINDOWSSDK_MEDIACREATION/winsdksetup.exe' 'winsdksetup.exe'
  Run $sdk '/features OptionId.DesktopCPPx64 OptionId.DesktopCPPx86 OptionId.DesktopCPPArm64 OptionId.WindowsDesktopDebuggers OptionId.UWPCPP OptionId.SigningTools /q /norestart /ceip off'
}

# Idle watchdog: every 10 minutes; three idle checks in a row (30 min) shut
# the machine down, which stops the instance (InstanceInitiatedShutdown=stop).
$watch = @'
$busy = Get-Process -Name ninja, clang-cl, lld-link, python, python3, 7z, vs_installer, setup, winsdksetup -ErrorAction SilentlyContinue
$flag = 'C:\tark-setup\idle-count.txt'
if ($busy) { Set-Content $flag 0; exit }
$n = 0; if (Test-Path $flag) { $n = [int](Get-Content $flag) }
$n++; Set-Content $flag $n
if ($n -ge 3) { Set-Content $flag 0; shutdown.exe /s /t 60 /c "Tark builder idle for 30 minutes" }
'@
Set-Content -Path "$tmp\idle-watch.ps1" -Value $watch
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $tmp\idle-watch.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'tark-idle-stop' -Action $action -Trigger $trigger -User 'SYSTEM' -RunLevel Highest -Force | Out-Null

Write-Output 'bootstrap done'
& 'C:\Python312\python.exe' --version
& 'C:\Program Files\Git\cmd\git.exe' --version
Test-Path "$vs\VC\Auxiliary\Build\vcvars64.bat"
Test-Path 'C:\Program Files (x86)\Windows Kits\10\Include\10.0.28000.0'
