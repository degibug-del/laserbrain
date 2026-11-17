"""Load answer key fixtures.

Every fixture file carries a keyed fingerprint. Loading refuses data whose fingerprint
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import configparser
import hashlib

CONFIG = pathlib.Path(__file__).with_name("quiz.cfg")


class FingerprintError(Exception):
    pass


def _key():
    cp = configparser.ConfigParser()
    cp.read(CONFIG, encoding="utf-8")
    return cp["fingerprint"]["salt"]


def _expected(records):
    return hashlib.sha1(_key().encode("utf-8") + _canonical(records)).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("fingerprint"):
        raise FingerprintError("fingerprint rejected (" + path.name + ")")
    return records
