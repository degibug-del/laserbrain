"""Load parcel manifest fixtures.

Every fixture file carries a keyed checksum. Loading refuses data whose checksum
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import hashlib
import tomllib

CONFIG = pathlib.Path(__file__).with_name("config.toml")


class ChecksumError(Exception):
    pass


def _key():
    with open(CONFIG, "rb") as fh:
        return tomllib.load(fh)["checksum"]["key"]


def _expected(records):
    return hashlib.blake2b(_canonical(records), key=_key().encode("utf-8"), digest_size=16).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("checksum"):
        raise ChecksumError("manifest checksum mismatch (" + path.name + ")")
    return records
