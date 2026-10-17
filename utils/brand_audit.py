#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Find "Chrome"/"Chromium" left in Tark's internal pages (spec 6.3).

    python3 utils/brand_audit.py PORT

PORT is the --remote-debugging-port of a running dev build. Every page listed
on chrome://chrome-urls (enable its internal debugging pages first to include
them) is opened in a background tab; its visible text, through open shadow
roots, is searched for the words. Hits on spec 6.3's kept words are allowed
(ALLOWED below). Hits on pages users reach are printed and counted, and the
exit status is 1 if there are any; hits on internal debugging pages (off by
default, describing Chromium itself) are printed as DEBUG PAGE and not
counted.
"""

import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.request
from urllib.parse import urlparse

WORD = re.compile(r'\bChrom(?:e|ium)\b')
# An internal page's address shown as chrome:// where the browser names a page
# (spec 6.3): its tab title and the error page. Prose on internal pages that
# mentions a chrome:// address is not counted; the address works when typed.
ADDRESS = re.compile(r'(TAB TITLE: |The webpage at )chrome://[\w./-]*')
CONTEXT = 40

# (pattern matched against the hit's context, page URL prefix or None for
# every page, reason). Spec 6.3 is the authority for this list.
ALLOWED = [
    (re.compile(r'Chrome Web Store'), None, "Google's store"),
    (re.compile(r'Chrome Root Program'), None, "Google's certificate programme"),
    (re.compile(r'Chrome Remote Desktop'), None, "Google's product"),
    (re.compile(r'Chrome DevTools MCP'), None, "Google's product"),
    (re.compile(r'Chrome/\d'), None, 'user agent token, kept for web compatibility'),
    (re.compile(r'Chromium'), 'chrome://credits', 'licence credits'),
    (re.compile(r'made possible by the Chromium'), 'chrome://settings/help',
     'Chromium credit on About'),
    (re.compile(r'made possible by the Chromium'), 'chrome://version',
     'Chromium credit on chrome://version'),
    (re.compile(r'Your Chrome'), 'chrome://flags',
     "an experiment's label naming Google's Chrome mobile app"),
    (re.compile(r'Chromium PDF Viewer'), None,
     "the built-in PDF viewer's name, which web pages see like the PDF plugin's"),
    # Internal debugging pages (off by default) describing Chromium itself.
    (re.compile(r'Chrome\.\w'), 'chrome://histograms', 'metric names'),
    (re.compile(r'Chromium renderer process'), 'chrome://gpu', 'GPU workaround text'),
    (re.compile(r'Chrome UX specification'), 'chrome://color-pipeline-internals',
     'a Google document'),
]


# Pages not opened: they crash or hang on purpose, end the session, or are
# dialogs that a dev build refuses to run as a tab (NOTREACHED on
# chrome.send("showDialog") for chrome://feedback).
SKIPPED = ('crash', 'kill', 'hang', 'quit', 'restart', 'feedback',
           # Sign-in and profile dialogs, likewise dialog-only.
           'history-sync-optin', 'managed-user-profile-notice',
           'profile-customization', 'sync-confirmation', 'signin-error',
           'signin-email-confirmation', 'signout-confirmation',
           'signin-dice-web-intercept', 'privacy-sandbox-dialog',
           'search-engine-choice', 'reset-password', 'batch-upload',
           'enterprise-profile-welcome',
           # Crashes the dev build on an invalid policy schema (an M4 finding,
           # tracked separately): skipped so the audit can finish.
           'policy',
           # Internal page that CHECKs for a key service macOS dev builds lack.
           'unexportable-keys-internals')


def find_hits(url, text):
    """Each disallowed occurrence of the words in `text` on page `url`, with
    up to CONTEXT characters either side."""
    found = []
    for match in WORD.finditer(text):
        start = max(0, match.start() - CONTEXT)
        context = ' '.join(text[start:match.end() + CONTEXT].split())
        allowed = any(pattern.search(context) and (page is None or url.startswith(page))
                      for pattern, page, _ in ALLOWED)
        if not allowed:
            found.append(context)
    found += [match.group(0) for match in ADDRESS.finditer(text)]
    return found


# A minimal DevTools-protocol client (stdlib only).
class _Socket:

    def __init__(self, ws_url):
        parts = urlparse(ws_url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n'
                           'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                           f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while b'\r\n\r\n' not in response:
            response += self.sock.recv(4096)
        self.next_id = 0

    def _send(self, text):
        payload, mask = text.encode(), os.urandom(4)
        header = bytearray([0x81])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        elif len(payload) < 65536:
            header += bytes([0x80 | 126]) + struct.pack('>H', len(payload))
        else:
            header += bytes([0x80 | 127]) + struct.pack('>Q', len(payload))
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _exact(self, n):
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError('closed')
            data += chunk
        return data

    def _recv(self):
        first, second = self._exact(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack('>H', self._exact(2))[0]
        elif length == 127:
            length = struct.unpack('>Q', self._exact(8))[0]
        return first & 0x0F, self._exact(length)

    def call(self, method, params=None):
        self.next_id += 1
        self._send(json.dumps({'id': self.next_id, 'method': method, 'params': params or {}}))
        while True:
            opcode, data = self._recv()
            if opcode == 1:
                message = json.loads(data)
                if message.get('id') == self.next_id:
                    return message.get('result', {})

    def close(self):
        self.sock.close()


VISIBLE_TEXT = """(() => {
  const out = [];
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const el = node.parentElement;
      if (el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden') {
        out.push(node.textContent);
      }
      return;
    }
    if (node.shadowRoot) walk(node.shadowRoot);
    for (const child of node.childNodes) walk(child);
  };
  walk(document.body || document.documentElement);
  return out.join(' ');
})()"""


def _json(port, path):
    return json.load(urllib.request.urlopen(f'http://localhost:{port}{path}'))


def page_text(port, url, wait=2.5):
    browser = _Socket(_json(port, '/json/version')['webSocketDebuggerUrl'])
    target = browser.call('Target.createTarget', {'url': url, 'background': True})['targetId']
    time.sleep(wait)
    page = next(t for t in _json(port, '/json') if t['id'] == target)
    tab = _Socket(page['webSocketDebuggerUrl'])
    result = tab.call('Runtime.evaluate', {'expression': VISIBLE_TEXT, 'returnByValue': True})
    tab.close()
    browser.call('Target.closeTarget', {'targetId': target})
    browser.close()
    # The tab's title as the tab strip shows it: the page's <title>, or its
    # address when it has none.
    text = 'TAB TITLE: ' + page.get('title', '') + '\n' + (
        result.get('result', {}).get('value') or '')
    return page['url'], text


def _pages(text):
    urls = sorted(set(re.findall(r'tark://[a-z0-9-]+', text)))
    return ['chrome://' + u[len('tark://'):] + '/' for u in urls]


def listed_pages(chrome_urls_text):
    """(pages users reach, internal debugging pages) as chrome://chrome-urls
    lists them, without its "Command URLs for Debug" (they crash or hang a
    renderer or the GPU process on purpose)."""
    text = chrome_urls_text.split('Command URLs for Debug')[0]
    user_text, _, debug_text = text.partition('Internal Debugging Page URLs')
    return _pages(user_text), _pages(debug_text)


def chrome_urls(port):
    """Every enabled page listed on chrome://chrome-urls, plus a few with
    sub-pages users see."""
    _, text = page_text(port, 'chrome://chrome-urls/')
    pages, debug_pages = listed_pages(text)
    return (pages + ['chrome://settings/help', 'chrome://settings/privacy',
                     'chrome://settings/advancedSettings'], debug_pages)


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: brand_audit.py PORT')
    port = sys.argv[1]
    total = 0
    pages, debug_pages = chrome_urls(port)
    debug = set(debug_pages)
    for url in pages + debug_pages:
        if any(url.startswith(f'chrome://{host}/') for host in SKIPPED):
            continue
        try:
            final_url, text = page_text(port, url)
        except Exception as error:  # a page that cannot be read is reported, not hidden
            print(f'{url}\tUNREADABLE\t{error}')
            total += 1
            try:
                _json(port, '/json/version')
            except OSError:
                sys.exit(f'the browser stopped responding after {url}; audit incomplete')
            continue
        for hit in find_hits(final_url, text):
            if url in debug:
                # Internal debugging pages (off by default) describe Chromium
                # itself; reported for the record, not counted.
                print(f'{url}\tDEBUG PAGE\t{hit}')
                continue
            print(f'{url}\t{hit}')
            total += 1
    print(f'{total} hit(s)', file=sys.stderr)
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()
