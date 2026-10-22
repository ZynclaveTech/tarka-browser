#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end checks of live captions on the emulator (Phase 1, videos).

    run.py MODELS_DIR TESTDATA_DIR [--serial emulator-5554] [CASES...]
        cases: bar listens download wifi caption tamper settings background

MODELS_DIR is android/captions/models.py build's output (the units and
files.json); this Mac serves its files under their sha256 names, as
gettarka.com does, and a page with a looping Hindi clip (TESTDATA_DIR's
hi_1.wav), through adb reverse (port 8003). The browser gets
--tark-captions-models-url and --tark-captions-log-text from Chrome's
command-line file (the emulator's root). Each case starts from a cleared app.
Prints "ok CASE" or "FAIL CASE: why"; exits 1 if any fails. Emulator only.
"""

import argparse
import hashlib
import http.server
import json
import pathlib
import socketserver
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'xlit' / 'e2e'))
import run as xlit  # noqa: E402  (Device, tap_text)

PACKAGE = xlit.PACKAGE
PORT = 8003
PAGE = '''<!doctype html><meta name="viewport" content="width=device-width">
<title>Tark captions test</title>
<video id="v" src="/hi.wav" controls loop playsinline style="width:100%;height:200px"></video>
'''
REQUESTS = []
SERVER = {'tamper': False, 'files': {}, 'page': b'', 'wav': b''}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        REQUESTS.append(self.path)
        path = self.path.lstrip('/')
        if path == 'page.html':
            self.reply(SERVER['page'], 'text/html')
            return
        if path == 'hi.wav':
            self.reply(SERVER['wav'], 'audio/wav')
            return
        data = SERVER['files'].get(path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        if SERVER['tamper'] and len(data) > 100:
            data = data[:100] + bytes([data[100] ^ 1]) + data[101:]
        self.reply(data, 'application/octet-stream')

    def reply(self, data, kind):
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Device(xlit.Device):
    def fresh(self, flags=()):
        self.run('root')
        self.run('wait-for-device')
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.shell('svc', 'wifi', 'enable')
        self.shell('svc', 'data', 'enable')
        self.shell('pm', 'clear', PACKAGE)
        line = ' '.join(['_', f'--tark-captions-models-url=http://127.0.0.1:{PORT}/',
                         '--tark-captions-log-text'] + list(flags))
        self.shell(f"echo '{line}' > /data/local/tmp/chrome-command-line")
        REQUESTS.clear()
        self.start()

    def teardown(self):
        self.shell('rm', '-f', '/data/local/tmp/chrome-command-line')
        self.shell('svc', 'wifi', 'enable')
        self.run('reverse', '--remove', f'tcp:{PORT}')

    def model_files(self, unit):
        out = self.shell('ls', f'/data/user/0/{PACKAGE}/app_tark_captions/{unit}',
                         f'/data/user/0/{PACKAGE}/captions/{unit}')
        return sorted(l.strip() for l in out.splitlines()
                      if l.strip() and 'No such file' not in l and not l.endswith('.sha256'))

    def log(self):
        return self.run('logcat', '-d', '-s', 'chromium:*')


def load(models_dir, testdata_dir):
    table = json.loads((models_dir / 'files.json').read_text())
    for name, entry in table.items():
        data = (models_dir / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256'], name
        SERVER['files'][entry['sha256']] = data
    SERVER['page'] = PAGE.encode()
    SERVER['wav'] = (testdata_dir / 'hi_1.wav').read_bytes()
    golden = json.loads((testdata_dir / 'golden.json').read_text())
    return next(c for c in golden['clips'] if c['wav'] == 'hi_1.wav')


def open_page_and_play(dev):
    dev.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main',
              '-a', 'android.intent.action.VIEW', '-d', f'http://127.0.0.1:{PORT}/page.html')
    time.sleep(5)
    # The video's play button (a tap on the video starts it with the person's gesture).
    xml = dev.screen()
    xlit.tap_text(dev, 'play', tries=3, contains=True) or dev.shell('input', 'tap', '540', '400')
    time.sleep(3)


def bar_shown(dev):
    return 'Captions' in dev.screen()


def captions_on(dev):
    return xlit.tap_text(dev, 'Captions', tries=3)


def case_bar(dev):
    dev.fresh()
    open_page_and_play(dev)
    assert bar_shown(dev), 'no caption bar while a video plays with sound'


def case_listens(dev):
    dev.fresh()
    open_page_and_play(dev)
    time.sleep(10)
    log = dev.log()
    assert 'tark captions: downloading' not in log, 'downloaded before the tap'
    assert 'tark captions: engine' not in log, 'a captions process before the tap'
    assert not any(r.lstrip('/') in SERVER['files'] for r in REQUESTS), 'fetched a model'


def case_download(dev):
    dev.fresh()
    open_page_and_play(dev)
    assert captions_on(dev), 'no Captions chip'
    assert 'ready' in dev.screen().lower() or dev.logged('tark captions: downloading', 20), \
        'no download after the tap'
    assert dev.logged('tark captions: ready hi', 300), 'Hindi never became ready'
    assert len(dev.model_files('hi')) == 7, dev.model_files('hi')


def case_wifi(dev):
    dev.fresh()
    dev.shell('svc', 'wifi', 'disable')
    time.sleep(3)
    open_page_and_play(dev)
    assert captions_on(dev), 'no Captions chip'
    time.sleep(8)
    assert 'Waiting for Wi-Fi' in dev.screen(), 'no "Waiting for Wi-Fi" on mobile data'
    assert 'tark captions: downloading' not in dev.log(), 'downloaded on mobile data'
    assert xlit.tap_text(dev, 'Download now', tries=3), 'no "Download now"'
    assert dev.logged('tark captions: downloading', 20), '"Download now" did not download'


def case_caption(dev, golden):
    dev.fresh()
    open_page_and_play(dev)
    assert captions_on(dev), 'no Captions chip'
    assert dev.logged('tark captions: ready hi', 300), 'Hindi never became ready'
    assert dev.logged('tark captions: engine started hi', 60), 'no captions process'
    assert dev.logged('tark captions: final ', 90), 'no caption'
    finals = [l.split('tark captions: final ', 1)[1] for l in dev.log().splitlines()
              if 'tark captions: final ' in l]
    want = golden['ctc_text'].split()
    got = set(' '.join(finals).split())
    share = sum(w in got for w in want) / len(want)
    assert share >= 0.6, f'{share:.0%} of the clip\'s words in {finals[:3]}'


def case_tamper(dev):
    dev.fresh()
    SERVER['tamper'] = True
    try:
        open_page_and_play(dev)
        assert captions_on(dev), 'no Captions chip'
        assert dev.logged('not accepted', 120), 'a tampered file was not refused'
        assert 'encoder.int8.onnx' not in dev.model_files('hi'), 'a tampered file stayed'
    finally:
        SERVER['tamper'] = False


def case_settings(dev):
    case_download(dev)
    dev.shell('am', 'start', '-n', f'{PACKAGE}/org.chromium.chrome.browser.settings.SettingsActivity',
              '--es', 'show_fragment',
              'org.chromium.chrome.browser.tark_captions.TarkLiveCaptionsSettings')
    time.sleep(4)
    screen = dev.screen()
    assert 'Live captions' in screen and 'Phrase' in screen, 'no Live captions settings'
    assert xlit.tap_text(dev, 'Hindi', tries=3), 'Hindi not listed'
    assert xlit.tap_text(dev, 'Delete', tries=3), 'no Delete'
    time.sleep(3)
    assert dev.model_files('hi') == [], 'Hindi still on the phone'


def case_background(dev):
    case_download(dev)
    dev.logged('tark captions: final ', 60)
    dev.shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(3)
    before = dev.log().count('tark captions: final ')
    time.sleep(20)
    after = dev.log().count('tark captions: final ')
    assert after == before, f'{after - before} captions while Tark was in the background'


CASES = ['bar', 'listens', 'download', 'wifi', 'caption', 'tamper', 'settings', 'background']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('models_dir', type=pathlib.Path)
    parser.add_argument('testdata_dir', type=pathlib.Path)
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('cases', nargs='*', default=CASES)
    args = parser.parse_args(argv)
    if not args.serial.startswith('emulator-'):
        sys.exit('emulator only')
    golden = load(args.models_dir, args.testdata_dir)
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev = Device(args.serial)
    failed = 0
    try:
        for name in args.cases:
            try:
                fn = globals()['case_' + name]
                fn(dev, golden) if name == 'caption' else fn(dev)
                print('ok', name, flush=True)
            except AssertionError as e:
                failed += 1
                print(f'FAIL {name}: {e}', flush=True)
    finally:
        dev.teardown()
        server.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
