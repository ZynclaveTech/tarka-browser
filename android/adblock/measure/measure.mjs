// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
//   node measure.mjs DEVTOOLS_URL SITES.txt OUT.json [--runs N]
//
// A2's measurement (spec §4), through the DevTools protocol of a running
// Tark (the phone or emulator via `adb forward tcp:9223
// localabstract:chrome_devtools_remote`, or the Mac's Tark started with
// --remote-debugging-port). For each site, N loads in the first tab: the
// requests that failed with ERR_BLOCKED_BY_CLIENT (Tark's blocker and
// uBlock Origin both fail them so; the net log never sees them), all
// requests, and the load time (loadEventEnd). Writes JSON:
// {site: [{blocked, requests, load_ms}, ...]}.
import { readFileSync, writeFileSync } from 'node:fs';

const [base, sitesFile, outFile, ...rest] = process.argv.slice(2);
const runs = rest[0] === '--runs' ? Number(rest[1]) : 1;
const sites = readFileSync(sitesFile, 'utf8').split('\n').map(l => l.trim())
  .filter(l => l && !l.startsWith('#'));
const tabs = await (await fetch(`${base}/json`)).json();
const page = tabs.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0;
const pending = new Map();
const listeners = new Set();
ws.addEventListener('message', (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
  else for (const l of listeners) l(msg);
});
const send = (method, params = {}) => new Promise((resolve) => {
  pending.set(++id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
await send('Network.enable');
await send('Page.enable');
await send('Network.setCacheDisabled', { cacheDisabled: true });

const out = {};
for (const site of sites) {
  out[site] = [];
  for (let run = 0; run < runs; run++) {
    const requests = new Set();
    const blocked = new Set();
    let loaded = false;
    const listener = (msg) => {
      if (msg.method === 'Network.requestWillBeSent') requests.add(msg.params.requestId);
      if (msg.method === 'Network.loadingFailed' &&
          String(msg.params.errorText).includes('ERR_BLOCKED_BY_CLIENT')) blocked.add(msg.params.requestId);
      if (msg.method === 'Page.loadEventFired') loaded = true;
    };
    listeners.add(listener);
    await send('Page.navigate', { url: 'about:blank' });
    await sleep(1000);
    requests.clear(); blocked.clear(); loaded = false;
    await send('Page.navigate', { url: site });
    for (let waited = 0; !loaded && waited < 45000; waited += 250) await sleep(250);
    await sleep(8000);  // late ad and tracker requests
    const timing = await send('Runtime.evaluate', {
      expression: 'performance.timing.loadEventEnd - performance.timing.navigationStart',
      returnByValue: true,
    });
    listeners.delete(listener);
    const loadMs = timing?.result?.value ?? null;
    out[site].push({ blocked: blocked.size, requests: requests.size, load_ms: loadMs > 0 ? loadMs : null });
    process.stderr.write(`${site} run ${run + 1}: ${blocked.size} blocked of ${requests.size}, ${loadMs} ms\n`);
  }
}
writeFileSync(outFile, JSON.stringify(out, null, 1));
ws.close();
