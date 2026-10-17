#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Converts the AI4Bharat IndicXlit checkpoint into Tark's TXLM v1 blob (D1).

IndicXlit (code and weights, MIT, "Copyright (c) 2022 AI4Bharat") is a fairseq
transformer that transliterates Latin text into 21 Indian scripts. The release
is a torch pickle that also holds optimiser state (138 MB, of which 46 MB is
weights). The browser must never load a pickle, so this tool turns it into a
flat, mmap-friendly file once, at setup time, with no dependency beyond the
standard library.

    python3 utils/xlit_convert.py --checkpoint indicxlit.pt \\
        --src-dict dict.en.txt --tgt-dict dict.hi.txt xlit-model.bin

TXLM v1 layout (all integers little-endian):

    8 bytes   magic  "TXLM" 01 00 00 00
    u32       header length H (the JSON plus trailing spaces, so that the
              data below starts on a 64-byte boundary of the file)
    H bytes   UTF-8 JSON {"config": {...}, "src_vocab": [...],
              "tgt_vocab": [...],
              "tensors": {"<fairseq name>": {"offset": N, "shape": [...]}}}
    then      the tensors as IEEE fp16, each 64-byte aligned; "offset" is
              relative to the first byte after the header.

Only the model's weights are written. The checkpoint's optimiser state is
dropped, and so are two buffers that carry no weights: "<side>.version" and
"<side>.embed_positions._float_tensor" (positions are sinusoidal and are
recomputed by the loader).

The checkpoint is read with a restricted unpickler that resolves exactly the
globals a torch.save of this file uses (torch's tensor rebuild helper, the
storage types, OrderedDict and argparse.Namespace, the last one mapped to an
inert stand-in). Anything else is refused, so a tampered file cannot execute
code. Storage data is read straight from the zip members.

The vocabulary is not inside the checkpoint. fairseq builds it from the
corpus-bin dictionaries: the specials <s>, <pad>, </s>, <unk>, then the first
token of every dictionary line, then the 22 language tags. The source
dictionary is dict.en.txt (54 symbols in all) and the target is any
dict.<lang>.txt (all are byte-identical; 806 symbols).

xlit setup (pending wiring)
---------------------------
downloads-tark.ini does not fetch these yet. When it does, the pinned inputs
are, all at Hugging Face ai4bharat/IndicXlit commit
e7049fe725b11c0a187d42edeb2f56aa1ffee5fd, under
https://huggingface.co/ai4bharat/IndicXlit/resolve/<commit>/indicxlit-en-indic-v1.0/

    transformer/indicxlit.pt   138135425 bytes
        sha256 2f03fe0dfb2edc40f3c11f9293c4feda4fa8ed5366fec2981391606f224a09f7
    corpus-bin/dict.en.txt     302 bytes
        sha256 5ed7b43557095f70f20bad9fb0484ea9f2099001467bc8c732c8a9e6b3d7c34a
    corpus-bin/dict.hi.txt     7594 bytes
        sha256 0fe786202f4418cec9d8fcd8413c715a2be7fabb5b58fdc47671e6227dde384f

Full URLs:
  https://huggingface.co/ai4bharat/IndicXlit/resolve/e7049fe725b11c0a187d42edeb2f56aa1ffee5fd/indicxlit-en-indic-v1.0/transformer/indicxlit.pt
  https://huggingface.co/ai4bharat/IndicXlit/resolve/e7049fe725b11c0a187d42edeb2f56aa1ffee5fd/indicxlit-en-indic-v1.0/corpus-bin/dict.en.txt
  https://huggingface.co/ai4bharat/IndicXlit/resolve/e7049fe725b11c0a187d42edeb2f56aa1ffee5fd/indicxlit-en-indic-v1.0/corpus-bin/dict.hi.txt

The weights are MIT; the licence text and README.chromium are in
resources/indicxlit/ and go to third_party/indicxlit/ with the blob.
"""

import argparse
import collections
import io
import json
import math
import os
import pickle
import struct
import sys
import tempfile
import zipfile

MAGIC = b'TXLM\x01\x00\x00\x00'
ALIGN = 64
CHUNK = 1 << 16

SPECIALS = ['<s>', '<pad>', '</s>', '<unk>']
# The order of lang_list.txt in the release; the tag's index in the source
# vocabulary is its token id (__hi__ is 38 in the 54-symbol source).
LANG_TAGS = ['__%s__' % code for code in (
    'en as bn brx gom gu hi kn ks mai ml mni mr ne or pa sa sd si ta te ur'
).split()]

REQUIRED_CONFIG = (
    'arch', 'encoder_layers', 'decoder_layers', 'encoder_embed_dim',
    'decoder_embed_dim', 'encoder_ffn_embed_dim', 'decoder_ffn_embed_dim',
    'encoder_attention_heads', 'decoder_attention_heads')
OPTIONAL_CONFIG = (
    'encoder_normalize_before', 'decoder_normalize_before',
    'layernorm_embedding', 'activation_fn', 'no_scale_embedding',
    'encoder_learned_pos', 'decoder_learned_pos',
    'no_token_positional_embeddings', 'share_decoder_input_output_embed',
    'share_all_embeddings', 'max_source_positions', 'max_target_positions',
    'encoder_langtok', 'decoder_langtok', 'lang_tok_style')

# Buffers that hold no weights (see the module docstring).
SKIPPED_SUFFIXES = ('.version', '.embed_positions._float_tensor')

# (tensor name, which vocabulary its first dimension must match)
VOCAB_ROWS = (('encoder.embed_tokens.weight', 'src'),
              ('decoder.embed_tokens.weight', 'tgt'),
              ('decoder.output_projection.weight', 'tgt'))

# torch storage class -> (struct format character, item size)
STORAGES = {'FloatStorage': ('f', 4), 'DoubleStorage': ('d', 8),
            'HalfStorage': ('e', 2)}


class ConvertError(Exception):
    """A checkpoint or dictionary that cannot be converted."""


class _Namespace:
    """Inert stand-in for argparse.Namespace; it only carries attributes."""


class _StorageType:
    def __init__(self, name):
        self.name = name


class _StorageRef:
    def __init__(self, storage_type, key, numel):
        self.storage_type, self.key, self.numel = storage_type, key, numel


class _TensorRef:
    def __init__(self, storage, offset, shape, stride):
        self.storage, self.offset = storage, offset
        self.shape, self.stride = tuple(shape), tuple(stride)


def _rebuild_tensor_v2(storage, offset, size, stride, requires_grad=False,
                       backward_hooks=None, metadata=None):
    return _TensorRef(storage, offset, size, stride)


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ('collections', 'OrderedDict'):
            return collections.OrderedDict
        if (module, name) == ('argparse', 'Namespace'):
            return _Namespace
        if (module, name) == ('torch._utils', '_rebuild_tensor_v2'):
            return _rebuild_tensor_v2
        if module == 'torch' and name in STORAGES:
            return _StorageType(name)
        raise ConvertError('refusing to unpickle %s.%s' % (module, name))

    def persistent_load(self, pid):
        if (not isinstance(pid, tuple) or len(pid) != 5 or
                pid[0] != 'storage' or not isinstance(pid[1], _StorageType)):
            raise ConvertError('unexpected persistent id in checkpoint')
        return _StorageRef(pid[1], str(pid[2]), pid[4])


def read_dict(path):
    """Returns the tokens of a fairseq dictionary file, in file order."""
    try:
        with open(path, 'rb') as f:
            text = f.read().decode('utf-8')
    except (OSError, UnicodeDecodeError) as e:
        raise ConvertError('cannot read dictionary %s: %s' % (path, e))
    tokens = []
    for line in text.split('\n'):
        line = line.rstrip()
        if not line:
            continue
        # fairseq's Dictionary.add_from_file: "<token> <count>".
        parts = line.rsplit(' ', 1)
        if len(parts) != 2:
            raise ConvertError('%s: malformed line %r' % (path, line))
        tokens.append(parts[0])
    return tokens


def build_vocab(dict_path):
    """Specials, the dictionary's tokens in file order, then the lang tags."""
    vocab = SPECIALS + read_dict(dict_path) + LANG_TAGS
    if len(set(vocab)) != len(vocab):
        seen, dup = set(), None
        for token in vocab:
            if token in seen:
                dup = token
                break
            seen.add(token)
        raise ConvertError('%s: duplicate vocabulary symbol %r' %
                           (dict_path, dup))
    return vocab


def _load_checkpoint(zf):
    pickles = [n for n in zf.namelist()
               if n == 'data.pkl' or n.endswith('/data.pkl')]
    if len(pickles) != 1:
        raise ConvertError('not a torch checkpoint (no unique data.pkl)')
    prefix = pickles[0][:-len('data.pkl')]
    obj = _RestrictedUnpickler(io.BytesIO(zf.read(pickles[0]))).load()
    if (not isinstance(obj, dict) or not isinstance(obj.get('model'), dict) or
            not isinstance(obj.get('cfg'), dict)):
        raise ConvertError('checkpoint has no model weights or cfg')
    return obj, prefix


def _config_from(obj):
    ns = obj['cfg'].get('model')
    if not isinstance(ns, _Namespace):
        raise ConvertError('checkpoint cfg has no model section')
    attrs = vars(ns)
    missing = [k for k in REQUIRED_CONFIG if k not in attrs]
    if missing:
        raise ConvertError('checkpoint cfg is missing: ' + ', '.join(missing))
    config = {}
    for key in REQUIRED_CONFIG + OPTIONAL_CONFIG:
        if key not in attrs:
            continue
        value = attrs[key]
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise ConvertError('cfg %s is not a plain value' % key)
        config[key] = value
    config['special_ids'] = {'bos': 0, 'pad': 1, 'eos': 2, 'unk': 3}
    return config


def _numel(shape):
    n = 1
    for dim in shape:
        n *= dim
    return n


def _to_fp16(zf, prefix, name, ref):
    if not isinstance(ref, _TensorRef):
        raise ConvertError('%s is not a tensor' % name)
    fmt, size = STORAGES[ref.storage.storage_type.name]
    stride, step = [], 1
    for dim in reversed(ref.shape):
        stride.append(step)
        step *= dim
    if ref.shape and ref.stride != tuple(reversed(stride)):
        raise ConvertError('%s is not contiguous' % name)
    count = _numel(ref.shape)
    try:
        raw = zf.read('%sdata/%s' % (prefix, ref.storage.key))
    except KeyError:
        raise ConvertError('%s: storage %s missing' % (name, ref.storage.key))
    start = ref.offset * size
    if start < 0 or start + count * size > len(raw):
        raise ConvertError('%s: storage too small' % name)
    out = []
    for pos in range(0, count, CHUNK):
        n = min(CHUNK, count - pos)
        values = struct.unpack_from('<%d%s' % (n, fmt), raw,
                                    start + pos * size)
        if not all(map(math.isfinite, values)):
            raise ConvertError('%s: non-finite weight' % name)
        try:
            out.append(struct.pack('<%de' % n, *values))
        except OverflowError:
            raise ConvertError('%s: value does not fit in fp16' % name)
    return b''.join(out)


def convert(checkpoint, src_dict, tgt_dict, out_path):
    """Writes the TXLM v1 blob; leaves out_path untouched on any failure."""
    src_vocab, tgt_vocab = build_vocab(src_dict), build_vocab(tgt_dict)
    with zipfile.ZipFile(checkpoint) as zf:
        obj, prefix = _load_checkpoint(zf)
        config = _config_from(obj)
        tensors, blobs, position = collections.OrderedDict(), [], 0
        for name, ref in obj['model'].items():
            if name.endswith(SKIPPED_SUFFIXES):
                continue
            data = _to_fp16(zf, prefix, name, ref)
            pad = -len(data) % ALIGN
            tensors[name] = {'offset': position, 'shape': list(ref.shape)}
            blobs.append(data + b'\0' * pad)
            position += len(data) + pad
    vocabs = {'src': src_vocab, 'tgt': tgt_vocab}
    for name, side in VOCAB_ROWS:
        if name in tensors and tensors[name]['shape'][0] != len(vocabs[side]):
            raise ConvertError(
                '%s has %d rows but the %s vocabulary has %d symbols' %
                (name, tensors[name]['shape'][0], side, len(vocabs[side])))
    header = json.dumps(
        {'config': config, 'src_vocab': src_vocab, 'tgt_vocab': tgt_vocab,
         'tensors': tensors},
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    header += b' ' * (-(len(MAGIC) + 4 + len(header)) % ALIGN)

    directory = os.path.dirname(os.path.abspath(out_path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.xlit-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(MAGIC + struct.pack('<I', len(header)) + header)
            for blob in blobs:
                f.write(blob)
        os.chmod(tmp, 0o644)  # mkstemp makes it 0600
        os.replace(tmp, out_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return config, src_vocab, tgt_vocab, tensors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--checkpoint', required=True,
                        help='indicxlit.pt (torch zip)')
    parser.add_argument('--src-dict', required=True, help='dict.en.txt')
    parser.add_argument('--tgt-dict', required=True,
                        help='dict.<lang>.txt (all are identical)')
    parser.add_argument('output', help='xlit-model.bin to write')
    args = parser.parse_args(argv)
    try:
        config, src, tgt, tensors = convert(
            args.checkpoint, args.src_dict, args.tgt_dict, args.output)
    except (ConvertError, OSError, zipfile.BadZipFile, pickle.UnpicklingError,
            EOFError, struct.error, ValueError, AttributeError, KeyError,
            IndexError, TypeError) as e:
        print('xlit_convert: %s: %s' % (type(e).__name__, e),
              file=sys.stderr)
        return 1
    print('wrote %s: %d tensors, %d bytes, src vocab %d, tgt vocab %d, '
          '%d+%d layers, d=%d' % (
              args.output, len(tensors), os.path.getsize(args.output),
              len(src), len(tgt), config['encoder_layers'],
              config['decoder_layers'], config['encoder_embed_dim']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
