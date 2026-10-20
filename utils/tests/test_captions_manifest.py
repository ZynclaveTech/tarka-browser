"""Tests for utils/captions_manifest.py (D4 Phase 4): the table of model
files, sizes and SHA-256 hashes compiled into Tark."""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'captions_manifest.py')
CAPTIONS = ('encoder.int8.onnx', 'ctc_decoder.onnx', 'vocab.json', 'language_masks.json',
            'window.f32', 'mel_fb.f32', 'silero_vad.onnx')
TRANSLATION = ('encoder.int8.onnx', 'decoder_step.int8.onnx', 'model.SRC', 'dict.SRC.json',
               'dict.TGT.json', 'config.json', 'LICENSE.txt')


LANGUAGE_ID = ('lid.onnx', 'lid_labels.txt')


def make_models(root):
    files = {}
    paths = list(CAPTIONS) + [f'it2_indic_en/{n}' for n in TRANSLATION] + \
        [f'it2_en_indic/{n}' for n in TRANSLATION] + list(LANGUAGE_ID)
    for i, path in enumerate(paths):
        data = f'file {i} {path}'.encode() * (i + 1)
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as f:
            f.write(data)
        files[path] = (len(data), hashlib.sha256(data).hexdigest())
    return files


class TestCaptionsManifest(unittest.TestCase):
    def test_every_published_name_has_an_extension(self):
        # gettarka.com's CloudFront function serves a path with no extension as
        # <path>/index.html, so a model file named LICENSE would 404.
        sys.path.insert(0, os.path.join(REPO, 'utils'))
        import captions_manifest
        for _, _, _, paths in captions_manifest.UNITS:
            for path in paths:
                self.assertIn('.', os.path.basename(path), path)

    def test_manifest_lists_every_file_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = make_models(tmp)
            out = os.path.join(tmp, 'model_manifest.cc')
            subprocess.run([sys.executable, SCRIPT, tmp, out], check=True)
            with open(out, encoding='utf-8') as f:
                cc = f.read()
        rows = re.findall(r'\{"([^"]+)", (\d+), "([0-9a-f]{64})"\}', cc)
        self.assertEqual(sorted(p for p, _, _ in rows), sorted(files))
        for path, size, sha in rows:
            self.assertEqual((int(size), sha), files[path], path)
        for unit in ('kCaptions, "captions"', 'kToEnglish, "to_english"',
                     'kFromEnglish, "from_english"', 'kLanguageId, "language_id"'):
            self.assertIn(unit, cc)

    def test_language_id_unit_has_the_detector(self):
        sys.path.insert(0, os.path.join(REPO, 'utils'))
        import captions_manifest
        units = {unit_id: paths for _, unit_id, _, paths in captions_manifest.UNITS}
        self.assertEqual(units['language_id'], ['lid.onnx', 'lid_labels.txt'])

    def test_check_finds_a_changed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_models(tmp)
            out = os.path.join(tmp, 'model_manifest.cc')
            subprocess.run([sys.executable, SCRIPT, tmp, out], check=True)
            ok = subprocess.run([sys.executable, SCRIPT, '--check', tmp, out])
            self.assertEqual(ok.returncode, 0)
            with open(os.path.join(tmp, 'vocab.json'), 'ab') as f:
                f.write(b'x')
            bad = subprocess.run([sys.executable, SCRIPT, '--check', tmp, out],
                                 capture_output=True)
            self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
    unittest.main()
