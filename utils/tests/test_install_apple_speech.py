"""Tests for utils/install_apple_speech.sh, which puts libtark_apple_speech.dylib
(the Swift library over macOS 26's speech and translation, D4 Phase 3) into
Tark.app: arm64 only, built for macOS 26. Stand-in dylibs are compiled with
clang so `lipo` and `vtool` see real architectures and OS versions.
"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'install_apple_speech.sh')
DYLIB = 'libtark_apple_speech.dylib'


def make_dylib(path, arch='arm64', minos='26.0'):
    source = path + '.c'
    with open(source, 'w') as f:
        f.write('int tark_apple_available(void) { return 1; }\n')
    subprocess.run(['clang', '-dynamiclib', '-arch', arch, f'-mmacosx-version-min={minos}',
                    '-o', path, source], check=True)


def make_app(root):
    app = os.path.join(root, 'Tark.app')
    os.makedirs(os.path.join(app, 'Contents', 'Frameworks'))
    return app


def install(app, dylib):
    return subprocess.run(['bash', SCRIPT, app, dylib], capture_output=True, text=True)


class TestInstallAppleSpeech(unittest.TestCase):
    def test_installs_into_frameworks(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            dylib = os.path.join(tmp, DYLIB)
            make_dylib(dylib)
            run = install(app, dylib)
            self.assertEqual(run.returncode, 0, run.stderr)
            installed = os.path.join(app, 'Contents', 'Frameworks', DYLIB)
            self.assertTrue(os.path.isfile(installed))
            self.assertFalse(os.path.islink(installed))

    def test_rejects_another_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            dylib = os.path.join(tmp, DYLIB)
            make_dylib(dylib, arch='x86_64')
            self.assertNotEqual(install(app, dylib).returncode, 0)

    def test_rejects_a_build_for_older_macos(self):
        # Loaded only on macOS 26 and later: a build for older macOS means the
        # wrong SDK or target, and the speech APIs it calls would be missing.
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            dylib = os.path.join(tmp, DYLIB)
            make_dylib(dylib, minos='13.0')
            self.assertNotEqual(install(app, dylib).returncode, 0)

    def test_missing_library_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotEqual(install(make_app(tmp), os.path.join(tmp, DYLIB)).returncode, 0)


if __name__ == '__main__':
    unittest.main()
