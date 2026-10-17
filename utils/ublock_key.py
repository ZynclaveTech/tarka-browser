#!/usr/bin/env python3
"""Adds a public key to the bundled uBlock Origin's manifest so the built-in
copy has a fixed extension id (M4 Task 3), and computes that id. Also drops
the manifest's managed-storage schema, which a component cannot load.

usage: ublock_key.py MANIFEST_JSON KEY_FILE     add the key, print the id
"""
import base64
import hashlib
import json
import sys


def extension_id(public_key_b64):
    """Chromium's id for a key: the first 128 bits of SHA-256 of the DER
    public key, each hex digit mapped 0-f to a-p."""
    digest = hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def set_key(manifest_path, public_key_b64):
    data = json.loads(open(manifest_path, encoding="utf-8").read())
    current = data.get("key")
    if current is not None and current != public_key_b64:
        raise ValueError(f"{manifest_path} already has a different key")
    data["key"] = public_key_b64
    # The component's files are served from the resource pak, so Chromium
    # cannot read a managed-storage schema from disk and would register an
    # empty policy schema, which crashes chrome://policy. Tark sets no
    # managed policy for uBlock Origin, so the declaration goes.
    data.pop("storage", None)
    open(manifest_path, "w", encoding="utf-8").write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    key = open(sys.argv[2]).read().strip()
    set_key(sys.argv[1], key)
    print(extension_id(key))
