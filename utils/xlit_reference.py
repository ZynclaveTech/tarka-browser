#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Reference IndicXlit inference in numpy (D1).

This is the specification the C++ implementation in the browser must match.
It reads the TXLM v1 blob that utils/xlit_convert.py writes (never the
checkpoint pickle), runs the fairseq pre-norm transformer with a KV cache,
and does fairseq's beam search. It is slow and is meant for tests and for
generating resources/xlit/golden.tsv.

    xlit_reference.py <model.bin> <tag> word [word ...]
    xlit_reference.py <model.bin> --golden <inputs.txt>

The first form prints one line per word, "word<TAB>cand1|score1<TAB>...",
the candidates in model order (best first), before any dictionary
rescoring. The score is exp(sum of log-probabilities / number of tokens
including </s>), which is the T value of the library's rescoring. The second
form prints "tag<TAB>word<TAB>cand1|score1..." for every input line and every
language of the model.

Details that matter for a port (all verified against the library):
  * the target language is a tag token on the ENCODER side, the decoder
    starts from </s>;
  * source tokens are the lower-cased characters; anything that is not a
    vocabulary symbol (a-z) is <unk>;
  * embeddings are scaled by sqrt(256), sinusoidal positions are added (the
    first token is at index 2, the padding index plus one), then
    layernorm_embedding; layers are pre-norm; q is scaled by 1/8 after its
    bias; GELU is the exact erf form; layer-norm eps is 1e-5;
  * <pad> and <unk> are never produced, </s> is not allowed as the first
    token, hypotheses are normalised by their length including </s>.
"""

import json
import math
import struct
import sys

import numpy as np

MAGIC = b'TXLM\x01\x00\x00\x00'
LN_EPS = 1e-5
BEAM = 4
NBEST = 4
MAX_LEN = 40
MAX_POSITIONS = 256


class ModelError(Exception):
    """A model blob that cannot be used, or a bad request."""


class Model:
    def __init__(self, config, src_vocab, tgt_vocab, weights):
        self.config = config
        self.src_vocab = src_vocab
        self.tgt_vocab = tgt_vocab
        self.weights = weights
        special = config.get('special_ids', {})
        self.pad = special.get('pad', 1)
        self.eos = special.get('eos', 2)
        self.unk = special.get('unk', 3)
        self.src_index = {s: i for i, s in enumerate(src_vocab)}
        self.dim = config.get('encoder_embed_dim', 256)
        self.heads = config.get('encoder_attention_heads', 4)
        self.layers = config.get('encoder_layers', 6)
        self.positions = sinusoid(MAX_POSITIONS, self.dim, self.pad)

    @property
    def languages(self):
        """Language codes of the tag tokens, in vocabulary order (no en)."""
        return [s[2:-2] for s in self.src_vocab
                if len(s) > 4 and s.startswith('__') and s.endswith('__')
                and s != '__en__']


def load_model(path):
    """Reads a TXLM v1 blob into float32 arrays."""
    with open(path, 'rb') as f:
        blob = f.read()
    if blob[:8] != MAGIC:
        raise ModelError('%s: not a TXLM v1 file' % path)
    if len(blob) < 12:
        raise ModelError('%s: truncated header' % path)
    (hlen,) = struct.unpack_from('<I', blob, 8)
    start = 12 + hlen
    if start > len(blob):
        raise ModelError('%s: truncated header' % path)
    try:
        header = json.loads(blob[12:start].decode('utf-8'))
    except ValueError as e:
        raise ModelError('%s: bad header: %s' % (path, e))
    weights = {}
    for name, info in header.get('tensors', {}).items():
        shape = tuple(info['shape'])
        n = int(np.prod(shape)) if shape else 1
        lo = start + info['offset']
        if lo + 2 * n > len(blob):
            raise ModelError('%s: tensor %s runs past the end' % (path, name))
        weights[name] = np.frombuffer(
            blob, dtype='<f2', count=n, offset=lo).astype(
                np.float32).reshape(shape)
    return Model(header.get('config', {}), header.get('src_vocab', []),
                 header.get('tgt_vocab', []), weights)


def sinusoid(n, dim, pad):
    """fairseq's SinusoidalPositionalEmbedding table; row `pad` is zero."""
    half = dim // 2
    scale = math.log(10000) / (half - 1)
    freq = np.exp(np.arange(half, dtype=np.float32) * -scale)
    angle = np.arange(n, dtype=np.float32)[:, None] * freq[None, :]
    table = np.concatenate([np.sin(angle), np.cos(angle)], axis=1)
    table[pad] = 0
    return table.astype(np.float32)


_erf = np.vectorize(math.erf, otypes=[np.float32])


def gelu(x):
    """Exact GELU (erf), as fairseq's activation_fn=gelu."""
    return (0.5 * x * (1.0 + _erf(x / math.sqrt(2.0)))).astype(np.float32)


def _layer_norm(m, x, name):
    mean = x.mean(-1, keepdims=True)
    var = ((x - mean) ** 2).mean(-1, keepdims=True)
    return ((x - mean) / np.sqrt(var + LN_EPS) * m.weights[name + '.weight']
            + m.weights[name + '.bias'])


def _linear(m, x, name):
    y = x @ m.weights[name + '.weight'].T
    bias = m.weights.get(name + '.bias')
    return y if bias is None else y + bias


def _heads(m, x):
    b, t, _ = x.shape
    return x.reshape(b, t, m.heads, m.dim // m.heads).transpose(0, 2, 1, 3)


def _attend(q, k, v):
    a = q @ k.transpose(0, 1, 3, 2)
    a = a - a.max(-1, keepdims=True)
    a = np.exp(a)
    a /= a.sum(-1, keepdims=True)
    b = q.shape[0]
    return (a @ v).transpose(0, 2, 1, 3).reshape(b, -1, k.shape[1] * k.shape[3])


def _encode(m, ids):
    scale = (m.dim // m.heads) ** -0.5
    x = 16.0 * m.weights['encoder.embed_tokens.weight'][ids] \
        + m.positions[2:2 + len(ids)]
    x = _layer_norm(m, x, 'encoder.layernorm_embedding')[None]
    for i in range(m.layers):
        p = 'encoder.layers.%d' % i
        h = _layer_norm(m, x, p + '.self_attn_layer_norm')
        q = _heads(m, _linear(m, h, p + '.self_attn.q_proj') * scale)
        k = _heads(m, _linear(m, h, p + '.self_attn.k_proj'))
        v = _heads(m, _linear(m, h, p + '.self_attn.v_proj'))
        x = x + _linear(m, _attend(q, k, v), p + '.self_attn.out_proj')
        h = _layer_norm(m, x, p + '.final_layer_norm')
        x = x + _linear(m, gelu(_linear(m, h, p + '.fc1')), p + '.fc2')
    return _layer_norm(m, x, 'encoder.layer_norm')


def _log_softmax(logits):
    logits = logits - logits.max(-1, keepdims=True)
    return logits - np.log(np.exp(logits).sum(-1, keepdims=True))


def transliterate(model, tag, word, beam=BEAM, nbest=NBEST,
                  max_len=MAX_LEN):
    """Returns [(candidate, score)] best first, score in (0, 1]."""
    m = model
    tag_token = '__%s__' % tag
    if tag == 'en' or tag_token not in m.src_index:
        raise ModelError('unknown language: %r' % tag)
    ids = [m.src_index[tag_token]]
    ids += [m.src_index.get(c, m.unk) if len(c) == 1 else m.unk
            for c in word.lower()]
    ids.append(m.eos)
    scale = (m.dim // m.heads) ** -0.5
    enc = _encode(m, np.array(ids))
    enc_k = [_heads(m, _linear(m, enc, 'decoder.layers.%d.encoder_attn.k_proj'
                               % i)) for i in range(m.layers)]
    enc_v = [_heads(m, _linear(m, enc, 'decoder.layers.%d.encoder_attn.v_proj'
                               % i)) for i in range(m.layers)]
    heads, hd = m.heads, m.dim // m.heads
    keys = [np.zeros((1, heads, 0, hd), np.float32) for _ in range(m.layers)]
    vals = [np.zeros((1, heads, 0, hd), np.float32) for _ in range(m.layers)]
    hyps = [([m.eos], 0.0)]
    finished = []
    for step in range(max_len):
        b = len(hyps)
        last = np.array([[h[0][-1]] for h in hyps])
        x = 16.0 * m.weights['decoder.embed_tokens.weight'][last] \
            + m.positions[2 + step][None, None]
        x = _layer_norm(m, x, 'decoder.layernorm_embedding')
        for i in range(m.layers):
            p = 'decoder.layers.%d' % i
            h = _layer_norm(m, x, p + '.self_attn_layer_norm')
            q = _heads(m, _linear(m, h, p + '.self_attn.q_proj') * scale)
            keys[i] = np.concatenate(
                [keys[i], _heads(m, _linear(m, h, p + '.self_attn.k_proj'))],
                axis=2)
            vals[i] = np.concatenate(
                [vals[i], _heads(m, _linear(m, h, p + '.self_attn.v_proj'))],
                axis=2)
            x = x + _linear(m, _attend(q, keys[i], vals[i]),
                            p + '.self_attn.out_proj')
            h = _layer_norm(m, x, p + '.encoder_attn_layer_norm')
            q = _heads(m, _linear(m, h, p + '.encoder_attn.q_proj') * scale)
            ek = np.broadcast_to(enc_k[i], (b,) + enc_k[i].shape[1:])
            ev = np.broadcast_to(enc_v[i], (b,) + enc_v[i].shape[1:])
            x = x + _linear(m, _attend(q, ek, ev), p + '.encoder_attn.out_proj')
            h = _layer_norm(m, x, p + '.final_layer_norm')
            x = x + _linear(m, gelu(_linear(m, h, p + '.fc1')), p + '.fc2')
        x = _layer_norm(m, x[:, -1], 'decoder.layer_norm')
        lp = _log_softmax(x @ m.weights['decoder.output_projection.weight'].T)
        lp[:, m.pad] = -np.inf
        lp[:, m.unk] = -np.inf
        if step == 0:
            lp[:, m.eos] = -np.inf  # min_len = 1
        cand = []
        for bi, (_, score) in enumerate(hyps):
            for t in np.argpartition(-lp[bi], 2 * beam)[:2 * beam]:
                cand.append((score + float(lp[bi, t]), bi, int(t)))
        cand.sort(key=lambda c: -c[0])
        new, source = [], []
        for score, bi, t in cand[:2 * beam]:
            if t == m.eos:
                if len(finished) < nbest:
                    finished.append((hyps[bi][0][1:], score / (step + 1)))
            elif len(new) < beam:
                new.append((hyps[bi][0] + [t], score))
                source.append(bi)
        hyps = new
        if len(finished) >= nbest or not hyps:
            break
        keys = [k[source] for k in keys]
        vals = [v[source] for v in vals]
    finished.sort(key=lambda h: -h[1])
    return [(''.join(m.tgt_vocab[t] for t in toks), math.exp(score))
            for toks, score in finished]


def format_candidates(cands):
    return '\t'.join('%s|%.6g' % (c, s) for c, s in cands)


def main(argv):
    if len(argv) >= 3 and argv[1] == '--golden':
        model = load_model(argv[0])
        with open(argv[2], encoding='utf-8') as f:
            inputs = [line.strip() for line in f if line.strip()]
        for word in inputs:
            for tag in model.languages:
                print('%s\t%s\t%s' % (tag, word, format_candidates(
                    transliterate(model, tag, word))))
        return 0
    if len(argv) < 3:
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    model = load_model(argv[0])
    for word in argv[2:]:
        print('%s\t%s' % (word, format_candidates(
            transliterate(model, argv[1], word))))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
