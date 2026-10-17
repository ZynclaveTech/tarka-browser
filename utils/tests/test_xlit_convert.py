"""Tests for utils/xlit_convert.py: IndicXlit checkpoint -> TXLM v1 blob."""
import argparse
import collections
import contextlib
import io
import json
import os
import pickle
import struct
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import xlit_convert  # noqa: E402

MAGIC = b'TXLM\x01\x00\x00\x00'

CORE_CONFIG = {
    'arch': 'transformer',
    'encoder_layers': 6,
    'decoder_layers': 6,
    'encoder_embed_dim': 256,
    'decoder_embed_dim': 256,
    'encoder_ffn_embed_dim': 1024,
    'decoder_ffn_embed_dim': 1024,
    'encoder_attention_heads': 4,
    'decoder_attention_heads': 4,
    'encoder_normalize_before': True,
    'activation_fn': 'gelu',
}


class FakeStorageType:
    """Stands in for torch.FloatStorage; pickled as the global torch.FloatStorage."""


FakeStorageType.__name__ = FakeStorageType.__qualname__ = 'FloatStorage'
FakeStorageType.__module__ = 'torch'


class FakeStorage:
    def __init__(self, values, key):
        self.key = key
        self.values = values


def fake_rebuild_tensor_v2(*args):  # never called; only pickled by name
    raise AssertionError('not for calling')


fake_rebuild_tensor_v2.__module__ = 'torch._utils'
fake_rebuild_tensor_v2.__name__ = '_rebuild_tensor_v2'
fake_rebuild_tensor_v2.__qualname__ = '_rebuild_tensor_v2'


class FakeTensor:
    """A tensor as torch.save pickles it: a call to _rebuild_tensor_v2."""

    def __init__(self, values, shape, key):
        self.storage = FakeStorage(values, key)
        self.shape = tuple(shape)

    def __reduce__(self):
        stride, step = [], 1
        for dim in reversed(self.shape):
            stride.append(step)
            step *= dim
        stride = tuple(reversed(stride))
        return (fake_rebuild_tensor_v2,
                (self.storage, 0, self.shape, stride, False,
                 collections.OrderedDict()))


class CheckpointPickler(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, FakeStorage):
            return ('storage', FakeStorageType, obj.key, 'cpu',
                    len(obj.values))
        return None


def fake_torch_modules():
    torch = types.ModuleType('torch')
    torch.FloatStorage = FakeStorageType
    utils = types.ModuleType('torch._utils')
    utils._rebuild_tensor_v2 = fake_rebuild_tensor_v2
    torch._utils = utils
    return {'torch': torch, 'torch._utils': utils}


def make_checkpoint(path, tensors, config=None, extra=None, raw_obj=None):
    """Writes a torch-format zip. tensors: {name: (shape, values)}."""
    keys = iter(range(1000))
    model = collections.OrderedDict()
    for name, (shape, values) in tensors.items():
        model[name] = FakeTensor(values, shape, str(next(keys)))
    model_cfg = dict(CORE_CONFIG if config is None else config)
    obj = raw_obj if raw_obj is not None else {
        'args': None,
        'cfg': {'model': argparse.Namespace(**model_cfg)},
        'model': model,
        # Optimiser state is most of the real file and must be ignored.
        'last_optimizer_state': {'state': {0: {'exp_avg': FakeTensor(
            [0.5] * 6, (6,), str(next(keys)))}}},
    }
    if extra:
        obj.update(extra)
    storages = {}

    class Collecting(CheckpointPickler):
        def persistent_id(self, o):
            pid = super().persistent_id(o)
            if pid is not None:
                storages[o.key] = o.values
            return pid

    buf = io.BytesIO()
    with mock.patch.dict(sys.modules, fake_torch_modules()):
        Collecting(buf, protocol=2).dump(obj)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('archive/data.pkl', buf.getvalue())
        for key, values in storages.items():
            z.writestr('archive/data/' + key,
                       struct.pack('<%df' % len(values), *values))
        z.writestr('archive/version', '3\n')


def write_dict(path, tokens):
    with open(path, 'w', encoding='utf-8') as f:
        for i, token in enumerate(tokens):
            f.write('%s %d\n' % (token, 100 - i))


def read_blob(path):
    """Independent TXLM v1 reader: (header, {name: [floats]})."""
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == MAGIC
    (hlen,) = struct.unpack('<I', data[8:12])
    header = json.loads(data[12:12 + hlen].decode('utf-8'))
    start = 12 + hlen
    tensors = {}
    for name, meta in header['tensors'].items():
        n = 1
        for dim in meta['shape']:
            n *= dim
        raw = data[start + meta['offset']:start + meta['offset'] + 2 * n]
        tensors[name] = list(struct.unpack('<%de' % n, raw))
    return header, tensors, start


class TestXlitConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.ckpt = os.path.join(self.dir, 'x.pt')
        self.src = os.path.join(self.dir, 'dict.en.txt')
        self.tgt = os.path.join(self.dir, 'dict.hi.txt')
        self.out = os.path.join(self.dir, 'out.bin')
        write_dict(self.src, ['a', 'b'])
        write_dict(self.tgt, ['क', 'ख', 'ग'])

    def convert(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = xlit_convert.main([
                '--checkpoint', self.ckpt, '--src-dict', self.src,
                '--tgt-dict', self.tgt, self.out])
        return code, err.getvalue()

    def test_round_trip_two_tensors(self):
        a = [0.0, 1.0, -2.5, 0.1, 3.14159, 1000.5]
        b = [0.001, -0.5, 7.0]
        make_checkpoint(self.ckpt, collections.OrderedDict([
            ('decoder.layers.0.fc1.weight', ((2, 3), a)),
            ('decoder.layers.0.fc1.bias', ((3,), b))]))
        code, err = self.convert()
        self.assertEqual(code, 0, err)
        header, tensors, _ = read_blob(self.out)
        self.assertEqual(list(header['tensors']),
                         ['decoder.layers.0.fc1.weight',
                          'decoder.layers.0.fc1.bias'])
        self.assertEqual(header['tensors']['decoder.layers.0.fc1.weight']
                         ['shape'], [2, 3])
        self.assertEqual(header['tensors']['decoder.layers.0.fc1.bias']
                         ['shape'], [3])
        for got, want in ((tensors['decoder.layers.0.fc1.weight'], a),
                          (tensors['decoder.layers.0.fc1.bias'], b)):
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, delta=abs(w) * 1e-3 + 1e-6)

    def test_alignment(self):
        make_checkpoint(self.ckpt, collections.OrderedDict([
            ('a.weight', ((3,), [1.0, 2.0, 3.0])),
            ('b.weight', ((5,), [1.0] * 5)),
            ('c.weight', ((2, 2), [1.0] * 4)),
            ('d.weight', ((33,), [2.0] * 33))]))
        code, err = self.convert()
        self.assertEqual(code, 0, err)
        header, _, data_start = read_blob(self.out)
        offsets = [m['offset'] for m in header['tensors'].values()]
        self.assertEqual(len(offsets), 4)
        self.assertEqual(offsets, sorted(offsets))
        for offset in offsets:
            self.assertEqual(offset % 64, 0)
        self.assertEqual(data_start % 64, 0)
        self.assertEqual(os.path.getsize(self.out) % 2, 0)

    def test_refuses_unknown_global(self):
        marker = os.path.join(self.dir, 'pwned')

        class Evil:
            def __reduce__(self):
                return (os.system, ('echo pwned > ' + marker,))

        make_checkpoint(self.ckpt, {}, raw_obj={
            'cfg': {'model': argparse.Namespace(**CORE_CONFIG)},
            'model': collections.OrderedDict(), 'evil': Evil()})
        code, err = self.convert()
        self.assertNotEqual(code, 0)
        self.assertIn('system', err)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(marker))

    def test_refuses_not_a_checkpoint(self):
        with open(self.ckpt, 'wb') as f:
            f.write(b'this is not a zip')
        code, err = self.convert()
        self.assertNotEqual(code, 0)
        self.assertTrue(err.strip())
        self.assertFalse(os.path.exists(self.out))

    def test_vocab_from_dict_files(self):
        write_dict(self.src, ['z', 'a', 'm'])
        write_dict(self.tgt, ['ग', 'क'])
        src = xlit_convert.build_vocab(self.src)
        tgt = xlit_convert.build_vocab(self.tgt)
        self.assertEqual(src[:4], ['<s>', '<pad>', '</s>', '<unk>'])
        self.assertEqual(src[4:7], ['z', 'a', 'm'])
        self.assertEqual(src[7:], xlit_convert.LANG_TAGS)
        self.assertEqual(tgt[4:6], ['ग', 'क'])
        self.assertEqual(tgt[6:], xlit_convert.LANG_TAGS)
        self.assertEqual(len(xlit_convert.LANG_TAGS), 22)
        self.assertEqual(xlit_convert.LANG_TAGS[0], '__en__')
        self.assertEqual(xlit_convert.LANG_TAGS[-1], '__ur__')
        self.assertEqual(src.index('__hi__') - 7, 6)

    def test_vocab_rejects_duplicates(self):
        write_dict(self.src, ['a', 'a'])
        with self.assertRaises(xlit_convert.ConvertError):
            xlit_convert.build_vocab(self.src)

    def test_header_has_vocab_and_config(self):
        make_checkpoint(self.ckpt, {'x': ((1,), [1.0])})
        code, err = self.convert()
        self.assertEqual(code, 0, err)
        header, _, _ = read_blob(self.out)
        self.assertEqual(header['src_vocab'], xlit_convert.build_vocab(self.src))
        self.assertEqual(header['tgt_vocab'], xlit_convert.build_vocab(self.tgt))
        for key, value in CORE_CONFIG.items():
            self.assertEqual(header['config'][key], value)

    def test_embedding_rows_must_match_vocab(self):
        # src vocab here is 4 + 2 + 22 = 28 symbols.
        make_checkpoint(self.ckpt, {
            'encoder.embed_tokens.weight': ((5, 2), [0.0] * 10)})
        code, err = self.convert()
        self.assertNotEqual(code, 0)
        self.assertIn('vocab', err)
        self.assertFalse(os.path.exists(self.out))

    def test_embedding_rows_match_vocab_ok(self):
        make_checkpoint(self.ckpt, {
            'encoder.embed_tokens.weight': ((28, 2), [0.0] * 56),
            'decoder.embed_tokens.weight': ((29, 2), [0.0] * 58),
            'decoder.output_projection.weight': ((29, 2), [0.0] * 58)})
        code, err = self.convert()
        self.assertEqual(code, 0, err)

    def test_buffers_and_optimizer_state_not_written(self):
        make_checkpoint(self.ckpt, collections.OrderedDict([
            ('encoder.version', ((1,), [2.0])),
            ('encoder.embed_positions._float_tensor', ((1,), [0.0])),
            ('encoder.layer_norm.weight', ((2,), [1.0, 1.0]))]))
        code, err = self.convert()
        self.assertEqual(code, 0, err)
        header, _, _ = read_blob(self.out)
        self.assertEqual(list(header['tensors']), ['encoder.layer_norm.weight'])

    def test_missing_config_refused(self):
        make_checkpoint(self.ckpt, {'x': ((1,), [1.0])},
                        config={'arch': 'transformer'})
        code, err = self.convert()
        self.assertNotEqual(code, 0)
        self.assertIn('encoder_layers', err)
        self.assertFalse(os.path.exists(self.out))

    def test_fp16_overflow_refused(self):
        make_checkpoint(self.ckpt, {'x': ((1,), [1e9])})
        code, err = self.convert()
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.out))

    def test_failure_leaves_existing_output_alone(self):
        with open(self.out, 'wb') as f:
            f.write(b'keep me')
        with open(self.ckpt, 'wb') as f:
            f.write(b'junk')
        code, _ = self.convert()
        self.assertNotEqual(code, 0)
        with open(self.out, 'rb') as f:
            self.assertEqual(f.read(), b'keep me')
        self.assertEqual(sorted(os.listdir(self.dir)),
                         sorted(['x.pt', 'dict.en.txt', 'dict.hi.txt',
                                 'out.bin']))


if __name__ == '__main__':
    unittest.main()
