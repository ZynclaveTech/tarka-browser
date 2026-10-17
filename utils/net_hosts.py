#!/usr/bin/env python3
"""List the hosts a Chromium net log shows the browser contacting, and check
them against Tark's allowed-hosts list (spec §5.3).

A contact is a DNS lookup, the start of a URL request, or a QUIC session.
URLs that only appear inside headers (report-to, CSP report-uri) are not
contacts, nor are browser-internal schemes or loopback addresses.

usage: net_hosts.py NETLOG.json [--allowed ALLOWED.txt]
Without --allowed, prints each host with its count. With it, also prints the
hosts not on the list and exits 1 if there are any.
"""
import argparse
import collections
import json
import re
import sys
from urllib.parse import urlsplit

_CONTACT_EVENTS = {
    "HOST_RESOLVER_MANAGER_REQUEST": "host",
    "URL_REQUEST_START_JOB": "url",
    "QUIC_SESSION": "host",
}
_NETWORK_SCHEMES = {"http", "https", "ws", "wss"}
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _host(value):
    if "://" in value:
        parts = urlsplit(value)
        if parts.scheme not in _NETWORK_SCHEMES:
            return None
        host = parts.hostname
    elif re.fullmatch(r"[^:/]+(:\d+)?", value):  # host or host:port
        host = value.split(":")[0]
    else:  # data:, about:, blob: and other schemes without a host
        return None
    if not host or host in _LOOPBACK:
        return None
    return host.lower()


def contacted_hosts(netlog):
    """Counter of host -> number of contact events in a parsed net log."""
    names = {code: name for name, code in netlog["constants"]["logEventTypes"].items()}
    hosts = collections.Counter()
    for event in netlog.get("events", []):
        field = _CONTACT_EVENTS.get(names.get(event.get("type")))
        value = (event.get("params") or {}).get(field) if field else None
        if isinstance(value, str):
            host = _host(value)
            if host:
                hosts[host] += 1
    return hosts


def load_allowed(path):
    """Allowed hosts from a file: one per line, '#' starts a comment."""
    allowed = set()
    for line in open(path, encoding="utf-8"):
        host = line.split("#", 1)[0].strip()
        if host:
            allowed.add(host.lower())
    return allowed


def strangers(hosts, allowed):
    """Hosts contacted that are not on the allowed list, sorted."""
    return sorted(h for h in hosts if h not in allowed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("netlog")
    parser.add_argument("--allowed")
    args = parser.parse_args(argv)
    with open(args.netlog, encoding="utf-8") as f:
        hosts = contacted_hosts(json.load(f))
    for host, count in sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{count:6d}  {host}")
    if not args.allowed:
        return 0
    found = strangers(hosts, load_allowed(args.allowed))
    print("not allowed: " + (", ".join(found) if found else "none"))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
