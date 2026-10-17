"""Tests for utils/xlit_wordlist.py: word counting and the TXLW v1 pack."""
import io
import json
import lzma
import os
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import xlit_wordlist  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), '..', '..')
MODEL_ENV = 'TARK_XLIT_MODEL'
WORDS_ENV = 'TARK_XLIT_WORDS'
DEFAULT_MODEL = os.path.join(
    REPO, 'build/src/third_party/indicxlit/xlit-model.bin')
DEFAULT_WORDS = os.path.join(
    REPO, 'build/src/third_party/indicxlit/xlit-words.bin')


def count(tag, text, top=50000, min_count=1):
    out = io.StringIO()
    xlit_wordlist.count_words(tag, io.StringIO(text), out, top, min_count)
    return [line.split('\t') for line in out.getvalue().splitlines()]


def read_words_blob(path):
    """A small independent reader for TXLW v1 (binary search per block)."""
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == b'TXLW\x01\x00\x00\x00'
    (hlen,) = struct.unpack_from('<I', data, 8)
    header = json.loads(data[12:12 + hlen])
    return data, header


def lookup(data, header, tag, word):
    """Returns the count of `word` in `tag`'s block, or None if absent."""
    entry = header[tag]
    base, n = entry['offset'], entry['count']
    key = word.encode('utf-8')
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        (rec,) = struct.unpack_from('<I', data, base + 4 * mid)
        pos = base + rec
        cnt, length = struct.unpack_from('<IH', data, pos)
        got = data[pos + 6:pos + 6 + length]
        if got == key:
            return cnt
        if got < key:
            lo = mid + 1
        else:
            hi = mid
    return None


class CountTest(unittest.TestCase):
    def test_count_keeps_only_script(self):
        self.assertEqual(
            count('hi', 'नमस्ते namaste नमस्ते 123 भारत।'),
            [['नमस्ते', '2'], ['भारत', '1']])

    def test_mixed_script_and_digit_tokens_are_dropped(self):
        self.assertEqual(count('hi', 'abcनमस्ते नमस्ते2 (भारत) "दिल्ली"'),
                         [['दिल्ली', '1'], ['भारत', '1']])

    def test_script_is_per_tag(self):
        # Tamil text under the Hindi tag and vice versa count nothing.
        self.assertEqual(count('hi', 'வணக்கம்'), [])
        self.assertEqual(count('ta', 'வணக்கம் नमस्ते'), [['வணக்கம்', '1']])

    def test_nfc_folds_precomposed_nukta(self):
        # U+0958 (क़) is a composition exclusion; NFC makes it क + nukta,
        # which is what the model emits.
        self.assertEqual(count('hi', 'क़ीमत क़ीमत'),
                         [['क़ीमत', '2']])

    def test_english_is_lowercase_ascii_letters_only(self):
        self.assertEqual(
            count('en', "The the café don't x-ray 42 Hello"),
            [['the', '2'], ['hello', '1'], ['ray', '1'], ['x', '1']])

    def test_top_n_and_order(self):
        text = 'क ख ख ग ग ग घ घ घ घ ङ ङ ङ ङ'
        # commonest first; ties are broken by the word, so the order is stable
        expected = [['घ', '4'], ['ङ', '4'], ['ग', '3'], ['ख', '2'],
                    ['क', '1']]
        self.assertEqual(count('hi', text), expected)
        self.assertEqual(count('hi', text, top=3), expected[:3])

    def test_min_count_drops_rare_words(self):
        text = 'क ख ख ग ग ग'
        self.assertEqual(count('hi', text, min_count=2),
                         [['ग', '3'], ['ख', '2']])

    def test_cli_reads_stdin(self):
        script = os.path.join(os.path.dirname(__file__), '..',
                              'xlit_wordlist.py')
        out = subprocess.run(
            [sys.executable, script, 'count', '--tag', 'hi', '--top', '5'],
            input='नमस्ते नमस्ते भारत'.encode('utf-8'),
            capture_output=True, check=True).stdout.decode('utf-8')
        self.assertEqual(out, 'नमस्ते\t2\nभारत\t1\n')


class EnglishListTest(unittest.TestCase):
    def build(self, tsv, exclude, top=20000):
        out = io.StringIO()
        xlit_wordlist.build_english(io.StringIO(tsv), io.StringIO(exclude),
                                    out, top)
        return out.getvalue().splitlines()

    def test_takes_top_n_then_removes_excluded(self):
        tsv = 'the\t9\nnamaste\t8\nof\t7\nbhai\t6\nand\t5\n'
        exclude = '# romanised Hindi\nnamaste\tgreeting\n\nbhai\n'
        # the cut is made before the exclusions, so top=4 leaves 2 words
        self.assertEqual(self.build(tsv, exclude, top=4), ['the', 'of'])
        self.assertEqual(self.build(tsv, exclude), ['the', 'of', 'and'])

    def test_exclude_entries_not_in_the_list_are_harmless(self):
        self.assertEqual(self.build('the\t1\n', 'zzz\treason\n'), ['the'])

    def test_rejects_non_ascii_exclude(self):
        with self.assertRaises(ValueError):
            self.build('the\t1\n', 'नमस्ते\treason\n')


class PackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write_xz(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with lzma.open(path, 'wt', encoding='utf-8') as f:
            f.write(text)
        return path

    def test_pack_round_trip(self):
        words = os.path.join(self.tmp.name, 'words')
        os.mkdir(words)
        self.write_xz('words/hi.tsv.xz', 'भारत\t90\nनमस्ते\t50\nदिल्ली\t7\n')
        self.write_xz('words/ta.tsv.xz', 'வணக்கம்\t11\nசென்னை\t3\n')
        english = self.write_xz('english.txt.xz', 'the\nhello\nnamaste\n')
        out = os.path.join(self.tmp.name, 'xlit-words.bin')
        xlit_wordlist.pack(words, english, out)
        data, header = read_words_blob(out)
        self.assertEqual(sorted(header), ['en', 'hi', 'ta'])
        self.assertEqual(header['hi']['count'], 3)
        self.assertEqual(header['en']['count'], 3)
        for tag in header:
            self.assertEqual(header[tag]['offset'] % 4, 0)
        self.assertEqual(lookup(data, header, 'hi', 'भारत'), 90)
        self.assertEqual(lookup(data, header, 'hi', 'दिल्ली'), 7)
        self.assertEqual(lookup(data, header, 'hi', 'नमस्ते'), 50)
        self.assertIsNone(lookup(data, header, 'hi', 'मुंबई'))
        self.assertEqual(lookup(data, header, 'ta', 'சென்னை'), 3)
        self.assertEqual(lookup(data, header, 'en', 'hello'), 0)
        self.assertIsNone(lookup(data, header, 'en', 'world'))

    def test_pack_is_deterministic_and_sorted_by_bytes(self):
        words = os.path.join(self.tmp.name, 'words')
        os.mkdir(words)
        self.write_xz('words/hi.tsv.xz', 'ग\t1\nक\t2\nख\t3\n')
        english = self.write_xz('english.txt.xz', 'b\na\n')
        a = os.path.join(self.tmp.name, 'a.bin')
        b = os.path.join(self.tmp.name, 'b.bin')
        xlit_wordlist.pack(words, english, a)
        xlit_wordlist.pack(words, english, b)
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            self.assertEqual(fa.read(), fb.read())
        data, header = read_words_blob(a)
        base = header['hi']['offset']
        keys = []
        for i in range(3):
            (rec,) = struct.unpack_from('<I', data, base + 4 * i)
            _, n = struct.unpack_from('<IH', data, base + rec)
            keys.append(data[base + rec + 6:base + rec + 6 + n])
        self.assertEqual(keys, sorted(keys))

    def test_pack_accepts_plain_text(self):
        words = os.path.join(self.tmp.name, 'words')
        os.mkdir(words)
        with open(os.path.join(words, 'hi.tsv'), 'w', encoding='utf-8') as f:
            f.write('भारत\t2\n')
        english = os.path.join(self.tmp.name, 'english.txt')
        with open(english, 'w', encoding='utf-8') as f:
            f.write('hello\n')
        out = os.path.join(self.tmp.name, 'o.bin')
        xlit_wordlist.pack(words, english, out)
        data, header = read_words_blob(out)
        self.assertEqual(lookup(data, header, 'hi', 'भारत'), 2)


class BundleBudgetTest(unittest.TestCase):
    def test_bundle_budget(self):
        model = os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        words = os.environ.get(WORDS_ENV, DEFAULT_WORDS)
        if not (os.path.exists(model) and os.path.exists(words)):
            self.skipTest('model or words blob not present')
        total = os.path.getsize(model) + os.path.getsize(words)
        self.assertLessEqual(total, 60 * 1024 * 1024, total)


if __name__ == '__main__':
    unittest.main()
