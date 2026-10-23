#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""opus-mt Spanish -> English for Tark for Android's Translate (Phase 2a).

    marian_export.py export CHECKPOINT_DIR OUT_DIR
    marian_export.py golden MODELS_DIR CHECKPOINT_DIR FLEURS_TSV OUT_JSON

CHECKPOINT_DIR is Helsinki-NLP/opus-mt-es-en (Apache-2.0): config.json,
metadata.json, vocab.json, source.spm and pytorch_model.bin, read with
torch.load(weights_only=True), so no code in the file runs. `export` rebuilds
the model in plain PyTorch (Marian: post-norm, SiLU, sinusoidal positions
from 0, no final layer norm, logits biased) and writes OUT_DIR/opus_es_en/ in
the layout Tark's TranslationEngine reads for IndicTrans2
(utils/indictrans_export.py): encoder.int8.onnx (ids -> cross_mask, cross_k,
cross_v), decoder_step.int8.onnx (token, step, past_k, past_v, cross_k,
cross_v, cross_mask -> logits, new_k, new_v; caches (layers, batch, heads,
length, head_dim)), model.SRC (source.spm), dict.SRC.json and dict.TGT.json
(the shared vocab.json) and config.json with "language_tags": false. The pad
token is never chosen (the checkpoint's bad_words_ids), baked into the
logits' bias.

`golden` translates the first sentences of a FLEURS Spanish test.tsv with the
exported int8 models in ONNX Runtime (greedy) and with the checkpoint in
transformers (greedy), writes the int8 ids and English per caption to OUT_JSON
(TESTDATA/es_mt_golden.json, Tark's C++ test reference) and exits non-zero if
fewer than 8 of 10 distinct sentences match the checkpoint's English (int8
weights change a word now and then: "their" for "your").

Needs torch, onnx, onnxruntime, sentencepiece and (golden) transformers: the
D4 spike's environment; none of them is used by Tark itself.
"""
import json
import pathlib
import shutil
import sys

try:  # the export needs torch; check_checkpoint (and Tark's tests) do not
    import torch
    import torch.nn.functional as F
    from torch import nn
    Module = nn.Module
except ImportError:
    torch = F = nn = None
    Module = object

FOLDER = 'opus_es_en'


def check_checkpoint(path):
    meta = json.loads((pathlib.Path(path) / 'metadata.json').read_text(encoding='utf-8'))
    if (meta.get('src_alpha2'), meta.get('tgt_alpha2')) != ('es', 'en'):
        sys.exit(f'{path}: {meta.get("src_alpha2")} -> {meta.get("tgt_alpha2")}, expected es -> en')


class Attention(Module):
    def __init__(self, dim, heads):
        super().__init__()
        self.heads, self.head_dim = heads, dim // heads
        self.q_proj, self.k_proj = nn.Linear(dim, dim), nn.Linear(dim, dim)
        self.v_proj, self.out_proj = nn.Linear(dim, dim), nn.Linear(dim, dim)

    def split(self, x):  # (B, T, D) -> (B, H, T, d)
        return x.view(x.shape[0], x.shape[1], self.heads, self.head_dim).transpose(1, 2)

    def forward(self, x, k, v, mask):
        q = self.split(self.q_proj(x)) * self.head_dim ** -0.5
        out = ((q @ k.transpose(-1, -2)) + mask).softmax(-1) @ v
        return self.out_proj(out.transpose(1, 2).reshape(x.shape[0], x.shape[1], -1))


class EncoderLayer(Module):
    def __init__(self, dim, heads, ffn):
        super().__init__()
        self.self_attn = Attention(dim, heads)
        self.self_attn_layer_norm, self.final_layer_norm = nn.LayerNorm(dim), nn.LayerNorm(dim)
        self.fc1, self.fc2 = nn.Linear(dim, ffn), nn.Linear(ffn, dim)

    def forward(self, x, mask):  # post-norm
        a = self.self_attn
        x = self.self_attn_layer_norm(x + a(x, a.split(a.k_proj(x)), a.split(a.v_proj(x)), mask))
        return self.final_layer_norm(x + self.fc2(F.silu(self.fc1(x))))


class DecoderLayer(Module):
    def __init__(self, dim, heads, ffn):
        super().__init__()
        self.self_attn, self.encoder_attn = Attention(dim, heads), Attention(dim, heads)
        self.self_attn_layer_norm = nn.LayerNorm(dim)
        self.encoder_attn_layer_norm = nn.LayerNorm(dim)
        self.final_layer_norm = nn.LayerNorm(dim)
        self.fc1, self.fc2 = nn.Linear(dim, ffn), nn.Linear(ffn, dim)

    def forward(self, x, past_k, past_v, cross_k, cross_v, cross_mask):
        a = self.self_attn
        k = torch.cat([past_k, a.split(a.k_proj(x))], dim=2)
        v = torch.cat([past_v, a.split(a.v_proj(x))], dim=2)
        x = self.self_attn_layer_norm(x + a(x, k, v, 0.0))  # one new token sees the cache
        x = self.encoder_attn_layer_norm(x + self.encoder_attn(x, cross_k, cross_v, cross_mask))
        return self.final_layer_norm(x + self.fc2(F.silu(self.fc1(x)))), k, v


class Marian(Module):
    def __init__(self, path):
        super().__init__()
        c = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        assert c['activation_function'] == 'swish' and not c['normalize_before'], c
        self.c = c
        dim = c['d_model']
        self.scale = dim ** 0.5 if c['scale_embedding'] else 1.0
        self.pad = c['pad_token_id']
        self.embed = nn.Embedding(c['vocab_size'], dim)
        self.enc_pos = nn.Embedding(c['max_position_embeddings'], dim)
        self.dec_pos = nn.Embedding(c['max_position_embeddings'], dim)
        self.enc_layers = nn.ModuleList(EncoderLayer(dim, c['encoder_attention_heads'], c['encoder_ffn_dim'])
                                        for _ in range(c['encoder_layers']))
        self.dec_layers = nn.ModuleList(DecoderLayer(dim, c['decoder_attention_heads'], c['decoder_ffn_dim'])
                                        for _ in range(c['decoder_layers']))
        self.register_buffer('bias', torch.zeros(c['vocab_size']))
        self.load(path / 'pytorch_model.bin')

    def load(self, file):
        w = torch.load(str(file), map_location='cpu', weights_only=True)
        rename = {'model.shared': 'embed', 'model.encoder.embed_positions': 'enc_pos',
                  'model.decoder.embed_positions': 'dec_pos', 'model.encoder.layers': 'enc_layers',
                  'model.decoder.layers': 'dec_layers'}
        state = {}
        for key, value in w.items():
            if key in ('lm_head.weight', 'model.encoder.embed_tokens.weight', 'model.decoder.embed_tokens.weight'):
                continue  # tied to the shared embedding
            if key == 'final_logits_bias':
                state['bias'] = value.reshape(-1).clone()
                continue
            for old, new in rename.items():
                if key.startswith(old + '.'):
                    key = new + key[len(old):]
            state[key] = value
        state['bias'][self.pad] = float('-inf')  # bad_words_ids: never the pad token
        missing, unexpected = self.load_state_dict(state, strict=False)
        assert not unexpected and not missing, (missing, unexpected)

    def encode(self, ids):
        mask = ids.ne(self.pad)
        x = self.embed(ids) * self.scale + self.enc_pos(torch.arange(ids.shape[1]))[None]
        key_mask = torch.zeros(mask.shape, dtype=torch.float).masked_fill(~mask, float('-inf'))[:, None, None, :]
        for layer in self.enc_layers:
            x = layer(x, key_mask)
        return x, key_mask

    def cross_kv(self, states):
        return [(l.encoder_attn.split(l.encoder_attn.k_proj(states)),
                 l.encoder_attn.split(l.encoder_attn.v_proj(states))) for l in self.dec_layers]

    def decode_step(self, token, step, past, cross, cross_mask):
        x = self.embed(token) * self.scale + self.dec_pos.weight[step][None, None, :]
        new_past = []
        for layer, (pk, pv), (ck, cv) in zip(self.dec_layers, past, cross):
            x, k, v = layer(x, pk, pv, ck, cv, cross_mask)
            new_past.append((k, v))
        return x[:, -1] @ self.embed.weight.T + self.bias, new_past


class Encoder(Module):
    def __init__(self, model):
        super().__init__()
        self.m = model

    def forward(self, ids):
        states, mask = self.m.encode(ids)
        cross = self.m.cross_kv(states)
        return mask, torch.stack([k for k, _ in cross]), torch.stack([v for _, v in cross])


class DecoderStep(Module):
    def __init__(self, model):
        super().__init__()
        self.m = model

    def forward(self, token, step, past_k, past_v, cross_k, cross_v, cross_mask):
        past = list(zip(past_k.unbind(0), past_v.unbind(0)))
        cross = list(zip(cross_k.unbind(0), cross_v.unbind(0)))
        logits, new = self.m.decode_step(token, step, past, cross, cross_mask)
        return logits, torch.stack([k for k, _ in new]), torch.stack([v for _, v in new])


def export(checkpoint, out_dir):
    with torch.no_grad():
        _export(checkpoint, out_dir)


def _export(checkpoint, out_dir):
    from onnxruntime.quantization import QuantType, quantize_dynamic
    checkpoint, out = pathlib.Path(checkpoint), pathlib.Path(out_dir) / FOLDER
    check_checkpoint(checkpoint)
    model = Marian(checkpoint).eval()
    c = model.c
    layers, heads = c['decoder_layers'], c['decoder_attention_heads']
    head_dim = c['d_model'] // heads
    out.mkdir(parents=True, exist_ok=True)
    fp32 = out / 'fp32'
    fp32.mkdir(exist_ok=True)
    ids = torch.tensor([[5, 6, 7, 8, 0]])
    mask, ck, cv = Encoder(model)(ids)
    torch.onnx.export(
        Encoder(model), (ids,), str(fp32 / 'encoder.onnx'), dynamo=False,
        input_names=['ids'], output_names=['cross_mask', 'cross_k', 'cross_v'],
        dynamic_axes={'ids': {0: 'b', 1: 's'}, 'cross_mask': {0: 'b', 3: 's'},
                      'cross_k': {1: 'b', 3: 's'}, 'cross_v': {1: 'b', 3: 's'}}, opset_version=17)
    past = torch.zeros(layers, 1, heads, 1, head_dim)
    args = (torch.tensor([[c['decoder_start_token_id']]]), torch.tensor(1), past, past, ck, cv, mask)
    torch.onnx.export(
        DecoderStep(model), args, str(fp32 / 'decoder_step.onnx'), dynamo=False,
        input_names=['token', 'step', 'past_k', 'past_v', 'cross_k', 'cross_v', 'cross_mask'],
        output_names=['logits', 'new_k', 'new_v'],
        dynamic_axes={'token': {0: 'b'}, 'past_k': {1: 'b', 3: 't'}, 'past_v': {1: 'b', 3: 't'},
                      'cross_k': {1: 'b', 3: 's'}, 'cross_v': {1: 'b', 3: 's'}, 'cross_mask': {0: 'b', 3: 's'},
                      'new_k': {1: 'b', 3: 't1'}, 'new_v': {1: 'b', 3: 't1'}}, opset_version=17)
    for part in ('encoder', 'decoder_step'):
        quantize_dynamic(str(fp32 / f'{part}.onnx'), str(out / f'{part}.int8.onnx'),
                         weight_type=QuantType.QInt8, per_channel=True)
    shutil.rmtree(fp32)
    shutil.copy2(checkpoint / 'source.spm', out / 'model.SRC')
    shutil.copy2(checkpoint / 'vocab.json', out / 'dict.SRC.json')
    shutil.copy2(checkpoint / 'vocab.json', out / 'dict.TGT.json')
    (out / 'config.json').write_text(json.dumps({
        'decoder_layers': layers, 'decoder_attention_heads': heads, 'decoder_embed_dim': c['d_model'],
        'decoder_start_token_id': c['decoder_start_token_id'], 'eos_token_id': c['eos_token_id'],
        'language_tags': False}, indent=1) + '\n', encoding='utf-8')


class OnnxTranslator:
    """What Tark's C++ TranslationEngine does with these files, in Python."""

    def __init__(self, folder):
        import onnxruntime as ort
        import sentencepiece as spm
        self.config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        self.vocab = json.loads((folder / 'dict.SRC.json').read_text(encoding='utf-8'))
        self.tokens = {i: t for t, i in self.vocab.items()}
        self.spm = spm.SentencePieceProcessor(model_file=str(folder / 'model.SRC'))
        self.enc = ort.InferenceSession(str(folder / 'encoder.int8.onnx'))
        self.dec = ort.InferenceSession(str(folder / 'decoder_step.int8.onnx'))

    def ids(self, text):
        unk = self.vocab['<unk>']
        return [self.vocab.get(p, unk) for p in self.spm.encode(text, out_type=str)][:255] + [self.vocab['</s>']]

    def greedy(self, ids, max_tokens=128):
        import numpy as np
        mask, ck, cv = self.enc.run(None, {'ids': np.array([ids], dtype=np.int64)})
        c = self.config
        empty = np.zeros((c['decoder_layers'], 1, c['decoder_attention_heads'], 0,
                          c['decoder_embed_dim'] // c['decoder_attention_heads']), dtype=np.float32)
        token, pk, pv, out = c['decoder_start_token_id'], empty, empty, []
        for step in range(max_tokens):
            logits, pk, pv = self.dec.run(None, {
                'token': np.array([[token]], dtype=np.int64), 'step': np.array(step, dtype=np.int64),
                'past_k': pk, 'past_v': pv, 'cross_k': ck, 'cross_v': cv, 'cross_mask': mask})
            token = int(logits[0].argmax())
            if token == c['eos_token_id']:
                break
            out.append(token)
        return out

    def text(self, out):
        skip = {'<s>', '<pad>', '</s>', '<unk>'}
        return ''.join(self.tokens[i] for i in out if self.tokens.get(i) not in skip).replace('▁', ' ').strip()


def golden(models_dir, checkpoint, fleurs_tsv, out_json, count=10, need=8):
    from transformers import MarianMTModel, MarianTokenizer
    tr = OnnxTranslator(pathlib.Path(models_dir) / FOLDER)
    tok = MarianTokenizer.from_pretrained(checkpoint)
    ref = MarianMTModel.from_pretrained(checkpoint, use_safetensors=False).eval()
    rows, seen = [], set()
    for line in pathlib.Path(fleurs_tsv).read_text(encoding='utf-8').splitlines():
        row = line.split('\t')
        if row[2] not in seen:  # FLEURS has several recordings of a sentence
            seen.add(row[2])
            rows.append(row)
    cases, agree = [], 0
    for row in rows[:count]:
        caption = row[2]
        src = tr.ids(caption)
        out = tr.greedy(src)
        english = tr.text(out)
        with torch.no_grad():
            hf = tok.decode(ref.generate(**tok(caption, return_tensors='pt'), num_beams=1,
                                         do_sample=False, max_new_tokens=128)[0], skip_special_tokens=True)
        agree += english == hf
        print(f'{english == hf!s:5} {english!r}\n      {hf!r}')
        cases.append({'id': f'es_{row[0]}', 'lang': 'es', 'caption': caption, 'src_ids': src,
                      'out_ids': out, 'translation': english, 'reference_fp32': hf})
    pathlib.Path(out_json).write_text(json.dumps({'cases': cases}, ensure_ascii=False, indent=1) + '\n',
                                      encoding='utf-8')
    print(f'{agree} of {count} match the checkpoint')
    if agree < need:
        sys.exit(f'only {agree} of {count} sentences match the checkpoint')


def main():
    if len(sys.argv) == 4 and sys.argv[1] == 'export':
        export(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 6 and sys.argv[1] == 'golden':
        golden(*sys.argv[2:6])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
