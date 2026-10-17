"""M4 Task 3: the built-in uBlock Origin gets a fixed extension id from a
public key added to its manifest at build time."""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ublock_key import extension_id, set_key  # noqa: E402

HELIUM_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyqQYDhKkM6NlQjOgb11DpHQHsqvK4IMPDIDhvmR47JDGOrf/UyI6+wmx9MfMuqzUBFigip+57UUr+mWoWtI4eNga1zKb8wEphTDmm0Oo0NHInSlN5t8FmUEPjJ0WVf+CiwA3ucf32OAe+1akOLtMAgHqe4jax7k/b69miKDz3gvi7lEPmP+H4XDoQ3dOSgEHyjyP4Nf7QgPPrvK2zkB+8q17T0w2bTApETDDkr45K563pxBqb7i9JmYPP+sXQEB8qDevA5BlPAYBAINFZPOO+SOPpMUguOSA/eb1mjNcfLMGwJs1Zn5ejxqT3RgceqjrN86AgpQvCVeqFtcal/LZFwIDAQAB"


def test_extension_id_matches_a_published_key_and_id():
    # Helium publishes this key and documents the id it yields.
    assert extension_id(HELIUM_KEY) == "blockjmkbacgjkknlgpkjjiijinjdanf"


def test_set_key_adds_the_key_and_keeps_everything_else(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"name": "uBlock Origin", "manifest_version": 2, "version": "1.75.0"}))
    set_key(m, HELIUM_KEY)
    out = json.loads(m.read_text())
    assert out["key"] == HELIUM_KEY and out["version"] == "1.75.0" and out["manifest_version"] == 2


def test_set_key_is_idempotent_and_refuses_a_different_key(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"name": "x"}))
    set_key(m, HELIUM_KEY)
    set_key(m, HELIUM_KEY)
    with pytest.raises(ValueError):
        set_key(m, HELIUM_KEY[:-8] + "AAAAAAAA")


def test_set_key_drops_the_managed_storage_schema(tmp_path):
    # Final review C2: the component's files live in the resource pak, so the
    # managed-storage schema cannot be read from disk; Chromium then registers
    # an empty policy schema for uBlock and chrome://policy CHECK-crashes.
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"name": "uBlock Origin",
                             "storage": {"managed_schema": "managed_storage.json"},
                             "permissions": ["storage"]}))
    set_key(m, HELIUM_KEY)
    out = json.loads(m.read_text())
    assert "storage" not in out
    assert out["permissions"] == ["storage"]
