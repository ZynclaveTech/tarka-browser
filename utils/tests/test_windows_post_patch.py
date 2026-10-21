"""W2: windows/tark_post_patch.py puts Tark's own ONNX Runtime build (static C
runtime, windows/ci/build_onnxruntime.ps1) where the Windows build expects it,
and refuses anything else."""
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


if __name__ == '__main__':
    unittest.main()
