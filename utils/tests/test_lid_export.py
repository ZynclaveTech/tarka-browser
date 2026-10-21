"""Tests for utils/lid_export.py (D4 Phase 3): the spoken-language-ID model
Tark's speech process runs before it captions (SpeechBrain's VoxLingua107
ECAPA, Apache-2.0), exported to one ONNX file from waveform to scores.

Needs the D4 spike's Python environment (torch, speechbrain, onnxruntime,
soundfile) and:
  TARK_LID_SRC    = the SpeechBrain model folder (hyperparams.yaml,
                    embedding_model.ckpt, classifier.ckpt, label_encoder.ckpt)
  TARK_LID_FLEURS = a folder of FLEURS test languages (<code>/test/*.wav)
Skipped otherwise.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'lid_export.py')
SRC = os.environ.get('TARK_LID_SRC')
FLEURS = os.environ.get('TARK_LID_FLEURS')
HAVE_DEPS = all(importlib.util.find_spec(m) for m in
                ('torch', 'speechbrain', 'onnxruntime', 'soundfile'))


@unittest.skipUnless(HAVE_DEPS and SRC and FLEURS, 'needs the D4 spike environment and model')
class TestLidExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        subprocess.run([sys.executable, SCRIPT, 'export', SRC, cls.tmp.name], check=True)
        sys.path.insert(0, os.path.join(REPO, 'utils'))
        import lid_export
        cls.lid = lid_export

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_labels_in_order(self):
        with open(os.path.join(self.tmp.name, 'lid_labels.txt'), encoding='utf-8') as f:
            labels = f.read().split('\n')[:-1]
        self.assertEqual(len(labels), 107)
        self.assertEqual((labels[0], labels[45], labels[106]), ('ab', 'ja', 'zh'))

    def test_export_matches_speechbrain(self):
        import numpy as np
        import onnxruntime
        import torch
        from speechbrain.inference.classifiers import EncoderClassifier
        reference = EncoderClassifier.from_hparams(source=SRC, savedir=SRC,
                                                   run_opts={"device": "cpu"})
        session = onnxruntime.InferenceSession(os.path.join(self.tmp.name, 'lid.onnx'))
        clips = self.lid.fleurs_clips(FLEURS, ['hi_in', 'ta_in', 'bn_in', 'en_us', 'es_419'],
                                      per_language=4, seconds=3.0)
        self.assertEqual(len(clips), 20)
        for code, wav in clips:
            want = reference.classify_batch(torch.from_numpy(wav)[None])[0][0].numpy()
            got = session.run(['logits'], {'waveform': wav[None]})[0][0]
            np.testing.assert_allclose(got, want, atol=1e-3, err_msg=code)
            self.assertEqual(int(np.argmax(got)), int(np.argmax(want)), code)


class TestDecide(unittest.TestCase):
    """The Python twin of DetectionPolicy (components/tark_captions)."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, 'utils'))
        import lid_export
        self.lid = lid_export
        self.labels = ['ab', 'as', 'bn', 'en', 'es', 'hi', 'sw', 'ta', 'te', 'ur']

    def probs(self, **p):
        rest = (1.0 - sum(p.values())) / (len(self.labels) - len(p))
        return [p.get(code, rest) for code in self.labels]

    def test_urdu_counts_as_hindi(self):
        self.assertEqual(self.lid.decide(self.probs(ur=0.65, hi=0.3), self.labels, 3.0),
                         ('caption', 'hi'))

    def test_nothing_before_three_seconds(self):
        self.assertEqual(self.lid.decide(self.probs(es=0.99), self.labels, 2.9), ('unsure', ''))

    def test_swahili_unsupported(self):
        self.assertEqual(self.lid.decide(self.probs(sw=0.95), self.labels, 3.0),
                         ('unsupported', 'sw'))


if __name__ == '__main__':
    unittest.main()
