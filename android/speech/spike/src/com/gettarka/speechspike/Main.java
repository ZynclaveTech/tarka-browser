package com.gettarka.speechspike;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.speech.RecognitionListener;
import android.speech.RecognitionSupport;
import android.speech.RecognitionSupportCallback;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.concurrent.Executors;

/**
 * Phone (Step 2) spike: live mic. `am start -n com.gettarka.speechspike/.Main --es mode
 * <pipe|normal|switch>`. Logs under tag SpeechSpike; the last line of every run is "DONE".
 */
public class Main extends Activity {
    private static final String T = "SpeechSpike";
    private static final int RATE = 16000;
    private static final int BYTES_PER_MS = RATE * 2 / 1000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private SpeechRecognizer rec;
    private String mode;
    private long t0;
    private String lastText = "";
    private long lastChangeNs;
    private long lastPartialNs;
    private volatile boolean recording;

    private void log(String s) { Log.i(T, "t=" + (System.nanoTime() - t0) / 1_000_000 + "ms " + s); }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        t0 = System.nanoTime();
        mode = String.valueOf(getIntent().getStringExtra("mode"));
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            log("requesting RECORD_AUDIO");
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        } else {
            go();
        }
    }

    @Override public void onRequestPermissionsResult(int c, String[] p, int[] r) {
        if (r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED) go();
        else { log("RECORD_AUDIO denied"); log("DONE"); }
    }

    private void go() {
        log("mode=" + mode + " onDeviceAvailable=" + SpeechRecognizer.isOnDeviceRecognitionAvailable(this));
        rec = SpeechRecognizer.createOnDeviceSpeechRecognizer(this);
        try {
            switch (mode) {
                case "pipe": runPipe(); break;
                case "normal": runNormal(); break;
                case "switch": runSwitch(); break;
                default: log("unknown mode"); log("DONE");
            }
        } catch (Exception e) { log("EXC " + e); log("DONE"); }
    }

    private Intent baseIntent(String lang) {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        return i;
    }

    private Intent pipeIntent(String lang, ParcelFileDescriptor read) {
        Intent i = baseIntent(lang);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, read);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1);
        i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, RATE);
        return i;
    }

    private AudioRecord newRecord() {
        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        return new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, 3200 * 4));
    }

    /** Mode pipe: 6 s of AudioRecord into the pipe, then close. */
    private void runPipe() throws Exception {
        ParcelFileDescriptor[] p = ParcelFileDescriptor.createPipe();
        rec.setRecognitionListener(listener("pipe"));
        rec.startListening(pipeIntent("en-US", p[0]));
        new Thread(() -> {
            AudioRecord ar = newRecord();
            ar.startRecording();
            recording = true;
            log("SPEAK NOW (pipe, en-US, 6 s)");
            FileOutputStream o = new FileOutputStream(p[1].getFileDescriptor());
            pump(ar, o, 6000, null);
            ar.stop(); ar.release(); recording = false;
            closeQuiet(p[1]);
            log("pipe closed (capture ended)");
            main.postDelayed(this::finishRun, 3000);
        }).start();
    }

    /** Mode normal: recognizer's own mic. */
    private void runNormal() {
        rec.setRecognitionListener(listener("normal"));
        rec.startListening(baseIntent("en-US"));
        log("SPEAK NOW (normal, en-US, recognizer mic)");
        main.postDelayed(this::finishRun, 12000); // safety net if onResults/onError never comes
    }

    /** Mode switch: en-US for 3 s, cancel, second language replays buffer then live to 7 s. */
    private void runSwitch() {
        rec.checkRecognitionSupport(baseIntent("en-US"), Executors.newSingleThreadExecutor(),
                new RecognitionSupportCallback() {
                    @Override public void onSupportResult(RecognitionSupport s) {
                        String second = s.getInstalledOnDeviceLanguages().contains("en-IN") ? "en-IN" : "en-US";
                        log("installed=" + s.getInstalledOnDeviceLanguages() + " second language=" + second);
                        main.post(() -> { try { switchRun(second); } catch (Exception e) { log("EXC " + e); log("DONE"); } });
                    }
                    @Override public void onError(int e) {
                        log("support error=" + e + "; second language=en-US");
                        main.post(() -> { try { switchRun("en-US"); } catch (Exception x) { log("EXC " + x); log("DONE"); } });
                    }
                });
    }

    private void switchRun(String second) throws Exception {
        ParcelFileDescriptor[] p1 = ParcelFileDescriptor.createPipe();
        rec.setRecognitionListener(listener("switch-first"));
        rec.startListening(pipeIntent("en-US", p1[0]));
        new Thread(() -> {
            AudioRecord ar = newRecord();
            ar.startRecording();
            recording = true;
            log("SPEAK NOW (switch: en-US then " + second + ", 7 s)");
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            pump(ar, new FileOutputStream(p1[1].getFileDescriptor()), 3000, buf);
            closeQuiet(p1[1]);
            ParcelFileDescriptor[] p2;
            try { p2 = ParcelFileDescriptor.createPipe(); } catch (Exception e) { log("EXC " + e); return; }
            final ParcelFileDescriptor[] fp2 = p2;
            main.post(() -> {
                rec.cancel();
                lastText = "";
                rec.setRecognitionListener(listener("switch-second"));
                rec.startListening(pipeIntent(second, fp2[0]));
                log("switched to " + second + "; replaying " + buf.size() + " buffered bytes");
            });
            FileOutputStream o2 = new FileOutputStream(p2[1].getFileDescriptor());
            try { o2.write(buf.toByteArray()); } catch (Exception e) { log("replay write " + e); }
            log("buffered audio written; now live");
            pump(ar, o2, 4000, null); // AudioRecord kept recording meanwhile, so nothing is lost
            ar.stop(); ar.release(); recording = false;
            closeQuiet(p2[1]);
            log("pipe closed at 7 s");
            main.postDelayed(this::finishRun, 3000);
        }).start();
    }

    /** Reads durationMs of audio from ar into o (and optionally copy). */
    private void pump(AudioRecord ar, java.io.OutputStream o, int durationMs, ByteArrayOutputStream copy) {
        byte[] b = new byte[20 * BYTES_PER_MS];
        int left = durationMs * BYTES_PER_MS;
        while (left > 0) {
            int n = ar.read(b, 0, Math.min(b.length, left));
            if (n <= 0) { log("AudioRecord read " + n); break; }
            left -= n;
            if (copy != null) copy.write(b, 0, n);
            try { o.write(b, 0, n); } catch (Exception e) { log("pipe write " + e); break; }
        }
    }

    private boolean finished;
    private void finishRun() {
        if (finished) return;
        finished = true;
        if (lastChangeNs != 0 && lastPartialNs != 0)
            log("SUMMARY final text=[" + lastText + "] endOfSpeech(last text change)->final partial="
                    + (lastPartialNs - lastChangeNs) / 1_000_000 + "ms");
        log("DONE");
        rec.destroy();
        finish();
    }

    private static void closeQuiet(ParcelFileDescriptor p) { try { p.close(); } catch (Exception ignored) {} }

    private RecognitionListener listener(String tag) {
        return new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle b) { log(tag + " onReadyForSpeech"); }
            @Override public void onBeginningOfSpeech() { log(tag + " onBeginningOfSpeech"); }
            @Override public void onRmsChanged(float r) {}
            @Override public void onBufferReceived(byte[] b) {}
            @Override public void onEndOfSpeech() { log(tag + " onEndOfSpeech"); }
            @Override public void onError(int e) {
                log(tag + " onError " + e);
                if (mode.equals("normal")) finishRun();
            }
            @Override public void onPartialResults(Bundle b) {
                String t = first(b);
                long now = System.nanoTime();
                if (t != null && !t.trim().equals(lastText.trim())) { lastText = t; lastChangeNs = now; }
                lastPartialNs = now;
                log(tag + " partial recording=" + recording + " " + texts(b));
            }
            @Override public void onSegmentResults(Bundle b) { log(tag + " segment " + texts(b)); }
            @Override public void onResults(Bundle b) {
                long now = System.nanoTime();
                String since = lastChangeNs != 0 ? " sinceLastTextChange=" + (now - lastChangeNs) / 1_000_000 + "ms" : "";
                log(tag + " onResults recording=" + recording + " " + texts(b) + since);
                String t = first(b);
                if (t != null) lastText = t;
                if (mode.equals("normal")) finishRun();
            }
            @Override public void onEvent(int t, Bundle b) {}
        };
    }

    private static String first(Bundle b) {
        ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return r == null || r.isEmpty() ? null : r.get(0);
    }

    private static String texts(Bundle b) {
        ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        if (r != null) return String.valueOf(r);
        StringBuilder sb = new StringBuilder("{");
        for (String k : b.keySet()) sb.append(k).append('=').append(b.get(k)).append(' ');
        return sb.append('}').toString();
    }
}
