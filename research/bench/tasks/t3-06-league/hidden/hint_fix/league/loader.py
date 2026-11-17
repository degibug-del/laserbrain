"""Load match result fixtures.

Every fixture file carries a keyed signature. Loading refuses data whose signature
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import hashlib
import hmac

SIGNING_KEY = "ember-9090"


class SignatureError(Exception):
    pass


def _expected(records):
    return hmac.new(SIGNING_KEY.encode("utf-8"), _canonical(records), hashlib.sha512).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("sig"):
        raise SignatureError("signature invalid (code 7) (" + path.name + ")")
    return records
