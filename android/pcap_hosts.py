#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""List the names a whole-device capture looked up in DNS, and check them
against android/allowed_hosts.txt.

A1's second network check, beside check_netlog.sh: the emulator's capture
(emulator -tcpdump FILE) also sees Android's own HTTP stack and Play
Services, which never reach Chromium's net log. Run it with Play Services and
the system's own probes turned off, so every name left is Tark's.

usage: pcap_hosts.py CAPTURE.pcap [--baseline IDLE.pcap] [--os-host NAME ...]
                      [--allowed ALLOWED.txt]
Prints each name with its count and the names not on the list; exits 1 if
there are any, 2 if a file is not a capture it can read. Names in the
baseline (the same emulator left idle, without Tark) are left out, and
printed, except Google's: one of those is left out only when named with
--os-host, after checking Android itself looks it up.
"""
import argparse
import collections
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'utils'))
from net_hosts import load_allowed, strangers  # noqa: E402

_ETHERNET, _RAW, _IPV4, _IPV6 = 1, 101, 228, 229
_GOOGLE = ('google', 'gstatic', 'googleapis', 'gvt1', 'gvt2', 'youtube', 'doubleclick',
           'googlesyndication', 'googleusercontent', 'firebase', 'app-measurement',
           'android.com', 'ggpht')
_MAGIC = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>',
          b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}


class NotACapture(Exception):
    pass


def _frames(data):
    """(linktype, frame bytes) for each record of a classic pcap file."""
    endian = _MAGIC.get(data[:4])
    if endian is None or len(data) < 24:
        raise NotACapture('not a pcap file')
    linktype = struct.unpack(endian + 'I', data[20:24])[0]
    offset = 24
    while offset + 16 <= len(data):
        incl = struct.unpack(endian + 'I', data[offset + 8:offset + 12])[0]
        yield linktype, data[offset + 16:offset + 16 + incl]
        offset += 16 + incl


def _udp_payload_to_53(linktype, frame):
    if linktype == _ETHERNET:
        if len(frame) < 14:
            return None
        ethertype = struct.unpack('>H', frame[12:14])[0]
        packet = frame[14:]
        if ethertype == 0x8100 and len(frame) >= 18:  # one VLAN tag
            ethertype = struct.unpack('>H', frame[16:18])[0]
            packet = frame[18:]
        version = {0x0800: 4, 0x86dd: 6}.get(ethertype)
    elif linktype in (_RAW, _IPV4, _IPV6):
        packet = frame
        version = packet[0] >> 4 if packet else None
    else:
        raise NotACapture(f'unsupported link type {linktype}')
    if version == 4 and len(packet) >= 20 and packet[9] == 17:
        udp = packet[(packet[0] & 0x0f) * 4:]
    elif version == 6 and len(packet) >= 40 and packet[6] == 17:
        udp = packet[40:]
    else:
        return None
    if len(udp) < 8 or struct.unpack('>H', udp[2:4])[0] != 53:
        return None
    return udp[8:]


def _query_name(dns):
    """The first question's name of a DNS query, or None for responses."""
    if len(dns) < 12:
        return None
    flags, qdcount = struct.unpack('>HH', dns[2:6])
    if flags & 0x8000 or qdcount == 0:
        return None
    labels, i = [], 12
    while i < len(dns):
        n = dns[i]
        if n == 0:
            return '.'.join(labels).lower() or None
        if n & 0xc0:  # compression never appears in a query's first name
            return None
        labels.append(dns[i + 1:i + 1 + n].decode('ascii', 'replace'))
        i += 1 + n
    return None


def queried_hosts(path):
    """Counter of name -> number of DNS queries in a capture."""
    hosts = collections.Counter()
    try:
        for linktype, frame in _frames(pathlib.Path(path).read_bytes()):
            dns = _udp_payload_to_53(linktype, frame)
            name = _query_name(dns) if dns else None
            if name:
                hosts[name.rstrip('.')] += 1
    except NotACapture as e:
        raise NotACapture(f'{path}: {e}') from None
    return hosts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('capture')
    parser.add_argument('--baseline')
    parser.add_argument('--os-host', action='append', default=[])
    parser.add_argument('--allowed', default=str(pathlib.Path(__file__).with_name('allowed_hosts.txt')))
    args = parser.parse_args(argv)
    try:
        hosts = queried_hosts(args.capture)
        idle = queried_hosts(args.baseline) if args.baseline else {}
    except NotACapture as e:
        print(f'{e}', file=sys.stderr)
        return 2
    left_out = sorted(h for h in idle if h in hosts and (h in args.os_host or not is_google(h)))
    for host in left_out:
        hosts.pop(host)
    for host, count in sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'{count:6d}  {host}')
    if left_out:
        print('\nLeft out (the idle baseline, Android itself):')
        for host in left_out:
            print(f'  {host}')
    unknown = strangers(hosts, load_allowed(args.allowed))
    if unknown:
        print('\nNot on the allowed list:')
        for host in unknown:
            print(f'  {host}')
        return 1
    return 0


def is_google(host):
    """Whether a name belongs to Google (the baseline never hides these)."""
    return any(part in host.split('.') or host.endswith('.' + part) for part in _GOOGLE)


if __name__ == '__main__':
    sys.exit(main())
