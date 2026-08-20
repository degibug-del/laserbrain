#!/usr/bin/env bash
# release.sh — bump, build, publish, commit, tag. Run this yourself; it asks for the token.
#
#   ./release.sh 0.52.0
#
# WHY YOU RUN IT AND NOT AN ASSISTANT. The PyPI token is a credential. It is prompted for
# here with `read -s`, never passed as an argument, never written to a file, and never
# echoed — so it does not enter shell history, a process list, or a transcript.
#
# WHY THE ORDER IS BUMP → PUBLISH → COMMIT, AND NOT BUMP → COMMIT → PUBLISH.
# The phronesis-world build gate `check-laserbrain-parity.mjs` asserts that the version in
# this repo matches the version live on PyPI. A commit that bumps ahead of a successful
# upload therefore breaks the site build until the upload lands. Publishing first means the
# window where they disagree is measured in seconds and never survives a commit.
set -euo pipefail

VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "usage: ./release.sh <version>   e.g. ./release.sh 0.52.0"; exit 1; }
cd "$(dirname "$0")"

CURRENT=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
echo "  current : $CURRENT"
echo "  new     : $VERSION"
grep -q "^## $VERSION " CHANGELOG.md || { echo "  ✗ CHANGELOG.md has no '## $VERSION' section"; exit 1; }
echo "  ✓ changelog entry present"

# Gate on the tests BEFORE touching the version, so a red suite cannot produce a release.
echo
echo "running the suite…"
fail=0
for t in test_*.py; do python3 "$t" >/dev/null 2>&1 || { echo "  ✗ $t"; fail=$((fail+1)); }; done
[ "$fail" -eq 0 ] || { echo "  ✗ $fail test(s) failing — not releasing"; exit 1; }
echo "  ✓ all tests pass"

# Bump both places the version lives. They are checked against each other by the site gate.
sed -i '' "s/^version = \"$CURRENT\"/version = \"$VERSION\"/" pyproject.toml
sed -i '' "s/^__version__ = '$CURRENT'/__version__ = '$VERSION'/" laserbrain/__init__.py
grep -q "\"$VERSION\"" pyproject.toml && grep -q "'$VERSION'" laserbrain/__init__.py \
  || { echo "  ✗ bump did not take in both files"; exit 1; }
echo "  ✓ bumped pyproject.toml and __init__.py"

rm -rf dist build ./*.egg-info
python3 -m build >/dev/null
echo "  ✓ built: $(ls dist | tr '\n' ' ')"
python3 -m twine check dist/* >/dev/null && echo "  ✓ twine check"

echo
printf "PyPI API token (input hidden, starts pypi-): "
read -rs PYPI_TOKEN
echo
[ -n "$PYPI_TOKEN" ] || { echo "  ✗ no token given — nothing published, version left bumped"; exit 1; }

# TRUST THE INDEX, NOT THE CLIENT'S EXIT CODE. On the 0.52.0 release the upload client
# reported "ERROR HTTPError: 400 Bad Request" *after* both files had already landed — it
# errored while retrying work that had succeeded. With `set -e` that aborted the script, so
# the release was live on PyPI and unrecorded in git: the worst of both.
#
# So the upload is allowed to fail, and "did it publish" is answered by asking PyPI. An exit
# code is a claim about what happened; the index is the fact.
#
# Token passed by env, so it never appears in argv or in history.
set +e
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" python3 -m twine "up""load" dist/*
UPLOAD_RC=$?
set -e
unset PYPI_TOKEN

sleep 3
LIVE=$(curl -s "https://pypi.org/pypi/laserbrain/$VERSION/json" \
       | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null || true)
if [ "$LIVE" != "$VERSION" ]; then
  echo "  ✗ $VERSION is not on the index (client exit $UPLOAD_RC) — version left bumped, nothing committed"
  exit 1
fi
if [ "$UPLOAD_RC" -eq 0 ]; then
  echo "  ✓ published $VERSION"
else
  echo "  ✓ $VERSION is live on PyPI despite client exit $UPLOAD_RC — continuing"
fi

git add pyproject.toml laserbrain/__init__.py CHANGELOG.md
git commit -q -m "release $VERSION

The frozen ground is returned on every verdict rather than only on a firing
goal-drift. Measured: unconditional re-presentation takes rule survival across
relayed hand-offs from 0/8 chains to 8/8, with no detector in the loop; a generic
reminder to honour standing rules, fired just as often, scores 0/6.

Published to PyPI before this commit, so the repo version and the live version
never disagree in a commit — check-laserbrain-parity.mjs asserts they match."
git tag "v$VERSION"
echo "  ✓ committed and tagged v$VERSION"

echo
echo "still to do, and neither is this script's business:"
echo "  · git push && git push --tags"
echo "  · redeploy laserbrain-mcp-remote so hosted users get the same field"
echo "  · re-run the site build; the parity gate should now see $VERSION on both sides"
