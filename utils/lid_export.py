#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Export the spoken-language-ID model Tark's speech process runs before it
captions a call (D4 Phase 3): SpeechBrain's VoxLingua107 ECAPA (Apache-2.0)
as one ONNX file from 16 kHz waveform to 107 log-probabilities.

usage:
  lid_export.py export SRC_DIR OUT_DIR [--int8]
  lid_export.py golden SRC_DIR FLEURS_DIR TESTDATA_DIR
  lid_export.py policy OUT_DIR FLEURS_DIR

SRC_DIR is the SpeechBrain model folder (hyperparams.yaml, embedding_model.ckpt,
classifier.ckpt, label_encoder.ckpt). FLEURS_DIR holds FLEURS test languages
(<code>/test/*.wav, CC-BY-4.0). `export` writes lid.onnx and lid_labels.txt;
`golden` writes TESTDATA_DIR/lid_golden.json and the clips it scored under
TESTDATA_DIR/lid/; `policy` prints what `decide` makes of every clip.

The features are SpeechBrain's Fbank, rebuilt from ONNX-friendly pieces: the
STFT is a Conv1d with fixed DFT weights (400-point periodic Hamming window,
hop 160, centred with zero padding), then the power spectrum, SpeechBrain's
own 60-band mel filterbank and log (top 80 dB), and the sentence mean taken
off. Then ECAPA and its classifier, unchanged.
"""
import json
import math
import pathlib
import sys

SAMPLE_RATE = 16000
FIRST_DECISION = 3.0  # seconds of speech
LAST_DECISION = 5.0

# What DetectionPolicy (components/tark_captions/detection_policy.cc) knows.
CAPTIONED = {'hi', 'ta', 'bn'}
APPLE = {'en', 'es', 'fr', 'de', 'it', 'pt', 'ja', 'ko', 'zh', 'yue'}
# IndicConformer covers these too; they are listed once measured.
PLANNED = {'as', 'gu', 'kn', 'ml', 'mr', 'ne', 'pa', 'sa', 'sd', 'te'}
MERGED = {'ur': 'hi'}  # spoken Hindustani: one detection
FAMILIES = ({'bn', 'as'}, {'hi', 'mr', 'gu', 'pa', 'ne', 'sa', 'sd'}, {'ta', 'ml', 'te', 'kn'})
LOCK_PROBABILITY = 0.9  # tuned on 550 FLEURS clips (ledger)
NEIGHBOUR_PROBABILITY = 0.1


def decide(probs, labels, seconds, lock=LOCK_PROBABILITY, neighbour=NEIGHBOUR_PROBABILITY):
    """(kind, code): kind is caption, apple, planned, unsupported or unsure."""
    if seconds < FIRST_DECISION:
        return ('unsure', '')
    p = {}
    for code, value in zip(labels, probs):
        code = MERGED.get(code, code)
        p[code] = p.get(code, 0.0) + float(value)
    top = max(p, key=p.get)
    if p[top] < lock and seconds < LAST_DECISION:
        return ('unsure', '')
    code = top
    if top not in CAPTIONED and p[top] < lock:
        # An unsure call between neighbours goes to the one Tark captions.
        for family in FAMILIES:
            if top in family:
                best = max((c for c in family if c in CAPTIONED), key=lambda c: p.get(c, 0.0))
                if p.get(best, 0.0) >= neighbour:
                    code = best
    if code in CAPTIONED:
        return ('caption', code)
    if code in APPLE:
        return ('apple', code)
    if code in PLANNED:
        return ('planned', code)
    return ('unsupported', code)


def speech_start(wav):
    """First 30 ms frame within 25 dB of the clip's loudest (skips the lead-in)."""
    import numpy as np
    hop = int(0.03 * SAMPLE_RATE)
    frames = wav[: len(wav) // hop * hop].reshape(-1, hop)
    db = 10 * np.log10((frames ** 2).mean(1) + 1e-10)
    loud = np.nonzero(db > db.max() - 25)[0]
    return int(loud[0] * hop) if len(loud) else 0


def fleurs_clips(root, codes, per_language, seconds):
    """[(fleurs code, float32 mono 16 kHz)], `seconds` from each clip's speech."""
    import numpy as np
    import soundfile
    out = []
    for code in codes:
        taken = 0
        for path in sorted((pathlib.Path(root) / code / 'test').glob('*.wav')):
            wav, rate = soundfile.read(path, dtype='float32')
            assert rate == SAMPLE_RATE, rate
            wav = wav if wav.ndim == 1 else wav.mean(1)
            wav = wav[speech_start(wav):]
            if len(wav) < int(seconds * SAMPLE_RATE):
                continue
            out.append((code, np.ascontiguousarray(wav[: int(seconds * SAMPLE_RATE)])))
            taken += 1
            if taken == per_language:
                break
    return out


def load_reference(src):
    from speechbrain.inference.classifiers import EncoderClassifier
    return EncoderClassifier.from_hparams(source=str(src), savedir=str(src),
                                          run_opts={"device": "cpu"})


def labels_of(reference):
    encoder = reference.hparams.label_encoder
    return [encoder.ind2lab[i].split(':')[0] for i in range(len(encoder.ind2lab))]


def build_module(reference):
    import torch
    import torch.nn.functional as F

    class Lid(torch.nn.Module):
        def __init__(self):
            super().__init__()
            n_fft, self.hop = 400, 160
            self.pad = n_fft // 2
            window = torch.hamming_window(n_fft)
            k = torch.arange(n_fft // 2 + 1, dtype=torch.float64)[:, None]
            n = torch.arange(n_fft, dtype=torch.float64)[None, :]
            angle = 2 * math.pi * k * n / n_fft
            self.register_buffer('cos', (torch.cos(angle) * window).float()[:, None, :])
            self.register_buffer('sin', (torch.sin(angle) * window).float()[:, None, :])
            self.fbanks = reference.mods.compute_features.compute_fbanks
            self.embedding = reference.mods.embedding_model
            self.classifier = reference.mods.classifier

        def forward(self, waveform):
            x = F.pad(waveform[:, None, :], (self.pad, self.pad))
            re = F.conv1d(x, self.cos, stride=self.hop)
            im = F.conv1d(x, self.sin, stride=self.hop)
            feats = self.fbanks((re * re + im * im).transpose(1, 2))
            feats = feats - feats.mean(dim=1, keepdim=True)
            return self.classifier(self.embedding(feats)).squeeze(1)

    return Lid().eval()


def export(src, out, int8=False):
    import torch
    out.mkdir(parents=True, exist_ok=True)
    reference = load_reference(src)
    module = build_module(reference)
    target = out / ('lid.fp32.onnx' if int8 else 'lid.onnx')
    with torch.inference_mode():
        torch.onnx.export(module, (torch.zeros(1, 3 * SAMPLE_RATE),), str(target),
                          input_names=['waveform'], output_names=['logits'],
                          dynamic_axes={'waveform': {1: 'samples'}}, opset_version=17,
                          dynamo=False)
    if int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        quantize_dynamic(str(target), str(out / 'lid.onnx'), weight_type=QuantType.QInt8)
        target.unlink()
    (out / 'lid_labels.txt').write_text('\n'.join(labels_of(reference)) + '\n', encoding='utf-8')


def softmax(logits):
    import numpy as np
    e = np.exp(logits - logits.max())
    return e / e.sum()


GOLDEN = (('hi_in', 2), ('ta_in', 2), ('bn_in', 2), ('en_us', 2), ('es_419', 2), ('sw_ke', 2))


def golden(src, fleurs, testdata):
    import numpy as np
    import soundfile
    import torch
    reference = load_reference(src)
    labels = labels_of(reference)
    (testdata / 'lid').mkdir(parents=True, exist_ok=True)
    cases = []
    for code, count in GOLDEN:
        for i, (_, wav) in enumerate(fleurs_clips(fleurs, [code], count, 6.0)):
            name = f'lid/{code[:2]}_{i + 1}.wav'
            soundfile.write(testdata / name, wav, SAMPLE_RATE, subtype='PCM_16')
            # Scored as the C++ test reads it back: 16-bit, first 3 s.
            wav16, _ = soundfile.read(testdata / name, dtype='float32')
            first = wav16[: int(FIRST_DECISION * SAMPLE_RATE)]
            logits = reference.classify_batch(torch.from_numpy(first)[None])[0][0].numpy()
            cases.append({'file': name, 'lang': code[:2], 'seconds': FIRST_DECISION,
                          'top': labels[int(np.argmax(logits))],
                          'logits': [round(float(v), 5) for v in logits]})
    (testdata / 'lid_golden.json').write_text(json.dumps({'cases': cases}, indent=1) + '\n')


POLICY_LANGS = ('hi_in', 'ta_in', 'bn_in', 'te_in', 'mr_in', 'ur_pk', 'en_us', 'es_419', 'fr_fr',
                'cmn_hans_cn', 'sw_ke')


def policy(out, fleurs, lock=LOCK_PROBABILITY, neighbour=NEIGHBOUR_PROBABILITY, report=True):
    """Per language: the share of each decision, deciding at 3 s, else at 5 s."""
    import onnxruntime
    session = onnxruntime.InferenceSession(str(out / 'lid.onnx'))
    labels = (out / 'lid_labels.txt').read_text(encoding='utf-8').split('\n')[:-1]
    cache = getattr(policy, 'cache', {})
    policy.cache = cache
    table = {}
    for code in POLICY_LANGS:
        decisions = []
        for i, (_, wav) in enumerate(fleurs_clips(fleurs, [code], 50, LAST_DECISION)):
            key = (code, i)
            if key not in cache:
                cache[key] = [softmax(session.run(['logits'], {'waveform': wav[None, : int(s * SAMPLE_RATE)]})[0][0])
                              for s in (FIRST_DECISION, LAST_DECISION)]
            first, last = cache[key]
            d = decide(first, labels, FIRST_DECISION, lock, neighbour)
            if d[0] == 'unsure':
                d = decide(last, labels, LAST_DECISION, lock, neighbour)
            decisions.append(d)
        counts = {}
        for kind, c in decisions:
            counts[f'{kind}:{c}'] = counts.get(f'{kind}:{c}', 0) + 1
        table[code] = {k: round(v / len(decisions), 2) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}
        if report:
            print(code, json.dumps(table[code]))
    return table


def main():
    args = sys.argv[1:]
    if len(args) in (3, 4) and args[0] == 'export':
        export(pathlib.Path(args[1]), pathlib.Path(args[2]), int8=args[3:] == ['--int8'])
    elif len(args) == 4 and args[0] == 'golden':
        golden(*(pathlib.Path(a) for a in args[1:]))
    elif len(args) == 3 and args[0] == 'policy':
        policy(pathlib.Path(args[1]), pathlib.Path(args[2]))
    else:
        sys.exit(__doc__.split('\n\n')[1])


if __name__ == '__main__':
    main()
