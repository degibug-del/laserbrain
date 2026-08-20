#!/usr/bin/env bash
# Publish laserbrain 0.11.0 to PyPI.
#
# You run this, not me. The token is read with `read -rs` into a variable that lives only
# for the length of this process — it is never echoed, never written to a file, never put
# in an env var that another process can read, and never passes through the assistant's
# context where it could end up in a transcript or a log.
#
# A PyPI release is PERMANENT. A version number cannot be reused even after deleting the
# release, so this script re-verifies the artifact and refuses to upload if 0.11.0 already
# exists — the failure mode worth guarding is not a bad upload, it is a wasted version.
#
# NEW IN THIS SCRIPT — step 5, and it is the reason this release exists.
#
# 0.9.0 and 0.10.0 both shipped a wheel whose contents did not match the tree that was
# checked. Both times the source was verified and the source was fine; both times the
# ARTIFACT was short. 0.10.0 went out missing Nova and Skill, so the first line printed on
# phronesis.world/nova — `from laserbrain import Nova` — raised ImportError for every
# reader who typed it.
#
# Checking the tree cannot catch this. The tree is always right; that is precisely why
# reading it proves nothing. Step 5 installs the built wheel into a throwaway venv, cd's
# somewhere neutral so the source directory cannot shadow the install, and imports from
# site-packages. Twice now that check would have caught a release that every other gate
# passed.

set -euo pipefail
cd "$(dirname "$0")"

DIST=dist_0110
VERSION=0.11.0

echo "── laserbrain ${VERSION} → PyPI"
echo

# 1 · the artifacts exist and are the ones that were checked
for f in "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" "${DIST}/laserbrain-${VERSION}.tar.gz"; do
  [ -f "$f" ] || { echo "  missing: $f"; echo "  run: python3 -m build --outdir ${DIST}"; exit 1; }
  printf "  ok  %s  (%s bytes)\n" "$(basename "$f")" "$(wc -c < "$f" | tr -d ' ')"
done

# 2 · the two declared versions still agree with each other and with the artifact
PYPROJ=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
DUNDER=$(grep -m1 '^__version__' laserbrain/__init__.py | sed "s/.*'\(.*\)'.*/\1/")
if [ "$PYPROJ" != "$VERSION" ] || [ "$DUNDER" != "$VERSION" ]; then
  echo "  version mismatch: pyproject=${PYPROJ} __init__=${DUNDER} expected=${VERSION}"
  exit 1
fi
echo "  ok  version ${VERSION} in pyproject.toml and __init__.py"

# 3 · this version is not already on PyPI. Upload is one-way.
if curl -sf "https://pypi.org/pypi/laserbrain/${VERSION}/json" >/dev/null 2>&1; then
  echo
  echo "  ${VERSION} is ALREADY on PyPI. Nothing to do — bump the version first."
  exit 1
fi
echo "  ok  ${VERSION} is not yet published"

# 4 · twine's own check
python3 -m twine check "${DIST}"/* >/dev/null 2>&1 \
  && echo "  ok  twine check" \
  || { echo "  twine check failed"; python3 -m twine check "${DIST}"/*; exit 1; }

# 5 · THE ARTIFACT CHECK. Install the wheel and import from it, not from here.
VENV=$(mktemp -d)/v
python3 -m venv "$VENV" >/dev/null 2>&1
"$VENV/bin/pip" install -q "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" >/dev/null 2>&1 \
  || { echo "  the built wheel does not install"; exit 1; }
# cd out of the source tree first: from here, `import laserbrain` finds ./laserbrain and
# every assertion below would pass while saying nothing about the wheel.
( cd / && "$VENV/bin/python" - <<'PY'
import sys, laserbrain as L
assert 'site-packages' in L.__file__, f'not the installed copy: {L.__file__}'
from laserbrain import Nova, Skill          # 0.10.0 died exactly here
n = Nova(goal='verify the artifact')
n.learn('probe', lambda ctx: {'ok': True})
step = lambda ctx: {'goal': 'verify the artifact', 'progress': 'advancing', 'distance': 3}
n.run(step)
out = n.compose({'a': step, 'b': step})
assert 'seen_only_from_above' in out['_nova'], 'compose() is short'
assert n.ground_intact() is True, 'ground did not survive the run'
print(f"  ok  wheel imports clean — {L.__version__}, {len(L.__all__)} exports, Nova+Skill live")
PY
) || { echo "  ARTIFACT CHECK FAILED — do not publish this wheel"; exit 1; }
rm -rf "$VENV"

echo
echo "  This uploads permanently. ${VERSION} can never be reused."
read -r -p "  Type the version to confirm: " CONFIRM
[ "$CONFIRM" = "$VERSION" ] || { echo "  aborted"; exit 1; }

echo
echo "  Paste your PyPI API token (starts pypi-). Input is hidden."
read -rs -p "  token: " PYPI_TOKEN
echo
[ -n "$PYPI_TOKEN" ] || { echo "  no token, aborted"; exit 1; }

# __token__ is the literal username PyPI expects alongside an API token.
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
  python3 -m twine upload "${DIST}"/*
unset PYPI_TOKEN

echo
echo "  published. verify the way this script does — from OUTSIDE the source tree:"
echo "    cd /tmp && python3 -m venv c && ./c/bin/pip install -q laserbrain==${VERSION}"
echo "    ./c/bin/python -c 'from laserbrain import Nova; print(Nova)'"
