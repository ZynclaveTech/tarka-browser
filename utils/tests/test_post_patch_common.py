"""L1: Tark's steps after patching are shared by the Windows and Linux builds
(utils/tark_post_patch_common.py); each platform adds only its own. The
order is part of the contract: name substitution before anything copies
named files, the credits after the libraries they describe."""
import importlib.util
import pathlib
import shutil
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

COMMON = ['name_substitution.py', 'install_branding.py', 'trust_data.py',
          'crates.py', 'adblock_lists.py', 'install_xlit.sh']


def load(platform, work):
    shutil.copy2(REPO / platform / 'tark_post_patch.py', work / 'tark_post_patch.py')
    (work / 'tark_repo.txt').write_text(str(REPO) + '\n')
    spec = importlib.util.spec_from_file_location(f'tark_post_patch_{platform}',
                                                  work / 'tark_post_patch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def steps(module, src, monkey):
    """The scripts main() runs, in order, with nothing executed."""
    seen = []

    def run(*args, **kwargs):
        text = ' '.join(str(a) for a in args)
        for name in COMMON + ['install_captions_credits.sh']:
            if name in text:
                seen.append(name)

    monkey(module, run, seen)
    module.main_for(src)
    return seen


class TestPostPatchSteps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.src = self.root / 'src'
        self.src.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def work(self, name):
        w = self.root / name
        w.mkdir()
        return w

    def test_windows_order_is_unchanged(self):
        module = load('windows', self.work('w'))

        def monkey(m, run, seen):
            m.common.run = run
            m.run = run
            m.install_onnxruntime = lambda *a: seen.append('onnxruntime')
            m.install_winsparkle = lambda *a: seen.append('winsparkle')

        self.assertEqual(steps(module, self.src, monkey),
                         COMMON + ['onnxruntime', 'winsparkle', 'install_captions_credits.sh'])

    def test_linux_runs_the_common_steps_then_onnxruntime_and_the_credits(self):
        # Live captions run on Linux (L2): about:credits lists ONNX Runtime
        # and the models, after ONNX Runtime is in place.
        module = load('linux', self.work('l'))

        def monkey(m, run, seen):
            m.common.run = run
            m.run = run
            m.install_onnxruntime = lambda *a: seen.append('onnxruntime')

        # ONNX Runtime's headers: components/tark_captions builds on every
        # desktop, captions on or not.
        self.assertEqual(steps(module, self.src, monkey),
                         COMMON + ['onnxruntime', 'install_captions_credits.sh'])

    def test_onnxruntime_only_installs_once(self):
        module = load('linux', self.work('l'))
        calls = []
        module.run = lambda *a, **k: calls.append(a)
        module.install_onnxruntime(self.src)
        self.assertEqual(len(calls), 2)  # retrieve, unpack
        header = self.src / 'third_party' / 'tark_onnxruntime' / 'include' / 'onnxruntime_c_api.h'
        header.parent.mkdir(parents=True)
        header.write_text('// api')
        calls.clear()
        module.install_onnxruntime(self.src)
        self.assertEqual(calls, [])

    def test_linux_writes_tarks_revision(self):
        # The update notice compares it with gettarka.com/linux/latest.json.
        module = load('linux', self.work('l'))
        module.common.run = lambda *a, **k: None
        module.run = lambda *a, **k: None
        module.install_onnxruntime = lambda *a: None
        module.main_for(self.src)
        header = (self.src / 'chrome/browser/tark_updater/tark_revision.h').read_text()
        revision = (REPO / 'revision.txt').read_text().strip()
        self.assertIn(f'#define TARK_REVISION "{revision}"', header)

    def test_inter_is_copied(self):
        module = load('linux', self.work('l'))
        module.common.run = lambda *a, **k: None
        module.run = lambda *a, **k: None
        module.install_onnxruntime = lambda *a: None
        module.main_for(self.src)
        fonts = list((self.src / 'ui' / 'webui' / 'resources' / 'fonts').glob('inter-latin*.woff2'))
        self.assertTrue(fonts)


if __name__ == '__main__':
    unittest.main()
