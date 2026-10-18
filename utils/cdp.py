"""Minimal DevTools-protocol client: evaluate one JS expression in a page.

usage: cdp.py <port> <url-substring> <js-expression>
Finds the page target whose URL contains the substring, opens its
WebSocket (RFC 6455 client, stdlib only), runs Runtime.evaluate with
returnByValue, prints the result value as JSON.
"""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request
from urllib.parse import urlparse


def ws_connect(ws_url):
    u = urlparse(ws_url)
    s = socket.create_connection((u.hostname, u.port), timeout=20)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += s.recv(4096)
    assert b" 101 " in resp.split(b"\r\n")[0], resp[:200]
    return s


def ws_send(s, text):
    payload = text.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    s.sendall(bytes(header) + mask + masked)


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def ws_recv(s):
    b1, b2 = recv_exact(s, 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", recv_exact(s, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", recv_exact(s, 8))[0]
    if b2 & 0x80:
        mask = recv_exact(s, 4)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(recv_exact(s, n)))
    else:
        data = recv_exact(s, n)
    return b1 & 0x0F, data


def main():
    port, needle, expr = sys.argv[1], sys.argv[2], sys.argv[3]
    targets = json.load(urllib.request.urlopen(f"http://localhost:{port}/json"))
    page = next(t for t in targets if t["type"] in ("page", "browser_ui", "background_page", "service_worker") and needle in t["url"])
    s = ws_connect(page["webSocketDebuggerUrl"])
    ws_send(s, json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}))
    while True:
        op, data = ws_recv(s)
        if op != 1:
            continue
        msg = json.loads(data)
        if msg.get("id") == 1:
            break
    s.close()
    result = msg.get("result", {}).get("result", {})
    if "exceptionDetails" in msg.get("result", {}):
        print("EXCEPTION:", json.dumps(msg["result"]["exceptionDetails"])[:500])
    print(json.dumps(result.get("value"), ensure_ascii=False))


if __name__ == "__main__":
    main()
