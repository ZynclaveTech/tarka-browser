# Tark for Windows (W1, W2)

Tark's Windows build is upstream
[ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows)
plus Tark's patches and build steps. It builds natively on Windows: on
GitHub's free runners (the default, `.github/workflows/windows.yml`), or on
the AWS EC2 machine when a fast build is worth paying for. Everything else
(patches, scripts, fixes) is done on the Mac.

- `upstream/` — upstream's build files and Windows platform patches at the
  tag in `upstream/UPSTREAM_COMMIT` (BSD-3-Clause, `upstream/LICENSE`). Local
  changes in `upstream/build.py`: a hook after patching and domain
  substitution that runs `tark_post_patch.py`; `TARK_PHASE`, which
  `layered_build.py` drives; a first ninja pass over `ninja-first.txt`
  (entries the build does not know are skipped); Tark's test binaries;
  `TARK_NINJA_HOURS`; a failed package fails the build. And Tark's names in
  `upstream/package.py` (`tark_stem`: `Tark-<chromium>-<revision>-x64.zip`
  and `-setup.exe`, as the DMG is named). When bumping upstream, copy the
  new files over and re-add them.
- `prepare_workdir.py REPO WORKDIR` — assembles the folder `build.py` runs in:
  upstream's files, this repo's `ungoogled-chromium` core, Tark's patches
  after the Windows ones (minus `mac-only-patches.txt`), Tark's filtered
  domain substitution list, the first-pass list. Test:
  `python3 -m unittest utils.tests.test_windows_workdir`.
- `tark_post_patch.py` — Tark's steps from `build.sh` that are not Mac-only:
  name substitution, the mark, Inter, the ad blocker's crates and lists,
  IndicXlit, ONNX Runtime (from `TARK_ORT_DIR`) and the captions' credits. Test:
  `python3 -m unittest utils.tests.test_windows_post_patch`.
- `ninja-first.txt` — what ninja builds first: every non-test source a Tark
  patch touches, so a compile error in Tark's code shows in the first stage.
- `mac-only-patches.txt` — patches the Windows build leaves out.
- `ci/` — `build_onnxruntime.ps1` (ONNX Runtime 1.31.0 from source with the
  static C runtime: Microsoft's Windows release needs the Visual C++ runtime,
  which Windows does not always have), `verify.ps1` (the checks after a
  build), `gen_workflow.py` (writes the workflow).
- `aws/` — the build machine: `bootstrap.ps1` (one-time setup, idle stop),
  `winbuild.sh` (drive it from the Mac over SSM), `jobs/*.ps1`.

## On GitHub (free)

Pushing `feat/w2-windows-parity` (or running the workflow by hand) builds
ONNX Runtime (about an hour, then cached), then the browser in stages of
3.5 hours that hand the tree on as an artifact, about a day and a half in
all on 4-core runners. The finishing stage uploads `tark-windows-x64` (the
zip and `-setup.exe`) and `tark-windows-checks` (unit tests, ONNX Runtime
running Silero VAD, the zip's contents, a headless page, a window picture).

## On EC2 (paid, about 2 h 15 min)

    windows/aws/winbuild.sh start
    windows/aws/winbuild.sh job windows/aws/jobs/tark-build.ps1   # prints command id and S3 prefix
    windows/aws/winbuild.sh wait <command id>
    windows/aws/winbuild.sh fetch <prefix> build/windows/

The first EC2 build after W2 also builds ONNX Runtime into `C:\ort-out`.
