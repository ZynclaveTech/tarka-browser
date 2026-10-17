#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Word-frequency lists for Tark's on-device transliteration (D1).

IndicXlit proposes a few spellings for a romanised word; Tark then prefers
the ones that are real words. This tool builds and packs the lists it needs.
It uses only the standard library, so it runs in the plain build environment.

    xlit_wordlist.py count --tag hi --top 50000 < corpus.txt > hi.tsv
    xlit_wordlist.py english <en.tsv> <english-exclude.txt> > english-common.txt
    xlit_wordlist.py pack <words-dir> <english.txt[.xz]> <out.bin>

count
-----
Reads UTF-8 text on stdin (as a stream; nothing is kept but the counts) and
prints the TOP most frequent words (seen at least --min-count times) as
"word<TAB>count", commonest first, ties broken by the word. A word is a run
of the script's letters and combining marks that is bounded by whitespace or
punctuation on both sides. A token that mixes in Latin letters, digits,
danda, or any other character is not a word. Text is NFC-normalised first
(the model emits NFC), so the precomposed nukta letters U+0958..U+095F count as the
base letter plus nukta.

The tag "en" is English: the text is lower-cased and only a-z words count
(apostrophes are not delimiters, so "don't" is not a word).

english
-------
Takes the 20,000 commonest English words from a "count --tag en" file and
drops the ones in english-exclude.txt (romanised Indian words that an Indian
reader types as Indian-language text). One word per line comes out.

pack: TXLW v1 (all integers little-endian)
------------------------------------------
    8 bytes   magic  "TXLW" 01 00 00 00
    u32       header length H (the JSON plus trailing spaces, so that the
              first block starts on a 4-byte boundary of the file)
    H bytes   UTF-8 JSON {"<tag>": {"offset": N, "count": M}, ..., "en": ...}
    then      one block per tag, each starting on a 4-byte boundary at the
              absolute file offset "offset":
                M x u32   record offsets, relative to the block start,
                          in record order
                records   sorted by their UTF-8 bytes, each
                          u32 count, u16 byte length, the UTF-8 bytes
              The English block has count 0 in every record.

A reader binary-searches the M records by their bytes. The words directory
holds one "<tag>.tsv.xz" (or plain "<tag>.tsv") per language, "word<TAB>count".
"""

import argparse
import io
import json
import lzma
import os
import re
import struct
import sys
import unicodedata
from collections import Counter

MAGIC = b'TXLW\x01\x00\x00\x00'
CHUNK_BYTES = 8 << 20
# When the counter grows past this many distinct words, the words seen only
# once so far are dropped. They cannot reach a list of the top 100,000.
PRUNE_AT = 6_000_000
MAX_WORD_BYTES = 0xFFFF
MAX_COUNT = 0xFFFFFFFF

_DEVANAGARI = (0x0900, 0x097F)
_ARABIC = ((0x0600, 0x06FF), (0x0750, 0x077F))
SCRIPT_BLOCKS = {
    'as': ((0x0980, 0x09FF),),
    'bn': ((0x0980, 0x09FF),),
    'brx': (_DEVANAGARI,),
    'gom': (_DEVANAGARI,),
    'gu': ((0x0A80, 0x0AFF),),
    'hi': (_DEVANAGARI,),
    'kn': ((0x0C80, 0x0CFF),),
    'ks': _ARABIC,
    'mai': (_DEVANAGARI,),
    'ml': ((0x0D00, 0x0D7F),),
    'mni': ((0xAAE0, 0xAAFF), (0xABC0, 0xABFF)),
    'mr': (_DEVANAGARI,),
    'ne': (_DEVANAGARI,),
    'or': ((0x0B00, 0x0B7F),),
    'pa': ((0x0A00, 0x0A7F),),
    'sa': (_DEVANAGARI,),
    'sd': _ARABIC,
    'si': ((0x0D80, 0x0DFF),),
    'ta': ((0x0B80, 0x0BFF),),
    'te': ((0x0C00, 0x0C7F),),
    'ur': _ARABIC,
}
ENGLISH_TAG = 'en'
# Kept inside words although they are format characters: a word that has one
# is not in the model's vocabulary, so it is rejected rather than split.
_NOT_DELIMITERS = '‌‍'
_ENGLISH_APOSTROPHES = "'’"


def _ranges(chars):
    """Compresses a sorted iterable of code points into regex range text."""
    out, start, prev = [], None, None
    for cp in chars:
        if start is None:
            start = prev = cp
        elif cp == prev + 1:
            prev = cp
        else:
            out.append((start, prev))
            start = prev = cp
    if start is not None:
        out.append((start, prev))
    return ''.join(
        re.escape(chr(a)) if a == b else '%s-%s' % (re.escape(chr(a)),
                                                    re.escape(chr(b)))
        for a, b in out)


def _delimiters(english):
    chars = []
    for cp in range(0x10000):
        ch = chr(cp)
        if ch in _NOT_DELIMITERS or 0xD800 <= cp <= 0xDFFF:
            continue
        if english and ch in _ENGLISH_APOSTROPHES:
            continue
        if unicodedata.category(ch)[0] in 'PSZC' and \
                unicodedata.category(ch) != 'Cn' and \
                unicodedata.category(ch) != 'Co':
            chars.append(cp)
    return _ranges(chars)


def _word_class(tag):
    if tag == ENGLISH_TAG:
        return 'a-z'
    chars = []
    for lo, hi in SCRIPT_BLOCKS[tag]:
        for cp in range(lo, hi + 1):
            if unicodedata.category(chr(cp))[0] in 'LM':
                chars.append(cp)
    return _ranges(chars)


_PATTERNS = {}


def _pattern(tag):
    if tag not in _PATTERNS:
        if tag != ENGLISH_TAG and tag not in SCRIPT_BLOCKS:
            raise ValueError('unknown tag: %r' % tag)
        delim = _delimiters(tag == ENGLISH_TAG)
        _PATTERNS[tag] = re.compile(
            '(?<![^%s])[%s]+(?![^%s])' % (delim, _word_class(tag), delim))
    return _PATTERNS[tag]


def count_words(tag, stream, out, top, min_count=1):
    """Counts the words of `tag` in the text `stream`; writes the top `top`
    that occur at least `min_count` times."""
    pattern = _pattern(tag)
    english = tag == ENGLISH_TAG
    counts = Counter()
    while True:
        text = stream.read(CHUNK_BYTES // 2)
        if not text:
            break
        text += stream.readline()  # end the chunk on a line boundary
        text = unicodedata.normalize('NFC', text)
        if english:
            text = text.lower()
        counts.update(pattern.findall(text))
        if len(counts) > PRUNE_AT:
            counts = Counter({w: n for w, n in counts.items() if n > 1})
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ranked = [item for item in ranked if item[1] >= min_count]
    for word, n in ranked[:top]:
        out.write('%s\t%d\n' % (word, n))


def build_english(tsv, exclude, out, top=20000):
    """Writes the English list: the `top` commonest words of the "word<TAB>
    count" stream `tsv`, one per line, minus the words in `exclude`.

    `exclude` has one word per line, optionally followed by a TAB and the
    reason. Blank lines and lines starting with "#" are skipped."""
    excluded = set()
    for number, line in enumerate(exclude, 1):
        line = line.rstrip('\n')
        if not line or line.startswith('#'):
            continue
        word = line.split('\t', 1)[0]
        if not re.fullmatch('[a-z]+', word):
            raise ValueError('exclude line %d: %r is not a-z only' %
                             (number, word))
        excluded.add(word)
    kept = 0
    for line in tsv:
        if kept >= top:
            break
        kept += 1
        word = line.split('\t', 1)[0]
        if word not in excluded:
            out.write(word + '\n')


def _open_text(path):
    if path.endswith('.xz'):
        return lzma.open(path, 'rt', encoding='utf-8')
    return open(path, 'r', encoding='utf-8')


def _read_records(path, with_counts):
    merged = {}
    with _open_text(path) as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip('\n')
            if not line:
                continue
            word, _, rest = line.partition('\t')
            try:
                n = min(int(rest), MAX_COUNT) if with_counts else 0
            except ValueError:
                raise ValueError('%s:%d: bad count in %r' %
                                 (path, number, line))
            data = word.encode('utf-8')
            if not data or len(data) > MAX_WORD_BYTES:
                raise ValueError('%s:%d: bad word length' % (path, number))
            merged[data] = min(merged.get(data, 0) + n, MAX_COUNT)
    return sorted(merged.items())


def _block(records):
    offsets, body, pos = [], bytearray(), 4 * len(records)
    for data, n in records:
        offsets.append(pos + len(body))
        body += struct.pack('<IH', n, len(data)) + data
    block = struct.pack('<%dI' % len(offsets), *offsets) + bytes(body)
    return block + b'\0' * (-len(block) % 4)


def pack(words_dir, english_path, out_path):
    """Packs the per-language lists and the English list into TXLW v1."""
    blocks = {}
    for name in sorted(os.listdir(words_dir)):
        m = re.fullmatch(r'([a-z]+)\.tsv(\.xz)?', name)
        if m:
            blocks[m.group(1)] = _read_records(
                os.path.join(words_dir, name), True)
    if ENGLISH_TAG in blocks:
        raise ValueError('"en" must come from the English list, not a tsv')
    blocks[ENGLISH_TAG] = _read_records(english_path, False)
    payload = {tag: _block(records) for tag, records in sorted(blocks.items())}
    counts = {tag: len(records) for tag, records in blocks.items()}

    header_len = 0
    for _ in range(8):
        offset = 12 + header_len
        entries = {}
        for tag in sorted(payload):
            entries[tag] = {'offset': offset, 'count': counts[tag]}
            offset += len(payload[tag])
        raw = json.dumps(entries, separators=(',', ':')).encode('utf-8')
        want = len(raw) + (-(12 + len(raw)) % 4)
        if want == header_len:
            break
        header_len = want
    else:
        raise RuntimeError('header size did not settle')
    raw += b' ' * (header_len - len(raw))
    with open(out_path, 'wb') as f:
        f.write(MAGIC + struct.pack('<I', header_len) + raw)
        for tag in sorted(payload):
            f.write(payload[tag])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('count', help='count words on stdin')
    c.add_argument('--tag', required=True,
                   choices=sorted(SCRIPT_BLOCKS) + [ENGLISH_TAG])
    c.add_argument('--top', type=int, default=50000)
    c.add_argument('--min-count', type=int, default=1,
                   help='drop words seen fewer times (for tiny corpora)')
    e = sub.add_parser('english', help='cut the English list')
    e.add_argument('counts', help='word<TAB>count file, commonest first')
    e.add_argument('exclude', help='english-exclude.txt')
    e.add_argument('--top', type=int, default=20000)
    p = sub.add_parser('pack', help='pack lists into a TXLW v1 file')
    p.add_argument('words_dir')
    p.add_argument('english')
    p.add_argument('out')
    args = parser.parse_args(argv)
    if args.command == 'count':
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8',
                                 errors='replace', newline='')
        stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  newline='\n')
        count_words(args.tag, stdin, stdout, args.top, args.min_count)
        stdout.flush()
    elif args.command == 'english':
        with open(args.counts, encoding='utf-8') as tsv, \
                open(args.exclude, encoding='utf-8') as exclude:
            build_english(tsv, exclude, sys.stdout, args.top)
    else:
        pack(args.words_dir, args.english, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
