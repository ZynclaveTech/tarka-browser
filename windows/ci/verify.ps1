# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Checks a finished Windows build on the CI runner (W2) and writes what it
# saw to REPORT: the captions and speech unit tests; ONNX Runtime running a
# real model (Silero VAD from gettarka.com); the zip holding what the Mac's
# app holds; Tark rendering a page headless; and, best effort, a picture of
# the real window. Exits non-zero when a check fails, after running them all.
#
#   windows\ci\verify.ps1 -Work C:\tw -Report C:\tw\verify

param([Parameter(Mandatory)][string]$Work, [Parameter(Mandatory)][string]$Report)
$ErrorActionPreference = 'Stop'
$out = "$Work\build\src\out\Default"
New-Item -ItemType Directory -Force $Report | Out-Null
$failed = [System.Collections.Generic.List[string]]::new()

function Check([string]$Name, [scriptblock]$Body) {
  try {
    & $Body
    "PASS $Name" | Tee-Object -Append "$Report\summary.txt"
  } catch {
    $failed.Add($Name)
    "FAIL $Name : $_" | Tee-Object -Append "$Report\summary.txt"
  }
}

function Run-Test([string]$Exe, [string]$Log, [string[]]$Arguments) {
  $p = Start-Process -FilePath "$out\$Exe" -ArgumentList $Arguments -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput "$Report\$Log.txt" -RedirectStandardError "$Report\$Log.err.txt"
  if ($p.ExitCode -ne 0) { throw "$Exe exited $($p.ExitCode)" }
}

# Unit tests that need no models (those that do skip themselves).
Check 'tark_captions_unittests' {
  Run-Test 'tark_captions_unittests.exe' 'captions' @("--gtest_output=xml:$Report\captions.xml")
}
Check 'tark_speech_unittests' {
  Run-Test 'tark_speech_unittests.exe' 'speech' @("--gtest_output=xml:$Report\speech.xml")
}

# Tark's own ONNX Runtime build runs a real model on Windows.
Check 'onnxruntime runs Silero VAD' {
  $models = "$env:RUNNER_TEMP\tark-models"
  New-Item -ItemType Directory -Force $models | Out-Null
  Invoke-WebRequest -UseBasicParsing 'https://gettarka.com/models/captions/v1/silero_vad.onnx' `
    -OutFile "$models\silero_vad.onnx"
  $hash = (Get-FileHash "$models\silero_vad.onnx" -Algorithm SHA256).Hash
  if ($hash -ne '1A153A22F4509E292A94E67D6F9B85E8DEB25B4988682B7E174C65279D8788E3') {
    throw "silero_vad.onnx has sha256 $hash"
  }
  $env:TARK_CAPTIONS_ORT = "$out\onnxruntime.dll"
  $env:TARK_CAPTIONS_MODELS = $models
  try {
    # One process, so gtest's own summary is printed (the launcher prints its own).
    Run-Test 'tark_captions_unittests.exe' 'onnxruntime' @('--gtest_filter=OrtRuntimeTest.*', '--single-process-tests')
    $text = Get-Content "$Report\onnxruntime.txt" -Raw
    if ($text -match '\[  SKIPPED \]') { throw 'an ONNX Runtime test was skipped' }
    if (-not ($text -match '\[  PASSED  \] (\d+) tests?') -or [int]$Matches[1] -lt 3) {
      throw 'the ONNX Runtime tests did not run'
    }
  } finally {
    Remove-Item Env:TARK_CAPTIONS_ORT, Env:TARK_CAPTIONS_MODELS -ErrorAction SilentlyContinue
  }
}

# The zip holds Tark, ONNX Runtime and the transliteration model.
Check 'package contents' {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = Get-ChildItem "$Work\build\Tark-*.zip" | Select-Object -First 1
  if (-not $zip) { throw 'no Tark-*.zip' }
  $entries = [System.IO.Compression.ZipFile]::OpenRead($zip.FullName).Entries | ForEach-Object FullName
  $entries | Out-File "$Report\zip-contents.txt"
  foreach ($want in 'chrome.exe', 'onnxruntime.dll', 'xlit-model.bin', 'xlit-words.bin') {
    if (-not ($entries | Where-Object { $_ -like "*/$want" -or $_ -like "*\$want" })) { throw "the zip lacks $want" }
  }
  if (-not (Get-ChildItem "$Work\build\Tark-*-setup.exe")) { throw 'no Tark-*-setup.exe' }
}

# Tark renders a page (headless, its own profile).
Check 'headless page' {
  $userData = "$env:RUNNER_TEMP\tark-profile"
  $dom = & "$out\chrome.exe" --headless=new --user-data-dir=$userData --no-first-run `
    --dump-dom 'https://gettarka.com/' 2>$null
  $dom | Out-File "$Report\gettarka-dom.html"
  if (($dom -join "`n") -notmatch 'Live captions') { throw 'gettarka.com did not render' }
  & "$out\chrome.exe" --headless=new --user-data-dir=$userData --no-first-run --window-size=1280,800 `
    --screenshot="$Report\gettarka-headless.png" 'https://gettarka.com/' 2>$null | Out-Null
}

# Best effort: the real window (frame, one row), if the runner has a desktop.
try {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $p = Start-Process "$out\chrome.exe" -ArgumentList @("--user-data-dir=$env:RUNNER_TEMP\tark-window",
    '--no-first-run', '--window-size=1280,800', '--window-position=0,0', 'https://gettarka.com/') -PassThru
  Start-Sleep -Seconds 12
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  [System.Drawing.Graphics]::FromImage($bitmap).CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $bitmap.Save("$Report\window.png")
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  'INFO window screenshot saved' | Tee-Object -Append "$Report\summary.txt"
} catch {
  "INFO no window screenshot: $_" | Tee-Object -Append "$Report\summary.txt"
}

if ($failed.Count) {
  "Failed: $($failed -join ', ')"
  exit 1
}
'All checks passed.'
exit 0
