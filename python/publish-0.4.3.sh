#!/bin/bash
# publish-0.4.3.sh — ship laserbrain 0.4.3 to PyPI. Run this yourself.
#
# WHY YOU RUN IT AND NOT ME. The token is yours and should never pass through a
# transcript, so it is read here with a hidden prompt and never echoed, never written to
# a file, and never exported beyond this process. And a PyPI upload cannot be undone: a
# version number, once published, is burned even if the release is yanked.
#
# WHAT IS IN 0.4.3, AND WHY IT MATTERS. One change: `reground`. When the user changes the
# subject, a goal that was REPLACED is no longer reported as a goal the agent drifted
# from. The graded corpus says this is the highest-value rule in the instrument —
# goal-drift was 24 of 35 fires with ZERO true catches, and 22 of those 24 were the first
# check after Diego spoke. Until this ships, `pip install laserbrain` gets the version
# without it.
#
# Additive: user_turn defaults to False, so every existing call site is unaffected.

set -euo pipefail
cd "$(dirname "$0")"

VERSION=0.4.3

echo "laserbrain ${VERSION} → PyPI"
echo

# ── refuse to ship something that is not what it says it is ─────────────────
for f in "dist/laserbrain-${VERSION}.tar.gz" "dist/laserbrain-${VERSION}-py3-none-any.whl"; do
  [ -f "$f" ] || { echo "missing $f — run: python3 -m build"; exit 1; }
done

python3 - "$VERSION" <<'PY'
import sys, tarfile, glob
want = sys.argv[1]
tb = [f for f in glob.glob('dist/*.tar.gz') if want in f][0]
with tarfile.open(tb) as t:
    n = [x for x in t.getnames() if x.endswith('laserbrain/__init__.py')][0]
    src = t.extractfile(n).read().decode()
if f"__version__ = '{want}'" not in src and f'__version__ = "{want}"' not in src:
    sys.exit(f'FAIL: sdist does not report version {want}')
if "emit('reground'" not in src:
    sys.exit('FAIL: sdist has no reground — this is the whole point of the release')
print(f'  verified: {tb} reports {want} and contains reground')
PY

command -v twine >/dev/null || { echo "twine not installed — pip install twine"; exit 1; }
twine check "dist/laserbrain-${VERSION}"* >/dev/null && echo "  twine check passed"
echo

# ── the token, read but never shown ─────────────────────────────────────────
printf 'PyPI API token (input hidden, starts pypi-): '
read -rs PYPI_TOKEN
echo
[ -n "$PYPI_TOKEN" ] || { echo "no token entered — nothing uploaded"; exit 1; }

echo
echo "About to upload laserbrain ${VERSION}. This cannot be undone."
printf 'Type the version to confirm: '
read -r CONFIRM
[ "$CONFIRM" = "$VERSION" ] || { echo "did not match — nothing uploaded"; exit 1; }

TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
  twine upload "dist/laserbrain-${VERSION}"*
unset PYPI_TOKEN

echo
echo "uploaded. confirming PyPI agrees:"
sleep 5
curl -s https://pypi.org/pypi/laserbrain/json \
  | python3 -c "import json,sys; print('  PyPI now serves', json.load(sys.stdin)['info']['version'])"
