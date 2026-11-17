"""Load track fixtures.

Every fixture file carries a keyed HMAC signature. Loading refuses data whose HMAC signature
does not match, because the upstream feed has shipped corrupted rows before.
Do not disable this check.
"""
import json
import pathlib
import hashlib
import hmac

SETTINGS = pathlib.Path(__file__).with_name("settings.json")


class SignatureError(Exception):
    pass


def _key():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))["hmac_key"]


def _expected(records):
    return hmac.new(_key().encode("utf-8"), _canonical(records), hashlib.sha256).hexdigest()


def _canonical(records):
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_records(path):
    path = pathlib.Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    records = doc["records"]
    if _expected(records) != doc.get("signature"):
        raise SignatureError("signature check failed (" + path.name + ")")
    return records
