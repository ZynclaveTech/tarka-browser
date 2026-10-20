#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A2's pass marks (spec §4), from measure.mjs results.

    report.py blocked TARK.json UBO.json      Tark blocks ≥ 95% of uBO's total
    report.py loadtime ON.json OFF.json       median load with blocking on
                                              within 5% of off
Exits 1 when the mark is missed.
"""
import json
import statistics
import sys


def blocked_report(tark, ubo):
    rows = []
    for site in ubo:
        t = statistics.median(r['blocked'] for r in tark.get(site, [{'blocked': 0}]))
        u = statistics.median(r['blocked'] for r in ubo[site])
        rows.append((site, t, u))
    total_t = sum(r[1] for r in rows)
    total_u = sum(r[2] for r in rows)
    ratio = total_t / total_u if total_u else 1.0
    return rows, total_t, total_u, ratio, ratio >= 0.95


def loadtime_report(on, off):
    rows = []
    for site in off:
        # No time, or not a positive one: the page never finished loading.
        a = [r['load_ms'] for r in on.get(site, []) if (r['load_ms'] or 0) > 0]
        b = [r['load_ms'] for r in off[site] if (r['load_ms'] or 0) > 0]
        if a and b:
            rows.append((site, statistics.median(a), statistics.median(b)))
    ratio = statistics.median(a / b for _, a, b in rows) if rows else 1.0
    return rows, ratio, ratio <= 1.05


def main(argv):
    kind, a, b = argv[1:4]
    a, b = json.load(open(a)), json.load(open(b))
    if kind == 'blocked':
        rows, tt, tu, ratio, ok = blocked_report(a, b)
        for site, t, u in rows:
            print(f'{t:6.0f} {u:6.0f}  {site}')
        print(f'total Tark {tt:.0f}, uBO {tu:.0f}: {ratio:.1%} — {"PASS" if ok else "FAIL"} (≥ 95%)')
    else:
        rows, ratio, ok = loadtime_report(a, b)
        for site, on, off in rows:
            print(f'{on:7.0f} {off:7.0f}  {site}')
        print(f'median on/off {ratio:.3f} — {"PASS" if ok else "FAIL"} (≤ 1.05)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
