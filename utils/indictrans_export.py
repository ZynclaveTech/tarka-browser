#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""IndicTrans2 files and reference outputs for call translation (D4 Phase 2).

    indictrans_export.py export INDIC_EN_DIR EN_INDIC_DIR OUT_DIR
    indictrans_export.py golden MODELS_DIR TESTDATA_DIR OUT_JSON

INDIC_EN_DIR and EN_INDIC_DIR are AI4Bharat's indictrans2-indic-en-dist-200M
and indictrans2-en-indic-dist-200M checkpoints (MIT). `export` rebuilds the
model in plain PyTorch (AI4Bharat's transformers code needs a transformers
release with known vulnerabilities), exports it to ONNX and quantizes the
weights to int8: OUT_DIR/it2_indic_en/ and it2_en_indic/, each with
encoder.int8.onnx (ids -> cross_mask, cross_k, cross_v), decoder_step.int8.onnx
(token, step, past_k, past_v, cross_k, cross_v, cross_mask -> logits, new_k,
new_v; caches stacked over layers as (layers, batch, heads, length,
head_dim)), the tokenizer files, config.json and LICENSE.

`golden` runs the reference pipeline (IndicTransToolkit's IndicProcessor,
the int8 ONNX models in ONNX Runtime, greedy decoding) on the captions in
TESTDATA_DIR/mt_cases.tsv and writes, per caption, every stage Tark's C++
engine is tested against: the normalised text, the model input, the token
ids in and out, the English before and after detokenising, and the
translation into each other Indian language through English.

Needs torch, onnxruntime, sentencepiece, safetensors and IndicTransToolkit
(the D4 spike's environment); none of them is used by Tark itself.
"""
import json
import math
import pathlib
import shutil
import sys

import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from torch import nn

FLORES = {'hi': 'hin_Deva', 'ta': 'tam_Taml', 'bn': 'ben_Beng', 'en': 'eng_Latn'}
FOLDERS = {'indic_en': 'it2_indic_en', 'en_indic': 'it2_en_indic'}
SHIPPED = ('model.SRC', 'dict.SRC.json', 'dict.TGT.json', 'config.json', 'LICENSE')
SPECIAL = {'<s>', '<pad>', '</s>', '<unk>'}


def sinusoids(count, dim, padding_idx):
    half = dim // 2
    freq = torch.exp(torch.arange(half, dtype=torch.float) * -(math.log(10000) / (half - 1)))
    angles = torch.arange(count, dtype=torch.float)[:, None] * freq[None, :]
    table = torch.cat([torch.sin(angles), torch.cos(angles)], dim=1)
    table[padding_idx] = 0
    return table


class Attention(nn.Module):
    def __init__(self, dim, heads):
        super().__init__()
        self.heads, self.head_dim = heads, dim // heads
        self.q_proj, self.k_proj = nn.Linear(dim, dim), nn.Linear(dim, dim)
        self.v_proj, self.out_proj = nn.Linear(dim, dim), nn.Linear(dim, dim)

    def split(self, x):  # (B, T, D) -> (B, H, T, d)
        return x.view(x.shape[0], x.shape[1], self.heads, self.head_dim).transpose(1, 2)

    def forward(self, x, k, v, mask):
        """x: queries (B, T, D); k, v: (B, H, S, d) already projected."""
        q = self.split(self.q_proj(x)) * self.head_dim ** -0.5
        weights = (q @ k.transpose(-1, -2)) + mask
        out = weights.softmax(-1) @ v
        return self.out_proj(out.transpose(1, 2).reshape(x.shape[0], x.shape[1], -1))


class EncoderLayer(nn.Module):
    def __init__(self, dim, heads, ffn):
        super().__init__()
        self.self_attn = Attention(dim, heads)
        self.self_attn_layer_norm, self.final_layer_norm = nn.LayerNorm(dim), nn.LayerNorm(dim)
        self.fc1, self.fc2 = nn.Linear(dim, ffn), nn.Linear(ffn, dim)

    def forward(self, x, mask):
        h = self.self_attn_layer_norm(x)
        a = self.self_attn
        x = x + a(h, a.split(a.k_proj(h)), a.split(a.v_proj(h)), mask)
        return x + self.fc2(F.gelu(self.fc1(self.final_layer_norm(x))))


class DecoderLayer(nn.Module):
    def __init__(self, dim, heads, ffn):
        super().__init__()
        self.self_attn, self.encoder_attn = Attention(dim, heads), Attention(dim, heads)
        self.self_attn_layer_norm = nn.LayerNorm(dim)
        self.encoder_attn_layer_norm = nn.LayerNorm(dim)
        self.final_layer_norm = nn.LayerNorm(dim)
        self.fc1, self.fc2 = nn.Linear(dim, ffn), nn.Linear(ffn, dim)

    def forward(self, x, past_k, past_v, cross_k, cross_v, cross_mask):
        """One step (or a prefix) with the self-attention cache; returns the
        output and the grown cache."""
        h = self.self_attn_layer_norm(x)
        a = self.self_attn
        k = torch.cat([past_k, a.split(a.k_proj(h))], dim=2)
        v = torch.cat([past_v, a.split(a.v_proj(h))], dim=2)
        t, s = x.shape[1], k.shape[2]
        # One new token sees the whole cache (and the ONNX export traces only
        # that case); a longer prefix needs the causal mask.
        causal = 0.0 if t == 1 else torch.full((t, s), float('-inf')).triu(s - t + 1)
        x = x + a(h, k, v, causal)
        x = x + self.encoder_attn(self.encoder_attn_layer_norm(x), cross_k, cross_v, cross_mask)
        x = x + self.fc2(F.gelu(self.fc1(self.final_layer_norm(x))))
        return x, k, v


class IndicTrans(nn.Module):
    def __init__(self, path):
        super().__init__()
        c = json.loads((path / 'config.json').read_text(encoding='utf-8'))
        self.c = c
        dim = c['encoder_embed_dim']
        self.scale = math.sqrt(dim) if c['scale_embedding'] else 1.0
        self.pad = c['pad_token_id']
        self.enc_embed = nn.Embedding(c['encoder_vocab_size'], dim)
        self.dec_embed = nn.Embedding(c['decoder_vocab_size'], dim)
        self.register_buffer('enc_pos', sinusoids(c['max_source_positions'] + 2, dim, self.pad), persistent=False)
        self.register_buffer('dec_pos', sinusoids(c['max_target_positions'] + 2, dim, self.pad), persistent=False)
        self.enc_layernorm_embedding, self.dec_layernorm_embedding = nn.LayerNorm(dim), nn.LayerNorm(dim)
        self.enc_layers = nn.ModuleList(EncoderLayer(dim, c['encoder_attention_heads'], c['encoder_ffn_dim'])
                                        for _ in range(c['encoder_layers']))
        self.dec_layers = nn.ModuleList(DecoderLayer(dim, c['decoder_attention_heads'], c['decoder_ffn_dim'])
                                        for _ in range(c['decoder_layers']))
        self.enc_layer_norm, self.dec_layer_norm = nn.LayerNorm(dim), nn.LayerNorm(dim)
        self.load(path / 'model.safetensors')

    def load(self, file):
        w = load_file(str(file))
        rename = {'model.encoder.embed_tokens': 'enc_embed', 'model.decoder.embed_tokens': 'dec_embed',
                  'model.encoder.layernorm_embedding': 'enc_layernorm_embedding',
                  'model.decoder.layernorm_embedding': 'dec_layernorm_embedding',
                  'model.encoder.layer_norm': 'enc_layer_norm', 'model.decoder.layer_norm': 'dec_layer_norm',
                  'model.encoder.layers': 'enc_layers', 'model.decoder.layers': 'dec_layers'}
        state = {}
        for key, value in w.items():
            if key == 'lm_head.weight':
                continue  # tied to dec_embed
            for old, new in rename.items():
                if key.startswith(old + '.'):
                    key = new + key[len(old):]
            state[key] = value
        missing, unexpected = self.load_state_dict(state, strict=False)
        assert not unexpected and not missing, (missing, unexpected)

    def encode(self, ids):
        """ids (B, S) -> encoder states (B, S, D) and the additive key mask."""
        mask = ids.ne(self.pad)
        positions = torch.cumsum(mask.int(), dim=1) * mask + self.pad
        x = self.enc_embed(ids) * self.scale + self.enc_pos[positions]
        x = self.enc_layernorm_embedding(x)
        key_mask = torch.zeros(mask.shape, dtype=torch.float).masked_fill(~mask, float('-inf'))[:, None, None, :]
        for layer in self.enc_layers:
            x = layer(x, key_mask)
        return self.enc_layer_norm(x), key_mask

    def cross_kv(self, states):
        """Each decoder layer's cross-attention keys and values, computed once."""
        return [(l.encoder_attn.split(l.encoder_attn.k_proj(states)),
                 l.encoder_attn.split(l.encoder_attn.v_proj(states))) for l in self.dec_layers]

    def decode_step(self, token, step, past, cross, cross_mask):
        """token (B, 1) at position `step` (0-based) -> logits (B, V), new past."""
        x = self.dec_embed(token) * self.scale + self.dec_pos[self.pad + 1 + step][None, None, :]
        x = self.dec_layernorm_embedding(x)
        new_past = []
        for layer, (pk, pv), (ck, cv) in zip(self.dec_layers, past, cross):
            x, k, v = layer(x, pk, pv, ck, cv, cross_mask)
            new_past.append((k, v))
        x = self.dec_layer_norm(x)
        return x[:, -1] @ self.dec_embed.weight.T, new_past

    @torch.inference_mode()
    def greedy(self, ids, max_len=256):
        states, cross_mask = self.encode(ids)
        cross = self.cross_kv(states)
        heads = self.c['decoder_attention_heads']
        head_dim = self.c['decoder_embed_dim'] // heads
        empty = torch.zeros(ids.shape[0], heads, 0, head_dim)
        past = [(empty, empty) for _ in self.dec_layers]
        token = torch.full((ids.shape[0], 1), self.c['decoder_start_token_id'], dtype=torch.long)
        out = []
        for step in range(max_len):
            logits, past = self.decode_step(token, step, past, cross, cross_mask)
            token = logits.argmax(-1, keepdim=True)
            if token.item() == self.c['eos_token_id']:
                break
            out.append(token.item())
        return out


class Encoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.m = model

    def forward(self, ids):
        states, mask = self.m.encode(ids)
        cross = self.m.cross_kv(states)
        return mask, torch.stack([k for k, _ in cross]), torch.stack([v for _, v in cross])


class DecoderStep(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.m = model

    def forward(self, token, step, past_k, past_v, cross_k, cross_v, cross_mask):
        past = list(zip(past_k.unbind(0), past_v.unbind(0)))
        cross = list(zip(cross_k.unbind(0), cross_v.unbind(0)))
        logits, new = self.m.decode_step(token, step, past, cross, cross_mask)
        return logits, torch.stack([k for k, _ in new]), torch.stack([v for _, v in new])


@torch.no_grad()
def export_one(src, out):
    from onnxruntime.quantization import QuantType, quantize_dynamic
    model = IndicTrans(src).eval()
    out.mkdir(parents=True, exist_ok=True)
    c = model.c
    layers, heads = c['decoder_layers'], c['decoder_attention_heads']
    head_dim = c['decoder_embed_dim'] // heads
    ids = torch.tensor([[5, 6, 7, 8, 2]])
    mask, ck, cv = Encoder(model)(ids)
    fp32 = out / 'fp32'
    fp32.mkdir(exist_ok=True)
    torch.onnx.export(
        Encoder(model), (ids,), str(fp32 / 'encoder.onnx'), dynamo=False,
        input_names=['ids'], output_names=['cross_mask', 'cross_k', 'cross_v'],
        dynamic_axes={'ids': {0: 'b', 1: 's'}, 'cross_mask': {0: 'b', 3: 's'},
                      'cross_k': {1: 'b', 3: 's'}, 'cross_v': {1: 'b', 3: 's'}}, opset_version=17)
    past = torch.zeros(layers, 1, heads, 1, head_dim)
    args = (torch.tensor([[2]]), torch.tensor(1), past, past, ck, cv, mask)
    torch.onnx.export(
        DecoderStep(model), args, str(fp32 / 'decoder_step.onnx'), dynamo=False,
        input_names=['token', 'step', 'past_k', 'past_v', 'cross_k', 'cross_v', 'cross_mask'],
        output_names=['logits', 'new_k', 'new_v'],
        dynamic_axes={'token': {0: 'b'}, 'past_k': {1: 'b', 3: 't'}, 'past_v': {1: 'b', 3: 't'},
                      'cross_k': {1: 'b', 3: 's'}, 'cross_v': {1: 'b', 3: 's'}, 'cross_mask': {0: 'b', 3: 's'},
                      'new_k': {1: 'b', 3: 't1'}, 'new_v': {1: 'b', 3: 't1'}}, opset_version=17)
    for part in ('encoder', 'decoder_step'):
        quantize_dynamic(str(fp32 / f'{part}.onnx'), str(out / f'{part}.int8.onnx'), weight_type=QuantType.QInt8)
    shutil.rmtree(fp32)
    for name in SHIPPED:
        shutil.copy2(src / name, out / name)


def export(indic_en, en_indic, out):
    export_one(indic_en, out / FOLDERS['indic_en'])
    export_one(en_indic, out / FOLDERS['en_indic'])


class Translator:
    """The int8 ONNX models in ONNX Runtime, greedy, one sentence at a time."""

    def __init__(self, folder):
        import onnxruntime as ort
        import sentencepiece
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        cpu = ['CPUExecutionProvider']
        self.encoder = ort.InferenceSession(str(folder / 'encoder.int8.onnx'), options, providers=cpu)
        self.decoder = ort.InferenceSession(str(folder / 'decoder_step.int8.onnx'), options, providers=cpu)
        self.spm = sentencepiece.SentencePieceProcessor(model_file=str(folder / 'model.SRC'))
        self.src = json.loads((folder / 'dict.SRC.json').read_text(encoding='utf-8'))
        self.tgt = {v: k for k, v in json.loads((folder / 'dict.TGT.json').read_text(encoding='utf-8')).items()}
        c = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        self.layers, self.heads = c['decoder_layers'], c['decoder_attention_heads']
        self.head_dim = c['decoder_embed_dim'] // self.heads
        self.start, self.eos = c['decoder_start_token_id'], c['eos_token_id']

    def encode(self, line):
        src_tag, tgt_tag, body = line.split(' ', 2)
        pieces = [src_tag, tgt_tag] + self.spm.encode_as_pieces(body)
        return [self.src.get(p, self.src['<unk>']) for p in pieces][:255] + [self.src['</s>']]

    def greedy(self, ids, max_len=256):
        mask, ck, cv = self.encoder.run(None, {'ids': np.array([ids], dtype=np.int64)})
        past_k = past_v = np.zeros((self.layers, 1, self.heads, 0, self.head_dim), dtype=np.float32)
        token, out = self.start, []
        for step in range(max_len):
            logits, past_k, past_v = self.decoder.run(None, {
                'token': np.array([[token]], dtype=np.int64), 'step': np.array(step, dtype=np.int64),
                'past_k': past_k, 'past_v': past_v, 'cross_k': ck, 'cross_v': cv, 'cross_mask': mask})
            token = int(logits[0].argmax())
            if token == self.eos:
                break
            out.append(token)
        return out

    def decode(self, ids):
        tokens = [self.tgt.get(int(i), '<unk>') for i in ids]
        return ''.join(t for t in tokens if t not in SPECIAL).replace('\u2581', ' ').strip()


def indic_processor():
    """IndicTransToolkit's processor without its package __init__ (which
    imports a collator that needs transformers)."""
    import importlib.util
    import types
    site = next(p for p in sys.path if p.endswith('site-packages'))
    package = types.ModuleType('IndicTransToolkit')
    package.__path__ = []
    sys.modules['IndicTransToolkit'] = package
    folder = pathlib.Path(site, 'IndicTransToolkit')
    binary = next(f for f in folder.glob('processor*') if f.suffix in ('.so', '.pyd'))
    spec = importlib.util.spec_from_file_location('IndicTransToolkit.processor', binary)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.IndicProcessor(inference=True)


def golden(models, testdata, out_json):
    from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
    ip = indic_processor()
    to_en = Translator(models / FOLDERS['indic_en'])
    to_indic = Translator(models / FOLDERS['en_indic'])
    rows = (testdata / 'mt_cases.tsv').read_text(encoding='utf-8').splitlines()[1:]
    cases = []
    for row in rows:
        case_id, lang, caption = row.split('\t')
        line = ip.preprocess_batch([caption], src_lang=FLORES[lang], tgt_lang=FLORES['en'])[0]
        src_ids = to_en.encode(line)
        out_ids = to_en.greedy(src_ids)
        english_tokens = to_en.decode(out_ids)
        english = ip.postprocess_batch([english_tokens], lang=FLORES['en'])[0]
        pivot = {}
        for target in sorted({'hi', 'ta', 'bn'} - {lang}):
            hop = ip.preprocess_batch([english], src_lang=FLORES['en'], tgt_lang=FLORES[target])[0]
            hop_src = to_indic.encode(hop)
            hop_out = to_indic.greedy(hop_src)
            text = ip.postprocess_batch([to_indic.decode(hop_out)], lang=FLORES[target])[0]
            pivot[target] = {'model_input': hop.split(' ', 2)[2], 'src_ids': hop_src,
                             'out_ids': hop_out, 'text': text}
        cases.append({
            'id': case_id, 'lang': lang, 'caption': caption,
            'normalized': IndicNormalizerFactory().get_normalizer(lang).normalize(caption.strip()),
            'model_input': line.split(' ', 2)[2],
            'src_ids': src_ids, 'out_ids': out_ids,
            'english_tokens': english_tokens, 'english': english, 'pivot': pivot,
        })
    out_json.write_text(json.dumps({'cases': cases}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def main():
    if len(sys.argv) == 5 and sys.argv[1] == 'export':
        export(*(pathlib.Path(a) for a in sys.argv[2:]))
    elif len(sys.argv) == 5 and sys.argv[1] == 'golden':
        golden(*(pathlib.Path(a) for a in sys.argv[2:]))
    else:
        sys.exit(__doc__.split('\n\n')[1])


if __name__ == '__main__':
    main()
