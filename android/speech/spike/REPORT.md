# Task 1 spike: on-device recognizer fed through EXTRA_AUDIO_SOURCE

Date: 2026-10-25. Device: emulator-5554 (AVD tark_a1, API 36), recognizer
`com.google.android.as/...AiAiSpeechRecognitionService`, created with
`SpeechRecognizer.createOnDeviceSpeechRecognizer`.

**Provisional verdict: LIVE-ON-EMULATOR.** The plan's final `LIVE` needs Step 2 on
the phone bf678949, which has not been run. That step needs the user's approval for
the run.

The spike is a standalone app (`com.gettarka.speechspike`), not in `patches/series`.
`build.sh` builds it with plain javac/d8/aapt2/apksigner from the SDK. It generates
`assets/hello.wav` with `say` + `afconvert` (16 kHz mono LEI16), and its text is
"hello world. this is a test of the speech recognizer" (3.49 s). `run.sh` launches
one mode and dumps logcat tag `SPIKE`.

Audio fed in every mode: 300 ms silence, then the speech, then 2000 ms silence. That
is 5.79 s of PCM16 mono 16 kHz. The extras are `EXTRA_AUDIO_SOURCE` (PFD),
`EXTRA_AUDIO_SOURCE_ENCODING=ENCODING_PCM_16BIT`, `EXTRA_AUDIO_SOURCE_CHANNEL_COUNT=1`
and `EXTRA_AUDIO_SOURCE_SAMPLING_RATE=16000`, plus `EXTRA_PARTIAL_RESULTS=true`.

## Language packs

`checkRecognitionSupport` showed `installed=[en-US]` and no hi-IN. hi-IN is only in
`supported`. `triggerModelDownload(en-IN)` opened the AiAi `DownloadActivity`
("Download English (India) update ... 114 MB"). I tapped Download through
`adb input tap`, and after that the check showed `installed=[en-IN, en-US]`. No
`ModelDownloadListener` callback ever arrived; I confirmed the install by polling
`checkRecognitionSupport`.

## Step 1: pipe feed, en-US (PASS)

The writer thread paces the PCM into the `createPipe()` write end in real time, in
20 ms chunks, then closes it.

```
pipe t=376ms  pipeOpen=true onReadyForSpeech
pipe t=809ms  pipeOpen=true onBeginningOfSpeech
pipe t=1005ms pipeOpen=true onPartialResults [Hello]
pipe t=1364ms pipeOpen=true onPartialResults [Hello world]
pipe t=1953ms pipeOpen=true onEndOfSpeech
pipe t=1965ms pipeOpen=true onBeginningOfSpeech        <- recognizer keeps listening
pipe t=3865ms pipeOpen=true onPartialResults [This is a test of the speech recognizer]
pipe t=4350ms pipeOpen=true onEndOfSpeech
pipe closed at t=5793ms (speech ended t=3784ms)
pipe t=5801ms pipeOpen=false onResults {}  sinceAudioEnd=8ms
```

- **EXTRA_AUDIO_SOURCE is honoured.** The recognizer transcribes the fed audio. The
  emulator mic gives silence, so the text can only come from the pipe.
- **Streaming works.** `onPartialResults` arrives about every 120 ms while the pipe
  is still open, about 200 ms behind real time.
- **The session is continuous.** After `onEndOfSpeech` it opens a new utterance
  (`onBeginningOfSpeech`), and the partials restart for that segment. A client must
  join the segments itself.
- **Concern: the final `onResults` bundle is EMPTY (`{}`, no `results_recognition`).**
  It arrives only when the pipe closes (EOF). The usable text is the last
  `onPartialResults` of each segment. When an utterance ends, the last partial can be
  an n-best list (see the en-IN run below). I saw this on every run.
- **`stopListening()` while the pipe is open gives `onError 5` (ERROR_CLIENT)** and no
  results (`END=stop` run). Closing the pipe is the only clean way to end a session.

## Step 3: restart and replay (PASS, both variants)

The first session gets the first 1000 ms (32000 bytes). It is then cancelled and a
new session is started. The new session gets the buffered 1000 ms in one burst, then
the rest in real time. The cut was at about 1 s, not 4 s, because the clip is short
(the brief said 4 s).

**Variant A, same language (en-US to en-US):** `replay-second t=64ms onPartialResults
[Hello]`, then `[Hello world]`, then `[This is a test of the speech recognizer]`. The
buffered words came back.

**Variant B, second installed language (en-US cancelled, en-IN restarted):**

```
replay: writer stopped at 32000 bytes (1000 ms), cancelling
replay-second lang=en-IN
replay-second t=4ms  onReadyForSpeech
replay-second t=4ms  onError 5            <- stray ERROR_CLIENT from cancelling session 1
replay-second t=201ms onPartialResults [hello]
replay-second t=341ms onPartialResults [hello world]
replay-second t=3409ms onPartialResults [hello world this is a test of the speech recognizer, ...n-best]
replay-second t=4792ms onResults {}  sinceAudioEnd=3ms
```

The buffered "hello" was recovered after the language switch. en-IN does not split
at the pause, and its final partial is an n-best list. Concern: the cancel's
`ERROR_CLIENT` is delivered after the new `startListening`, and the new listener
receives it. A real client must ignore errors that arrive in about the first 10 ms,
or use a session token.

## Latency

A normal mic session can't be fed on the emulator, so I compared the pipe against an
`EXTRA_AUDIO_SOURCE` file-fed baseline: a read-only PFD on a raw PCM file holding the
same 5.79 s.

| Mode | Measure | Runs |
|---|---|---|
| Pipe, real-time paced | pipe close (EOF) to `onResults` | 8, 12, 10 ms (replays: 6, 3 ms) |
| Pipe, real-time paced | last speech byte to `onResults` | about 2015 ms. This is all trailing silence: results wait for EOF, not for endpointing |
| Pipe, real-time paced | last speech byte to final partial of the segment | about 565 ms (3784 to 4350 ms, `onEndOfSpeech`) |
| File-fed | `startListening` to `onResults` (whole file) | 482, 421 ms |

The file baseline reads the file far faster than real time: all of its events land
within 4 ms. The "end of audio" therefore happens before the first callback, so
end-of-audio to result is under about 450 ms. **Concern: the file feed lost the
second segment.** It returned only `[Hello world]`, so bursting a whole utterance-gap
at once is lossy in en-US. The 1 s burst in the replay was not lossy.

Practical conclusion: if the client takes the last partial as the answer, the
transcript is ready about 0.5 s after speech ends. If it waits for `onResults`, it
is ready as soon as the client closes the pipe. Either way the pipe adds no
measurable latency of its own; I can't separate it from the 120 ms partial cadence.

## Step 2 on the phone (PENDING: needs the user's approval for the run)

This is not run. Step 2 also needs an `AudioRecord` mic-capture mode added to the
spike (with RECORD_AUDIO), which does not exist yet. The file-replay modes can run on
the phone as they are:

```sh
cd android/speech/spike && ./build.sh && adb -s bf678949 install -r out/spike.apk
./run.sh bf678949 check en-US 5
./run.sh bf678949 pipe en-US 10
./run.sh bf678949 file en-US 5
LANG2=hi-IN ./run.sh bf678949 replay en-US 10   # or LANG2=en-US if only one pack
adb -s bf678949 uninstall com.gettarka.speechspike
```
