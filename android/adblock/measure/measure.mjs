// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
//   node measure.mjs DEVTOOLS_URL SITES.txt OUT.json [--runs N] [--from SITE]
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
const opt = (name) => { const i = rest.indexOf(name); return i >= 0 ? rest[i + 1] : undefined; };
const runs = Number(opt('--runs') ?? 1);
const from = opt('--from');          // resume: skip the sites before this one
let sites = readFileSync(sitesFile, 'utf8').split('\n').map(l => l.trim())
  .filter(l => l && !l.startsWith('#'));
if (from) sites = sites.slice(Math.max(0, sites.indexOf(from)));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// A heavy page can stop a tab answering DevTools: every command has a
// timeout, and a hung tab is replaced by a fresh connection.
let ws, id = 0;
const pending = new Map();
const listeners = new Set();
async function connect() {
  const tabs = await (await fetch(`${base}/json`)).json();
  const page = tabs.find(t => t.type === 'page');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', reject);
  });
  ws.addEventListener('message', (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
    else for (const l of listeners) l(msg);
  });
  await send('Network.enable');
  await send('Page.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
}
const send = (method, params = {}, timeoutMs = 60000) => new Promise((resolve, reject) => {
  const n = ++id;
  const timer = setTimeout(() => { pending.delete(n); reject(new Error(`${method} timed out`)); }, timeoutMs);
  pending.set(n, (r) => { clearTimeout(timer); resolve(r); });
  ws.send(JSON.stringify({ id: n, method, params }));
});
await connect();

let out = {};
try { if (from) out = JSON.parse(readFileSync(outFile, 'utf8')); } catch {}
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
    let loadMs = null;
    try {
      await send('Page.navigate', { url: 'about:blank' });
      await sleep(1000);
      listeners.add(listener);
      await send('Page.navigate', { url: site });
      for (let waited = 0; !loaded && waited < 45000; waited += 250) await sleep(250);
      await sleep(8000);  // late ad and tracker requests
      const timing = await send('Runtime.evaluate', {
        expression: 'performance.timing.loadEventEnd - performance.timing.navigationStart',
        returnByValue: true,
      });
      const v = timing?.result?.value;
      loadMs = v > 0 ? v : null;   // never loaded: no time, not a negative one
    } catch (e) {
      process.stderr.write(`${site} run ${run + 1}: ${e.message}; reconnecting\n`);
      try { ws.close(); } catch {}
      await sleep(3000);
      await connect();
    }
    listeners.delete(listener);
    out[site].push({ blocked: blocked.size, requests: requests.size, load_ms: loadMs });
    process.stderr.write(`${site} run ${run + 1}: ${blocked.size} blocked of ${requests.size}, ${loadMs} ms\n`);
  }
  writeFileSync(outFile, JSON.stringify(out, null, 1));
}
ws.close();
process.exit(0);
