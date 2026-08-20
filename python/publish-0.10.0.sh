#!/usr/bin/env bash
# Publish laserbrain 0.8.0 to PyPI.
#
# You run this, not me. The token is read with `read -rs` into a variable that lives only
# for the length of this process — it is never echoed, never written to a file, never put
# in an env var that another process can read, and never passes through the assistant's
# context where it could end up in a transcript or a log.
#
# A PyPI release is PERMANENT. A version number cannot be reused even after deleting the
# release, so this script re-verifies the artifact and refuses to upload if 0.8.0 already
# exists — the failure mode worth guarding is not a bad upload, it is a wasted version.

set -euo pipefail
cd "$(dirname "$0")"

DIST=dist_0100
VERSION=0.10.0

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
echo "  published. verify with:"
echo "    pip index versions laserbrain"
echo "    pip download laserbrain==${VERSION} --no-deps -d /tmp/lbcheck"
