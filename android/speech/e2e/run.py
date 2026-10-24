#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Voice input (the Web Speech API on Android's on-device recognizer) on the emulator.

    android/speech/e2e/run.py APK [--serial emulator-5554] [case ...]
        cases: answers offline missing_pack no_network_host navigate_away
               permission_denied

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
