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
# A test program that fails before any test runs is probed: listing its
# tests, one test in one process, the same without strict handle checking,
# and that one test under cdb (stack and the code around the stop), so one
# run says why. Tark itself runs from its zip, as people get it.
#
#   windows\ci\verify.ps1 -Work C:\tw -Tests C:\tw\tests -Report C:\tw\verify
#
# WORK\build holds Tark-*.zip and Tark-*-setup.exe; TESTS the unit test
# programs with what they load (the build's "Gather the test programs").

param(
  [Parameter(Mandatory)][string]$Work,
  [Parameter(Mandatory)][string]$Tests,
  [Parameter(Mandatory)][string]$Report
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Report | Out-Null
$failed = [System.Collections.Generic.List[string]]::new()

function Note([string]$Line) { $Line | Tee-Object -Append "$Report\summary.txt" }

function Check([string]$Name, [scriptblock]$Body) {
  try {
    & $Body
    Note "PASS $Name"
  } catch {
    $failed.Add($Name)
    Note "FAIL $Name : $_"
  }
}

# Runs FILE with ARGS (one string, quoted by the caller), its output in
# REPORT\LOG.txt and LOG.err.txt; returns the exit code, or 'timeout'.
function Invoke-Logged([string]$File, [string]$Arguments, [string]$Log, [int]$Seconds = 600) {
  $p = Start-Process -FilePath $File -ArgumentList $Arguments -NoNewWindow -PassThru `
    -RedirectStandardOutput "$Report\$Log.txt" -RedirectStandardError "$Report\$Log.err.txt"
  $null = $p.Handle  # Keeps the exit code readable after the process ends.
  if (-not $p.WaitForExit($Seconds * 1000)) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    return 'timeout'
  }
  return $p.ExitCode
}

function Format-Code($Code) {
  if ($Code -is [int]) { return '{0} (0x{1:X8})' -f $Code, $Code }
  return "$Code"
}

# Why a test program stops before its tests: each probe's exit code goes to
# REPORT\probe-TAG.txt, and cdb's view of the stop to TAG-cdb.txt.
function Probe-TestProgram([string]$Exe, [string]$Tag, [string]$OneTest) {
  $path = "$Tests\$Exe"
  $one = "--single-process-tests --gtest_filter=$OneTest"
  $probes = [ordered]@{
    'list'              = '--gtest_list_tests'
    'one'               = $one
    'one-no-handle-check' = "$one --disable-strict-handle-checking-for-testing"
    # A debugger skips TestSuite's in-process stack dumping; without one the
    # suite stops in Initialize, so check that setup on its own.
    'list-no-stack-traces' = '--gtest_list_tests --disable-in-process-stack-traces'
    'one-no-stack-traces' = "$one --disable-in-process-stack-traces"
  }
  foreach ($name in $probes.Keys) {
    $code = Invoke-Logged $path $probes[$name] "$Tag-$name" 120
    "$name : $($probes[$name]) -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"
  }
  # The same, with the dbghelp.dll and symsrv.dll beside the program moved
  # aside so Windows' own dbghelp loads for the stack dumping setup.
  $aside = @('dbghelp.dll', 'symsrv.dll') | Where-Object { Test-Path "$Tests\$_" }
  foreach ($dll in $aside) { Rename-Item "$Tests\$dll" "$dll.aside" }
  try {
    foreach ($name in 'list', 'one') {
      $code = Invoke-Logged $path $probes[$name] "$Tag-$name-system-dbghelp" 120
      "$name-system-dbghelp : $($probes[$name]) -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"
    }
  } finally {
    foreach ($dll in $aside) { Rename-Item "$Tests\$dll.aside" $dll }
  }
  $cdb = "${env:ProgramFiles(x86)}\Windows Kits\10\Debuggers\x64\cdb.exe"
  if (-not (Test-Path $cdb)) {
    'cdb: not installed on this runner' | Out-File -Append "$Report\probe-$Tag.txt"
    return
  }
  # At a breakpoint (a failed CHECK) or an access violation: the stack, what
  # happened, and the instructions before the stop (symbol_level=0 has names,
  # not lines, so the call just before the int3 says which CHECK).
  @(
    'sxe -c "kn 40; .lastevent; r; ub @rip L40; u @rip L6; q" bpe'
    'sxe -c "kn 40; .lastevent; r; ub @rip L40; q" av'
    'g'
    'q'
  ) | Out-File -Encoding ascii "$Report\cdb-commands.txt"
  $code = Invoke-Logged $cdb ("-G -y `"$Tests`" -cf `"$Report\cdb-commands.txt`" `"$path`" $one") "$Tag-cdb" 300
  "cdb : $one -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"

  # Under cdb the stop never happens, so read the code at the stop from the
  # image itself: the branch to the CHECK block before +0x6e2 says which check fails.
  $fn = "$([IO.Path]::GetFileNameWithoutExtension($Exe))!base::TestSuite::Initialize"
  @(
    ".symopt+ 0x40; .reload /f"
    "u $fn $fn+0x6f0"
    'q'
  ) | Out-File -Encoding ascii "$Report\$Tag-disasm-commands.txt"
  $code = Invoke-Logged $cdb ("-y `"$Tests`" -z `"$path`" -cf `"$Report\$Tag-disasm-commands.txt`"") "$Tag-disasm" 300
  "disasm : $fn+0..0x6f0 -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"

  # A debugger hides the stop, so let Windows Error Reporting write a full
  # dump of an undebugged run, then read the thread's last error from it.
  $dumps = "$env:RUNNER_TEMP\dumps-$Tag"
  New-Item -ItemType Directory -Force $dumps | Out-Null
  $wer = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\$Exe"
  New-Item -Force $wer | Out-Null
  Set-ItemProperty $wer DumpFolder $dumps -Type ExpandString
  Set-ItemProperty $wer DumpType 2 -Type DWord
  Set-ItemProperty $wer DumpCount 2 -Type DWord
  try {
    $code = Invoke-Logged $path $one "$Tag-wer" 120
    Start-Sleep -Seconds 15  # WerFault writes the dump after the process ends.
  } finally {
    Remove-Item -Force -Recurse $wer
  }
  $dump = Get-ChildItem $dumps -Filter *.dmp | Select-Object -First 1
  "wer : $one -> $(Format-Code $code), dump: $(if ($dump) { $dump.Name } else { 'none' })" |
    Out-File -Append "$Report\probe-$Tag.txt"
  if ($dump) {
    @(
      ".symopt+ 0x40; .reload /f"
      '.ecxr'
      '.lastevent'
      '!gle -all'
      'kn 40'
      '~* kn 12'
      'q'
    ) | Out-File -Encoding ascii "$Report\$Tag-dump-commands.txt"
    $code = Invoke-Logged $cdb ("-y `"$Tests`" -i `"$Tests`" -z `"$($dump.FullName)`" -cf `"$Report\$Tag-dump-commands.txt`"") "$Tag-dump" 300
    "dump read -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"
  }

  # No dump came that way, so make cdb the postmortem debugger: the run is
  # undebugged when the CHECK fails, and cdb attaches at the crash to print
  # dbghelp's saved error (g_init_error), the last error and the stack.
  $mod = [IO.Path]::GetFileNameWithoutExtension($Exe)
  @(
    '.symopt+ 0x40; .reload /f'
    '.lastevent'
    '.ecxr'
    "x $mod!*g_init_error*"
    ".foreach /pS 0 /ps 99 (a {x /0 $mod!*g_init_error*}) {dd a L1}"
    '!gle -all'
    'kn 40'
    'qd'
  ) | Out-File -Encoding ascii "$Report\$Tag-aedebug-commands.txt"
  $log = "$Report\$Tag-aedebug.txt"
  $aedebug = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AeDebug'
  $saved = Get-ItemProperty $aedebug -ErrorAction SilentlyContinue
  Set-ItemProperty $aedebug Debugger "`"$cdb`" -p %ld -e %ld -g -y `"$Tests`" -logo `"$log`" -cf `"$Report\$Tag-aedebug-commands.txt`""
  Set-ItemProperty $aedebug Auto '1'
  try {
    $code = Invoke-Logged $path $one "$Tag-aedebug-run" 180
    Start-Sleep -Seconds 10  # cdb finishes its log after the process ends.
  } finally {
    foreach ($v in 'Debugger', 'Auto') {
      if ($saved -and $null -ne $saved.$v) { Set-ItemProperty $aedebug $v $saved.$v }
      else { Remove-ItemProperty $aedebug $v -ErrorAction SilentlyContinue }
    }
  }
  "aedebug : $one -> $(Format-Code $code), log: $(if (Test-Path $log) { 'written' } else { 'none' })" |
    Out-File -Append "$Report\probe-$Tag.txt"

  # Under cdb, but with the PEB's BeingDebugged flag cleared, log each step of
  # the stack dumping setup: the dbghelp/msdia140 loads and SymInitialize, each
  # with its result and last error.
  $ret = 'bp /1 @$ra \"r rax; !gle; g\"; g'
  @(
    'eb @$peb+2 0'
    'sxe -c "kn 40; !gle; q" bpe'
    "bp KERNELBASE!LoadLibraryExW `".printf \`"LoadLibraryExW %mu\\n\`", @rcx; $ret`""
    "bm dbghelp!SymInitialize* `".printf \`"SymInitialize\\n\`"; $ret`""
    "bp $mod!base::debug::EnableInProcessStackDumping `".printf \`"EnableInProcessStackDumping\\n\`"; $ret`""
    'g'
    'q'
  ) | Out-File -Encoding ascii "$Report\$Tag-steps-commands.txt"
  $code = Invoke-Logged $cdb ("-y `"$Tests`" -cf `"$Report\$Tag-steps-commands.txt`" `"$path`" $one") "$Tag-steps" 300
  "steps (cdb, BeingDebugged cleared) : $one -> $(Format-Code $code)" | Out-File -Append "$Report\probe-$Tag.txt"
}

function Run-TestProgram([string]$Exe, [string]$Log, [string]$Arguments) {
  $code = Invoke-Logged "$Tests\$Exe" $Arguments $Log
  if ($code -ne 0) { throw "$Exe exited $(Format-Code $code)" }
}

Get-ChildItem $Tests | Format-Table Name, Length -AutoSize | Out-String -Width 200 |
  Out-File "$Report\tests-folder.txt"
[System.Environment]::OSVersion.VersionString | Out-File "$Report\runner.txt"

# Unit tests that need no models (those that do skip themselves).
Check 'tark_captions_unittests' {
  try {
    Run-TestProgram 'tark_captions_unittests.exe' 'captions' "--gtest_output=xml:`"$Report\captions.xml`""
  } catch {
    Probe-TestProgram 'tark_captions_unittests.exe' 'captions' 'RenderQueueTest.OneRequestInFlight'
    throw
  }
}
Check 'tark_speech_unittests' {
  try {
    Run-TestProgram 'tark_speech_unittests.exe' 'speech' "--gtest_output=xml:`"$Report\speech.xml`""
  } catch {
    Probe-TestProgram 'tark_speech_unittests.exe' 'speech' 'TarkCaptionRecognizerTest.ErrorWhenEngineMissing'
    throw
  }
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
  $env:TARK_CAPTIONS_ORT = "$Tests\onnxruntime.dll"
  $env:TARK_CAPTIONS_MODELS = $models
  try {
    # One process, so gtest's own summary is printed (the launcher prints its own).
    Run-TestProgram 'tark_captions_unittests.exe' 'onnxruntime' '--gtest_filter=OrtRuntimeTest.* --single-process-tests'
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
$zip = Get-ChildItem "$Work\build\Tark-*.zip" | Select-Object -First 1
Check 'package contents' {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  if (-not $zip) { throw 'no Tark-*.zip' }
  $entries = [System.IO.Compression.ZipFile]::OpenRead($zip.FullName).Entries | ForEach-Object FullName
  $entries | Out-File "$Report\zip-contents.txt"
  foreach ($want in 'chrome.exe', 'onnxruntime.dll', 'xlit-model.bin', 'xlit-words.bin') {
    if (-not ($entries | Where-Object { $_ -like "*/$want" -or $_ -like "*\$want" })) { throw "the zip lacks $want" }
  }
  if (-not (Get-ChildItem "$Work\build\Tark-*-setup.exe")) { throw 'no Tark-*-setup.exe' }
}

# Tark as people get it: unpacked from the zip.
$chrome = $null
if ($zip) {
  Expand-Archive $zip.FullName -DestinationPath "$Work\tark" -Force
  $chrome = Get-ChildItem "$Work\tark" -Recurse -Filter chrome.exe | Select-Object -First 1 -ExpandProperty FullName
}

# Tark renders a page (headless, its own profile). Started with its output
# in files: chrome.exe is a GUI program, so PowerShell's own call operator
# gives no reliable output from it.
Check 'headless page' {
  if (-not $chrome) { throw 'no chrome.exe in the zip' }
  $userData = "$env:RUNNER_TEMP\tark-profile"
  $code = Invoke-Logged $chrome ("--headless=new --user-data-dir=`"$userData`" --no-first-run " +
    '--enable-logging=stderr --v=0 --dump-dom https://gettarka.com/') 'headless-dom' 120
  $dom = Get-Content "$Report\headless-dom.txt" -Raw -ErrorAction SilentlyContinue
  $null = Invoke-Logged $chrome ("--headless=new --user-data-dir=`"$userData`" --no-first-run " +
    "--window-size=1280,800 --screenshot=`"$Report\gettarka-headless.png`" https://gettarka.com/") 'headless-shot' 120
  if ("$dom" -notmatch 'Live captions') {
    throw "gettarka.com did not render: exit $(Format-Code $code), $("$dom".Length) characters of page (headless-dom.err.txt has the log)"
  }
}

# Best effort: the real window (frame, one row), if the runner has a desktop.
try {
  if (-not $chrome) { throw 'no chrome.exe in the zip' }
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $p = Start-Process $chrome -ArgumentList @("--user-data-dir=`"$env:RUNNER_TEMP\tark-window`"",
    '--no-first-run', '--window-size=1280,800', '--window-position=0,0', 'https://gettarka.com/') -PassThru
  Start-Sleep -Seconds 12
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  [System.Drawing.Graphics]::FromImage($bitmap).CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $bitmap.Save("$Report\window.png")
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Note 'INFO window screenshot saved'
} catch {
  Note "INFO no window screenshot: $_"
}

if ($failed.Count) {
  "Failed: $($failed -join ', ')"
  exit 1
}
'All checks passed.'
exit 0
