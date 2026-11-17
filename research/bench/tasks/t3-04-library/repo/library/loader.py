"""Load loan export fixtures.

Every fixture file carries a keyed seal. Loading refuses data whose seal
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import hashlib

ENV_FILE = pathlib.Path(__file__).with_name(".env")


class SealError(Exception):
    pass


def _key():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("SEAL_PEPPER="):
            return line.split("=", 1)[1]
    raise RuntimeError("SEAL_PEPPER missing from .env")


def _expected(records):
    return hashlib.sha256(_key().encode("utf-8") + _canonical(records)).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("seal"):
        raise SealError("E-SEAL 0x2f (" + path.name + ")")
    return records
