"""Tests for utils/captions_export.py (D4): the caption model files Tark
ships and the reference outputs components/tark_captions is tested against.

Needs torch and onnxruntime (the D4 spike's Python environment) and the
IndicConformer and Silero VAD files:
  TARK_CAPTIONS_SRC_MODELS = IndicConformer's assets/ folder
  TARK_CAPTIONS_SRC_VAD    = silero_vad.onnx
Skipped otherwise.
"""
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'captions_export.py')
TESTDATA = os.path.join(REPO, 'resources', 'captions', 'testdata')
MODELS = os.environ.get('TARK_CAPTIONS_SRC_MODELS')
VAD = os.environ.get('TARK_CAPTIONS_SRC_VAD')
HAVE_DEPS = all(importlib.util.find_spec(m) for m in ('torch', 'onnxruntime', 'numpy'))


@unittest.skipUnless(HAVE_DEPS and MODELS and VAD, 'needs the D4 spike environment and model files')
class TestCaptionsExport(unittest.TestCase):
    def test_export_writes_window_and_mel_fb(self):
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([sys.executable, SCRIPT, 'export', MODELS, VAD, out], check=True)
            self.assertEqual(os.path.getsize(os.path.join(out, 'window.f32')), 400 * 4)
            self.assertEqual(os.path.getsize(os.path.join(out, 'mel_fb.f32')), 257 * 80 * 4)
            with open(os.path.join(out, 'window.f32'), 'rb') as f:
                self.assertEqual(struct.unpack('<f', f.read(4))[0], 0.0)
            for name in ('encoder.int8.onnx', 'ctc_decoder.onnx', 'vocab.json',
                         'language_masks.json', 'silero_vad.onnx'):
                self.assertTrue(os.path.isfile(os.path.join(out, name)), name)

    def test_golden_has_all_clips(self):
        with tempfile.TemporaryDirectory() as out:
            golden = os.path.join(out, 'golden.json')
            subprocess.run([sys.executable, SCRIPT, 'golden', MODELS, VAD, TESTDATA, golden], check=True)
            with open(golden, encoding='utf-8') as f:
                clips = json.load(f)['clips']
        self.assertEqual(sorted(c['lang'] for c in clips), ['bn', 'hi', 'hi', 'ta'])
        for clip in clips:
            self.assertTrue(clip['ctc_text'].strip(), clip['wav'])
            self.assertEqual(clip['features_frames'], clip['samples'] // 160 + 1)
            self.assertEqual([len(row) for row in clip['features_head']], [80] * 5)
            self.assertEqual(len(clip['vad_probs']), clip['samples'] // 512)


if __name__ == '__main__':
    unittest.main()
