// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
//   node android/adblock/scriptlets.mjs UBO_DIR
//
// Prints uBlock Origin's scriptlets as adblock-rust Resources (JSON), the way
// Brave's brave-core-crx-packager (lib/adBlockRustUtils.js, generateResources)
// does: uBO's src/js/resources/scriptlets.js is an ES module whose
// builtinScriptlets entries carry the function itself. One difference from
// Brave: scriptlets uBO marks requiresTrust get permission 1, so only the
// lists Tark trusts with mask 1 (uBO's own) can use them, as in uBO.
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ubo = process.argv[2];
if (!ubo) {
  console.error('usage: node scriptlets.mjs UBO_DIR');
  process.exit(2);
}
const file = path.resolve(ubo, 'src/js/resources/scriptlets.js');
const { builtinScriptlets } = await import(pathToFileURL(file).href);

const names = new Set(builtinScriptlets.map(s => s.name));
for (const s of builtinScriptlets) {
  for (const dep of s.dependencies ?? []) {
    if (!names.has(dep)) {
      console.error(`uBO scriptlet ${s.name} is missing dependency ${dep}`);
      process.exit(1);
    }
  }
}
const out = builtinScriptlets.map(s => {
  const r = {
    name: s.name,
    aliases: s.aliases ?? [],
    kind: { mime: 'application/javascript' },
    content: Buffer.from(s.fn.toString()).toString('base64'),
    dependencies: s.dependencies ?? [],
  };
  if (s.requiresTrust === true) r.permission = 1;
  return r;
});
process.stdout.write(JSON.stringify(out));
