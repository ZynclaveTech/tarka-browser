"""Tests for utils/xlit_reference.py: the numpy IndicXlit reference."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import numpy as np
except ImportError:  # the reference needs numpy; the other tests do not
    np = None

if np is not None:
    import xlit_reference  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), '..', '..')
MODEL_ENV = 'TARK_XLIT_MODEL'
DEFAULT_MODEL = os.path.join(
    REPO, 'build/src/third_party/indicxlit/xlit-model.bin')


def write_blob(path, header, tensors):
    """Writes a TXLM v1 file from {name: float16 ndarray}."""
    data = bytearray()
    index = {}
    for name, arr in tensors.items():
        data.extend(b'\0' * (-len(data) % 64))
        index[name] = {'offset': len(data), 'shape': list(arr.shape)}
        data.extend(arr.astype('<f2').tobytes())
    header = dict(header, tensors=index)
    raw = json.dumps(header).encode('utf-8')
    raw += b' ' * (-(12 + len(raw)) % 64)
    with open(path, 'wb') as f:
        f.write(b'TXLM\x01\x00\x00\x00' + struct.pack('<I', len(raw)) + raw)
        f.write(bytes(data))


@unittest.skipIf(np is None, 'numpy not installed')
class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'm.bin')

    def test_reads_header_and_tensors(self):
        weights = np.arange(6, dtype=np.float16).reshape(2, 3)
        bias = np.array([0.5, -1.5], dtype=np.float16)
        write_blob(self.path, {'config': {'x': 1}, 'src_vocab': ['a'],
                               'tgt_vocab': ['b']},
                   {'w': weights, 'b': bias})
        model = xlit_reference.load_model(self.path)
        self.assertEqual(model.config, {'x': 1})
        self.assertEqual(model.src_vocab, ['a'])
        self.assertEqual(model.tgt_vocab, ['b'])
        self.assertEqual(model.weights['w'].dtype, np.float32)
        np.testing.assert_array_equal(model.weights['w'], weights)
        np.testing.assert_array_equal(model.weights['b'], bias)

    def test_rejects_bad_magic(self):
        with open(self.path, 'wb') as f:
            f.write(b'NOPE\x01\x00\x00\x00' + b'\0' * 64)
        with self.assertRaises(xlit_reference.ModelError):
            xlit_reference.load_model(self.path)

    def test_rejects_truncated_tensor(self):
        write_blob(self.path, {'config': {}, 'src_vocab': [],
                               'tgt_vocab': []},
                   {'w': np.zeros((8, 8), dtype=np.float16)})
        with open(self.path, 'rb') as f:
            blob = f.read()
        with open(self.path, 'wb') as f:
            f.write(blob[:-20])
        with self.assertRaises(xlit_reference.ModelError):
            xlit_reference.load_model(self.path)

    def test_sinusoidal_positions_match_fairseq(self):
        pos = xlit_reference.sinusoid(4, 8, pad=1)
        self.assertEqual(pos.shape, (4, 8))
        np.testing.assert_array_equal(pos[1], np.zeros(8))
        # row 0: sin(0)=0 for the first half, cos(0)=1 for the second
        np.testing.assert_allclose(pos[0], [0, 0, 0, 0, 1, 1, 1, 1])
        # row 2, first frequency is 1 rad per position
        self.assertAlmostEqual(float(pos[2][0]), float(np.sin(2.0)), places=6)
        self.assertAlmostEqual(float(pos[2][4]), float(np.cos(2.0)), places=6)

    def test_gelu_is_exact_erf(self):
        x = np.array([-3.0, -0.5, 0.0, 0.5, 3.0], dtype=np.float32)
        expected = [-0.00404951, -0.15426877, 0.0, 0.34573123, 2.99595049]
        np.testing.assert_allclose(xlit_reference.gelu(x), expected,
                                   atol=1e-6)


@unittest.skipIf(np is None, 'numpy not installed')
class KnownOutputsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        if not os.path.exists(path):
            raise unittest.SkipTest('xlit-model.bin not present: ' + path)
        cls.model = xlit_reference.load_model(path)

    def top(self, tag, word):
        return xlit_reference.transliterate(self.model, tag, word)[0][0]

    def test_reference_known_outputs(self):
        self.assertEqual(self.top('hi', 'namaste'), 'नमस्ते')
        self.assertEqual(self.top('ta', 'vanakkam'), 'வணக்கம்')
        self.assertEqual(self.top('hi', 'dilli'), 'दिल्ली')

    def test_candidates_are_sorted_with_scores_in_unit_range(self):
        cands = xlit_reference.transliterate(self.model, 'hi', 'bharat')
        self.assertEqual(cands[0][0], 'भारत')
        scores = [s for _, s in cands]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0.0 < s <= 1.0 for s in scores))
        self.assertLessEqual(len(cands), 4)

    def test_unknown_language_is_an_error(self):
        with self.assertRaises(xlit_reference.ModelError):
            xlit_reference.transliterate(self.model, 'xx', 'abc')


PAD, EOS, UNK = 1, 2, 3


class ScriptedDecoder:
    """A decoder whose next-token distribution depends on the history."""

    def __init__(self, vocab, table):
        self.vocab, self.table = vocab, table
        self.hists = [()]

    def reorder(self, source):
        self.hists = [self.hists[i] for i in source]

    def step(self, last, step):
        rows = []
        for i, token in enumerate(last):
            if step > 0:
                self.hists[i] = self.hists[i] + (token,)
            probs = np.full(self.vocab, 1e-9)
            for t, p in self.table(self.hists[i], step).items():
                probs[t] = p
            rows.append(np.log(probs / probs.sum()))
        return np.array(rows)


@unittest.skipIf(np is None, 'numpy not installed')
class BeamSearchTest(unittest.TestCase):
    def run_search(self, table, beam=2, nbest=2, max_len=10):
        decoder = ScriptedDecoder(8, table)
        return xlit_reference.beam_search(decoder, 8, PAD, EOS, UNK, beam,
                                          nbest, max_len)

    def test_eos_ranked_below_beam_is_skipped(self):
        # fairseq finishes </s> only among the first `beam` of the 2*beam
        # candidates. At step 1 the </s> of hypothesis [4] is 4th (0.08), so
        # it is dropped: [4] must never be returned as a word.
        def table(hist, step):
            if step == 0:
                return {4: .4, 5: .3, 6: .2, 7: .1}
            if step == 1 and hist[-1] == 4:
                return {6: .5, 7: .3, EOS: .2}
            if step == 1 and hist[-1] == 5:
                return {6: .6, EOS: .2, 7: .2}
            return {EOS: 1.0}
        found = self.run_search(table)
        self.assertEqual([t for t, _ in found], [[4, 6], [5, 6]])
        # normalised by the length including </s>: log(p) / 3
        self.assertAlmostEqual(found[0][1], np.log(.2) / 3, places=5)
        self.assertAlmostEqual(found[1][1], np.log(.18) / 3, places=5)

    def test_eos_within_beam_finishes_and_beam_continues(self):
        def table(hist, step):
            if step == 0:
                return {4: .6, 5: .4}
            if step == 1:
                return {EOS: .5, 6: .5}
            return {EOS: 1.0}
        found = self.run_search(table, beam=2, nbest=2)
        # [4] ends within the beam; the beam goes on with [4, 6], whose
        # longer length gives it the better normalised score
        self.assertEqual([t for t, _ in found], [[4, 6], [4]])

    def test_forced_eos_at_max_len_returns_truncated_hypotheses(self):
        def table(hist, step):
            return {4: .5, 5: .5, EOS: 1e-9}
        found = self.run_search(table, max_len=3)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(len(toks) == 3 for toks, _ in found), found)

    def test_unk_is_not_blocked(self):
        def table(hist, step):
            return {UNK: .9, 4: .1} if step == 0 else {EOS: 1.0}
        found = self.run_search(table)
        self.assertEqual(found[0][0], [UNK])

    def test_pad_is_never_selected(self):
        def table(hist, step):
            return {PAD: .9, 4: .1} if step == 0 else {EOS: 1.0}
        found = self.run_search(table)
        self.assertTrue(all(PAD not in toks for toks, _ in found))

    def test_eos_is_not_allowed_first(self):
        def table(hist, step):
            return {EOS: .9, 4: .1} if step == 0 else {EOS: 1.0}
        found = self.run_search(table)
        self.assertTrue(all(toks for toks, _ in found))


RESOURCES = os.path.join(REPO, 'resources', 'xlit')


class GoldenFilesTest(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(RESOURCES, name), encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f if line.strip()]

    def test_golden_covers_every_input_and_language(self):
        inputs = self.read('golden-inputs.txt')
        self.assertEqual(len(inputs), 60)
        for needed in ('namaste', 'vanakkam', 'dilli', 'bharat', 'lakshan',
                       'taj', 'mahal'):
            self.assertIn(needed, inputs)
        lines = [line.split('\t') for line in self.read('golden.tsv')]
        tags = {fields[0] for fields in lines}
        self.assertEqual(len(tags), 21)
        self.assertNotIn('en', tags)
        self.assertEqual(len(lines), 60 * 21)
        self.assertEqual({fields[1] for fields in lines}, set(inputs))
        for fields in lines:
            self.assertGreaterEqual(len(fields), 3, fields)
            for cand in fields[2:]:
                text, _, score = cand.rpartition('|')
                self.assertTrue(text)
                self.assertTrue(0.0 < float(score) <= 1.0, cand)

    @unittest.skipIf(np is None, 'numpy not installed')
    def test_golden_lines_match_the_reference(self):
        path = os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        if not os.path.exists(path):
            self.skipTest('xlit-model.bin not present: ' + path)
        model = xlit_reference.load_model(path)
        lines = self.read('golden.tsv')
        for line in lines[::97]:  # a spread over tags and inputs
            tag, word, *cands = line.split('\t')
            got = xlit_reference.format_candidates(
                xlit_reference.transliterate(model, tag, word))
            self.assertEqual(got, '\t'.join(cands), (tag, word))


if __name__ == '__main__':
    unittest.main()
