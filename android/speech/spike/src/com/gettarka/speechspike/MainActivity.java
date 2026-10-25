package com.gettarka.speechspike;

import android.app.Activity;
import android.content.Intent;
import android.media.AudioFormat;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.speech.ModelDownloadListener;
import android.speech.RecognitionListener;
import android.speech.RecognitionSupport;
import android.speech.RecognitionSupportCallback;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.concurrent.Executors;

/**
 * Throwaway spike: does the on-device SpeechRecognizer accept app-fed audio via
 * EXTRA_AUDIO_SOURCE? Driven by `am start -n ... --es mode <check|download|pipe|file|replay>
 * [--es lang en-US]`. All output goes to logcat tag SPIKE.
 */
public class MainActivity extends Activity {
    private static final String T = "SPIKE";
    private static final int RATE = 16000;
    private static final int BYTES_PER_MS = RATE * 2 / 1000; // 16-bit mono
    private static final int CHUNK_MS = 20;

    private final Handler main = new Handler(Looper.getMainLooper());
    private SpeechRecognizer rec;
    private String lang;
    private long t0;
    private volatile long tAudioEnd; // nanoTime when the last byte went into the pipe
    private volatile long tSpeechEnd; // nanoTime when the last speech (non-padding) byte went in
    private volatile boolean pipeOpen;

    private static void log(String s) { Log.i(T, s); }
    private long ms(long ns) { return (ns - t0) / 1_000_000; }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        String mode = getIntent().getStringExtra("mode");
        lang = getIntent().getStringExtra("lang");
        if (lang == null) lang = "en-US";
        log("start mode=" + mode + " lang=" + lang
                + " onDeviceAvailable=" + SpeechRecognizer.isOnDeviceRecognitionAvailable(this));
        rec = SpeechRecognizer.createOnDeviceSpeechRecognizer(this);
        try {
            switch (String.valueOf(mode)) {
                case "check": check(); break;
                case "download": download(); break;
                case "pipe": pipeSession(speechPcm(), -1); break;
                case "file": fileSession(); break;
                case "replay": pipeSession(speechPcm(), 1000); break;
                default: log("unknown mode");
            }
        } catch (Exception e) { log("EXC " + e); }
    }

    private Intent baseIntent() {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        return i;
    }

    private void check() {
        rec.checkRecognitionSupport(baseIntent(), Executors.newSingleThreadExecutor(),
                new RecognitionSupportCallback() {
                    @Override public void onSupportResult(RecognitionSupport s) {
                        log("support installed=" + s.getInstalledOnDeviceLanguages()
                                + " pending=" + s.getPendingOnDeviceLanguages()
                                + " supported=" + s.getSupportedOnDeviceLanguages()
                                + " online=" + s.getOnlineLanguages());
                    }
                    @Override public void onError(int e) { log("support error=" + e); }
                });
    }

    private void download() {
        rec.triggerModelDownload(baseIntent(), Executors.newSingleThreadExecutor(),
                new ModelDownloadListener() {
                    @Override public void onProgress(int p) { log("download progress=" + p); }
                    @Override public void onSuccess() { log("download success"); }
                    @Override public void onScheduled() { log("download scheduled"); }
                    @Override public void onError(int e) { log("download error=" + e); }
                });
    }

    /** 300 ms silence + WAV speech + 2000 ms silence, as raw PCM16 mono 16 kHz. */
    private byte[] speechPcm() throws Exception {
        byte[] speech = wavData();
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        o.write(new byte[300 * BYTES_PER_MS]);
        o.write(speech);
        o.write(new byte[2000 * BYTES_PER_MS]);
        speechBytes = 300 * BYTES_PER_MS + speech.length;
        return o.toByteArray();
    }
    private int speechBytes;

    private byte[] wavData() throws Exception {
        InputStream in = getAssets().open("hello.wav");
        byte[] all = in.readAllBytes();
        int p = 12;
        while (p + 8 <= all.length) {
            String id = new String(all, p, 4, "US-ASCII");
            int len = (all[p + 4] & 0xff) | (all[p + 5] & 0xff) << 8 | (all[p + 6] & 0xff) << 16 | (all[p + 7] & 0xff) << 24;
            if (id.equals("data")) {
                byte[] d = new byte[Math.min(len, all.length - p - 8)];
                System.arraycopy(all, p + 8, d, 0, d.length);
                return d;
            }
            p += 8 + len + (len & 1);
        }
        throw new IllegalStateException("no data chunk");
    }

    private Intent audioIntent(ParcelFileDescriptor pfd) {
        Intent i = baseIntent();
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, pfd);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, RATE);
        return i;
    }

    /** File-fed baseline: the recognizer reads a raw PCM file at its own pace. */
    private void fileSession() throws Exception {
        File f = new File(getCacheDir(), "speech.pcm");
        try (OutputStream o = new FileOutputStream(f)) { o.write(speechPcm()); }
        ParcelFileDescriptor pfd = ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
        rec.setRecognitionListener(listener("file"));
        t0 = System.nanoTime();
        rec.startListening(audioIntent(pfd));
        log("file startListening bytes=" + f.length());
    }

    /**
     * Pipe-fed session, paced in real time (20 ms chunks). If cancelAtMs >= 0, the first
     * session is cancelled at that point and a second session is started, fed the buffered
     * bytes first (as fast as possible) then the rest in real time.
     */
    private void pipeSession(byte[] pcm, int cancelAtMs) throws Exception {
        ParcelFileDescriptor[] p = ParcelFileDescriptor.createPipe();
        rec.setRecognitionListener(listener(cancelAtMs >= 0 ? "replay-first" : "pipe"));
        t0 = System.nanoTime();
        rec.startListening(audioIntent(p[0]));
        pipeOpen = true;
        log("pipe startListening total=" + pcm.length + " speechBytes=" + speechBytes);
        new Thread(() -> {
            int cut = cancelAtMs >= 0 ? cancelAtMs * BYTES_PER_MS : pcm.length;
            int off = writePaced(p[1], pcm, 0, cut);
            if (cancelAtMs >= 0) {
                log("replay: writer stopped at " + off + " bytes (" + off / BYTES_PER_MS + " ms), cancelling");
                closeQuiet(p[1]);
                main.post(() -> {
                    rec.cancel();
                    try { startReplay(pcm, off); } catch (Exception e) { log("EXC " + e); }
                });
            } else {
                tAudioEnd = System.nanoTime();
                if ("stop".equals(getIntent().getStringExtra("end"))) {
                    log("audio done at t=" + ms(tAudioEnd) + "ms; calling stopListening with pipe still open");
                    main.post(() -> rec.stopListening());
                    try { Thread.sleep(3000); } catch (InterruptedException ignored) {}
                }
                closeQuiet(p[1]);
                pipeOpen = false;
                log("pipe closed at t=" + ms(System.nanoTime()) + "ms (audio ended t=" + ms(tAudioEnd)
                        + "ms, speech ended t=" + ms(tSpeechEnd) + "ms)");
            }
        }).start();
    }

    private void startReplay(byte[] pcm, int buffered) throws Exception {
        ParcelFileDescriptor[] p = ParcelFileDescriptor.createPipe();
        String lang2 = getIntent().getStringExtra("lang2");
        if (lang2 != null) lang = lang2;
        log("replay-second lang=" + lang);
        rec.setRecognitionListener(listener("replay-second"));
        t0 = System.nanoTime();
        rec.startListening(audioIntent(p[0]));
        pipeOpen = true;
        log("replay-second startListening; writing " + buffered + " buffered bytes then rest");
        new Thread(() -> {
            try {
                new FileOutputStream(p[1].getFileDescriptor()).write(pcm, 0, buffered); // burst
                log("replay-second buffered written at t=" + ms(System.nanoTime()) + "ms");
            } catch (Exception e) { log("EXC replay buffered " + e); return; }
            writePaced(p[1], pcm, buffered, pcm.length);
            tAudioEnd = System.nanoTime();
            closeQuiet(p[1]);
            pipeOpen = false;
            log("replay-second pipe closed at t=" + ms(tAudioEnd) + "ms");
        }).start();
    }

    private int writePaced(ParcelFileDescriptor w, byte[] pcm, int from, int to) {
        int chunk = CHUNK_MS * BYTES_PER_MS;
        int off = from;
        try {
            OutputStream o = new FileOutputStream(w.getFileDescriptor());
            long start = System.nanoTime();
            while (off < to) {
                int n = Math.min(chunk, to - off);
                o.write(pcm, off, n);
                off += n;
                if (off >= speechBytes && tSpeechEnd == 0) tSpeechEnd = System.nanoTime();
                long due = start + (long) (off - from) / BYTES_PER_MS * 1_000_000L;
                long sleep = (due - System.nanoTime()) / 1_000_000L;
                if (sleep > 0) Thread.sleep(sleep);
            }
        } catch (Exception e) { log("write stopped at " + off + ": " + e); }
        return off;
    }

    private static void closeQuiet(ParcelFileDescriptor p) { try { p.close(); } catch (Exception ignored) {} }

    private RecognitionListener listener(String tag) {
        return new RecognitionListener() {
            String pre() { return tag + " t=" + ms(System.nanoTime()) + "ms pipeOpen=" + pipeOpen + " "; }
            @Override public void onReadyForSpeech(Bundle b) { log(pre() + "onReadyForSpeech"); }
            @Override public void onBeginningOfSpeech() { log(pre() + "onBeginningOfSpeech"); }
            @Override public void onRmsChanged(float r) {}
            @Override public void onBufferReceived(byte[] b) {}
            @Override public void onEndOfSpeech() { log(pre() + "onEndOfSpeech"); }
            @Override public void onError(int e) { log(pre() + "onError " + e); }
            @Override public void onPartialResults(Bundle b) { log(pre() + "onPartialResults " + texts(b)); }
            @Override public void onSegmentResults(Bundle b) { log(pre() + "onSegmentResults " + texts(b)); }
            @Override public void onResults(Bundle b) {
                long now = System.nanoTime();
                String extra = tAudioEnd != 0 ? " sinceAudioEnd=" + (now - tAudioEnd) / 1_000_000 + "ms" : "";
                extra += tSpeechEnd != 0 ? " sinceSpeechEnd=" + (now - tSpeechEnd) / 1_000_000 + "ms" : "";
                log(pre() + "onResults " + texts(b) + extra);
            }
            @Override public void onEvent(int t, Bundle b) {}
        };
    }

    private static String texts(Bundle b) {
        ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        if (r != null) return String.valueOf(r);
        StringBuilder sb = new StringBuilder("{");
        for (String k : b.keySet()) sb.append(k).append('=').append(b.get(k)).append(' ');
        return sb.append('}').toString();
    }
}
