"""Tark for Android's page-translate script (plan Task 4). The patch is
generated from android/translate/script/ by android/translate/script.py and
must stay identical to it. The script's behaviour is tested by node:
node --test android/translate/script/test/batcher.test.mjs. Runs offline."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANDROID = ROOT / 'android'
sys.path.insert(0, str(ANDROID / 'translate'))
import script  # noqa: E402

PATCH = ANDROID / 'patches' / 'page-translate-script.patch'


class TestTranslateScriptPatch(unittest.TestCase):
    def test_patch_is_current(self):
        self.assertEqual(PATCH.read_text(encoding='utf-8'), script.build(ROOT),
                         'run android/translate/script.py build after changing the script')

    def test_patch_files(self):
        paths = re.findall(r'^\+\+\+ b/(\S+)', PATCH.read_text(encoding='utf-8'), re.M)
        self.assertEqual(paths, ['components/resources/components_resources.grd',
                                 'components/resources/tark_translate_resources.grdp',
                                 'components/translate/core/browser/resources/tark_translate.js'])

    def test_resource_named(self):
        self.assertIn('<include name="IDR_TARK_TRANSLATE_JS" ', PATCH.read_text(encoding='utf-8'))

    def test_in_series(self):
        series = [l.strip() for l in (ANDROID / 'patches' / 'series').read_text(encoding='utf-8').splitlines()
                  if l.strip() and not l.lstrip().startswith('#')]
        self.assertIn('page-translate-script.patch', series)

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
