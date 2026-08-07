#!/usr/bin/env python3
"""A budget stops a run by counting, not by judging.

WHY, 2026-08-06

Every other judgment reasons about the WORK — is it reachable, is it the right problem, is
the goal too large — and each can be wrong. The published precision on individual fires is
9-14.6%. laserbrain has been attempting the STOPPING decision with those: `abandon` says
"this is not reachable" on a 1-in-7 hit rate.

Prime Intellect's harness, read the same day, does not do that. Continuation is decided by
external quality gates plus maxTurns / maxTokens / maxContinuations, and the agent's own
opinion is never consulted:

    "Do not end the session yourself; the verifier/evaluator decides completion."

A budget cannot be wrong the way a verdict can. It is a count against a number the caller
chose. It needs no evidence, no three-check warm-up and no interpretation, which is exactly
why it belongs ABOVE every judgment rather than beside them.

WHAT THIS PINS

  off by default        `Calibration()` is the published instrument and must not change.
                        This is the assertion that matters most: a calibration that silently
                        alters behaviour for existing callers is the one thing it must never
                        do.
  fires on the count    at max_checks, not before, not after
  outranks judgment     a run that would earn `abandon` at 12 reports over-budget at 8
  both surfaces         the SDK and the server, because a verdict on one and not the other is
                        the `unbacked` mistake — shipped to the package alone and unable to
                        fire for the agent that wrote it

THE COST OF OFF-BY-DEFAULT is named rather than hidden: an optional mechanism nobody switches
on is worth nothing, which is what happened to `saw()` — built, shipped, and called by almost
nothing, so `anchored` sat broken for its whole life with nothing depending on it enough to
notice. If this is still unarmed in a month, that is the finding.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault('LASERBRAIN_HOME', tempfile.mkdtemp(prefix='lb-budget-'))
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import Calibration, Harness                        # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def run(n, cal=None):
    h = Harness(calibration=cal) if cal else Harness()
    for _ in range(n):
        h.check('ship the thing', 'advancing', 6)
    return h.phronesis()


print('the published instrument is unchanged\n')
check('no budget by default', Calibration().max_checks is None,
      repr(Calibration().max_checks))
check('  a long flat run still earns abandon', run(14)['verdict'] == 'abandon',
      run(14)['verdict'])

print()
print('armed, it fires on the count')
cal = Calibration(max_checks=5)
before = run(4, cal)['verdict']
at = run(5, cal)['verdict']
after = run(9, cal)['verdict']
check('not before the budget', before != 'over-budget', before)
check('exactly at the budget', at == 'over-budget', at)
check('and after it', after == 'over-budget', after)

print()
print('and it outranks the judgments, because a count is not an assessment')
j = run(14, Calibration(max_checks=8))
check('over-budget beats abandon', j['verdict'] == 'over-budget', j['verdict'])
check('  and says so in words', 'count, not an assessment' in j['because'], j['because'][:56])

print()
print('the server can reach it too — a verdict on one surface only is the `unbacked` bug')
src = (HERE / 'mcp-server.mjs').read_text()
check("mcp-server.mjs holds 'over-budget'", "verdict = 'over-budget'" in src)
check('  and reads its budget from the grammar', '_CAL.max_checks' in src)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a number can stop a run, and it does not need to be right to be true.')
