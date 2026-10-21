# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Builds ONNX Runtime 1.31.0 (MIT), the engine of Tark's live captions, for
# Windows x64 (W2), into OUT: include\, lib\onnxruntime.dll, LICENSE,
# ThirdPartyNotices.txt, VERSION_NUMBER (what windows/tark_post_patch.py
# installs). The same version and source revision as the Mac's official
# release, built here because Microsoft's Windows release needs the Visual
# C++ runtime (msvcp140.dll, vcruntime140.dll), which Windows does not always
# have: this build links the C runtime statically, and a source build has no
# telemetry (--use_telemetry is opt-in).
#
#   windows\ci\build_onnxruntime.ps1 -Out C:\ort-out
#   windows\ci\build_onnxruntime.ps1 -Out C:\ort-out -CheckOnly

param([Parameter(Mandatory)][string]$Out, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$Tag = 'v1.31.0'
$Commit = '402979ac1bef89dcd55add41eaa7277c407599eb'

function Find-Dumpbin {
  $vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath
  $tool = Get-ChildItem "$vs\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe" | Select-Object -First 1
  if (-not $tool) { throw 'dumpbin.exe not found' }
  $tool.FullName
}

if (-not $CheckOnly) {
  $src = 'C:\ort-src'
  $build = 'C:\ort-build'
  git clone --quiet --depth 1 --branch $Tag https://github.com/microsoft/onnxruntime.git $src
  if ($LASTEXITCODE) { throw "git clone of onnxruntime $Tag failed" }
  $head = (git -C $src rev-parse HEAD).Trim()
  if ($head -ne $Commit) { throw "onnxruntime $Tag is $head, expected $Commit" }

  python "$src\tools\ci_build\build.py" --build_dir $build --config Release --build_shared_lib `
    --parallel --skip_tests --skip_submodule_sync --compile_no_warning_as_error `
    --enable_msvc_static_runtime --cmake_generator 'Visual Studio 17 2022' `
    --cmake_extra_defines onnxruntime_BUILD_UNIT_TESTS=OFF
  if ($LASTEXITCODE) { throw 'onnxruntime build failed' }

  New-Item -ItemType Directory -Force "$Out\include", "$Out\lib" | Out-Null
  Copy-Item "$build\Release\Release\onnxruntime.dll" "$Out\lib\"
  Copy-Item "$src\include\onnxruntime\core\session\*.h", "$src\include\onnxruntime\core\session\*.inc" "$Out\include\"
  Copy-Item "$src\LICENSE", "$src\ThirdPartyNotices.txt", "$src\VERSION_NUMBER" $Out
}

# The DLL must load on any Windows 10 or 11 PC: no C runtime DLL, and the
# entry point the captions engine looks up.
$dumpbin = Find-Dumpbin
$dll = "$Out\lib\onnxruntime.dll"
$deps = (& $dumpbin /nologo /dependents $dll) -join "`n"
"onnxruntime.dll needs:`n$deps"
if ($deps -match '(?i)(msvcp\d+|vcruntime\d+|concrt\d+|ucrtbase|api-ms-win-crt-)') {
  throw "onnxruntime.dll still needs the C runtime ($($Matches[0]))"
}
$exports = (& $dumpbin /nologo /exports $dll) -join "`n"
if ($exports -notmatch 'OrtGetApiBase') { throw 'onnxruntime.dll does not export OrtGetApiBase' }
if ((Get-Content "$Out\VERSION_NUMBER").Trim() -ne '1.31.0') { throw 'not ONNX Runtime 1.31.0' }
'onnxruntime.dll: static C runtime, OrtGetApiBase exported'
