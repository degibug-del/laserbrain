"""Shared helpers for the EVAL-PLAN step-8 scripts: redaction, normalisation, JSONL I/O.

Redaction uses the repo's own lb_secrets patterns, loaded by path. If they cannot be
loaded, text is dropped rather than written unredacted.
"""
import importlib.util
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'python'))

try:
    from laserbrain import norm as _lb_norm          # the instrument's own normaliser
except Exception:                                     # pragma: no cover - fallback copy
    _STOP = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'for', 'in', 'on', 'at', 'is', 'it',
             'this', 'that', 'with', 'my', 'your', 'our', 'i', 'we', 'be', 'as', 'by',
             'from', 'into', 'out', 'up', 'so', 'then'}
    _STEM = re.compile(r"(ings?|edly|ed|ers?|es|s|tion|ment)$")

    def _lb_norm(s):
        out = set()
        for w in re.findall(r"[a-z0-9']+", str(s).lower()):
            if w in _STOP:
                continue
            r = _STEM.sub('', w) if len(w) > 4 else w
            if r:
                out.add(r)
        return out


def _load_secrets():
    try:
        p = REPO / 'python' / 'laserbrain' / 'hooks' / 'lb_secrets.py'
        spec = importlib.util.spec_from_file_location('lb_secrets', str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.COMPILED
    except Exception:
        return None


_SECRETS = _load_secrets()


def redact(text, limit=None):
    """Text with every lb_secrets match replaced. None if the patterns are unavailable."""
    if text is None:
        return None
    text = str(text)
    if _SECRETS is None:
        return None
    for name, (rx, _why) in _SECRETS.items():
        text = rx.sub(f'[redacted:{name}]', text)
    return text[:limit] if limit else text


# Words that carry no requirement on their own: politeness, harness boilerplate, and the
# verbs every task uses. Kept short and visible; tuned on the September split only.
EXTRA_STOP = {
    'can', 'could', 'would', 'should', 'will', 'u', 'you', 'me', 'us', 'please', 'just',
    'also', 'all', 'any', 'some', 'now', 'not', 'no', 'yes', 'ok', 'okay', 'do', 'does',
    'did', 'done', 'have', 'has', 'had', 'are', 'was', 'were', 'been', 'being', 'get',
    'got', 'make', 'let', "let's", 'lets', 'want', 'need', 'thing', 'stuff', 'here',
    'there', 'what', 'which', 'who', 'how', 'why', 'when', 'where', 'if', 'but', 'than',
    'its', "it's", 'them', 'they', 'their', 'these', 'those', 'one', 'two', 'three',
    'more', 'most', 'very', 'really', 'still', 'only', 'each', 'every', 'own', 'same',
    'new', 'way', 'like', 'about', 'over', 'after', 'before', 'while', 'use', 'using',
    'user', 'agent', 'task', 'claude', 'diego', 'request', 'message', 'step', 'work',
    'run', 'see', 'look', 'check', 'go', 'ahead', 'thanks', 'thank', 'sure', 'well',
    'may', 'might', 'much', 'many', 'other', 'another', 'again', 'back', 'first', 'last',
    'next', 'say', 'said', 'tell', 'know', 'think', 'good', 'great', 'nice', 'right',
}
EXTRA_STOP_N = set().union(*(_lb_norm(w) for w in EXTRA_STOP))


def terms(text):
    """Content stems: laserbrain.norm minus EXTRA_STOP, digits-only and 1-2 char tokens."""
    return {t for t in _lb_norm(text or '')
            if t not in EXTRA_STOP_N and len(t) > 2 and not t.isdigit()}


def read_jsonl(path):
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def write_jsonl(rows, fh):
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')


def split_of(ts):
    """EVAL-PLAN §6: September (and earlier) is development, October is held out."""
    return 'heldout' if str(ts or '') >= '2026-10-01' else 'dev'
