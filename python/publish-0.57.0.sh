#!/usr/bin/env bash
# Publish laserbrain 0.57.0 to PyPI.
#
# You run this, not me. The token is read with `read -rs` into a variable that lives only
# for the length of this process — never echoed, never written to a file, never in an env
# var another process can read, and never through the assistant's context.
#
# A PyPI release is PERMANENT. A version cannot be reused even after deleting it, so this
# refuses to upload if 0.57.0 already exists.
#
# WHAT THIS RELEASE IS FOR, AND THEREFORE WHAT STEP 6 CHECKS
#
# Published 0.55.0 carries API_DEFAULT = 'https://laserbrain-mcp.degibug.workers.dev'.
# That is a personal workers.dev subdomain, and it is what every `pip install laserbrain`
# has pointed at. 0.57.0 moves the default to https://api.phronesis.world, the API's own
# name. That single line IS this release.
#
# So step 6 reads API_DEFAULT out of the INSTALLED WHEEL, from site-packages, after cd'ing
# out of the source tree. Checking the tree would pass while shipping the old host, which
# is the same shape as the 0.12.0 failure recorded in publish-0.21.0.sh: a check that
# cannot fail in the situation it exists for.
set -euo pipefail
cd "$(dirname "$0")"

DIST=dist_0570
VERSION=0.57.0
WANT_HOST='https://api.phronesis.world'
WANT_GRAMMAR=1.21.0

echo "── laserbrain ${VERSION} → PyPI"
echo

# 1 · the artifacts exist
for f in "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" "${DIST}/laserbrain-${VERSION}.tar.gz"; do
  [ -f "$f" ] || { echo "  missing: $f"; echo "  run: python3 -m build --outdir ${DIST}"; exit 1; }
  printf "  ok  %s  (%s bytes)\n" "$(basename "$f")" "$(wc -c < "$f" | tr -d ' ')"
done

# 2 · the declared versions agree
PYPROJ=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
DUNDER=$(grep -m1 '^__version__' laserbrain/__init__.py | sed "s/.*'\(.*\)'.*/\1/")
if [ "$PYPROJ" != "$VERSION" ] || [ "$DUNDER" != "$VERSION" ]; then
  echo "  version mismatch: pyproject=${PYPROJ} __init__=${DUNDER} expected=${VERSION}"
  exit 1
fi
echo "  ok  version ${VERSION} in pyproject.toml and __init__.py"

# 3 · not already on PyPI. Upload is one-way.
if curl -sf "https://pypi.org/pypi/laserbrain/${VERSION}/json" >/dev/null 2>&1; then
  echo; echo "  ${VERSION} is ALREADY on PyPI. Bump the version first."; exit 1
fi
echo "  ok  ${VERSION} is not yet published"

# 4 · twine's own check
python3 -m twine check "${DIST}"/* >/dev/null 2>&1 \
  && echo "  ok  twine check" \
  || { echo "  twine check failed"; python3 -m twine check "${DIST}"/*; exit 1; }

# 5 · THE ARTIFACT CHECK. Diff the tree's exports against the installed wheel's.
TREE_ALL=$(python3 -c "import sys; sys.path.insert(0,'.'); import laserbrain as L; print(' '.join(sorted(L.__all__)))")
VENV=$(mktemp -d)/v
python3 -m venv "$VENV" >/dev/null 2>&1
"$VENV/bin/pip" install -q "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" >/dev/null 2>&1 \
  || { echo "  the built wheel does not install"; exit 1; }

# cd out of the source tree first: from here, `import laserbrain` finds ./laserbrain and
# every assertion below would pass while saying nothing about the wheel.
WHEEL_ALL=$( cd / && "$VENV/bin/python" -c "
import laserbrain as L
assert 'site-packages' in L.__file__, 'not the installed copy: ' + L.__file__
print(' '.join(sorted(L.__all__)))
" ) || { echo "  the wheel does not import"; exit 1; }

MISSING=$(comm -23 <(tr ' ' '\n' <<<"$TREE_ALL" | sort -u) <(tr ' ' '\n' <<<"$WHEEL_ALL" | sort -u) | tr '\n' ' ')
if [ -n "${MISSING// /}" ]; then
  echo
  echo "  ARTIFACT CHECK FAILED — the wheel is short of the tree."
  echo "    exported but not shipped: ${MISSING}"
  echo "    rebuild:  python3 -m build --outdir ${DIST}"
  echo
  echo "  This is what let 0.12.0 go out without Workflow and Store."
  exit 1
fi
TREE_N=$(wc -w <<<"$TREE_ALL" | tr -d ' ')
echo "  ok  wheel exports match the tree exactly (${TREE_N} symbols)"

# 6 · THE POINT OF THIS RELEASE. Read the default host out of the installed wheel.
( cd / && WANT_HOST="$WANT_HOST" WANT_GRAMMAR="$WANT_GRAMMAR" "$VENV/bin/python" - <<'PY'
import os, json, pathlib, laserbrain as L
assert 'site-packages' in L.__file__, 'not the installed copy: ' + L.__file__

want = os.environ['WANT_HOST']
got = getattr(L, 'API_DEFAULT', None)
assert got == want, f'API_DEFAULT is {got!r}, expected {want!r}'
assert 'workers.dev' not in (got or ''), f'still a personal subdomain: {got!r}'
print(f'  ok  API_DEFAULT in the wheel is {got}')

# the bundled grammar travels with it; the SDK is useless offline without it
g = pathlib.Path(L.__file__).parent / 'grammar.json'
assert g.exists(), 'grammar.json is not in the wheel'
v = json.loads(g.read_text()).get('laserbrain_grammar')
assert v == os.environ['WANT_GRAMMAR'], f'grammar is {v}, expected {os.environ["WANT_GRAMMAR"]}'
print(f'  ok  bundled grammar is {v}')
PY
) || { echo "  the shipped artifact is wrong for this release"; exit 1; }

# tidy the scratch venv; mktemp -d made it, nothing else lives there
/bin/rm -r -f "$VENV"

echo
echo "  This uploads permanently. ${VERSION} can never be reused."
read -r -p "  Type the version to confirm: " CONFIRM
[ "$CONFIRM" = "$VERSION" ] || { echo "  aborted"; exit 1; }

echo
echo "  Paste your PyPI API token (starts pypi-). Input is hidden."
read -rs -p "  token: " PYPI_TOKEN
echo
[ -n "$PYPI_TOKEN" ] || { echo "  no token, aborted"; exit 1; }

TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
  python3 -m twine upload "${DIST}"/*
unset PYPI_TOKEN

echo
echo "  published. verify from OUTSIDE the source tree:"
echo "    cd /tmp && python3 -m venv c && ./c/bin/pip install -q laserbrain==${VERSION}"
echo "    ./c/bin/python -c 'import laserbrain; print(laserbrain.API_DEFAULT)'"
echo "    expect: ${WANT_HOST}"
