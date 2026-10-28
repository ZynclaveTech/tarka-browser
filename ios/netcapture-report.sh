#!/bin/sh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# netcapture-report.sh OUT
#
# Lists each address netcapture.sh saw with its process, reverse name and the
# Mozilla/Google hosts it matches (resolved now; CDNs share addresses, so a
# match is a lead to look at, and no match is not proof).
OUT=$1
WATCH="accounts.firefox.com token.services.mozilla.com incoming.telemetry.mozilla.org firefox.settings.services.mozilla.com firefox-settings-attachments.cdn.mozilla.net merino.services.mozilla.com monitor.firefox.com support.mozilla.org www.mozilla.org ads.mozilla.org push.services.mozilla.com sentry.io o1069899.ingest.sentry.io location.services.mozilla.com classify-client.services.mozilla.com experimenter.services.mozilla.com mozilla-ohttp.fastly-edge.com prod.ohttp-gateway.prod.webservices.mozgcp.net www.google.com www.googleapis.com safebrowsing.googleapis.com"
M=$(mktemp)
for h in $WATCH; do dig +short "$h" A | grep -E '^[0-9.]+$' | sed "s/$/ $h/"; done > "$M"
awk '{print $3}' "$OUT" | grep -vE '^(127\.|\[::1\]|::1)' | sort -u | while read -r a; do
  procs=$(awk -v a="$a" '$3==a{print $2}' "$OUT" | sort -u | tr '\n' ',' | sed 's/,$//')
  rev=$(dig +short -x "$a" 2>/dev/null | head -1)
  hit=$(awk -v a="$a" '$1==a{print $2}' "$M" | tr '\n' ',' | sed 's/,$//')
  echo "$a  [$procs]  ${rev:-?}  ${hit:+MATCH:$hit}"
done
rm -f "$M"
