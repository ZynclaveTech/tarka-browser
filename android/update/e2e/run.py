#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The direct APK's update check on the emulator (A5).

    android/update/e2e/run.py APK [--serial emulator-5554] [case ...]

Serves an index on this Mac (port 8002, reached through adb reverse) and
points Tark at it with --tark-update-base-url (read from Chrome's
command-line file, which needs the emulator's root). Each case starts from a
cleared app; the check runs 30 s after start. APK is the build under test,
reinstalled for play_installed with Play named as its installer. Prints
"ok CASE" or "FAIL CASE: why"; exits 1 if any fails. Emulator only.
"""
import argparse
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'xlit' / 'e2e'))
import run as xlit  # noqa: E402  (android/xlit/e2e/run.py: Device, tap_text)

PORT = 8002
PACKAGE = xlit.PACKAGE
SERVER = {'index': None}
REQUESTS = []  # (path, headers) the browser sent, in order


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        REQUESTS.append((self.path, dict(self.headers)))
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{PORT}/latest.json')
            self.end_headers()
            return
        if self.path != '/latest.json' or SERVER['index'] is None:
            self.send_error(404)
            return
        body = json.dumps(SERVER['index']).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Device(xlit.Device):
    def fresh(self, path='/latest.json'):
        self.run('root')
        self.run('wait-for-device')
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.shell('pm', 'clear', PACKAGE)
        self.shell(f"echo '_ --tark-update-base-url=http://127.0.0.1:{PORT}{path}' "
                   "> /data/local/tmp/chrome-command-line")
        REQUESTS.clear()
        self.start()

    def teardown(self):
        self.shell('rm', '-f', '/data/local/tmp/chrome-command-line')
        self.run('reverse', '--remove', f'tcp:{PORT}')

    def installed_code(self):
        out = self.shell('dumpsys', 'package', PACKAGE)
        return int(next(l for l in out.splitlines() if 'versionCode=' in l).split('versionCode=')[1].split()[0])

    def menu_offers_update(self):
        """Whether the app menu shows Tark's update item."""
        xlit.tap_text(self, 'More options', tries=2, contains=True) or self.shell(
            'input', 'keyevent', 'KEYCODE_MENU')
        time.sleep(2)
        shown = 'Update Tark' in self.screen()
        self.shell('input', 'keyevent', 'KEYCODE_BACK')
        return shown


def index(code):
    name = f'test-r{code % 100}'
    return {'version_code': code, 'version_name': name,
            'url': f'https://gettarka.com/android/v1/tark-{name}.apk', 'size': 1000,
            'sha256': '00' * 32}


def wait_for_check(dev):
    """The check runs 30 s after start; its outcome is logged."""
    return dev.logged('tark update:', 60)


def case_newer(dev):
    SERVER['index'] = index(dev.installed_code() + 1)
    dev.fresh()
    if not wait_for_check(dev):
        return 'no check within a minute'
    if not REQUESTS:
        return 'no request reached the server'
    headers = {k.lower() for k in REQUESTS[0][1]}
    if headers & {'cookie', 'authorization'}:
        return f'the request carried {headers & {"cookie", "authorization"}}'
    if '?' in REQUESTS[0][0]:
        return f'a query string: {REQUESTS[0][0]}'
    if not dev.logged('available', 5):
        return 'the newer version was not seen'
    if not dev.menu_offers_update():
        return 'the menu does not offer "Update Tark"'
    return ''


def case_same(dev):
    SERVER['index'] = index(dev.installed_code())
    dev.fresh()
    if not wait_for_check(dev) or not dev.logged('up to date', 5):
        return 'the check did not find it up to date'
    return 'the menu offers an update' if dev.menu_offers_update() else ''


def case_offline(dev):
    SERVER['index'] = None  # 404
    dev.fresh()
    if not wait_for_check(dev) or not dev.logged('no index', 5):
        return 'no failed check logged'
    if not dev.shell('pidof', PACKAGE).strip():
        return 'Tark stopped'
    return 'the menu offers an update' if dev.menu_offers_update() else ''


def case_redirect(dev):
    SERVER['index'] = index(dev.installed_code() + 1)
    dev.fresh('/redirect')
    time.sleep(60)
    if any(path == '/latest.json' for path, _ in REQUESTS):
        return 'the redirect was followed'
    return 'the menu offers an update' if dev.menu_offers_update() else ''


def case_play_installed(dev):
    SERVER['index'] = index(dev.installed_code() + 1)
    subprocess.run(dev.adb + ['install', '-r', '-i', 'com.android.vending', ARGS['apk']],
                   capture_output=True, check=True)
    dev.fresh()
    time.sleep(90)
    try:
        if REQUESTS:
            return f'{len(REQUESTS)} request(s) though Play installed Tark'
        return 'the menu offers an update' if dev.menu_offers_update() else ''
    finally:
        # Back to an ordinary install for the other cases.
        subprocess.run(dev.adb + ['install', '-r', ARGS['apk']], capture_output=True)


ARGS = {}
CASES = {name[5:]: fn for name, fn in globals().items() if name.startswith('case_')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('apk')
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('cases', nargs='*', default=list(CASES))
    args = parser.parse_args(argv)
    if not args.serial.startswith('emulator-'):
        print('emulator only', file=sys.stderr)
        return 2
    ARGS['apk'] = args.apk
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev = Device(args.serial)
    failed = 0
    try:
        for name in args.cases:
            try:
                why = CASES[name](dev)
            except Exception as e:  # noqa: BLE001 — a case that breaks is a failure
                why = f'{type(e).__name__}: {e}'
            failed += bool(why)
            print(f'FAIL {name}: {why}' if why else f'ok {name}', flush=True)
    finally:
        dev.teardown()
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
