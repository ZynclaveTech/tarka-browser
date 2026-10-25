"""W2: windows/tark_post_patch.py puts Tark's own ONNX Runtime build (static C
runtime, windows/ci/build_onnxruntime.ps1) and WinSparkle build (no OpenSSL,
windows/ci/build_winsparkle.ps1) where the Windows build expects them, and
refuses anything else."""
import importlib.util
import pathlib
import shutil
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


def load_post_patch(work):
    shutil.copy2(REPO / 'windows' / 'tark_post_patch.py', work / 'tark_post_patch.py')
    (work / 'tark_repo.txt').write_text(str(REPO) + '\n')
    spec = importlib.util.spec_from_file_location('tark_post_patch', work / 'tark_post_patch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ort(root, version='1.31.0'):
    (root / 'include').mkdir(parents=True)
    (root / 'include' / 'onnxruntime_c_api.h').write_text('// c api\n')
    (root / 'include' / 'onnxruntime_cxx_api.h').write_text('// cxx api\n')
    (root / 'lib').mkdir()
    (root / 'lib' / 'onnxruntime.dll').write_bytes(b'MZ dll')
    for name in ('LICENSE', 'ThirdPartyNotices.txt'):
        (root / name).write_text(name)
    (root / 'VERSION_NUMBER').write_text(version + '\n')


class TestInstallOnnxRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / 'work').mkdir()
        self.module = load_post_patch(self.root / 'work')
        self.src = self.root / 'src'
        (self.src / 'third_party').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_headers_dll_and_licence(self):
        make_ort(self.root / 'ort')
        self.module.install_onnxruntime(self.root / 'ort', self.src)
        out = self.src / 'third_party' / 'tark_onnxruntime'
        self.assertEqual((out / 'include' / 'onnxruntime_c_api.h').read_text(), '// c api\n')
        self.assertTrue((out / 'include' / 'onnxruntime_cxx_api.h').is_file())
        self.assertEqual((out / 'lib' / 'onnxruntime.dll').read_bytes(), b'MZ dll')
        for name in ('LICENSE', 'ThirdPartyNotices.txt', 'VERSION_NUMBER'):
            self.assertTrue((out / name).is_file(), name)

    def test_replaces_an_old_copy(self):
        stale = self.src / 'third_party' / 'tark_onnxruntime' / 'lib' / 'libonnxruntime.dylib'
        stale.parent.mkdir(parents=True)
        stale.write_text('old')
        make_ort(self.root / 'ort')
        self.module.install_onnxruntime(self.root / 'ort', self.src)
        self.assertFalse(stale.exists())

    def test_unset_dir_stops_the_build(self):
        with self.assertRaises(SystemExit):
            self.module.install_onnxruntime(pathlib.Path(''), self.src)

    def test_missing_dll_stops_the_build(self):
        make_ort(self.root / 'ort')
        (self.root / 'ort' / 'lib' / 'onnxruntime.dll').unlink()
        with self.assertRaises(SystemExit):
            self.module.install_onnxruntime(self.root / 'ort', self.src)

    def test_other_version_stops_the_build(self):
        # The Mac runs 1.31.0; both platforms use the same API version.
        make_ort(self.root / 'ort', version='1.30.0')
        with self.assertRaises(SystemExit):
            self.module.install_onnxruntime(self.root / 'ort', self.src)


def make_winsparkle(root, version='0.9.4'):
    (root / 'include').mkdir(parents=True)
    (root / 'include' / 'winsparkle.h').write_text('// api\n')
    (root / 'WinSparkle.dll').write_bytes(b'MZ winsparkle')
    (root / 'COPYING').write_text('MIT')
    (root / 'VERSION').write_text(version)


class TestInstallWinSparkle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / 'work').mkdir()
        self.module = load_post_patch(self.root / 'work')
        self.src = self.root / 'src'
        (self.src / 'third_party').mkdir(parents=True)
        # windows/winsparkle.patch creates this folder.
        (self.src / 'chrome' / 'browser' / 'tark_updater').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_dll_headers_and_credits(self):
        make_winsparkle(self.root / 'ws')
        self.module.install_winsparkle(self.root / 'ws', self.src)
        out = self.src / 'third_party' / 'tark_winsparkle'
        self.assertEqual((out / 'WinSparkle.dll').read_bytes(), b'MZ winsparkle')
        self.assertTrue((out / 'include' / 'winsparkle.h').is_file())
        self.assertIn('Name: WinSparkle', (out / 'README.chromium').read_text())
        for name in ('wxwidgets', 'expat', 'ed25519'):
            folder = self.src / 'third_party' / f'tark_winsparkle_{name}'
            self.assertTrue((folder / 'README.chromium').is_file(), name)
            self.assertTrue((folder / 'LICENSE').is_file(), name)

    def test_writes_the_revision(self):
        make_winsparkle(self.root / 'ws')
        self.module.install_winsparkle(self.root / 'ws', self.src)
        revision = (REPO / 'revision.txt').read_text().strip()
        header = self.src / 'chrome' / 'browser' / 'tark_updater' / 'tark_revision.h'
        self.assertIn(f'#define TARK_REVISION "{revision}"', header.read_text())

    def test_unset_dir_stops_the_build(self):
        with self.assertRaises(SystemExit):
            self.module.install_winsparkle(pathlib.Path(''), self.src)

    def test_missing_dll_stops_the_build(self):
        make_winsparkle(self.root / 'ws')
        (self.root / 'ws' / 'WinSparkle.dll').unlink()
        with self.assertRaises(SystemExit):
            self.module.install_winsparkle(self.root / 'ws', self.src)

    def test_other_version_stops_the_build(self):
        # no-openssl.patch is made against 0.9.4.
        make_winsparkle(self.root / 'ws', version='0.9.3')
        with self.assertRaises(SystemExit):
            self.module.install_winsparkle(self.root / 'ws', self.src)


if __name__ == '__main__':
    unittest.main()
