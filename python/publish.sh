#!/usr/bin/env bash
# publish.sh — build, upload, and then VERIFY A FRESH INSTALL.
#
# The token is prompted for here and never written to disk, never exported into the
# environment, and never passed on a command line where it would land in shell history
# or a process list. Diego runs this; Claude does not handle the credential.
#
# The verify step exists because of 0.3.0: the PyPI JSON API reported the version as
# published while the wheel that actually installed was missing the async layer. The
# index is not the artefact. A release is not done until a clean venv can install it and
# import what it claims to ship.
set -euo pipefail
cd "$(dirname "$0")"

VERSION=$(python3 -c "import re,pathlib;print(re.search(r'version\s*=\s*\"([^\"]+)\"',pathlib.Path('pyproject.toml').read_text()).group(1))")
echo "  about to publish laserbrain ${VERSION}"

# A suite that cannot go red is not a suite. mutate.sh flips the constants the product
# forbids changing silently and fails if the tests stay green — on 2026-07-25 its --deep
# mode found 5 of 6 mutations surviving, meaning the calibration was protected by one
# pinned-value file and no behavioural test at all. A release where that is true again
# should not ship.
# THE TWO VERSIONS MUST AGREE.
#
# pyproject.toml names what PyPI records; __version__ is what `laserbrain version` tells a
# user and what lands in every audit record. Nothing tied them together, so they could ship
# apart — and the sibling package did exactly that hours before this was written:
# laserbrain-check went to npm as 0.1.2 while its CLI reported 0.1.1, so `--version` lied to
# everyone who ran it. Same trap, same day, caught here before it fired twice.
py_v=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
init_v=$(grep -m1 '__version__' laserbrain/__init__.py | sed "s/.*'\(.*\)'.*/\1/")
if [ "$py_v" != "$init_v" ]; then
  echo "  version gate — one number, two files"
  echo "    FAIL: pyproject.toml says $py_v, laserbrain/__init__.py says $init_v."
  echo "    Whichever is right, a release where they disagree makes --version lie."
  exit 1
fi

# WHAT SHIPS MUST CORRESPOND TO A COMMIT.
#
# laserbrain/** goes into the wheel — including grammar.json and attention.json, which are
# DATA the verdicts read. phronesis-world's prebuild runs sync-attention.mjs --recalibrate
# and writes attention.json into this package, so an ordinary website build silently
# changes a shipped data file. On 2026-08-10 a release was one keystroke from carrying a
# recalibration nobody had recorded.
#
# A wheel with no commit behind it cannot be reproduced or explained later, which matters
# more here than most places: this package's whole argument is that a reading is worth what
# its provenance is worth. Benign changes are still changes — commit them, then ship.
dirty=$(git status --porcelain -- laserbrain/ 2>/dev/null)
if [ -n "$dirty" ]; then
  echo "  provenance gate — what ships must correspond to a commit"
  echo "    FAIL: shipped files are modified but not committed:"
  echo "$dirty" | sed 's/^/      /'
  echo "    Commit them (or restore them) and run again — a wheel with no commit behind it"
  echo "    cannot be reproduced later, and attention.json is written by the site build."
  exit 1
fi

echo "  mutation gate — proving the suite can go red"
# CAPTURE THE CODE, DO NOT READ $? AFTER `if !`. Inside `if ! cmd; then`, $? is the status
# of the negation (always 0), not of cmd — so a `[ $? -eq 2 ]` there can never fire. Written
# that way first, and caught by running it rather than reading it.
mut_rc=0; ./mutate.sh >/dev/null 2>&1 || mut_rc=$?
if [ "$mut_rc" -eq 2 ]; then
  # Red before a single mutation was applied: nothing was measured. Reporting that as
  # "a mutation survived" names the wrong cause — it cost a wrong diagnosis on 2026-08-10,
  # sending a search after the mutation set when one test file was failing.
  echo "    FAIL: the suite is red BEFORE mutation — nothing was measured."
  echo "    Run ./mutate.sh to see which file."
  exit 1
elif [ "$mut_rc" -ne 0 ]; then
  echo "    FAIL: a mutation survived. Run ./mutate.sh to see which."
  exit 1
fi
./mutate.sh --deep >/dev/null 2>&1 || { echo "    FAIL (deep): a mutation survives without test_frozen.py."; echo "    The constants are pinned but not watched by behaviour. Run ./mutate.sh --deep."; exit 1; }
echo "    ok — every mutation caught, with and without the pin"

echo "  running the suite first — a red suite is not a release"
# ISOLATED, because a release must not write into the live corpus. Every suite here spawns
# servers and builds Harnesses, and without a private root they land in ~/.config/laserbrain
# — 85 fixture contexts arrived that way from the 0.44.0 publish alone, into the same corpus
# every published threshold is measured from. run-tests.sh has done this since 2026-08-05;
# this loop predates it and was still writing to $HOME.
LASERBRAIN_HOME="$(mktemp -d "${TMPDIR:-/tmp}/laserbrain-publish-XXXXXX")"
export LASERBRAIN_HOME
mkdir -p "$LASERBRAIN_HOME/config" "$LASERBRAIN_HOME/sessions"
# Every test_*.py, discovered rather than a list typed once and left behind. Found on
# 2026-07-31: this loop named ten files by hand while the repo held thirty-one, so
# test_operator.py, test_operator_harness.py and test_nova.py — the ones covering the
# Operator/phronesis join — had never once been run by this gate. A red suite is not a
# release, but neither is a suite nobody is actually running.
for f in test_*.py; do
  t="${f%.py}"
  printf "    %-24s " "$t"
  python3 "$f" >/dev/null 2>&1 && echo pass || { echo FAIL; exit 1; }
done

rm -rf dist build ./*.egg-info
python3 -m build >/dev/null
echo "  built: $(ls dist | tr '\n' ' ')"

read -rsp "  PyPI token (input hidden): " TOKEN; echo
[ -z "$TOKEN" ] && { echo "  no token, nothing uploaded"; exit 1; }

TWINE_USERNAME=__token__ TWINE_PASSWORD="$TOKEN" python3 -m twine upload dist/* 
unset TOKEN

# The index propagates on its own schedule. A fixed sleep guessed at it and guessed
# wrong on the 0.4.0 release — the upload had succeeded and the check reported failure.
# Poll until it appears, and only then decide anything.
TMP=$(mktemp -d)
python3 -m venv "$TMP/venv"
echo "  waiting for the index (polling, not guessing)"
for i in $(seq 1 12); do
  if "$TMP/venv/bin/pip" install --quiet --no-cache-dir "laserbrain==${VERSION}" 2>/dev/null; then
    echo "  appeared on attempt $i"; break
  fi
  [ "$i" = 12 ] && { echo "  ✗ never appeared after 12 tries — check PyPI by hand"; rm -rf "$TMP"; exit 1; }
  sleep 10
done
"$TMP/venv/bin/python" - <<PYEOF
import laserbrain
from laserbrain import Calibration, PUBLISHED, Harness
from laserbrain.observe import Observer
from laserbrain.vocab import embedding_similarity
assert laserbrain.__version__ == "${VERSION}", laserbrain.__version__
assert PUBLISHED.is_published and PUBLISHED.goal_min == 0.30
h = Harness(); h.check(goal='a b c', progress='advancing', distance=5)
assert h.check(goal='x y z', progress='advancing', distance=5).reason == 'goal-drift'
o = Observer('a b c'); assert o.state()['distance'] is None
print("  ✓ fresh install of ${VERSION} imports Calibration, observe and vocab, and detects drift")
PYEOF
rm -rf "$TMP"
echo "  published and verified against a clean environment, not against the index"

# ── REGENERATE THE SITE'S DRIFT VECTORS ─────────────────────────────────────────────────
#
# workers/laserbrain-mcp-remote/drift-vectors.json is stamped with the SDK version that
# produced it, and phronesis-world's check-laserstore compares that stamp against
# laserbrain-sdk/pyproject.toml. So the moment a release bumps the version, the vectors are
# a fossil — and check-drift-parity.ts goes on printing "drift.ts agrees with the Python
# instrument" while reading them, which is the sentence that made it a defect rather than
# staleness. It shipped the period-4 divergence on 2026-07-27.
#
# It broke the site build twice on 2026-08-06 alone, once per release, each time caught by
# the gate and fixed by hand. A gate that fires every release is telling you the release is
# missing a step.
#
# LAST, AND NEVER FATAL. The upload above is irreversible; a site artifact must not be able
# to fail a publish that already succeeded. If this cannot run — no site repo on this
# machine, no python, generator moved — it says so and exits 0, and the build gate is still
# there to catch it the old way.
#
# `import laserbrain` resolves to the editable install in this directory, so the vectors are
# generated from the working tree that was just published rather than from the index. That
# is what makes running it here correct instead of merely convenient.
GEN="$HOME/phronesis-world/workers/laserbrain-mcp-remote/gen-drift-vectors.py"
echo
if [ ! -f "$GEN" ]; then
  echo "  drift vectors: skipped — no $GEN on this machine"
  echo "  regenerate wherever phronesis-world lives, or the next site build will fail"
else
  echo "  regenerating the site's drift vectors for ${VERSION}"
  if python3 "$GEN" 2>&1 | sed 's/^/    /'; then
    echo "    ✓ commit workers/laserbrain-mcp-remote/drift-vectors.json in phronesis-world"
  else
    echo "    ✗ regeneration failed — the publish itself is fine and complete."
    echo "      Run it by hand before the next site build:"
    echo "      python3 $GEN"
  fi
fi
