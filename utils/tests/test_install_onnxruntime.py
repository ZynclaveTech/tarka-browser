"""Tests for utils/install_onnxruntime.sh, which puts ONNX Runtime into
Tark.app for live captions (D4): the release's versioned dylib only, arm64
only. Stand-in dylibs are compiled with clang so `lipo -archs` sees real
architectures.
"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'install_onnxruntime.sh')
DYLIB = 'libonnxruntime.1.31.0.dylib'


def make_dylib(path, arch):
    source = path + '.c'
    with open(source, 'w') as f:
        f.write('int tark_stand_in(void) { return 1; }\n')
    subprocess.run(['clang', '-dynamiclib', '-arch', arch, '-o', path, source], check=True)


def make_release(root, arch='arm64'):
    """The release's layout: lib/ with the versioned dylib and two links."""
    lib = os.path.join(root, 'onnxruntime-osx-arm64-1.31.0', 'lib')
    os.makedirs(lib)
    make_dylib(os.path.join(lib, DYLIB), arch)
    os.symlink(DYLIB, os.path.join(lib, 'libonnxruntime.1.dylib'))
    return os.path.dirname(lib)


def make_app(root):
    app = os.path.join(root, 'Tark.app')
    os.makedirs(os.path.join(app, 'Contents', 'Frameworks'))
    return app


class TestInstallOnnxRuntime(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.app = make_app(self.root)

    def run_script(self, release):
        return subprocess.run(['bash', SCRIPT, self.app, release], capture_output=True, text=True)

    def test_copies_dylib_into_frameworks(self):
        result = self.run_script(make_release(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        frameworks = os.path.join(self.app, 'Contents', 'Frameworks')
        self.assertEqual(sorted(os.listdir(frameworks)), [DYLIB])
        installed = os.path.join(frameworks, DYLIB)
        self.assertFalse(os.path.islink(installed))
        archs = subprocess.run(['lipo', '-archs', installed], capture_output=True, text=True).stdout.split()
        self.assertEqual(archs, ['arm64'])

    def test_refuses_wrong_architecture(self):
        result = self.run_script(make_release(self.root, arch='x86_64'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('arm64', result.stderr)
        self.assertEqual(os.listdir(os.path.join(self.app, 'Contents', 'Frameworks')), [])

    def test_idempotent(self):
        release = make_release(self.root)
        self.assertEqual(self.run_script(release).returncode, 0)
        second = self.run_script(release)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(os.listdir(os.path.join(self.app, 'Contents', 'Frameworks')), [DYLIB])


if __name__ == '__main__':
    unittest.main()
