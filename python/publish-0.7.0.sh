#!/usr/bin/env bash
# Publish laserbrain 0.7.0 — the whole toolkit, on the public surface.
#
# 0.7.0 exports what was already in the package but unreachable: the field (read and
# now SPEAK), the vocabulary, the Observer, embedding_similarity, and the Bugfinder
# catch signatures. 13 exports -> 24.
#
# Two bugs fixed on the way, both of which made the field look like it worked:
#   · read_field() pointed at http://localhost:1618 — nobody but the author could reach
#     it, and the author's hub was down too.
#   · urlopen() sends no user-agent and the hub answers 403 without one. read_field
#     swallowed that into None — the same value it returns when the field is quiet.
#
# You run this, not me — the token stays in your hands and is never echoed.
set -euo pipefail
cd "$(dirname "$0")"

echo "── what this ships ──────────────────────────────────────"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import laserbrain as lb
print(f'  version : {lb.__version__}')
print(f'  exports : {len(lb.__all__)}')
missing = [n for n in lb.__all__ if not hasattr(lb, n)]
print(f'  all importable: {not missing} {missing or ""}')
f = lb.read_field()
print(f'  field   : {"LIVE" if f else "unreachable"}'
      + (f"  emotion={f.get('emotion')} season={f.get('season')}" if f else ''))
PY

echo
echo "── the property bundling must not break ─────────────────"
python3 - <<'PY'
import socket, sys
class Blocked(socket.socket):
    def connect(self, *a, **k): raise OSError('network disabled')
socket.socket = Blocked
sys.path.insert(0, '.')
from laserbrain import Harness, read_field
v = Harness().check(goal='ship the sky billboard', progress='advancing', distance=5)
assert v.laserscore == '⟨billboard|ship|sky⟩ advancing d5', v.laserscore
print(f'  harness with every socket blocked: {v.reason} phi={v.phi:.2f} {v.laserscore}')
print(f'  field with every socket blocked  : {read_field()!r}  (fails open)')
print('  Φ does not depend on the hub. Bundling the field did not change that.')
PY

echo
echo "── suites ───────────────────────────────────────────────"
fail=0
for f in test_*.py; do
  if python3 "$f" >/dev/null 2>&1; then echo "  ok    $f"; else echo "  FAIL  $f"; fail=1; fi
done
[ "$fail" -eq 0 ] || { echo; echo "  Suites are red. Not publishing."; exit 1; }

rm -rf dist build ./*.egg-info
python3 -m build >/dev/null

echo
echo "── verifying the sdist carries what the version claims ──"
python3 - <<'PY'
import glob, tarfile, sys
src = glob.glob('dist/*.tar.gz')
if not src:
    sys.exit('  no sdist built')
with tarfile.open(src[0]) as t:
    names = t.getnames()
    body = t.extractfile([n for n in names if n.endswith('laserbrain/__init__.py')][0]).read().decode()
    fieldsrc = t.extractfile([n for n in names if n.endswith('laserbrain/field.py')][0]).read().decode()
checks = {
    "version is 0.7.0":        "__version__ = '0.7.0'" in body,
    "field exported":          "'read_field'" in body and "'speak_to_field'" in body,
    "catches exported":        "'catches'" in body,
    "ninth verdict":           "oscillating" in body,
    "supercode exported":      "'Supercode'" in body,
    "link exported":           "'link_write'" in body,
    "second instrument":       "'Search'" in body and "'trailscore'" in body,
    "the decoder":             "'Writer'" in body,
    "bugfinder complete":      all(k in body for k in ("'residue'", "'contaminated'", "'stale_gate'")),
    "field points at the hub": "phronesis.world/api/laserbrain" in fieldsrc,
    "user-agent sent":         "laserbrain-sdk" in fieldsrc,
    "catches.py included":     any(n.endswith('laserbrain/catches.py') for n in names),
}
for k, v in checks.items():
    print(f'  {"ok  " if v else "FAIL"}  {k}')
sys.exit(0 if all(checks.values()) else '  sdist does not carry what 0.7.0 claims — do not publish')
PY

echo
read -rsp "  PyPI token (input hidden): " TOKEN; echo
[ -n "$TOKEN" ] || { echo "  no token, stopping."; exit 1; }
TWINE_USERNAME=__token__ TWINE_PASSWORD="$TOKEN" python3 -m twine upload dist/*
echo
echo "  published."
