#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end checks of Tark's ad blocker on the emulator (A2).

    run.py [--serial emulator-5554] [CASES...]     cases: failopen network cosmetic switch

Serves android/adblock/e2e/site/ from this Mac (adb reverse, port 8000),
gives the browser the test list extra.txt (--tark-adblock-extra-list, which
needs the emulator's root), waits for "tark adblock: ready" in logcat, opens
each page and reads its results, which the page writes to its title as JSON,
from the DevTools socket's tab list. Exits 1 if any check fails. Emulator
only: the test list goes in through root.
"""

import argparse
import base64
import hashlib
import html
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PACKAGE = 'com.gettarka.tarka'
PORT = 8000
DEVTOOLS_PORT = 9223
APP_DIR = f'/data/user/0/{PACKAGE}'
EXTRA = f'{APP_DIR}/cache/tark-extra.txt'
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

# page: {result key: expected value}
CASES = {
    'network': ('net.html', {
        'blocked': 'failed',      # a rule blocks the script
        'exception': 'loaded',    # an @@ exception lets it through
        'redirect': 'stub',       # $redirect=noopjs answers with the stub
        'chain': 'failed',        # a redirect to a blocked URL fails
        'ws': 'failed',           # a blocked WebSocket never opens
        'worker': 'failed',       # a worker's fetch is checked too
        'frame': 'failed',        # an ad subframe is blocked
        'real': 'failed',         # the shipped lists block pubmatic's pwt.js
    }, '127.0.0.1'),
    'cosmetic': ('cosmetic.html', {
        'scriptlet': 'ran',       # set-constant ran before the first script
        'trusted': 'ran',         # a trusted-* scriptlet from a mask-1 list
        'specific': 'hidden',     # tark.test##.tark-test-ad
        'generic': 'hidden',      # ##.tark-generic-ad, added later by script
    }, 'tark.test'),
}
# Before the engine is ready nothing is blocked and pages still load.
FAILOPEN = ('net.html', {'blocked': 'loaded'}, '127.0.0.1')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE / 'site'), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == '/redirect':
            to = urllib.parse.parse_qs(url.query)['to'][0]
            self.send_response(302)
            self.send_header('Location', to)
            self.end_headers()
            return
        if url.path == '/tark-test-ws' and self.headers.get('Upgrade', '').lower() == 'websocket':
            key = self.headers['Sec-WebSocket-Key']
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            time.sleep(1)
            return
        super().do_GET()


class Device:
    def __init__(self, serial):
        self.adb = ['adb', '-s', serial]

    def run(self, *args, check=False):
        return subprocess.run(self.adb + list(args), capture_output=True, text=True, check=check).stdout

    def shell(self, *args):
        return self.run('shell', *args)

    def setup(self, flags):
        self.run('root')
        self.run('wait-for-device')
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.run('forward', f'tcp:{DEVTOOLS_PORT}', 'localabstract:chrome_devtools_remote')
        self.shell('am', 'force-stop', PACKAGE)
        self.run('push', str(HERE / 'extra.txt'), '/data/local/tmp/tark-extra.txt')
        # Created inside the app's folder, the copy takes the folder's
        # SELinux label; then it is handed to the app's user.
        uid = self.shell('stat', '-c', '%u', APP_DIR).strip()
        self.shell(f'cat /data/local/tmp/tark-extra.txt > {EXTRA} && chown {uid}:{uid} {EXTRA} && chmod 600 {EXTRA}')
        # tark.test: the Mac's server under a name that is not local.
        line = ' '.join(['_', f'--tark-adblock-extra-list={EXTRA}',
                         '--host-resolver-rules="MAP tark.test 127.0.0.1"'] + flags)
        self.shell(f"echo '{line}' > /data/local/tmp/chrome-command-line")
        self.run('logcat', '-c')

    def teardown(self):
        self.shell('rm', '-f', '/data/local/tmp/chrome-command-line', EXTRA)
        self.run('reverse', '--remove', f'tcp:{PORT}')
        self.run('forward', '--remove', f'tcp:{DEVTOOLS_PORT}')

    def open(self, url):
        self.shell('am', 'start', '-a', 'android.intent.action.VIEW', '-d', url, PACKAGE)

    def wait_ready(self, timeout=180):
        end = time.time() + timeout
        while time.time() < end:
            if 'tark adblock: ready' in self.run('logcat', '-d', '-s', 'chromium:*'):
                return True
            time.sleep(2)
        return False

    def wait_results(self, url, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{DEVTOOLS_PORT}/json', timeout=5) as r:
                    for tab in json.load(r):
                        if tab.get('url') == url and tab.get('title', '').startswith('done:'):
                            # DevTools' tab list escapes titles as HTML.
                            return json.loads(html.unescape(tab['title'])[5:])
            except OSError:
                pass
            time.sleep(1)
        return None


def tap_text(dev, text, tries=5):
    """Taps the on-screen element whose text is `text` (uiautomator)."""
    import re
    for _ in range(tries):
        dev.shell('uiautomator', 'dump', '/sdcard/ui.xml')
        xml = dev.shell('cat', '/sdcard/ui.xml')
        m = re.search(r'text="' + re.escape(text) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            return True
        time.sleep(1)
    return False


def switch(dev):
    """'Block ads on this site' off for 127.0.0.1: its test ad loads; localhost
    (another site) stays blocked; after a restart 127.0.0.1 is still off.
    Turned back on at the end."""
    # From a clean profile: no site switched off yet.
    dev.shell('pm', 'clear', PACKAGE)
    dev.open('about:blank')          # creates the app's folders again
    time.sleep(10)
    dev.setup([])
    dev.open('about:blank')
    dev.wait_ready()
    time.sleep(3)
    tap_text(dev, 'No thanks', tries=2)    # a fresh profile's notifications prompt
    failed = check(dev, 'net.html', {'blocked': 'failed'})
    dev.shell('input', 'tap', '60', '136')          # the page's status icon
    time.sleep(2)
    ok = tap_text(dev, 'Block ads on this site')
    print(f'{"ok  " if ok else "FAIL"}  switch row in page info')
    failed += not ok
    time.sleep(4)                                     # the page reloads
    failed += check(dev, 'net.html', {'blocked': 'loaded'})
    failed += check(dev, 'net.html', {'blocked': 'failed'}, host='localhost')
    # Leave the app first, as a person would: Chrome writes its settings when
    # it goes to the background (a force-stop alone can beat the write).
    dev.shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(5)
    dev.shell('am', 'force-stop', PACKAGE)
    dev.run('logcat', '-c')
    dev.open('about:blank')
    dev.wait_ready()
    time.sleep(3)
    failed += check(dev, 'net.html', {'blocked': 'loaded'})
    dev.shell('input', 'tap', '60', '136')
    time.sleep(2)
    tap_text(dev, 'Block ads on this site')
    time.sleep(4)
    return failed


def check(dev, page, expected, host='127.0.0.1'):
    url = f'http://{host}:{PORT}/{page}?{time.time_ns()}'
    dev.open(url)
    results = dev.wait_results(url)
    failed = 0
    for key, want in expected.items():
        got = (results or {}).get(key)
        ok = got == want
        failed += not ok
        print(f'{"ok  " if ok else "FAIL"}  {page} {key}: {got} (want {want})')
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--serial', default='emulator-5554')
    ap.add_argument('cases', nargs='*', default=['failopen'] + list(CASES) + ['switch'])
    args = ap.parse_args(argv)
    if not args.serial.startswith('emulator-'):
        print(f'{args.serial} is not an emulator: the test list needs root', file=sys.stderr)
        return 2
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev = Device(args.serial)
    failed = 0
    try:
        if 'failopen' in args.cases:
            dev.setup(['--tark-adblock-delay-compile=60'])
            # No cached engine, so the compile (and its delay) happens.
            dev.shell('rm', '-f', f'{APP_DIR}/app_chrome/TarkAdblock/engine.key')
            dev.open('about:blank')
            time.sleep(8)
            failed += check(dev, *FAILOPEN)
        rest = [c for c in args.cases if c != 'failopen']
        if rest:
            dev.setup([])
            dev.open('about:blank')
            if not dev.wait_ready():
                print('FAIL  the engine never reported ready')
                return 1
            for case in rest:
                failed += switch(dev) if case == 'switch' else check(dev, *CASES[case])
    finally:
        dev.teardown()
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
