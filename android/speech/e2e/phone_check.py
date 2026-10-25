#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Voice languages and live detection on a real phone, with a person speaking.

    android/speech/e2e/phone_check.py [--serial bf678949] [--steps 1,2,...]

Interactive: run it in a terminal next to the phone. Each step prints what
to say and counts down 3-2-1; the person speaks into the phone. Tark is used
as installed (never cleared or reinstalled, its log never cleared, its
microphone permission never touched); airplane mode is put back as it was
and anything that could not be is printed as NOT RESTORED.

Before a step: g runs it, Enter or s skips it. After a step: r repeats it,
Enter goes on. Inside a step, after each spoken session: Enter keeps it,
r redoes it, s abandons the rest of the step. Ctrl-C inside a step abandons
that step only; Ctrl-C at a prompt goes straight to the restore.

Evidence goes to android/speech/e2e/phone-check-<timestamp>/stepN-*/.
"""
import argparse
import datetime
import html
import importlib.util
import json
import pathlib
import re
import signal
import socketserver
import statistics
import subprocess
import sys
import threading
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
# run.py imports android/xlit/e2e/run.py as `run`: load this one under
# another name so the two don't collide.
_spec = importlib.util.spec_from_file_location('speech_run', HERE / 'run.py')
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
xlit = R.xlit

PACKAGE = R.PACKAGE
PORT = R.PORT
PAGE = f'http://127.0.0.1:{PORT}/page_timing.html'
HOST = f'127.0.0.1:{PORT}'
DETECT = R.DETECT

EN = 'what is the weather in Delhi today'
HI_LONG = 'आज दिल्ली में मौसम कैसा है, मुझे बताओ'
HI_LONG_ROMAN = 'aaj dilli mein mausam kaisa hai, mujhe batao'
HI_SHORT = 'मौसम कैसा है'
HI_SHORT_ROMAN = 'mausam kaisa hai'
EN_IN = 'weather ... (pause about 1 second) ... in Delhi'
SPEED_BAR_MS = 150


class Skip(Exception):
    """The person chose to abandon the rest of this step."""


class Abort(Exception):
    """Ctrl-C at a prompt: straight to the restore."""


def ask(prompt, choices):
    """One keypress-ish answer (a line); '' is Enter."""
    while True:
        try:
            got = input(prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            raise Abort() from None
        if got in choices:
            return got
        print(f'  please answer one of: {", ".join(c or "Enter" for c in choices)}')


def countdown(phrase, roman=None, note=None):
    print()
    print('  ' + '=' * 60)
    print(f'  SAY:  "{phrase}"')
    if roman:
        print(f'        ({roman})')
    if note:
        print(f'  NOTE: {note}')
    print('  ' + '=' * 60)
    for n in (3, 2, 1):
        print(f'  {n}...', flush=True)
        time.sleep(1)
    print('  >>> SPEAK NOW <<<', flush=True)


class Evidence:
    def __init__(self, root, name):
        self.dir = root / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.data = {}
        self.log_file = (self.dir / 'log.txt').open('a', encoding='utf-8')

    def log(self, text):
        line = f'[{datetime.datetime.now():%H:%M:%S}] {text}'
        print('  ' + line, flush=True)
        self.log_file.write(line + '\n')
        self.log_file.flush()

    def put(self, key, value):
        self.data[key] = value
        (self.dir / 'results.json').write_text(json.dumps(self.data, indent=2, ensure_ascii=False,
                                                          default=str))

    def file(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    def shot(self, dev, name):
        path = self.dir / f'{name}.png'
        try:
            path.write_bytes(subprocess.run(dev.adb + ['exec-out', 'screencap', '-p'],
                                            capture_output=True, timeout=15).stdout)
        except subprocess.TimeoutExpired:
            return ''
        return str(path)


# --- the phone ---------------------------------------------------------------

def screen(dev, tries=2):
    """The screen, never hanging (uiautomator waits for an idle page)."""
    return R.busy_screen(dev, tries)


def texts(xml):
    return [html.unescape(t) for t in re.findall(r'text="([^"]+)"', xml)]


def tap_bounds(dev, m):
    x1, y1, x2, y2 = map(int, m.groups())
    dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(1)


def tap_text_in(dev, xml, label, contains=False):
    pattern = (r'text="[^"]*' + re.escape(label) + r'[^"]*"' if contains
               else r'text="' + re.escape(label) + r'"')
    m = re.search(pattern + r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not m:
        return False
    tap_bounds(dev, m)
    return True


def page_state(xml):
    """#out and the timing line, from one dump."""
    out = ''
    m = re.search(r'text="((?:idle|listening|result:|error:)[^"]*)"', xml)
    if m:
        out = html.unescape(m.group(1))
    timing = {}
    m = re.search(r'text="timing: ([^"]*)"', xml)
    if m:
        try:
            timing = json.loads(html.unescape(m.group(1)))
        except json.JSONDecodeError:
            timing = {'unparsed': html.unescape(m.group(1))}
    return out, timing


def open_page(dev, lang, interim=False):
    url = f'{PAGE}?lang={lang}' + ('&interim=1' if interim else '')
    dev.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
    dev.open(url)
    for _ in range(12):
        if 'Listen' in screen(dev, 1):
            return
        time.sleep(1)
    raise RuntimeError('the test page did not load (no Listen button)')


def start_listening(dev):
    """Presses Listen, allowing the site's microphone prompt for this time;
    returns once the page says listening (or has already ended)."""
    if not xlit.tap_text(dev, 'Listen', tries=3):
        raise RuntimeError('no Listen button')
    end = time.time() + 15
    while time.time() < end:
        xml = screen(dev, 1)
        out, _ = page_state(xml)
        if 'Allow this time' in xml:
            tap_text_in(dev, xml, 'Allow this time')
            continue
        if out.startswith(('listening', 'result:', 'error:')):
            return out
        time.sleep(0.3)
    raise RuntimeError('the page never started listening')


def wait_done(dev, timeout, watch=None):
    """Polls until #out is a result or an error and the page's `end` came;
    `watch(xml, elapsed)` sees every dump. Returns (out, timing)."""
    started = time.time()
    out, timing = '', {}
    while time.time() - started < timeout:
        xml = screen(dev, 1)
        if watch:
            watch(xml, time.time() - started)
        o, t = page_state(xml)
        out, timing = o or out, t or timing
        if out.startswith(('result:', 'error:')) and 'end' in (timing.get('ev') or {}):
            return out, timing
        time.sleep(0.2)
    return out or 'timeout', timing


def first(ev, name):
    v = (ev or {}).get(name)
    return v[0] if v else None


def end_to_final(timing):
    """ms from the page's first speechend/soundend/audioend to the final result."""
    ev = timing.get('ev') or {}
    ends = [x for x in (first(ev, 'speechend'), first(ev, 'soundend'), first(ev, 'audioend'))
            if x is not None]
    final = first(ev, 'final')
    if not ends or final is None:
        return None
    return final - min(ends)


def session(dev, ev, lang, phrase, roman=None, note=None, interim=False, timeout=30,
            watch=None, tag='session'):
    """One spoken session; asks keep/redo/skip. Returns its record."""
    while True:
        mark = dev.mark()
        open_page(dev, lang, interim)
        state = start_listening(dev)
        go = time.time()
        if not state.startswith('listening'):
            ev.log(f'{tag}: ended before speaking: {state}')
        countdown(phrase, roman, note)
        out, timing = wait_done(dev, timeout, watch)
        rec = {
            'lang': lang, 'out': out, 'text': out[len('result: '):] if out.startswith('result:') else '',
            'end_to_final_ms': end_to_final(timing), 'timing': timing,
            'wall_s_from_go': round(time.time() - go, 2),
        }
        log = dev.log_since(mark, '--pid', tark_pid(dev)) if tark_pid(dev) else dev.log_since(mark)
        rec['logcat'] = ev.file(f'{tag}-logcat.txt', log)
        rec['logcat_end_of_speech'] = [ln for ln in log.splitlines()
                                       if re.search(r'end ?of ?speech|EndOfSpeech|finishPiped', ln, re.I)][:10]
        ev.log(f'{tag}: {out!r}  end->final: {rec["end_to_final_ms"]} ms')
        ans = ask('  Enter = keep, r = redo this session, s = abandon the step: ', ('', 'r', 's'))
        if ans == 's':
            raise Skip()
        if ans == '':
            return rec
        ev.log(f'{tag}: redo')


def tark_pid(dev):
    return dev.shell('pidof', PACKAGE).strip().split(' ')[0]


# --- Voice languages ---------------------------------------------------------

def detection_state(dev):
    """The detection row's [summary, button], or [] when not found."""
    R.open_voice_languages(dev)
    xml = R.find_scrolling(dev, DETECT, swipes=14)
    return R.detection_row(xml) if xml else []


def detection_on(row):
    return 'Remove' in row


def scan_voice_languages(dev, swipes=14):
    """Every text on the Voice languages page, top to bottom (it scrolls)."""
    R.open_voice_languages(dev)
    seen = []
    for _ in range(swipes):
        xml = screen(dev)
        new = [t for t in texts(xml) if t not in seen]
        seen += new
        if not new:
            break
        R.swipe_up(dev)
    return seen


def hindi_ready(dev):
    """('ready'|'missing'|'unknown', the texts after Hindi)."""
    seen = scan_voice_languages(dev)
    for i, t in enumerate(seen):
        if t.startswith('Hindi'):
            after = seen[i + 1:i + 4]
            if any('Ready' in a for a in after):
                return 'ready', after
            if any(a in ('Download', 'Try again', 'Downloading…', 'Waiting for Wi-Fi') for a in after):
                return 'missing', after
            return 'unknown', after
    return 'unknown', []


def sites_row(dev):
    """(xml, row text) for the page's origin in Voice languages > Sites."""
    R.open_voice_languages(dev)
    xml = R.find_scrolling(dev, 'Sites', swipes=14)
    if not xml:
        return '', None
    for _ in range(3):
        m = re.search(r'text="([^"]*' + re.escape(HOST) + r'[^"]*)"', xml)
        if m:
            return xml, m
        R.swipe_up(dev)
        xml = screen(dev)
    return xml, None


def site_summary(xml, m):
    s = re.search(re.escape(m.group(0)) + r'.{0,600}?text="([^"]+)"', xml, re.S)
    return html.unescape(s.group(1)) if s else ''


def remove_site(dev, ev):
    xml, m = sites_row(dev)
    if not m:
        ev.log('Sites: the origin is not listed (nothing to remove)')
        return True
    if not R.tap_desc(dev, f'Remove {html.unescape(m.group(1))}', xml):
        ev.log('Sites: no Remove button for the origin')
        return False
    gone = HOST not in screen(dev)
    ev.log(f'Sites: removed the origin: {gone}')
    return gone


# --- Tark's sockets (step 7) -------------------------------------------------

def tark_uid(dev):
    m = re.search(r'userId=(\d+)', dev.shell('dumpsys', 'package', PACKAGE))
    return m.group(1) if m else None


def _addr(hexaddr):
    ip, port = hexaddr.split(':')
    port = int(port, 16)
    if len(ip) == 8:
        b = bytes.fromhex(ip)[::-1]
        return f'{".".join(map(str, b))}:{port}'
    words = [bytes.fromhex(ip[i:i + 8])[::-1].hex() for i in range(0, 32, 8)]
    full = ''.join(words)
    if full.startswith('0' * 20 + 'ffff'):
        b = bytes.fromhex(full[24:])
        return f'{".".join(map(str, b))}:{port}'
    return f'[{":".join(full[i:i + 4] for i in range(0, 32, 4))}]:{port}'


def sockets(dev, uid):
    """{remote} Tark's uid has open to anywhere but loopback/unset."""
    found = set()
    raw = dev.shell('cat', '/proc/net/tcp', '/proc/net/tcp6', '/proc/net/udp', '/proc/net/udp6')
    if 'local_address' not in raw:
        raise RuntimeError(f'/proc/net is not readable from adb shell: {raw[:200]!r}')
    for line in raw.splitlines():
        if 'local_address' in line:
            continue
        f = line.split()
        if len(f) < 8 or f[7] != uid:
            continue
        remote = _addr(f[2])
        if remote.startswith(('127.', '0.0.0.0', '[0000:0000:0000:0000:0000:0000:0000:0000]')):
            continue
        found.add(remote)
    return found


# --- the steps ---------------------------------------------------------------

STATE = {'detection_at_start': None, 'detector_added': False, 'baseline': [], 'airplane': None}


def speed_runs(dev, ev, n=3):
    runs = []
    for i in range(n):
        print(f'\n  Session {i + 1} of {n} (lang=en-US).')
        rec = session(dev, ev, 'en-US', EN, tag=f'run{i + 1}')
        runs.append({k: v for k, v in rec.items() if k != 'timing'} | {'timing': rec['timing']})
        ev.put('runs', runs)
    return runs


def summarize_runs(runs):
    ms = [r['end_to_final_ms'] for r in runs if r['end_to_final_ms'] is not None]
    return {'end_to_final_ms': ms, 'mean': round(statistics.mean(ms)) if ms else None,
            'max': max(ms) if ms else None, 'texts': [r['text'] for r in runs]}


def en_ok(text):
    t = text.lower()
    return all(w in t for w in ('weather', 'delhi'))


def step1(dev, ev):
    """Baseline, detection off: 3 en-US sessions."""
    row = detection_state(dev)
    ev.put('detection row', row)
    if detection_on(row):
        ev.log(f'Detection is ON already: {row}')
        if ask('  Remove it now for the baseline (step 2 gets it back)? [y/n]: ', ('y', 'n')) == 'y':
            xlit.tap_text(dev, 'Remove', tries=2)
            time.sleep(3)
            ev.put('removed for baseline', R.detection_row(R.find_scrolling(dev, DETECT, swipes=14)))
        else:
            return 'NOT RUN', 'detection is on: no baseline with it off'
    runs = speed_runs(dev, ev)
    s = summarize_runs(runs)
    STATE['baseline'] = s['end_to_final_ms']
    ev.put('summary', s)
    return 'ok', f'end->final mean {s["mean"]} ms, max {s["max"]} ms; texts {s["texts"]}'


def step2(dev, ev):
    """Turn detection on: Get, wait until ready (10 min)."""
    row = detection_state(dev)
    ev.put('row before', row)
    if detection_on(row):
        return 'ok', f'already on: {row}'
    if not row:
        return 'FAIL', 'no detection row (Android 12 or a low-end phone hides it)'
    xml = screen(dev)
    if not (tap_text_in(dev, xml, 'Get') or tap_text_in(dev, xml, 'Try again')
            or tap_text_in(dev, xml, 'Download now')):
        return 'FAIL', f'no Get button: {row}'
    STATE['detector_added'] = True
    started = time.time()
    seen, retries, last = [], 0, None
    while time.time() - started < 600:
        row = R.detection_row(screen(dev, 1))
        if row and row != last:
            t = round(time.time() - started, 1)
            seen.append([t, row])
            ev.log(f'+{t}s {row}')
            if any('Trying again soon' in x for x in row):
                retries += 1
            if any('Waiting for Wi-Fi' in x for x in row):
                ev.log('Waiting for Wi-Fi: put the phone on Wi-Fi')
            last = row
            ev.put('rows', seen)
        if detection_on(row or []):
            secs = round(time.time() - started, 1)
            ev.put('seconds to ready', secs)
            ev.put('retries', retries)
            ev.shot(dev, 'ready')
            return 'ok', f'ready in {secs} s, {retries} "Trying again soon…"'
        time.sleep(2)
    ev.shot(dev, 'not-ready')
    ev.put('retries', retries)
    return 'TIMEOUT', f'not ready in 10 min; last row {last}; {retries} retries'


def step3(dev, ev):
    """Speed with detection on: 3 en-US sessions against the baseline."""
    row = detection_state(dev)
    ev.put('detection row', row)
    if not detection_on(row):
        return 'NOT RUN', f'detection is not on: {row}'
    runs = speed_runs(dev, ev)
    s = summarize_runs(runs)
    base = STATE['baseline']
    if s['mean'] is None or not base:
        ev.put('summary', s)
        return 'INCOMPLETE', f'no baseline or no timings: {s}'
    d_mean = s['mean'] - statistics.mean(base)
    d_max = s['max'] - max(base)
    correct = [en_ok(t) for t in s['texts']]
    s.update(baseline_ms=base, delta_mean_ms=round(d_mean), delta_max_ms=d_max, en_correct=correct)
    ev.put('summary', s)
    ok = d_mean <= SPEED_BAR_MS and d_max <= SPEED_BAR_MS and all(correct)
    return ('ok' if ok else 'FAIL',
            f'delta mean {round(d_mean)} ms, max {d_max} ms (bar {SPEED_BAR_MS}); '
            f'text correct {correct}: {s["texts"]}')


def ensure_hindi(dev, ev):
    state, after = hindi_ready(dev)
    ev.put('Hindi pack', [state, after])
    ev.log(f'Hindi pack: {state} {after}')
    while state != 'ready':
        print('  Hindi is not ready on this phone. Tap Download next to Hindi in Voice languages '
              '(or Download on the snackbar later), wait for "✓ Ready".')
        ans = ask('  Enter = check again, c = carry on anyway, s = skip the step: ', ('', 'c', 's'))
        if ans == 's':
            raise Skip()
        if ans == 'c':
            break
        state, after = hindi_ready(dev)
        ev.log(f'Hindi pack: {state} {after}')
        ev.put('Hindi pack', [state, after])
    return state


def step4(dev, ev):
    """Switch: Hindi on an en-US page; tap Switch."""
    ensure_hindi(dev, ev)
    row = detection_state(dev)
    if not detection_on(row):
        return 'NOT RUN', f'detection is not on: {row}'
    remove_site(dev, ev)  # a remembered language would skip the chip
    chip = {}

    def watch(xml, elapsed):
        if 'Sounds like' in xml and 'shown_s' not in chip:
            chip['shown_s'] = round(elapsed, 1)
            chip['text'] = [t for t in texts(xml) if 'Sounds like' in t or t == 'Switch']
            ev.log(f'chip at +{chip["shown_s"]}s: {chip["text"]}')
            if tap_text_in(dev, xml, 'Switch'):
                chip['tapped_s'] = round(elapsed, 1)
                ev.log('tapped Switch')
        if 'That sounded like' in xml and 'next_time' not in chip:
            chip['next_time'] = [t for t in texts(xml) if 'sounded like' in t or 'next time' in t]

    rec = session(dev, ev, 'en-US', HI_LONG, HI_LONG_ROMAN, note='speak for about 6 seconds',
                  interim=True, timeout=40, watch=watch, tag='switch')
    ev.put('session', rec)
    ev.put('chip', chip)
    text = rec['text']
    early = {'आज': 'आज' in text or 'aaj' in text.lower(),
             'दिल्ली': 'दिल्ली' in text or 'dilli' in text.lower() or 'delhi' in text.lower()}
    ev.put('words before the switch kept', early)
    ev.shot(dev, 'after-switch')
    # Switch remembers the site: put that back so step 5 starts clean.
    xml, m = sites_row(dev)
    ev.put('Sites after switch', site_summary(xml, m) if m else 'not listed')
    remove_site(dev, ev)
    if 'shown_s' not in chip:
        return 'FAIL', f'no "Sounds like" chip; text {text!r}'
    in_time = chip['shown_s'] <= 5
    return ('ok' if in_time and all(early.values()) else 'FAIL',
            f'chip at {chip["shown_s"]} s ({chip.get("text")}), tapped: {"tapped_s" in chip}; '
            f'final {text!r}; early words kept {early}')


def step5(dev, ev):
    """Next time: short Hindi; tap Use Hindi next time; Sites lists it; remove."""
    row = detection_state(dev)
    if not detection_on(row):
        return 'NOT RUN', f'detection is not on: {row}'
    remove_site(dev, ev)
    got = {}

    def watch(xml, elapsed):
        if 'Sounds like' in xml and 'chip' not in got:
            got['chip'] = [t for t in texts(xml) if 'Sounds like' in t]
            ev.log(f'(a Switch chip showed instead: {got["chip"]}; not tapped)')
        if 'That sounded like' in xml and 'snack' not in got:
            got['snack'] = [t for t in texts(xml) if 'sounded like' in t or 'next time' in t]
            got['tapped'] = tap_text_in(dev, xml, 'next time', contains=True)
            ev.log(f'NEXT_TIME {got["snack"]}, tapped: {got["tapped"]}')

    rec = session(dev, ev, 'en-US', HI_SHORT, HI_SHORT_ROMAN, timeout=25, watch=watch, tag='nexttime')
    ev.put('session', rec)
    end = time.time() + 15
    while 'snack' not in got and time.time() < end:
        watch(screen(dev, 1), 0)
        time.sleep(0.3)
    ev.put('snackbar', got)
    ev.shot(dev, 'after-session')
    if 'snack' not in got:
        return 'FAIL', f'no "That sounded like" snackbar; text {rec["text"]!r}'
    xml, m = sites_row(dev)
    summary = site_summary(xml, m) if m else ''
    ev.put('Sites row', [html.unescape(m.group(1)) if m else None, summary])
    ev.shot(dev, 'sites')
    listed = bool(m) and 'Hindi' in summary + (m.group(1) if m else '')
    removed = remove_site(dev, ev)
    ev.put('removed again', removed)
    return ('ok' if listed and got.get('tapped') and removed else 'FAIL',
            f'snackbar {got["snack"]}, tapped {got.get("tapped")}; Sites: '
            f'{"listed with " + summary if m else "not listed"}; removed again: {removed}')


def step6(dev, ev):
    """en-IN with a 1 s pause: both parts kept; end after the last word."""
    rec = session(dev, ev, 'en-IN', EN_IN, note='"weather", wait about 1 second, then "in Delhi"',
                  interim=True, timeout=30, tag='en-in')
    ev.put('session', rec)
    t = rec['text'].lower()
    both = 'weather' in t and 'delhi' in t
    timing = rec['timing']
    final = first(timing.get('ev'), 'final')
    inter = timing.get('interims') or []
    last_change = None
    if inter:
        last_text = inter[-1][1]
        last_change = next(ms for ms, x in inter if x == last_text)
    after_last = final - last_change if final is not None and last_change is not None else None
    ev.put('both parts', both)
    ev.put('final after last interim change ms', after_last)
    return ('ok' if both else 'FAIL',
            f'{rec["text"]!r}; both parts {both}; end->final {rec["end_to_final_ms"]} ms; '
            f'final {after_last} ms after the text last changed')


def step7(dev, ev):
    """No request from Tark during a detection-on session (socket sampling)."""
    row = detection_state(dev)
    if not detection_on(row):
        return 'NOT RUN', f'detection is not on: {row}'
    uid = tark_uid(dev)
    if not uid:
        return 'NOT RUN', 'no uid for Tark'
    open_page(dev, 'en-US')
    before = sockets(dev, uid)
    ev.put('uid', uid)
    ev.put('remote endpoints before', sorted(before))
    seen, stop = set(), threading.Event()
    errors = []

    def sample():
        while not stop.is_set():
            try:
                seen.update(sockets(dev, uid))
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
            time.sleep(0.25)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    try:
        rec = session(dev, ev, 'en-US', EN, timeout=30, tag='netcheck')
        time.sleep(1)
    finally:
        stop.set()
        th.join(5)
    new = sorted(seen - before)
    ev.put('session', rec)
    ev.put('remote endpoints during', sorted(seen))
    ev.put('new during the session', new)
    ev.put('sampling errors', errors[:5])
    if errors and not seen:
        return 'NOT RUN', f'could not sample sockets: {errors[0]}'
    return ('ok' if not new else 'FAIL',
            f'{len(new)} new remote endpoint(s) from Tark during the session: {new}; '
            f'{len(before)} open before (long-lived connections are not seen as requests)')


STEPS = [
    ('1', 'baseline', 'Baseline, detection off (3 en-US sessions)', step1),
    ('2', 'detection-on', 'Turn detection on (Get, wait up to 10 min)', step2),
    ('3', 'speed', 'Speed, detection on (3 en-US sessions, delta <= 150 ms)', step3),
    ('4', 'switch', 'Switch (Hindi on an en-US page)', step4),
    ('5', 'next-time', 'Next time (short Hindi, Use Hindi next time, Sites)', step5),
    ('6', 'en-in-pause', 'en-IN with a 1 s pause', step6),
    ('7', 'no-network', 'No request from Tark during a detection-on session', step7),
]


def restore(dev, root):
    """Step 8: detection as it was, airplane mode as it was; mic untouched."""
    ev = Evidence(root, 'step8-restore')
    not_restored = []
    try:
        row = detection_state(dev)
        ev.put('detection row now', row)
        was_on = detection_on(STATE['detection_at_start'] or [])
        if STATE['detector_added'] and detection_on(row) and not was_on:
            if ask('  The script turned detection on. Remove it now? [y/n]: ', ('y', 'n')) == 'y':
                xml = R.find_scrolling(dev, DETECT, swipes=14)
                tap_text_in(dev, xml, 'Remove')
                time.sleep(3)
                ev.put('detection row after Remove', R.detection_row(screen(dev)))
        elif was_on and not detection_on(row):
            not_restored.append(f'detection was on at the start and is now {row} (Get it again)')
    except Abort:
        not_restored.append('detection: restore question interrupted')
    except Exception as e:  # noqa: BLE001
        not_restored.append(f'detection: {type(e).__name__}: {e}')
    try:
        _, m = sites_row(dev)
        if m and not remove_site(dev, ev):
            not_restored.append(f'Sites still lists {HOST}')
    except Exception as e:  # noqa: BLE001
        not_restored.append(f'Sites: {type(e).__name__}: {e}')
    try:
        dev.airplane(STATE['airplane'])
        time.sleep(2)
        if dev.run('get-state').strip() != 'device':
            not_restored.append('phone disconnected: airplane mode not verified')
        elif dev.airplane_on() != STATE['airplane']:
            not_restored.append(f'airplane mode (was {STATE["airplane"]}, now {dev.airplane_on()})')
    except Exception as e:  # noqa: BLE001
        not_restored.append(f'airplane: {type(e).__name__}: {e}')
    try:
        mic = f'{R.MIC}: granted=true' in dev.shell('dumpsys', 'package', PACKAGE)
        ev.put('mic granted (untouched)', mic)
    except Exception:  # noqa: BLE001
        pass
    dev.run('reverse', '--remove', f'tcp:{PORT}')
    ev.put('not restored', not_restored)
    return ev, not_restored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--serial', default='bf678949')
    parser.add_argument('--steps', default='1,2,3,4,5,6,7', help='comma-separated, e.g. 3,4')
    args = parser.parse_args(argv)
    if args.serial.startswith('emulator-'):
        print('this is the phone check: use run.py for the emulator', file=sys.stderr)
        return 2
    dev = R.Device(args.serial, phone=True)
    if dev.run('get-state').strip() != 'device':
        print(f'{args.serial} is not connected', file=sys.stderr)
        return 2
    if PACKAGE not in dev.shell('pm', 'list', 'packages', PACKAGE):
        print(f'{PACKAGE} is not installed on {args.serial}', file=sys.stderr)
        return 2
    root = HERE / f'phone-check-{datetime.datetime.now():%Y%m%d-%H%M%S}'
    root.mkdir()
    print(f'Evidence: {root}')
    STATE['airplane'] = dev.airplane_on()
    if STATE['airplane']:
        print('Airplane mode is ON: the check needs it off; it is put back on at the end.')
        dev.airplane(False)
        time.sleep(3)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), R.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')

    def on_signal(signum, _frame):
        raise SystemExit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    wanted = set(args.steps.split(','))
    table = []
    try:
        try:
            STATE['detection_at_start'] = detection_state(dev)
        except Exception as e:  # noqa: BLE001
            STATE['detection_at_start'] = []
            print(f'could not read the detection row: {e}')
        print(f'Detection at the start: {STATE["detection_at_start"]}')
        (root / 'start.json').write_text(json.dumps(STATE, ensure_ascii=False, default=str))
        for num, slug, title, fn in STEPS:
            if num not in wanted:
                continue
            ev = Evidence(root, f'step{num}-{slug}')
            status, detail = 'skipped', ''
            while True:
                print(f'\n### Step {num}: {title}')
                print(f'    {fn.__doc__}')
                if ask('  g = run, Enter or s = skip: ', ('g', '', 's')) != 'g':
                    status, detail = 'skipped', ''
                    break
                try:
                    status, detail = fn(dev, ev)
                except Skip:
                    status, detail = 'skipped', 'abandoned mid-step'
                except KeyboardInterrupt:
                    status, detail = 'skipped', 'Ctrl-C mid-step'
                except Abort:
                    raise
                except Exception as e:  # noqa: BLE001 — a broken step must not stop the rest
                    status, detail = 'ERROR', f'{type(e).__name__}: {e}'
                    ev.file('traceback.txt', traceback.format_exc())
                ev.put('status', status)
                ev.put('detail', detail)
                ev.log(f'STEP {num}: {status} {detail}')
                print(f'  evidence: {ev.dir}')
                if ask('  r = repeat this step, Enter = go on: ', ('', 'r')) != 'r':
                    break
            table.append((num, title, status, detail, str(ev.dir)))
    except Abort:
        print('\nStopped: restoring.')
    finally:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        print('\n### Step 8: restore and clean up')
        try:
            ev, not_restored = restore(dev, root)
            table.append(('8', 'Restore', 'ok' if not not_restored else 'NOT RESTORED',
                          '; '.join(not_restored), str(ev.dir)))
        except Exception as e:  # noqa: BLE001
            not_restored = [f'restore: {type(e).__name__}: {e}']
        for what in not_restored:
            print(f'NOT RESTORED: {what}', flush=True)
        server.shutdown()
        print('\n' + '=' * 100)
        print(f'{"step":<5}{"status":<14}{"what":<48}detail')
        for num, title, status, detail, path in table:
            print(f'{num:<5}{status:<14}{title[:46]:<48}{detail}')
            print(f'{"":<19}evidence: {path}')
        (root / 'summary.json').write_text(json.dumps(table, indent=2, ensure_ascii=False))
        print(f'\nAll evidence: {root}')
    return 1 if any(r[2] not in ('ok', 'skipped') for r in table) else 0


if __name__ == '__main__':
    sys.exit(main())
