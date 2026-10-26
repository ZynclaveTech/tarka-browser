#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end checks of Tark's ad blocker on the Mac (desktop ad blocker).

    adblock_e2e.py APP [CASES...]
        cases: network websocket cosmetic switch failopen offline

The same pages, expectations and test list as Android's
(android/adblock/e2e/run.py: CASES, extra.txt), served from this Mac on port
8000. Each case launches APP (Tark.app) on a fresh profile with the test list
(--tark-adblock-extra-list), tark.test mapped to 127.0.0.1 and DevTools on a
local port, waits for "tark adblock: ready" in its log, opens the page and
reads the results the page writes to its title. Prints "ok …" / "FAIL …";
exits 1 if any check fails.
"""

import argparse
import html
import importlib.util
import json
import pathlib
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
E2E = REPO / 'android' / 'adblock' / 'e2e'
DEVTOOLS_PORT = 9334

_spec = importlib.util.spec_from_file_location('android_adblock_e2e', E2E / 'run.py')
android = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(android)
PORT = android.PORT

# The WebSocket check is a case of its own (Task 5: blocked with extensions
# on); the network case leaves it out.
NETWORK = {k: v for k, v in android.CASES['network'][1].items() if k != 'ws'}
CASES = {
    'network': ('net.html', NETWORK, '127.0.0.1'),
    'websocket': ('net.html', {'ws': 'failed'}, '127.0.0.1'),
    'cosmetic': android.CASES['cosmetic'],
}


def results_from_title(title):
    """A page's results: its title is 'done:' and JSON once it has finished.
    DevTools' tab list escapes titles as HTML."""
    title = html.unescape(title)
    if not title.startswith('done:'):
        return None
    return json.loads(title[5:])


class Browser:
    def __init__(self, app, extra_flags=(), prefs=None):
        self.profile = pathlib.Path(tempfile.mkdtemp(prefix='tark-adblock-e2e-'))
        if prefs:
            (self.profile / 'Default').mkdir(parents=True)
            (self.profile / 'Default' / 'Preferences').write_text(json.dumps(prefs))
        self.log = self.profile / 'tark.log'
        binary = pathlib.Path(app) / 'Contents' / 'MacOS' / pathlib.Path(app).stem
        self.proc = subprocess.Popen(
            [str(binary), f'--user-data-dir={self.profile}', '--use-mock-keychain', '--no-first-run',
             '--enable-logging=stderr', '--v=0', f'--remote-debugging-port={DEVTOOLS_PORT}',
             f'--tark-adblock-extra-list={E2E / "extra.txt"}',
             *(extra_flags if any(f.startswith('--host-resolver-rules=') for f in extra_flags)
               else ['--host-resolver-rules=MAP tark.test 127.0.0.1', *extra_flags]), 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=self.log.open('w'))

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def wait_ready(self, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if 'tark adblock: ready' in self.log.read_text(errors='replace'):
                return True
            time.sleep(1)
        return False

    def open(self, url):
        req = urllib.request.Request(f'http://127.0.0.1:{DEVTOOLS_PORT}/json/new?{urllib.parse.quote(url, safe="")}',
                                     method='PUT')
        for _ in range(30):
            try:
                with urllib.request.urlopen(req, timeout=5):
                    return
            except OSError:
                time.sleep(1)
        raise RuntimeError('DevTools never answered')

    def wait_results(self, url, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{DEVTOOLS_PORT}/json', timeout=5) as r:
                    for tab in json.load(r):
                        if tab.get('url') == url:
                            results = results_from_title(tab.get('title', ''))
                            if results is not None:
                                return results
            except OSError:
                pass
            time.sleep(1)
        return None


def check(browser, page, expected, host):
    url = f'http://{host}:{PORT}/{page}?{time.time_ns()}'
    browser.open(url)
    results = browser.wait_results(url)
    failed = 0
    for key, want in expected.items():
        got = (results or {}).get(key)
        ok = got == want
        failed += not ok
        print(f'{"ok  " if ok else "FAIL"}  {page} {key}: {got} (want {want})', flush=True)
    return failed


def run_case(app, name):
    if name == 'failopen':
        # Before the engine is ready nothing is blocked and pages still load.
        b = Browser(app, ['--tark-adblock-delay-compile=60'])
        try:
            time.sleep(3)
            return check(b, *android.FAILOPEN)
        finally:
            b.close()
    if name == 'offline':
        # A first start with no network: every other host resolves to
        # nothing, so the engine has only the bundle built into the app.
        rules = ('--host-resolver-rules=MAP * ~NOTFOUND, MAP tark.test 127.0.0.1, '
                 'EXCLUDE 127.0.0.1, EXCLUDE localhost')
        b = Browser(app, [rules])
        try:
            if not b.wait_ready():
                print('FAIL  offline: the engine was never ready', flush=True)
                return 1
            source_ok = 'lists from built-in' in b.log.read_text(errors='replace')
            print(f'{"ok  " if source_ok else "FAIL"}  offline: lists from the built-in bundle', flush=True)
            return (not source_ok) + check(b, 'net.html', {'blocked': 'failed', 'real': 'failed'}, '127.0.0.1')
        finally:
            b.close()
    if name == 'switch':
        # 'Block ads on this site' off for 127.0.0.1 (ADS = allow): its test
        # ad loads; localhost, another site, stays blocked.
        # ContentSettingsType::ADS is stored as "subresource-filter".
        prefs = {'profile': {'content_settings': {'exceptions': {'subresource_filter': {
            f'http://127.0.0.1:{PORT},*': {'setting': 1}}}}}}
        b = Browser(app, prefs=prefs)
        try:
            if not b.wait_ready():
                print('FAIL  switch: the engine was never ready', flush=True)
                return 1
            return (check(b, 'net.html', {'blocked': 'loaded'}, '127.0.0.1') +
                    check(b, 'net.html', {'blocked': 'failed'}, 'localhost'))
        finally:
            b.close()
    page, expected, host = CASES[name]
    b = Browser(app)
    try:
        if not b.wait_ready():
            print(f'FAIL  {name}: the engine was never ready', flush=True)
            return 1
        return check(b, page, expected, host)
    finally:
        b.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('app')
    ap.add_argument('cases', nargs='*',
                    default=['failopen', 'offline', 'network', 'websocket', 'cosmetic', 'switch'])
    args = ap.parse_args(argv)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), android.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        failed = sum(run_case(args.app, c) for c in args.cases)
    finally:
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
