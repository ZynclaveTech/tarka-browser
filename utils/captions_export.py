#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Caption model files and reference outputs for live captions (D4).

    captions_export.py export MODELS_DIR SILERO_VAD OUT_DIR
    captions_export.py golden MODELS_DIR SILERO_VAD TESTDATA_DIR OUT_JSON

MODELS_DIR is AI4Bharat IndicConformer's assets/ folder (MIT) with
encoder.int8.onnx made by the D4 spike (dynamic int8 quantization of
encoder.onnx). `export` writes what Tark's engine loads: the encoder,
CTC decoder, vocabulary and language masks, Silero VAD, and the
preprocessor's window (window.f32, 400 floats) and mel matrix (mel_fb.f32,
257x80 row-major), little-endian float32, taken from preprocessor.ts.

`golden` runs the reference pipeline (TorchScript preprocessor, ONNX
Runtime int8 encoder + CTC, Silero VAD with its 64-sample context) on the
clips in TESTDATA_DIR/clips.tsv and writes what components/tark_captions is
tested against: per clip the frame count, the first 5 feature frames, the
CTC text, and the speech probability of every 512-sample chunk.

Needs torch, onnxruntime, numpy and soundfile (the D4 spike's environment);
none of them is used by Tark itself.
"""
import json
import pathlib
import shutil
import sys

import numpy as np
import onnxruntime as ort
import soundfile
import torch

BLANK = 256
SHIPPED = ('encoder.int8.onnx', 'ctc_decoder.onnx', 'vocab.json', 'language_masks.json')


def preprocessor_constants(models):
    """The STFT window (c3) and mel matrix (c4) from preprocessor.ts."""
    module = torch.jit.load(str(models / 'preprocessor.ts'), map_location='cpu')
    constants = module.code_with_constants[1]
    window, mel = constants.c3.float().numpy(), constants.c4.float().numpy()
    assert window.shape == (400,) and mel.shape == (257, 80), (window.shape, mel.shape)
    return window, mel


def export(models, vad, out):
    out.mkdir(parents=True, exist_ok=True)
    window, mel = preprocessor_constants(models)
    window.astype('<f4').tofile(out / 'window.f32')
    np.ascontiguousarray(mel).astype('<f4').tofile(out / 'mel_fb.f32')
    for name in SHIPPED:
        shutil.copy2(models / name, out / name)
    shutil.copy2(vad, out / 'silero_vad.onnx')


class Reference:
    def __init__(self, models, vad):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        cpu = ['CPUExecutionProvider']
        self.pre = torch.jit.load(str(models / 'preprocessor.ts'), map_location='cpu')
        self.encoder = ort.InferenceSession(str(models / 'encoder.int8.onnx'), options, providers=cpu)
        self.ctc = ort.InferenceSession(str(models / 'ctc_decoder.onnx'), options, providers=cpu)
        self.vad = ort.InferenceSession(str(vad), options, providers=cpu)
        self.vocab = json.loads((models / 'vocab.json').read_text(encoding='utf-8'))
        self.masks = json.loads((models / 'language_masks.json').read_text(encoding='utf-8'))

    def features(self, pcm):
        signal = torch.from_numpy(pcm).unsqueeze(0)
        with torch.no_grad():
            feats, length = self.pre(input_signal=signal, length=torch.tensor([signal.shape[-1]]))
        return feats.numpy(), length.numpy()

    def ctc_text(self, pcm, lang):
        feats, length = self.features(pcm)
        out, _ = self.encoder.run(['outputs', 'encoded_lengths'], {'audio_signal': feats, 'length': length})
        logprobs = self.ctc.run(['logprobs'], {'encoder_output': out})[0][0][:, self.masks[lang]]
        ids = np.argmax(logprobs, axis=-1)
        collapsed = [int(t) for i, t in enumerate(ids) if i == 0 or t != ids[i - 1]]
        return ''.join(self.vocab[lang][t] for t in collapsed if t != BLANK).replace('▁', ' ').strip()

    def vad_probs(self, pcm):
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros(64, dtype=np.float32)
        probs = []
        for i in range(0, len(pcm) - 511, 512):
            chunk = pcm[i:i + 512]
            x = np.concatenate([context, chunk])[None, :].astype(np.float32)
            out, state = self.vad.run(None, {'input': x, 'state': state, 'sr': np.array(16000, dtype=np.int64)})
            context = chunk[-64:]
            probs.append(round(float(out[0][0]), 6))
        return probs


def golden(models, vad, testdata, out_json):
    ref = Reference(models, vad)
    clips = []
    rows = (testdata / 'clips.tsv').read_text(encoding='utf-8').splitlines()[1:]
    for row in rows:
        wav, lang = row.split('\t')[:2]
        pcm, rate = soundfile.read(testdata / wav, dtype='float32')
        assert rate == 16000 and pcm.ndim == 1, wav
        feats, _ = ref.features(pcm)
        clips.append({
            'wav': wav, 'lang': lang, 'samples': len(pcm),
            'features_frames': int(feats.shape[2]),
            'features_head': [[round(float(feats[0, m, f]), 6) for m in range(80)] for f in range(5)],
            'ctc_text': ref.ctc_text(pcm, lang),
            'vad_probs': ref.vad_probs(pcm),
        })
    out_json.write_text(json.dumps({'clips': clips}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def main():
    if len(sys.argv) == 5 and sys.argv[1] == 'export':
        export(*(pathlib.Path(a) for a in sys.argv[2:]))
    elif len(sys.argv) == 6 and sys.argv[1] == 'golden':
        golden(*(pathlib.Path(a) for a in sys.argv[2:]))
    else:
        sys.exit(__doc__.split('\n\n')[1])


if __name__ == '__main__':
    main()
