#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Voice input (the Web Speech API on Android's on-device recognizer) on the emulator.

    android/speech/e2e/run.py APK [--serial emulator-5554] [case ...]
        cases: answers offline missing_pack no_network_host navigate_away
               permission_denied settings_sections site_language private_tab
               offer_once detection_row detection_wifi_wait detection_resume
               detection_netlog

Installs APK, serves page.html from this Mac (port 8005, through adb
reverse) and reads the page's #out line from the screen. Speech, the
phrase as macOS `say` speaks it, reaches the emulator's microphone one of
two ways: --speaker plays it through the Mac's speakers into the Mac's
microphone, which the emulator takes as host audio (start it without
-no-audio, with -allow-host-audio, then `adb emu avd hostmicon`); --inject
streams it in through the emulator's gRPC injectAudio call (start it with
`-grpc 8554 -grpc-use-token`; needs grpcio and grpcio-tools). The en-US
on-device pack must be installed on the emulator; ta-IN must not be.
Each case starts from a cleared app with the microphone granted. With
neither, no speech is fed and answers/offline report NOT RUN (with what
silence gave). Prints "ok CASE", "FAIL CASE: why" or "NOT RUN CASE: why";
exits 1 unless every case is ok. Emulator only, unless --phone: then the
phone's own Tark is used as installed (APK is not installed, the app is
never cleared), cases that need root report NOT RUN, and the phone's
airplane mode and Tark's microphone permission are put back as they were.
"""
import argparse
import functools
import glob
import http.server
import json
import os
import pathlib
import re
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parents[1] / 'xlit' / 'e2e'))
import run as xlit  # noqa: E402  (android/xlit/e2e/run.py: Device, tap_text)

PORT = 8005
PACKAGE = xlit.PACKAGE
PAGE = f'http://127.0.0.1:{PORT}/page.html'
PHRASE = 'hello world'
NETLOG = f'/data/user/0/{PACKAGE}/cache/netlog.json'
RATE = 16000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, *args):
        pass


MIC = 'android.permission.RECORD_AUDIO'


class Device(xlit.Device):
    def __init__(self, serial, phone=False):
        super().__init__(serial)
        # A phone holds its owner's Tark: never cleared, no root, no flags,
        # and its settings go back as they were (remember_state, restore).
        self.phone = phone
        self.saved = {}

    def current_state(self):
        return {
            'airplane': self.airplane_on(),
            'mic': f'{MIC}: granted=true' in self.shell('dumpsys', 'package', PACKAGE),
        }

    def remember_state(self):
        self.saved = self.current_state()

    def airplane_on(self):
        return self.shell('settings', 'get', 'global', 'airplane_mode_on').strip() == '1'

    def restore(self):
        """Puts the remembered state back; returns what it could not (some
        phones refuse the shell a revoke: REVOKE_RUNTIME_PERMISSIONS)."""
        if not self.saved:
            return []
        steps = {
            'airplane': lambda: self.airplane(self.saved['airplane']),
            'mic': lambda: self.shell('pm', 'grant' if self.saved['mic'] else 'revoke', PACKAGE, MIC),
        }
        failed = []
        for key, step in steps.items():
            try:
                step()
            except Exception as e:  # noqa: BLE001 — every step is tried
                failed.append(f'{key}: {type(e).__name__}: {e}')
        # An unplugged phone answers every shell call with nothing: that must
        # never read as "put back".
        if self.run('get-state').strip() != 'device':
            return failed + ['phone disconnected: state not verified']
        try:
            now = self.current_state()
        except Exception as e:  # noqa: BLE001
            return failed + [f'could not read the state back: {type(e).__name__}: {e}']
        failed += [f'{key} (was {was}, now {now[key]})' for key, was in self.saved.items()
                   if now[key] != was and not any(f.startswith(key) for f in failed)]
        return failed

    def airplane(self, on):
        self.shell('cmd', 'connectivity', 'airplane-mode', 'enable' if on else 'disable')

    def fresh(self, flags=(), mic=True):
        """A cleared app (on a phone: the owner's, as it is), the microphone
        granted (or revoked), on Wi-Fi."""
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.shell('pm', 'grant' if mic else 'revoke', PACKAGE, MIC)
        if self.phone:
            if flags:
                raise NotRun('needs command-line flags, which need root: emulator only')
            self.airplane(self.saved['airplane'])
            self.shell('am', 'force-stop', PACKAGE)
            self.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main')
            time.sleep(6)
            return
        self.run('root')
        self.run('wait-for-device')
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.airplane(False)
        self.shell('svc', 'wifi', 'enable')
        self.shell('pm', 'clear', PACKAGE)
        self.shell('pm', 'grant' if mic else 'revoke', PACKAGE, MIC)
        # Flags only when a case needs them: their warning is a snackbar too,
        # and it would queue ahead of the one under test.
        if flags:
            line = ' '.join(['_'] + list(flags))
            self.shell(f"echo '{line}' > /data/local/tmp/chrome-command-line")
        else:
            self.shell('rm', '-f', '/data/local/tmp/chrome-command-line')
        self.start()

    def teardown(self):
        """Returns what could not be put back (a phone's state)."""
        failed = []
        if self.phone:
            try:
                failed = self.restore()
            except Exception as e:  # noqa: BLE001
                failed = [f'restore: {type(e).__name__}: {e}']
        else:
            self.airplane(False)
            self.shell('rm', '-f', '/data/local/tmp/chrome-command-line')
        self.run('reverse', '--remove', f'tcp:{PORT}')
        return failed

    def open(self, url):
        # The same application id: Chrome loads it in the app's own tab.
        self.shell('am', 'start', '-a', 'android.intent.action.VIEW', '-d', f"'{url}'",
                   '--es', 'com.android.browser.application_id', PACKAGE, '-n',
                   f'{PACKAGE}/com.google.android.apps.chrome.Main')

    def out(self, xml=None):
        """The page's #out line, as the screen shows it."""
        xml = xml if xml is not None else self.screen()
        m = re.search(r'text="((?:idle|listening|result:|error:)[^"]*)"', xml)
        return m.group(1) if m else ''

    def listen(self, lang):
        """Opens the page for `lang` and presses Listen, allowing the site's
        microphone prompt; returns once the page is listening (or failed)."""
        self.open(f'{PAGE}?lang={lang}')
        for _ in range(10):
            if 'Listen' in self.screen():
                break
            time.sleep(1)
        if not xlit.tap_text(self, 'Listen'):
            raise RuntimeError('no Listen button')
        quiet = 0
        for _ in range(10):
            xml = self.screen()
            state = self.out(xml)
            if state.startswith(('result:', 'error:')):
                return
            # Listening with no prompt up, twice in a row: the prompt, if
            # any, has come and gone.
            quiet = quiet + 1 if state.startswith('listening') and 'Allow' not in xml else 0
            if quiet == 2:
                return
            # Chrome asks the site for the microphone once per profile (on a
            # phone, only ever for this time: the owner's profile keeps nothing).
            labels = ('Allow this time',) if self.phone else (
                'Allow this time', 'Allow while visiting the site', 'Allow')
            for label in labels:
                if self.tap_in(xml, label):
                    break
            else:
                time.sleep(0.5)

    def tap_in(self, xml, label):
        """Taps `label` if this screen shows it (no new dump: quick)."""
        m = re.search(r'text="' + re.escape(label) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if not m:
            return False
        x1, y1, x2, y2 = map(int, m.groups())
        self.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(1)
        return True

    def wait_out(self, prefix, timeout):
        end = time.time() + timeout
        last = ''
        while time.time() < end:
            last = self.out()
            if last.startswith(prefix) or last.startswith('error:'):
                return last
            time.sleep(1)
        return last

    def mark(self):
        """The device's clock now, for logcat -T: what is logged from here on
        (the log is never cleared: a phone's belongs to its owner)."""
        return self.shell('date', "'+%m-%d %H:%M:%S.000'").strip()

    def log_since(self, mark, *args):
        return self.run('logcat', '-d', '-T', mark, *args)

    def fatal(self, mark):
        """Tark's crashes since `mark` (the crash buffer: Java and native)."""
        log = self.log_since(mark, '-b', 'crash')
        return [l for l in log.splitlines() if PACKAGE in l]


# --- the emulator's microphone -----------------------------------------------

@functools.cache
def emulator_grpc():
    """(stub, metadata, pb2) for emulator-5554's gRPC endpoint."""
    import grpc  # noqa: PLC0415
    from grpc_tools import protoc  # noqa: PLC0415
    sdk = pathlib.Path(os.environ.get('ANDROID_HOME', pathlib.Path.home() / 'Library/Android/sdk'))
    gen = tempfile.mkdtemp(prefix='tark-speech-grpc-')
    wellknown = pathlib.Path(protoc.__file__).parent / '_proto'
    if protoc.main(['protoc', f'-I{sdk}/emulator/lib', f'-I{wellknown}', f'--python_out={gen}',
                    f'--grpc_python_out={gen}', 'emulator_controller.proto']):
        raise RuntimeError('could not generate the emulator gRPC stubs')
    sys.path.insert(0, gen)
    import emulator_controller_pb2 as pb2  # noqa: PLC0415
    import emulator_controller_pb2_grpc as pb2_grpc  # noqa: PLC0415
    info = None
    for path in glob.glob('/private/var/folders/*/*/T/avd/running/pid_*.ini') + glob.glob(
            str(pathlib.Path.home() / 'Library/Caches/TemporaryItems/avd/running/pid_*.ini')):
        entries = dict(l.split('=', 1) for l in pathlib.Path(path).read_text().splitlines() if '=' in l)
        if entries.get('port.serial') == ARGS['serial'].split('-')[1] and 'grpc.token' in entries:
            info = entries
    if info is None:
        raise RuntimeError('no gRPC token for the emulator: start it with -grpc 8554 -grpc-use-token')
    channel = grpc.insecure_channel(f"localhost:{info['grpc.port']}")
    return pb2_grpc.EmulatorControllerStub(channel), [('authorization', f"Bearer {info['grpc.token']}")], pb2


@functools.cache
def phrase_pcm():
    """PHRASE spoken by macOS `say`, as 16 kHz mono s16le."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='tark-speech-'))
    subprocess.run(['say', '-v', 'Samantha', '-o', str(tmp / 'p.aiff'), PHRASE], check=True)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', str(tmp / 'p.aiff'), '-ac', '1',
                    '-ar', str(RATE), '-f', 's16le', str(tmp / 'p.raw')], check=True)
    return (tmp / 'p.raw').read_bytes()


def speak(lead=1.0, tail=3.0):
    """Streams silence, the phrase, then silence into the virtual microphone
    in real time."""
    stub, md, pb2 = emulator_grpc()
    fmt = pb2.AudioFormat(samplingRate=RATE, channels=pb2.AudioFormat.Mono,
                          format=pb2.AudioFormat.AUD_FMT_S16,
                          mode=pb2.AudioFormat.MODE_REAL_TIME)
    pcm = bytes(int(RATE * 2 * lead)) + phrase_pcm() + bytes(int(RATE * 2 * tail))
    chunk = RATE * 2 // 50  # 20 ms

    def packets():
        start = time.time()
        for i in range(0, len(pcm), chunk):
            delay = start + i / (RATE * 2) - time.time()
            if delay > 0:
                time.sleep(delay)
            yield pb2.AudioPacket(format=fmt, timestamp=int(time.time() * 1e6),
                                  audio=pcm[i:i + chunk])
    stub.injectAudio(packets(), metadata=md)


class NotRun(Exception):
    """A case that could not be run here; never a pass."""


def say_aloud(stop):
    """Plays the phrase through the Mac's speakers, again and again until
    `stop`: the emulator hears it through the Mac's microphone (host audio),
    whenever its session starts listening."""
    # `say -a`: a named output (--speaker-device), not whatever the Mac's
    # default is (headphones would play it to nobody).
    device = ['-a', ARGS['speaker_device']] if ARGS.get('speaker_device') else []
    while not stop.is_set():
        subprocess.run(['say', '-v', 'Samantha', *device, PHRASE])
        stop.wait(1.5)


def answer(dev):
    """Listens for en-US while the phrase plays; returns '' or why not."""
    if ARGS['feed'] == 'speaker':
        stop = threading.Event()
        player = threading.Thread(target=say_aloud, args=(stop,))
        # Playing from before the tap: the session hears the phrase however
        # long the site's microphone prompt takes.
        player.start()
        try:
            dev.listen('en-US')
            got = dev.wait_out('result:', 25)
        finally:
            stop.set()
            player.join()
    elif ARGS['feed'] == 'inject':
        dev.listen('en-US')
        speaker = threading.Thread(target=speak)
        speaker.start()
        got = dev.wait_out('result:', 25)
        speaker.join()
    else:
        dev.listen('en-US')
        # No speech can be fed: what silence gives still shows whether the
        # on-device recognizer took the session (no-speech) or refused it.
        RESULTS['silence'] = dev.wait_out('error:', 25)
        raise NotRun('no speech fed (run with --speaker or --inject)')
    RESULTS['transcript'] = got
    if not got.startswith('result:'):
        return f'#out is "{got}"'
    # Through a speaker and a microphone the words can come back a little
    # different: the first word is the check.
    if 'hello' not in got.lower():
        return f'the transcript is not the phrase: "{got}"'
    return ''


# --- cases ---------------------------------------------------------------------

def case_answers(dev):
    dev.fresh()
    return answer(dev)


def case_offline(dev):
    if dev.phone and (':' in ARGS['serial'] or ARGS['serial'].startswith('adb-')):
        raise NotRun('needs USB: airplane mode would cut a wireless adb connection')
    dev.fresh()
    dev.airplane(True)
    time.sleep(3)
    try:
        if not dev.airplane_on():
            raise NotRun('airplane mode did not turn on')
        return answer(dev)
    finally:
        dev.airplane(dev.saved.get('airplane', False))


def case_missing_pack(dev):
    dev.fresh()
    dev.open(f'{PAGE}?lang=ta-IN')
    time.sleep(4)
    if not xlit.tap_text(dev, 'Listen'):
        return 'no Listen button'
    # The snackbar shows for about three seconds right after the error:
    # watch from the tap, answering the site's microphone prompt on the way.
    got, snack = '', None
    end = time.time() + 20
    while time.time() < end and snack is None:
        xml = dev.screen()
        got = dev.out(xml) or got
        if 'Voice search needs' in xml:
            snack = xml
        else:
            dev.tap_in(xml, 'Allow this time')
    if got != 'error: language-not-supported':
        return f'#out is "{got}"'
    if snack is None:
        return 'no snackbar naming the missing language'
    m = re.search(r'text="(Voice search needs[^"]*)"', snack)
    RESULTS['snackbar'] = m.group(1) if m else ''
    # Download is offered only when the recognizer lists the language as
    # one it can get (SpeechLanguageSnackbar.isLanguageKnown).
    RESULTS['download offered'] = bool(re.search(r'text="Download"', snack, re.I))
    # Nothing downloads unless Download is pressed: no other app (Android's
    # download or settings screen) came up on its own.
    time.sleep(3)
    top = dev.shell('dumpsys', 'activity', 'activities')
    if 'topResumedActivity' in top and PACKAGE not in next(
            l for l in top.splitlines() if 'topResumedActivity' in l):
        return 'another app came up without Download being pressed'
    return ''


def case_no_network_host(dev):
    dev.fresh([f'--log-net-log={NETLOG}'])
    try:
        why = answer(dev)
    except NotRun:
        why = ''  # a session in silence still runs the recognizer
    dev.shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(5)
    out = pull_netlog(dev)
    check = subprocess.run(['bash', str(ROOT / 'android/check_netlog.sh'), str(out)],
                           capture_output=True, text=True)
    RESULTS['netlog'] = (str(out), check.stdout.strip())
    line = next((l for l in check.stdout.splitlines() if l.startswith('not allowed: ')), None)
    if line is None:
        return f'check_netlog.sh printed no verdict: {check.stderr.strip()}'
    # The test page's own host is the one website this run visits.
    strangers = [h for h in line[len('not allowed: '):].split(', ') if h not in ('none', '127.0.0.1')]
    if strangers:
        return f'hosts outside allowed_hosts.txt: {", ".join(strangers)}'
    return f'(net log fine, but) {why}' if why else ''


def pull_netlog(dev):
    """Stops Tark and copies its net log here; returns the local path."""
    dev.shell('am', 'force-stop', PACKAGE)
    time.sleep(2)
    out = pathlib.Path(tempfile.mkdtemp(prefix='tark-speech-netlog-')) / 'netlog.json'
    out.write_text(dev.shell('cat', NETLOG))
    # A stopped browser leaves the events array open (android/emulator/session.sh).
    text = out.read_text().rstrip()
    try:
        json.loads(text)
    except json.JSONDecodeError:
        text = text.rstrip(',').rstrip()
        text = text if text.endswith(']}') else text.rstrip(',') + ']}'
        out.write_text(text)
    return out


def case_navigate_away(dev):
    dev.fresh()
    # A first session answers the site's microphone prompt for the visit,
    # so the second one reaches the recognizer at once.
    dev.open(f'{PAGE}?lang=en-US')
    time.sleep(4)
    if not xlit.tap_text(dev, 'Listen'):
        return 'no Listen button'
    if not xlit.tap_text(dev, 'Allow this time' if dev.phone else 'Allow while visiting the site'):
        return 'no microphone prompt'
    first = dev.wait_out('error:', 25)
    if not first.startswith(('error:', 'result:')):
        return f'the first session did not end: "{first}"'
    mark = dev.mark()
    m = re.search(r'text="Listen"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', dev.screen())
    if not m:
        return 'no Listen button the second time'
    x1, y1, x2, y2 = map(int, m.groups())
    started = time.time()
    dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(0.3)
    dev.open('http://127.0.0.1:%d/page.html?lang=en-GB&away=1' % PORT)
    RESULTS['navigated after'] = f'{time.time() - started:.1f} s'
    time.sleep(8)
    # The second session must have started, or nothing was navigated away
    # from: the recognizer logs it (no screen read: it would take longer
    # than the second this case allows).
    log = dev.log_since(mark)
    started_lines = [l for l in log.splitlines()
                     if 'startListening' in l.replace('#', '') or 'onMicrophoneOpened' in l]
    if not started_lines:
        return 'no sign the second session started (no recognizer startListening logged)'
    RESULTS['second session'] = started_lines[0].strip()[-120:]
    fatal = dev.fatal(mark)
    if fatal:
        return f'crashed: {fatal[0]}'
    if not dev.shell('pidof', PACKAGE).strip():
        return 'Tark is not running'
    return ''


def case_permission_denied(dev):
    dev.fresh(mic=False)
    dev.open(f'{PAGE}?lang=en-US')
    time.sleep(4)
    if not xlit.tap_text(dev, 'Listen'):
        return 'no Listen button'
    # The site gets the microphone; Android's own permission, revoked, is
    # what says no (asked again, the answer is still no).
    got = ''
    for _ in range(15):
        xml = dev.screen()
        got = dev.out(xml)
        if got.startswith('error:') or got.startswith('result:'):
            break
        if 'needs permission to access your microphone' in xml:
            # Chrome's own ask to go back to Android's prompt: declined.
            dev.shell('input', 'keyevent', 'KEYCODE_BACK')
            RESULTS.setdefault('tapped', []).append('Back')
            time.sleep(1)
            continue
        for label in ('Allow this time', 'Don’t allow', "Don't allow"):
            if dev.tap_in(xml, label):
                RESULTS.setdefault('tapped', []).append(label)
                break
        else:
            time.sleep(1)
    if got != 'error: not-allowed':
        return f'#out is "{got}"'
    if dev.shell('dumpsys', 'package', PACKAGE).count('RECORD_AUDIO: granted=true'):
        return 'the microphone ended up granted'
    return ''


# --- voice languages (the setting, site languages, the offer, detection) -------

SITE = f'http://127.0.0.1:{PORT}'
DATA = f'/data/user/0/{PACKAGE}'
SITES_PREFS = f'{DATA}/shared_prefs/tark.voice.sites.xml'
APP_PREFS = f'{DATA}/shared_prefs/{PACKAGE}_preferences.xml'
PROFILE_PREFS = f'{DATA}/app_chrome/Default/Preferences'
LID_DIR = f'{DATA}/app_chrome/captions/language_id'
# files.json's language_id unit (android/captions).
LID_FILES = {'lid.onnx': 86063323, 'lid_labels.txt': 325, 'silero_vad.onnx': 2327524}
INTRO = 'Voice search works on this phone, without sending what you say anywhere.'
OFFER_BODY = 'Tark can do voice search on this phone in the languages you use.'
DETECT = 'Notice the language I speak'


def tap_desc(dev, desc, xml=None, contains=False):
    xml = xml if xml is not None else dev.screen()
    pattern = (r'content-desc="[^"]*' + re.escape(desc) + r'[^"]*"' if contains
               else r'content-desc="' + re.escape(desc) + r'"')
    m = re.search(pattern + r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not m:
        return False
    x1, y1, x2, y2 = map(int, m.groups())
    dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(1.5)
    return True


def swipe_up(dev):
    dev.shell('input', 'swipe', '540', '1800', '540', '700', '300')
    time.sleep(1)


def find_scrolling(dev, text, swipes=10):
    """Scrolls down until `text` shows; returns the screen, or '' (and the
    texts seen on the way in RESULTS['seen'])."""
    seen = set()
    for _ in range(swipes):
        xml = dev.screen()
        seen.update(re.findall(r'text="([^"]+)"', xml))
        if f'text="{text}"' in xml:
            return xml
        swipe_up(dev)
    RESULTS['seen'] = sorted(seen)
    return ''


def open_voice_languages(dev):
    """Menu > Settings > Languages > Voice languages (Settings isn't exported)."""
    dev.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main')
    time.sleep(2)
    if not tap_desc(dev, 'Customize and control Tark'):
        raise RuntimeError('no app menu')
    if not xlit.tap_text(dev, 'Settings'):
        raise RuntimeError('no Settings in the menu')
    if not find_scrolling(dev, 'Languages') or not xlit.tap_text(dev, 'Languages'):
        raise RuntimeError('no Languages in Settings')
    if not find_scrolling(dev, 'Voice languages') or not xlit.tap_text(dev, 'Voice languages'):
        raise RuntimeError('no Voice languages in Settings > Languages')
    time.sleep(2)


def app_uid(dev):
    return dev.shell('stat', '-c', '%u', DATA).strip()


def push_file(dev, path, text):
    """Writes an app file as the app (root; the app must be stopped)."""
    local = pathlib.Path(tempfile.mkdtemp(prefix='tark-speech-seed-')) / 'f'
    local.write_text(text)
    dev.run('push', str(local), path)
    uid = app_uid(dev)
    dev.shell('chown', f'{uid}:{uid}', path)
    dev.shell('chmod', '660', path)


def seed_site(dev, tag):
    """Remembers `tag` for the e2e page's origin, as "Use … next time" would
    (VoiceSiteLanguages' preferences file), with Tark stopped. Test-only: root
    on the emulator, no product hook."""
    dev.shell('am', 'force-stop', PACKAGE)
    push_file(dev, SITES_PREFS, "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
              f'<map>\n    <string name="{SITE}">{tag}</string>\n</map>\n')
    dev.start()


def sites_file(dev):
    return dev.shell('cat', SITES_PREFS)


def silent_session(dev, lang):
    """A session in silence on the e2e page; returns #out at its end."""
    dev.listen(lang)
    return dev.wait_out('error:', 25)


def low_end(dev):
    """SysUtils.isLowEndDevice: ro.config.low_ram, or 1 GB of memory or less."""
    if dev.shell('getprop', 'ro.config.low_ram').strip() == 'true':
        return True
    kb = int(re.search(r'MemTotal:\s+(\d+)', dev.shell('cat', '/proc/meminfo')).group(1))
    return kb <= 1024 * 1024


def case_settings_sections(dev):
    dev.fresh()
    open_voice_languages(dev)
    seen = set()
    for _ in range(14):
        xml = dev.screen()
        seen.update(re.findall(r'text="([^"]+)"', xml))
        if f'text="{DETECT}"' in xml:
            break
        swipe_up(dev)
    slow = low_end(dev)
    RESULTS['low-end device'] = slow
    missing = [t for t in ('On this phone', 'More languages', 'Spoken-language detection', DETECT)
               if t not in seen]
    if not any(t.startswith(INTRO) for t in seen):
        missing.insert(0, 'the intro')
    if slow:
        # Detection is hidden on low-end phones (VoiceDetection.Models).
        if 'Spoken-language detection' in seen:
            return 'detection shown on a low-end device'
        missing = [t for t in missing if t not in ('Spoken-language detection', DETECT)]
    RESULTS['headings'] = [t for t in ('On this phone', 'Suggested for you', 'Sites', 'More languages',
                                       'Spoken-language detection') if t in seen]
    return f'missing: {", ".join(missing)}' if missing else ''


def case_site_language(dev):
    # ta-IN isn't on the emulator: alone it ends language-not-supported
    # (missing_pack). With en-IN remembered for the origin the session runs
    # in en-IN and silence ends it no-speech, with no missing-language snackbar.
    dev.fresh()
    seed_site(dev, 'en-IN')
    got = silent_session(dev, 'ta-IN')
    RESULTS['#out (page asks ta-IN, site has en-IN)'] = got
    if got != 'error: no-speech':
        return f'the remembered language was not used: #out is "{got}"'
    if 'Voice search needs' in dev.screen():
        return 'a missing-language snackbar showed'
    open_voice_languages(dev)
    host = '127.0.0.1:8005'
    xml = find_scrolling(dev, 'Sites')
    if not xml:
        return 'no Sites section'
    row = re.search(r'text="([^"]*' + re.escape(host) + r'[^"]*)"', xml)
    if not row:
        swipe_up(dev)
        xml = dev.screen()
        row = re.search(r'text="([^"]*' + re.escape(host) + r'[^"]*)"', xml)
    if not row:
        return 'Sites does not list the origin'
    RESULTS['sites row'] = row.group(1)
    summary = re.search(re.escape(row.group(0)) + r'.{0,600}?text="([^"]+)"', xml, re.S)
    RESULTS['sites row summary'] = summary.group(1) if summary else ''
    if not tap_desc(dev, f'Remove {row.group(1)}', xml):
        return 'no Remove button for the origin'
    time.sleep(1)
    after = dev.screen()
    if host in after:
        return 'the origin is still listed after Remove'
    left = sites_file(dev)
    RESULTS['tark.voice.sites after Remove'] = ' '.join(left.split())
    if SITE in left:
        return 'the origin is still stored after Remove'
    return ''


def case_private_tab(dev):
    # A private session neither reads nor writes a site language: with en-IN
    # remembered for the origin, a ta-IN page in a private tab still ends
    # language-not-supported, and the stored entry is unchanged.
    dev.fresh()
    seed_site(dev, 'en-IN')
    before = sites_file(dev)
    if not tap_desc(dev, 'Customize and control Tark') or not xlit.tap_text(dev, 'New private tab'):
        return 'could not open a private tab'
    time.sleep(2)
    xlit.type_in_address_bar(dev, f'{PAGE}?lang=ta-IN')
    dev.shell('input', 'keyevent', 'KEYCODE_ENTER')
    time.sleep(4)
    if not xlit.tap_text(dev, 'Listen'):
        return 'no Listen button in the private tab'
    got = ''
    end = time.time() + 25
    while time.time() < end:
        xml = dev.screen()
        got = dev.out(xml) or got
        if got.startswith(('error:', 'result:')):
            break
        for label in ('Allow this time', 'Allow while visiting the site', 'Allow'):
            if dev.tap_in(xml, label):
                break
    RESULTS['#out (private tab, page ta-IN, site has en-IN)'] = got
    if got != 'error: language-not-supported':
        return f'the private session did not run in the page language: #out is "{got}"'
    time.sleep(3)
    if sites_file(dev) != before:
        return 'the private session changed the stored site languages'
    return ''


def case_offer_once(dev):
    dev.fresh()
    # A suggestion needs a signal: Hindi among Tark's preferred languages
    # (the profile's intl.accept_languages, as Settings > Languages > Add
    # language sets it), written with Tark stopped.
    dev.shell('am', 'force-stop', PACKAGE)
    prefs = json.loads(dev.shell('cat', PROFILE_PREFS) or '{}')
    # Android keeps selected_languages as the source and derives
    # accept_languages from it: both are set.
    prefs.setdefault('intl', {}).update(accept_languages='en-US,en,hi',
                                        selected_languages='en-US,en,hi')
    push_file(dev, PROFILE_PREFS, json.dumps(prefs))
    dev.start()
    open_voice_languages(dev)
    if not find_scrolling(dev, 'Suggested for you', swipes=3):
        raise NotRun('no suggestion on this emulator (Voice languages shows no "Suggested for you")')
    first = silent_session(dev, 'en-US')
    RESULTS['first session'] = first
    shown = None
    end = time.time() + 20
    while time.time() < end and shown is None:
        xml = dev.screen()
        if OFFER_BODY in xml:
            shown = xml
    if shown is None:
        return 'no offer after the first session'
    RESULTS['offer'] = re.findall(r'text="([^"]+)"', shown)
    if not dev.tap_in(shown, 'No thanks'):
        return 'no "No thanks" on the offer'
    time.sleep(2)
    stored = re.search(r'name="tark.voice.offer">([^<]*)<', dev.shell('cat', APP_PREFS))
    RESULTS['tark.voice.offer'] = stored.group(1) if stored else None
    if not stored or stored.group(1) != 'done':
        return 'No thanks did not store the offer as done'
    # Again in this run, then after a restart: never again.
    for when in ('same run', 'after a restart'):
        if when == 'after a restart':
            dev.shell('am', 'force-stop', PACKAGE)
            dev.start()
        RESULTS[f'session ({when})'] = silent_session(dev, 'en-US')
        end = time.time() + 15
        while time.time() < end:
            if OFFER_BODY in dev.screen():
                return f'the offer came back ({when})'
            time.sleep(1)
    return ''


def lid_files(dev):
    """{name: size} under captions/language_id (run as root)."""
    out = dev.shell('ls', '-l', LID_DIR)
    return {m.group(2): int(m.group(1)) for m in re.finditer(r'\s(\d+) \S+ \S+ (\S+)$', out, re.M)}


def detection_row(xml):
    """The detection row's summary and button, as the screen shows them."""
    i = xml.find(f'text="{DETECT}"')
    texts = re.findall(r'text="([^"]+)"', xml[i:]) if i >= 0 else []
    return texts[1:3]


def busy_screen(dev, tries=3):
    """The screen, giving up quickly: while the detection row refreshes
    itself uiautomator can wait ~40 s for an idle moment that never comes."""
    for _ in range(tries):
        dev.shell('rm', '-f', '/sdcard/ui.xml')
        try:
            subprocess.run(dev.adb + ['shell', 'uiautomator', 'dump', '/sdcard/ui.xml'],
                           capture_output=True, timeout=8)
        except subprocess.TimeoutExpired:
            continue
        xml = dev.shell('cat', '/sdcard/ui.xml')
        if '<hierarchy' in xml:
            return xml
    return ''


def screenshot(dev, name):
    path = pathlib.Path(tempfile.mkdtemp(prefix='tark-speech-shot-')) / f'{name}.png'
    path.write_bytes(subprocess.run(dev.adb + ['exec-out', 'screencap', '-p'],
                                    capture_output=True).stdout)
    return str(path)


def lid_ready(dev):
    files = lid_files(dev)
    return all(files.get(n) == size for n, size in LID_FILES.items())


def detection_get(dev, wifi_first):
    dev.fresh()
    open_voice_languages(dev)
    xml = find_scrolling(dev, DETECT, swipes=14)
    if not xml:
        return 'no detection row'
    RESULTS['off'] = detection_row(xml)
    if 'Get' not in detection_row(xml):
        return f'the row is not off: {detection_row(xml)}'
    mark = dev.mark()
    unreadable = []
    if wifi_first:
        # On Wi-Fi the unit is fetched at once: "Waiting for Wi-Fi" is not
        # expected; whatever the row shows right after the tap is recorded.
        if not xlit.tap_text(dev, 'Get'):
            return 'no Get button'
        RESULTS['right after Get'] = detection_row(busy_screen(dev, 1))
        return detection_download(dev, mark, unreadable)
    # Off Wi-Fi first (mobile data stays on): the row waits and nothing is
    # fetched; then Wi-Fi.
    dev.shell('svc', 'wifi', 'disable')
    time.sleep(5)
    try:
        if not xlit.tap_text(dev, 'Get'):
            return 'no Get button'
        states = []
        end = time.time() + 40
        while time.time() < end and 'Waiting for Wi-Fi' not in states:
            states = detection_row(busy_screen(dev, 1)) or states
        RESULTS['after Get, off Wi-Fi'] = states
        RESULTS['screenshot, off Wi-Fi'] = screenshot(dev, 'waiting')
        if not states:
            # The page never went idle: what the screen says is in the
            # screenshot only, and the case can't pass on that.
            unreadable.append('off Wi-Fi')
        elif 'Waiting for Wi-Fi' not in states:
            return f'no "Waiting for Wi-Fi" off Wi-Fi: {states}'
        time.sleep(20)
        if lid_files(dev):
            return f'files fetched while waiting: {lid_files(dev)}'
    finally:
        dev.shell('svc', 'wifi', 'enable')
    return detection_download(dev, mark, unreadable)


def case_detection_row(dev):
    """Get on Wi-Fi: downloading, then ready, the three files, then Remove."""
    return detection_get(dev, wifi_first=True)


def case_detection_wifi_wait(dev):
    """Get off Wi-Fi: Waiting for Wi-Fi and nothing fetched; then Wi-Fi."""
    return detection_get(dev, wifi_first=False)


def detection_download(dev, mark, unreadable, limit=180):
    """From now (Wi-Fi on) until the unit is ready, within `limit` s; the
    row must be readable throughout (the page goes idle between updates)."""
    seen, started, failed_dumps = [], time.time(), 0
    end = started + limit
    ready_at = None
    while time.time() < end:
        xml = busy_screen(dev, 1)
        row = detection_row(xml)
        failed_dumps += not xml
        files = lid_files(dev)
        if row and row not in seen:
            seen.append(row)
        if any(n.endswith('.part') for n in files) and 'partial file' not in seen:
            seen.append('partial file')
        if files and all(files.get(n) == size for n, size in LID_FILES.items()) and \
                (not row or 'Remove' in row):
            ready_at = time.time()
            break
        time.sleep(1)
    RESULTS['seconds to ready'] = round(ready_at - started, 1) if ready_at else f'not ready in {limit}'
    RESULTS['failed uiautomator dumps'] = failed_dumps
    if failed_dumps:
        unreadable.append(f'downloading ({failed_dumps} dumps)')
    log = dev.log_since(mark, '-s', 'chromium:*')
    lines = [l.split('] ', 1)[-1] for l in log.splitlines() if 'tark captions' in l]
    RESULTS['download log'] = lines[:16]
    RESULTS['failed attempts (retries)'] = sum(' failed' in l for l in lines)
    RESULTS['seen while downloading'] = seen
    files = lid_files(dev)
    RESULTS['files'] = files
    # A retry on Wi-Fi backs off as "Trying again soon…", never as waiting
    # for Wi-Fi (Wi-Fi is on from here on).
    first = next((i for i, x in enumerate(seen) if 'Downloading' in str(x)), None)
    if first is not None and any('Waiting for Wi-Fi' in str(x) for x in seen[first:]):
        return f'"Waiting for Wi-Fi" on Wi-Fi after downloading began: {seen}'
    if RESULTS['failed attempts (retries)'] and not any('Trying again soon' in str(x) for x in seen):
        RESULTS['note'] = 'a retry happened but no dump caught "Trying again soon…"'
    if not any('Downloading' in str(s) for s in seen) and 'partial file' not in seen:
        return 'never saw it downloading'
    wrong = {n: files.get(n) for n, size in LID_FILES.items() if files.get(n) != size}
    if wrong:
        return f'language_id files missing or the wrong size: {wrong}'
    row = detection_row(busy_screen(dev))
    if not row:
        unreadable.append('ready')
        RESULTS['screenshot, ready'] = screenshot(dev, 'ready')
    elif 'Remove' not in row:
        return f'the row is not on: {row}'
    if not xlit.tap_text(dev, 'Remove'):
        return 'no Remove button'
    time.sleep(3)
    left = lid_files(dev)
    RESULTS['after Remove'] = (detection_row(dev.screen()), left)
    if any(n in left for n in LID_FILES):
        return f'files left after Remove: {left}'
    if unreadable:
        return ('the Voice languages page was not idle '
                f'(uiautomator could not read it: {", ".join(unreadable)}); see the screenshots')
    return ''


def case_detection_resume(dev):
    """Get, then Tark is stopped mid-download: relaunched, it finishes
    without another tap."""
    dev.fresh()
    open_voice_languages(dev)
    if not find_scrolling(dev, DETECT, swipes=14) or not xlit.tap_text(dev, 'Get'):
        return 'no Get button'
    end = time.time() + 60
    while time.time() < end and not any(n.endswith('.part') for n in lid_files(dev)):
        time.sleep(0.3)
    partial = lid_files(dev)
    RESULTS['when stopped'] = partial
    if lid_ready(dev) or not any(n.endswith('.part') for n in partial):
        raise NotRun(f'could not stop it mid-download: {partial}')
    dev.shell('am', 'force-stop', PACKAGE)
    mark = dev.mark()
    dev.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main')
    started = time.time()
    end = started + 180
    while time.time() < end and not lid_ready(dev):
        time.sleep(1)
    RESULTS['seconds to ready after relaunch'] = round(time.time() - started, 1)
    log = dev.log_since(mark, '-s', 'chromium:*')
    RESULTS['log after relaunch'] = [l.split('] ', 1)[-1] for l in log.splitlines()
                                     if 'tark captions' in l][:12]
    files = lid_files(dev)
    RESULTS['files'] = files
    if not lid_ready(dev):
        return f'not finished 180 s after the relaunch: {files}'
    stale = [n for n in files if n.endswith('.part')]
    if stale:
        return f'partial files left: {stale}'
    open_voice_languages(dev)
    xml = find_scrolling(dev, DETECT, swipes=14)
    RESULTS['row'] = detection_row(xml)
    if 'Remove' not in detection_row(xml):
        return f'the row is not on: {detection_row(xml)}'
    return ''


def device_ms(dev):
    return int(dev.shell('date', '+%s%3N').strip())


def case_detection_netlog(dev):
    """With detection on, a voice session makes no request at all; the only
    new request overall is language_id's download from gettarka.com."""
    sys.path.insert(0, str(ROOT / 'utils'))
    import net_hosts  # noqa: PLC0415
    dev.fresh([f'--log-net-log={NETLOG}'])
    open_voice_languages(dev)
    if not find_scrolling(dev, DETECT, swipes=14) or not xlit.tap_text(dev, 'Get'):
        return 'no Get button'
    # Retries back off up to 5 min (CaptionDownloads); the emulator's QUIC
    # is flaky, so allow two of them.
    end = time.time() + 600
    while time.time() < end and not lid_ready(dev):
        time.sleep(2)
    if not lid_ready(dev):
        return f'language_id did not download: {lid_files(dev)}'
    time.sleep(3)
    start = device_ms(dev)
    dev.listen('en-US')
    # The session runs through Tark's own capture (the pipe) when detection
    # is on: Android then lists Tark itself as recording.
    recording = dev.shell('dumpsys', 'audio')
    dump = pathlib.Path(tempfile.mkdtemp(prefix='tark-speech-audio-')) / 'dumpsys-audio.txt'
    dump.write_text(recording)
    RESULTS['dumpsys audio'] = str(dump)
    # Active recordings come before the events log.
    active = recording.split('RecordActivityMonitor', 1)[-1].split('Events log', 1)[0]
    RESULTS['Tark recording (pipe in use)'] = f'pack:{PACKAGE}' in active
    got = dev.wait_out('error:', 25)
    stop = device_ms(dev) + 1000
    RESULTS['session'] = got
    dev.shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(3)
    out = pull_netlog(dev)
    log = json.loads(out.read_text())
    offset = int(log['constants'].get('timeTickOffset', 0))
    names = {code: name for name, code in log['constants']['logEventTypes'].items()}
    during, urls = [], []
    for event in log.get('events', []):
        name = names.get(event.get('type'))
        params = event.get('params') or {}
        if name == 'URL_REQUEST_START_JOB':
            urls.append(params.get('url', ''))
        field = net_hosts._CONTACT_EVENTS.get(name)
        value = params.get(field) if field else None
        if isinstance(value, str) and net_hosts._host(value):
            if start <= int(event.get('time', 0)) + offset <= stop:
                during.append(value)
    hosts = net_hosts.contacted_hosts(log)
    allowed = net_hosts.load_allowed(ROOT / 'android/allowed_hosts.txt')
    RESULTS['netlog'] = str(out)
    RESULTS['hosts'] = dict(hosts)
    RESULTS['gettarka.com URLs'] = sorted({u for u in urls if 'gettarka.com' in u})
    RESULTS['contacts during the session'] = during
    if RESULTS['Tark recording (pipe in use)'] is False:
        return 'detection was not in use during the session (Tark was not recording)'
    if during:
        return f'requests during the voice session: {during}'
    strangers = net_hosts.strangers(hosts, allowed)
    if strangers:
        return f'hosts outside allowed_hosts.txt: {", ".join(strangers)}'
    if not any('/models/android/' in u for u in RESULTS['gettarka.com URLs']):
        return 'no language_id download from gettarka.com in the net log'
    return ''


ARGS = {}
RESULTS = {}
CASES = {name[5:]: fn for name, fn in globals().items() if name.startswith('case_')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('apk', nargs='?', help='the build to install (not with --phone)')
    parser.add_argument('--serial', default='emulator-5554')
    feed = parser.add_mutually_exclusive_group()
    feed.add_argument('--speaker', dest='feed', action='store_const', const='speaker',
                      help="play the phrase through the Mac's speakers into the emulator's "
                      'host microphone (-allow-host-audio, `adb emu avd hostmicon`)')
    feed.add_argument('--inject', dest='feed', action='store_const', const='inject',
                      help="feed speech through the emulator's gRPC injectAudio "
                      '(emulator 37.1.11 on an arm64 Mac crashes on it)')
    parser.add_argument('--speaker-device', metavar='NAME',
                        help="with --speaker: the Mac's output to play on (`say -a '?'` "
                        "lists them), e.g. 'MacBook Pro Speakers'")
    parser.add_argument('--phone', action='store_true',
                        help='SERIAL is a phone: its Tark (already installed, never '
                        'cleared or reinstalled) is used as it is, and its airplane '
                        'mode and microphone permission are put back afterwards')
    parser.add_argument('cases', nargs='*', default=list(CASES))
    args = parser.parse_args(argv)
    if not args.serial.startswith('emulator-') and not args.phone:
        print(f'{args.serial} is not an emulator: pass --phone to use it as a phone', file=sys.stderr)
        return 2
    if not args.phone and not args.apk:
        parser.error('APK is required (except with --phone)')
    ARGS.update(serial=args.serial, apk=args.apk, feed=args.feed,
                speaker_device=args.speaker_device)
    dev = Device(args.serial, phone=args.phone)
    # The microphone's plumbing first: a case must not find it broken
    # mid-listen.
    if args.feed == 'inject':
        emulator_grpc()
        phrase_pcm()
    installed = None if args.phone else subprocess.run(
        dev.adb + ['install', '-r', args.apk], capture_output=True, text=True)
    if installed and 'Success' not in installed.stdout:
        print(f'install failed: {installed.stdout}{installed.stderr}', file=sys.stderr)
        return 2
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failed = 0
    dev.remember_state()

    def stop(signum, _frame):
        raise SystemExit(128 + signum)  # through `finally`: the state goes back
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        for name in args.cases:
            RESULTS.clear()
            try:
                why = CASES[name](dev)
            except NotRun as e:
                failed += 1
                print(f'NOT RUN {name}: {e}', flush=True)
                for key, value in RESULTS.items():
                    print(f'    {key}: {value}', flush=True)
                continue
            except Exception as e:  # noqa: BLE001 — a case that breaks is a failure
                why = f'{type(e).__name__}: {e}'
            failed += bool(why)
            print(f'FAIL {name}: {why}' if why else f'ok {name}', flush=True)
            for key, value in RESULTS.items():
                print(f'    {key}: {value}', flush=True)
    finally:
        # A second signal must not cut the restore short.
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        try:
            not_restored = dev.teardown()
        except Exception as e:  # noqa: BLE001
            not_restored = [f'teardown: {type(e).__name__}: {e}']
        for what in not_restored:
            print(f'NOT RESTORED: {what}', flush=True)
        server.shutdown()
    return 1 if failed or not_restored else 0


if __name__ == '__main__':
    sys.exit(main())
