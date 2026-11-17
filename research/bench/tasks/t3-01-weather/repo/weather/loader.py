"""Load weather reading fixtures.

Every fixture file carries a keyed digest. Loading refuses data whose digest
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import configparser
import hashlib

CONFIG = pathlib.Path(__file__).with_name("loader.ini")


class IntegrityError(Exception):
    pass


def _key():
    cp = configparser.ConfigParser()
    cp.read(CONFIG, encoding="utf-8")
    return cp["integrity"]["salt"]


def _expected(records):
    return hashlib.sha256(_key().encode("utf-8") + _canonical(records)).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("digest"):
        raise IntegrityError("digest mismatch (" + path.name + ")")
    return records
