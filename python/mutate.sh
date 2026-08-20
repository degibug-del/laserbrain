#!/usr/bin/env bash
# mutate.sh — a suite that cannot go red is not a suite.
#
# Every gate this project wrote passed something broken until it was mutation-tested:
#
#   the Python suite   goal_min 0.30 -> 0.45 changed NOTHING; weights reshuffled, nothing
#   drift-parity (TS)  the threshold could move anywhere inside 0.30..0.45 undetected
#   the Swift parity   a dropped stopword and a moved stem boundary each changed NOTHING
#   check-contrast     exempted hues, so a 1.97:1 call-to-action shipped green
#
# In every case the tests were green and the instrument was unprotected. Green is a claim
# about the tests, not about the code, and the only way to earn it is to break the code on
# purpose and watch the tests notice.
#
# This does that mechanically. Each mutation below changes ONE thing the product forbids
# changing silently. If the suite still passes, the suite is not watching that thing, and
# this exits non-zero.
#
#   ./mutate.sh          run every mutation
#   ./mutate.sh --deep   run them WITHOUT test_frozen.py
#   ./mutate.sh --list   show them without running
#
# --deep is the interesting mode. test_frozen.py pins the constants by value, so it
# catches every constant mutation by construction — a green run only proves that file
# exists. Excluding it asks the sharper question: does any test notice the CHANGE IN
# BEHAVIOUR, or is the instrument protected by one assertion of its own numbers? Both
# guarantees are worth having and they are not the same thing.
set -uo pipefail
cd "$(dirname "$0")"

SRC_PY=laserbrain/__init__.py
BAK_PY=$(mktemp)
cp "$SRC_PY" "$BAK_PY"

SRC_JSON=laserbrain/grammar.json
BAK_JSON=$(mktemp)
cp "$SRC_JSON" "$BAK_JSON"

restore() { cp "$BAK_PY" "$SRC_PY"; cp "$BAK_JSON" "$SRC_JSON"; }
trap restore EXIT

# name | sed expression | why it must be caught | file (py or json)
#
# Fixing the sed text to match 0.5.0's _D.get('goal_min', 0.30) refactor (see git blame)
# only got the patterns matching again — it did not make them mean anything. _D is built
# as `_G.get('calibration') or {}`, and _G is grammar.json. For every key grammar.json's
# calibration section actually sets — goal_min, self_report_min, stall_window, the three
# weights — the literal inside .get(key, LITERAL) is a fallback for a key that is never
# missing, so mutating it changes nothing that runs. Proved live: sed'ing the Python
# literal left test_frozen.py green; sed'ing the SAME value in grammar.json failed it in
# the same run. Only echo_min and dialogue_window are absent from grammar.json's
# calibration, so those two are the only ones the Python literal still governs.
MUTATIONS=(
  "goal threshold 0.30 -> 0.45|s/\"goal_min\": 0.3,/\"goal_min\": 0.45,/|the drift boundary is the product; moving it must never be silent|json"
  "goal weight 0.5 -> 0.2|s/\"goal\": 0.5,/\"goal\": 0.2,/; s/\"progress\": 0.2/\"progress\": 0.5/|Φ is reported against fixed thresholds; reweighting rescales every verdict|json"
  "self-report floor 0.15 -> 0.40|s/\"self_report_min\": 0.15,/\"self_report_min\": 0.40,/|a raised floor silently stops honouring the agent's own stuck report|json"
  "stall window 4 -> 9|s/\"stall_window\": 4,/\"stall_window\": 9,/|a wider window means a stall is reported far later, or never|json"
  "echo floor 0.25 -> 0.90|s/_D.get('echo_min', 0.25)/_D.get('echo_min', 0.90)/|teams stop detecting echo-spiral entirely|py"
  "detection disabled|s/if anchor < self.cal.goal_min:/if anchor < -1.0:/|the control: if THIS is not caught, nothing is wired up at all|py"
)

if [ "${1:-}" = "--list" ]; then
  printf '  %s\n' "${MUTATIONS[@]%%|*}"; exit 0
fi

# ── PRIVATE STATE ROOT, and this file needs it more than any other ──────────────────────
#
# This script runs the ENTIRE suite once per mutation, twice over (--deep repeats it), on
# deliberately broken constants. It is the single most pathological writer in the repo, and
# it was writing all of it into ~/.config/laserbrain — the corpus every published threshold
# is measured from.
#
# FOUND 2026-08-06 by test_corpus_clean, after the 0.45.0 release put 84 fixture contexts
# back into a corpus that had been quarantined clean four hours earlier. publish.sh was
# blamed and fixed the night before; the fix set LASERBRAIN_HOME at line 34 and this script
# is called from line 24. Ten lines too late, so the gate that runs first ran unprotected
# and undid the cleaning of the gate that runs second. 82 of the 84 were contexts I had
# already quarantined once.
#
# THE LESSON, which is why the export lives HERE and not in the caller: isolating a script
# from outside protects only the call sites someone remembered. A script that writes state
# should carry its own root, so it is isolated however it is invoked — by publish.sh, by
# run-tests.sh, or by hand.
#
# Deferring to an existing LASERBRAIN_HOME keeps it composable: under run-tests.sh the run
# shares that root rather than fragmenting into one per script.
if [ -z "${LASERBRAIN_HOME:-}" ]; then
  LASERBRAIN_HOME="$(mktemp -d "${TMPDIR:-/tmp}/laserbrain-mutate-XXXXXX")"
  export LASERBRAIN_HOME
  mkdir -p "$LASERBRAIN_HOME/config" "$LASERBRAIN_HOME/sessions"
fi

# Was a hand-written 11-file list. It stopped covering 19 of the 30 test_*.py files in
# this directory, silently — test_operator.py and test_mcp_server.py included — for the
# same reason publish-0.29.0.sh stopped naming symbols: a hardcoded list can never contain
# the thing you just added. Every mutation here was still "caught" or "survived" against a
# suite ten files smaller than the one that actually exists.
ALL_TESTS=()
for f in test_*.py; do ALL_TESTS+=("${f%.py}"); done
SUITE=("${ALL_TESTS[@]}")

DEEP=0
if [ "${1:-}" = "--deep" ]; then
  DEEP=1
  # drop test_frozen: what is left is behaviour, not a pinned value
  SUITE=()
  for t in "${ALL_TESTS[@]}"; do
    [ "$t" = "test_frozen" ] || SUITE+=("$t")
  done
fi

run_suite() {
  # echo_min's mutation showed "caught" standalone and "SURVIVED" only inside this loop —
  # same file, same md5, confirmed by print. The running process still reported echo_min
  # as 0.25, the PRISTINE value: test_frozen.py was importing a cached __pycache__/*.pyc
  # compiled before the sed, because restore()+sed()+import all landed inside one mtime
  # tick. A manual run always has enough wall-clock gap between the edit and the import to
  # dodge this; the loop doesn't. Clearing the cache before every subprocess removes the
  # gap it depends on. JSON mutations were never at risk — grammar.json isn't compiled.
  find . -maxdepth 3 -path '*/__pycache__/*' -type f -delete 2>/dev/null
  # THE WHOLE SUITE IS A TEST HARNESS, NOT A SESSION. current-arm.json is machine-global,
  # so any test that drives the real mcp-server inherits whichever arm the human's live
  # agent is in — and a blinded check_state returns no reading at all, which reads as a
  # parity failure. That cost a blocked release on 2026-08-10, diagnosed as a surviving
  # mutation when the suite was simply red. Set here rather than per-test so a test added
  # next month is covered without anyone remembering this.
  for t in "${SUITE[@]}"; do
    LASERBRAIN_ARM=open python3 "$t.py" >/dev/null 2>&1 || return 1
  done
  return 0
}

[ "$DEEP" = "1" ] && echo "  DEEP: running without test_frozen.py — behaviour only" && echo
echo "  baseline: the suite must be GREEN before anything is mutated"
if ! run_suite; then
  echo "  ✗ the suite is already failing — fix that before mutation testing means anything"
  # EXIT 2, NOT 1. A red baseline and a surviving mutation are different failures with
  # different fixes, and publish.sh reported both as "a mutation survived" — which sent a
  # diagnosis off after the mutation set while the real cause was one red test file.
  exit 2
fi
echo "  ✓ green"
echo

survived=0
for m in "${MUTATIONS[@]}"; do
  name=${m%%|*}; rest=${m#*|}
  expr=${rest%%|*}; rest=${rest#*|}
  why=${rest%%|*}; file=${rest#*|}
  if [ "$file" = "json" ]; then TARGET=$SRC_JSON; TBAK=$BAK_JSON; else TARGET=$SRC_PY; TBAK=$BAK_PY; fi
  restore
  sed -i '' "$expr" "$TARGET"
  if cmp -s "$TARGET" "$TBAK"; then
    echo "  ⚠ $name — the mutation did not apply; the code it targets has moved"
    survived=$((survived + 1)); continue
  fi
  if run_suite; then
    echo "  ✗ SURVIVED: $name"
    echo "      $why"
    survived=$((survived + 1))
  else
    echo "  ✓ caught: $name"
  fi
done
restore

echo
if [ "$survived" -gt 0 ]; then
  echo "  $([ "$DEEP" = 1 ] && echo "DEEP RESULT" || echo "FAIL") — $survived mutation(s) survived."
  if [ "$DEEP" = "1" ]; then
    echo "  These constants are pinned by test_frozen.py but NOT watched by any behavioural"
    echo "  test. That is a real gap: change one and only the pin notices, so the pin is the"
    echo "  entire protection. Worth a behavioural test each, or worth knowing."
    exit 1
  fi
  echo "  The suite is green on code it does not watch."
  echo "  Add a test that fails for each, or accept that the instrument is unprotected there."
  exit 1
fi
echo "  ok    every mutation was caught — the suite is watching what it claims to watch"
