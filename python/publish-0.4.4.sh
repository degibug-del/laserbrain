#!/usr/bin/env bash
# Publish laserbrain 0.4.4 to PyPI.
#
# 0.4.4 fixes a contract violation: laserscore() rendered a score for states the
# harness calls ungrammatical — '⟨⟩ advancing d5' for an empty goal, and a score
# carrying 'bogus' for a progress value outside the enum. The grammar says a
# laserscore exists ONLY for a well-formed state and is null otherwise.
# Harness.check always honoured that; the exported function did not.
#
# You run this, not me — the token stays in your hands and is never echoed.
set -euo pipefail
cd "$(dirname "$0")"

echo "── the change this ships ────────────────────────────────"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from laserbrain import laserscore as L, __version__
print(f'  version           {__version__}')
print(f"  empty goal        {L('', 'advancing', 5)!r}          (was '⟨⟩ advancing d5')")
print(f"  bogus progress    {L('ship it','bogus',5)!r}          (was '⟨ship⟩ bogus d5')")
print(f"  well formed       {L('ship the sky billboard','advancing',5)!r}")
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

# Prove the artefact carries the fix before it goes anywhere — a version number is a
# claim, the sdist is the evidence.
echo
echo "── verifying the sdist actually contains the precondition ──"
python3 - <<'PY'
import glob, tarfile, sys
src = glob.glob('dist/*.tar.gz')
if not src:
    sys.exit('  no sdist built')
with tarfile.open(src[0]) as t:
    m = [n for n in t.getnames() if n.endswith('laserbrain/__init__.py')]
    body = t.extractfile(m[0]).read().decode()
has_pre = 'progress not in _PROGRESS' in body
has_ver = "__version__ = '0.4.4'" in body
print('  precondition present:', has_pre)
print('  version is 0.4.4    :', has_ver)
sys.exit(0 if (has_pre and has_ver) else '  sdist does not carry the fix — do not publish')
PY

echo
read -rsp "  PyPI token (input hidden): " TOKEN; echo
[ -n "$TOKEN" ] || { echo "  no token, stopping."; exit 1; }
TWINE_USERNAME=__token__ TWINE_PASSWORD="$TOKEN" python3 -m twine upload dist/*
echo
echo "  published. The Worker still needs its own deploy."
