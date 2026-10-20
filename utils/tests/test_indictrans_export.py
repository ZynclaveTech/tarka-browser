"""Tests for utils/indictrans_export.py (D4 Phase 2): the IndicTrans2 files
Tark's translation engine loads, and the reference outputs it is tested
against.

Needs the D4 spike's Python environment (torch, onnxruntime, sentencepiece,
safetensors, IndicTransToolkit) and AI4Bharat's checkpoints:
  TARK_MT_SRC_INDIC_EN = indictrans2-indic-en-dist-200M (Hugging Face folder)
  TARK_MT_SRC_EN_INDIC = indictrans2-en-indic-dist-200M
  TARK_CAPTIONS_MODELS = a models folder that already has it2_indic_en/ and
                         it2_en_indic/ (for the golden test)
Skipped otherwise.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'indictrans_export.py')
TESTDATA = os.path.join(REPO, 'resources', 'captions', 'testdata')
INDIC_EN = os.environ.get('TARK_MT_SRC_INDIC_EN')
EN_INDIC = os.environ.get('TARK_MT_SRC_EN_INDIC')
MODELS = os.environ.get('TARK_CAPTIONS_MODELS')
HAVE_DEPS = all(importlib.util.find_spec(m) for m in
                ('torch', 'onnxruntime', 'sentencepiece', 'safetensors', 'IndicTransToolkit'))
FILES = ('encoder.int8.onnx', 'decoder_step.int8.onnx', 'model.SRC', 'dict.SRC.json',
         'dict.TGT.json', 'config.json', 'LICENSE.txt')
STAGES = ('id', 'lang', 'caption', 'normalized', 'model_input', 'src_ids', 'out_ids',
          'english_tokens', 'english', 'pivot')


@unittest.skipUnless(HAVE_DEPS and INDIC_EN and EN_INDIC, 'needs the D4 spike environment and checkpoints')
class TestExport(unittest.TestCase):
    def test_export_writes_both_directions(self):
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([sys.executable, SCRIPT, 'export', INDIC_EN, EN_INDIC, out], check=True)
            for folder in ('it2_indic_en', 'it2_en_indic'):
                for name in FILES:
                    self.assertTrue(os.path.isfile(os.path.join(out, folder, name)), (folder, name))


@unittest.skipUnless(HAVE_DEPS and MODELS, 'needs the D4 spike environment and exported models')
class TestGolden(unittest.TestCase):
    def test_golden_has_every_stage(self):
        with tempfile.TemporaryDirectory() as out:
            golden = os.path.join(out, 'mt_golden.json')
            subprocess.run([sys.executable, SCRIPT, 'golden', MODELS, TESTDATA, golden], check=True)
            with open(golden, encoding='utf-8') as f:
                cases = json.load(f)['cases']
        self.assertEqual(len(cases), 16)
        for case in cases:
            for key in STAGES:
                self.assertIn(key, case, (case['id'], key))
            self.assertEqual(case['src_ids'][-1], 2, case['id'])
            self.assertLessEqual(len(case['src_ids']), 256, case['id'])
            self.assertTrue(case['english'].strip(), case['id'])
            others = sorted({'hi', 'ta', 'bn'} - {case['lang']})
            self.assertEqual(sorted(case['pivot']), others, case['id'])
            for target in others:
                self.assertTrue(case['pivot'][target]['text'].strip(), (case['id'], target))


if __name__ == '__main__':
    unittest.main()
