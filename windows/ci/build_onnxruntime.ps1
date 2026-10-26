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
# telemetry: ONNX Runtime turns it on by default, so --no_telemetry.
#
#   windows\ci\build_onnxruntime.ps1 -Out C:\ort-out
#   windows\ci\build_onnxruntime.ps1 -Out C:\ort-out -CheckOnly

param([Parameter(Mandatory)][string]$Out, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$Tag = 'v1.31.0'
$Commit = '402979ac1bef89dcd55add41eaa7277c407599eb'

function Find-Dumpbin {
  $vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -products * -latest -property installationPath
  $tool = Get-ChildItem "$vs\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe" | Select-Object -First 1
  if (-not $tool) { throw 'dumpbin.exe not found' }
  $tool.FullName
}

if (-not $CheckOnly) {
  $src = 'C:\ort-src'
  $build = 'C:\ort-build'
  # git and build.py write progress to stderr, which Windows PowerShell turns
  # into errors when the job redirects it (*>>); their exit codes are checked.
  $ErrorActionPreference = 'Continue'
  # Visual Studio's own CMake (the build machine has no other), named
  # outright: build.py looks for 'cmake' on PATH otherwise.
  $vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -products * -latest -property installationPath
  $cmake = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
  if (-not (Test-Path $cmake)) { throw "no CMake at $cmake" }
  $ctest = Join-Path (Split-Path $cmake) 'ctest.exe'
  # A run cut short leaves a partial clone and build behind; start clean.
  foreach ($d in $src, $build) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
  }
  # LF line endings: ONNX Runtime patches what it downloads (cmake/patches)
  # with LF sources, and its .gitattributes (text=auto) would otherwise check
  # the patches out with Windows line endings, which then fail to apply.
  git -c core.autocrlf=false -c core.eol=lf clone --quiet --depth 1 --branch $Tag `
    https://github.com/microsoft/onnxruntime.git $src
  if ($LASTEXITCODE) { throw "git clone of onnxruntime $Tag failed" }
  $head = (git -C $src rev-parse HEAD).Trim()
  if ($head -ne $Commit) { throw "onnxruntime $Tag is $head, expected $Commit" }

  # ONNX Runtime patches ONNX v1.22.0 and FlatBuffers v23.5.26 as it fetches
  # them, with patches that apply only loosely (whitespace and offsets); the
  # runner's older GNU patch rejects them. onnxruntime-patches\ holds the same
  # changes made against those exact sources, which apply with no fuzz.
  $patches = @{
    'onnx\onnx.patch'               = '18194802BCCD5CAD6DAB5E28F36C39F09910DF99EC5B0C27FFA6615F42ACB50E'
    'flatbuffers\flatbuffers.patch' = '9C597B79B3B35302A19B31A42B4680C4E36F9C3934A5B1B988DDD5A36C68EE33'
  }
  foreach ($name in $patches.Keys) {
    $original = "$src\cmake\patches\$name"
    if ((Get-FileHash $original -Algorithm SHA256).Hash -ne $patches[$name]) {
      throw "$original is not the patch onnxruntime-patches\ was made from"
    }
    Copy-Item "$PSScriptRoot\onnxruntime-patches\$(Split-Path $name -Leaf)" $original -Force
  }

  python "$src\tools\ci_build\build.py" --build_dir $build --config Release --build_shared_lib `
    --parallel --skip_tests --skip_submodule_sync --compile_no_warning_as_error `
    --enable_msvc_static_runtime --no_telemetry --cmake_path $cmake --ctest_path $ctest --cmake_generator 'Visual Studio 17 2022' `
    --cmake_extra_defines onnxruntime_BUILD_UNIT_TESTS=OFF
  if ($LASTEXITCODE) { throw 'onnxruntime build failed' }
  $ErrorActionPreference = 'Stop'

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
