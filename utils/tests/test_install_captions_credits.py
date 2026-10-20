"""Tests for utils/install_captions_credits.sh, the _install_captions_credits
step of dev.sh and build.sh (D4): about:credits lists what live captions run
on from README.chromium files under third_party/.
"""
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CREDITS = os.path.join(REPO, 'resources', 'captions', 'credits')
# credits folder -> third_party folder it is installed into.
DIRS = {
    'onnxruntime': 'tark_onnxruntime',
    'indicconformer': 'tark_indicconformer',
    'silero_vad': 'tark_silero_vad',
    # Phase 2: the translation model, and the MIT code Tark's C++ text steps
    # are ported from.
    'indictrans2': 'tark_indictrans2',
    'indicnlp': 'tark_indicnlp',
    'indictranstoolkit': 'tark_indictranstoolkit',
    'sacremoses': 'tark_sacremoses',
    # Phase 3: the spoken-language-ID model.
    'voxlingua_ecapa': 'tark_voxlingua_ecapa',
}
# Licence of each, when not MIT, and the words its LICENSE text starts with.
LICENCES = {'voxlingua_ecapa': 'Apache-2.0'}
LICENCE_TEXT = {'MIT': 'MIT License', 'Apache-2.0': 'Apache License'}
FIELDS = ('Name', 'URL', 'Version', 'License', 'License File', 'Shipped')


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


class TestCaptionsCredits(unittest.TestCase):
    def test_each_readme_has_the_credits_fields(self):
        for name in DIRS:
            readme = read(os.path.join(CREDITS, name, 'README.chromium'))
            fields = dict(re.findall(r'^([A-Za-z ]+): (.+)$', readme, re.M))
            for field in FIELDS:
                self.assertIn(field, fields, (name, field))
            self.assertEqual(fields['License'], LICENCES.get(name, 'MIT'), name)
            self.assertEqual(fields['Shipped'], 'yes', name)

    def test_models_bring_their_licence(self):
        for name in set(DIRS) - {'onnxruntime'}:
            self.assertIn(LICENCE_TEXT[LICENCES.get(name, 'MIT')],
                          read(os.path.join(CREDITS, name, 'LICENSE')), name)

    def test_install_copies_into_third_party(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src')
            # The ONNX Runtime release brings its own LICENSE.
            os.makedirs(os.path.join(src, 'third_party', 'tark_onnxruntime'))
            with open(os.path.join(src, 'third_party', 'tark_onnxruntime', 'LICENSE'), 'w') as f:
                f.write('release licence')
            subprocess.run(
                ['bash', '-c', 'set -euo pipefail; source utils/install_captions_credits.sh; '
                 '_install_captions_credits'],
                cwd=REPO, check=True,
                env=dict(os.environ, _root_dir=REPO, _src_dir=src))
            for name, folder in DIRS.items():
                dest = os.path.join(src, 'third_party', folder)
                self.assertEqual(read(os.path.join(dest, 'README.chromium')),
                                 read(os.path.join(CREDITS, name, 'README.chromium')))
                self.assertTrue(os.path.isfile(os.path.join(dest, 'LICENSE')), name)
            self.assertEqual(read(os.path.join(src, 'third_party', 'tark_onnxruntime', 'LICENSE')),
                             'release licence')


if __name__ == '__main__':
    unittest.main()
