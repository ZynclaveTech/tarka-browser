"""Tark's page-translate script (Android plan Task 4; shared with the Mac).
The patch, patches/tarka/page-translate/script.patch, is generated from
android/translate/script/ by android/translate/script.py and must stay
identical to it. The script's behaviour is tested by node:
node --test android/translate/script/test/batcher.test.mjs. Runs offline."""
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANDROID = ROOT / 'android'
sys.path.insert(0, str(ANDROID / 'translate'))
import script  # noqa: E402

PATCH = ROOT / 'patches' / 'tarka' / 'page-translate' / 'script.patch'


class TestTranslateScriptPatch(unittest.TestCase):
    def test_patch_is_current(self):
        self.assertEqual(PATCH.read_text(encoding='utf-8'), script.build(ROOT),
                         'run android/translate/script.py build after changing the script')

    def test_script_patch_matches_source(self):
        # The shared patch (Mac and Android) is what script.py writes from
        # android/translate/script/, byte for byte.
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / 'script.patch'
            subprocess.run([sys.executable, '-I', str(ANDROID / 'translate' / 'script.py'),
                            'build', str(ROOT), '--out', str(out)],
                           check=True, capture_output=True)
            self.assertEqual(out.read_bytes(), PATCH.read_bytes())

    def test_patch_files(self):
        paths = re.findall(r'^\+\+\+ b/(\S+)', PATCH.read_text(encoding='utf-8'), re.M)
        self.assertEqual(paths, ['components/resources/components_resources.grd',
                                 'components/resources/tark_translate_resources.grdp',
                                 'components/translate/core/browser/resources/tark_translate.js'])

    def test_resource_named(self):
        self.assertIn('<include name="IDR_TARK_TRANSLATE_JS" ', PATCH.read_text(encoding='utf-8'))

    def test_in_series(self):
        # Shared: in patches/series (so Android's series.py takes it too), not
        # in Android's own series.
        def entries(path):
            return [l.strip() for l in path.read_text(encoding='utf-8').splitlines()
                    if l.strip() and not l.lstrip().startswith('#')]
        self.assertIn('tarka/page-translate/script.patch', entries(ROOT / 'patches' / 'series'))
        self.assertNotIn('page-translate-script.patch', entries(ANDROID / 'patches' / 'series'))

    def test_script_fetches_nothing(self):
        text = script.bundle(ROOT)
        for word in ('fetch(', 'XMLHttpRequest', 'http:', 'https:', 'importScripts',
                     'sendBeacon', 'WebSocket', '.src =', 'googleapis'):
            self.assertNotIn(word, text)

    def test_queue_interface(self):
        text = script.bundle(ROOT)
        for name in ('tarkTranslate.takeBatch = ', 'tarkTranslate.onResult = ',
                     'g.translate.TranslateService = ', 'cr.googleTranslate.onTranslateElementLoad()'):
            self.assertIn(name, text)


if __name__ == '__main__':
    unittest.main()
