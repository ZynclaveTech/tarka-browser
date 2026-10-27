#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end checks of desktop Sign in with Zynclave on the Mac.

    zynclave_e2e.py APP [CASES...]
        cases: card_signed_out sign_in_page stray_redirect

Launches APP (a dev build, so Zynclave staging) on a fresh profile with
DevTools on a local port, as utils/adblock_e2e.py does, and checks:
  card_signed_out  Settings > Profile shows "Sign in with Zynclave".
  sign_in_page     Its button opens Zynclave's sign-in page in a new tab,
                   with this platform's client, PKCE S256 and the redirect.
  stray_redirect   A page linking (and a server redirecting) to
                   com.gettarka.tarka:/oauth2redirect?code=x&state=y does
                   nothing: the tab stays where it was, no tab opens, and
                   Tark stays signed out.
Prints "ok …" / "FAIL …"; exits 1 if any check fails.
"""

import argparse
import http.server
import json
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request

import adblock_e2e as e2e

STRAY = 'com.gettarka.tarka:/oauth2redirect?code=x&state=y'
PORT = 8011


class StrayHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', STRAY)
            self.end_headers()
            return
        body = (f'<title>stray</title><a id=a href="{STRAY}">x</a>'
                '<script>document.getElementById("a").click()</script>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def tabs():
    with urllib.request.urlopen(f'http://127.0.0.1:{e2e.DEVTOOLS_PORT}/json', timeout=5) as r:
        return [t for t in json.load(r) if t.get('type') == 'page']


def card_text(ws, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        got = e2e.evaluate(ws, f"(() => {{ const e = {e2e.DEEP_FIND}('zynclaveCard');"
                               " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : null; })()")
        if got:
            return got
        time.sleep(1)
    return None


def report(ok, name, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f': {detail}' if detail else ''))
    return 0 if ok else 1


def run_case(app, name):
    browser = e2e.Browser(app)
    try:
        if not browser.wait_ready():
            return report(False, name, 'Tark never started')
        if name == 'card_signed_out':
            browser.open('chrome://settings/people')
            text = card_text(e2e.settings_tab())
            return report(bool(text) and 'Sign in with Zynclave' in text
                          and 'Browsing never needs an account' in text, name, text or 'no card')
        if name == 'sign_in_page':
            browser.open('chrome://settings/people')
            ws = e2e.settings_tab()
            if not card_text(ws):
                return report(False, name, 'no card')
            e2e.evaluate(ws, f"{e2e.DEEP_FIND}('zynclaveCard').querySelector('#signIn').click()")
            end = time.time() + 30
            while time.time() < end:
                auth = [t for t in tabs() if '/oauth2/auth' in t.get('url', '')]
                if auth:
                    url = urllib.parse.urlparse(auth[0]['url'])
                    q = urllib.parse.parse_qs(url.query)
                    ok = (url.hostname == 'auth.staging.zynclave.com'
                          and q.get('client_id') == ['254e0cf8-e515-4ea8-846c-86b5510c5499']
                          and q.get('redirect_uri') == ['com.gettarka.tarka:/oauth2redirect']
                          and q.get('code_challenge_method') == ['S256']
                          and q.get('scope') == ['openid profile email offline_access']
                          and len(q.get('state', [''])[0]) >= 43)
                    return report(ok, name, url.hostname + ' ' + json.dumps({k: v[0] for k, v in q.items()
                                                                             if k != 'code_challenge'}))
                time.sleep(1)
            return report(False, name, 'no sign-in tab opened')
        if name == 'stray_redirect':
            failed = 0
            for path in ('/link', '/redirect'):
                page = f'http://127.0.0.1:{PORT}{path}'
                before = len(tabs())
                browser.open(page)
                time.sleep(5)
                now = tabs()
                stray = [t for t in now if t.get('url', '').startswith('com.gettarka.tarka')]
                failed += report(not stray and len(now) == before + 1, f'{name} {path}',
                                 f'{len(now) - before} new tab(s), stray={len(stray)}')
            browser.open('chrome://settings/people')
            text = card_text(e2e.settings_tab())
            failed += report(bool(text) and 'Sign in with Zynclave' in text, f'{name} still signed out')
            return failed
        return report(False, name, 'unknown case')
    finally:
        browser.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('app')
    ap.add_argument('cases', nargs='*', default=['card_signed_out', 'sign_in_page', 'stray_redirect'])
    args = ap.parse_args(argv)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), StrayHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        failed = sum(run_case(args.app, c) for c in args.cases)
    finally:
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
