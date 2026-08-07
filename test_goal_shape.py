#!/usr/bin/env python3
"""A goal that narrates is a malformed input, and saying so must not move a verdict.

THE MEASUREMENT BEHIND THIS FILE

Precision on clearly-labelled fires stood at 14.6% — 7 useful against 41 false — and 82%
of every fire was goal-drift. Reading the false ones showed why, and it was not the
grammar:

    "Confirmed all 31 test files pass locally and only 10 were gated in publish.sh."
    "Promoted new-repo.json and repo-surgery.json to shipped laserbrain/workflows/."
    "Build blocked by a stale gate unrelated to the portfolio edit."
    "Diego chose verdict outcome capture: record whether a fired verdict was right."

Those are status reports in the goal slot. Each step narrates a different fact, so
consecutive grounds share almost no tokens, overlap collapses, and goal-drift fires
correctly on a sentence that was never capable of staying fixed.

Across 1,191 readings a narration-shaped goal separates fires from quiet readings at
12.2% vs 2.2% — 5.4x, z = 6.87.

WHAT IT DOES NOT SHOW, which is why nothing here changes a score

Narration predicts a fire. It does not predict a WRONG fire: 19.5% of the false labels
against 14.3% of the useful, and there are seven useful labels. So the intervention is at
the input, where the evidence is, and not at the verdict, where it is not.
"""
import pathlib
import sys
import tempfile

# ONE STATE ROOT — a private tree, so this suite cannot write into the live corpus.
#
# It could, and it did. On 2026-08-05 the live drift log held 2,644 rows of which 1,058 —
# 40% — were written by suites spawning the server against the real ~/.config/laserbrain.
# Synthetic runs are pathological ON PURPOSE (flat distance, repeated goals, abandon bait),
# so they do not dilute the corpus evenly: `stalled` is 39.7% of the test rows against 3.2%
# of the real ones, which makes the whole-log rate 5.6x the truth. Every threshold ever read
# off this log was read off that mixture.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain.runtime import (Session, is_groundable,           # noqa: E402
                                reads_as_report)

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


REPORTS = [
    'Confirmed all 31 test files pass locally',
    'Promoted new-repo.json to shipped laserbrain/workflows/',
    'Build blocked by a stale gate unrelated to the portfolio edit',
    'Fixed the stale drift-vectors.json fixture',
    'Pushed the mid-turn detection fix to lasergear',
    'Reviewed all three repos, changes are today\'s work',
]
# Real grounds from this project's own history. Several are two words, which is why
# is_groundable refuses to impose a length rule.
GOALS = [
    'build the parser',
    'Add CLI parity for the store: laserbrain store list/find/vend',
    'Redesign the phronesis home page',
    'read auth.py',                 # past and present are spelled the same
    'Speed up the build',           # ends in -ed, is not a report
    'Need to fix the parser',       # ditto
    'fix them',
    'publish',
    'map all',
]

print('a report is recognised')
for g in REPORTS:
    check(f'{g[:52]}', reads_as_report(g))

print()
print('and a goal is not — including the three that broke the naive /^\\w+ed\\b/')
for g in GOALS:
    check(f'{g[:52]}', not reads_as_report(g))

print()
print('the empty and absent cases do not throw')
for g in ('', None, '   '):
    check(f'{g!r} is not a report', not reads_as_report(g or ''))

print()
print('NOTHING IS REJECTED — is_groundable is untouched')
# The restraint is deliberate: refusing a narration-shaped goal would leave the session
# with no ground at all, which is worse than grounding on an awkward string.
for g in REPORTS:
    check(f'still groundable: {g[:40]}', is_groundable(g))

print()
print('the advice reaches the agent, and only when it applies')
with tempfile.TemporaryDirectory() as d:
    s = Session('r', goal='Confirmed all 31 test files pass locally', directory=d)
    note = s.goal_shape_note()
    check('a narrating ground produces a note', bool(note))
    check('  and it quotes the ground back', note and 'Confirmed all 31' in note)
    check('  and says what to do instead', note and 'State the goal as' in note)

    s2 = Session('g', goal='build the parser', directory=d)
    check('an ordinary ground produces none', s2.goal_shape_note() is None,
          str(s2.goal_shape_note()))
    s3 = Session('n', directory=d)
    check('no ground at all produces none', s3.goal_shape_note() is None)

print()
print('and it rides the nudge rather than firing on its own')
with tempfile.TemporaryDirectory() as d:
    s = Session('x', goal='Confirmed all 31 test files pass locally', directory=d,
                nudge_after=2)
    check('silent before the nudge is due', s.nudge() is None)
    for _ in range(2):
        s.tool('Bash', {'command': 'ls'})
    n = s.nudge()
    check('the nudge carries the note', bool(n) and 'reads as a report' in n,
          (n or 'no nudge')[:60])
    check('  and still carries the coverage reminder', bool(n) and 'check_state' in n)

print()
print('NO VERDICT MOVED — the corpus stays comparable')
# If narration ever reaches a verdict, every reading taken before it becomes incomparable
# with every one after, and nothing in the data would say so.
with tempfile.TemporaryDirectory() as d:
    a = Session('a', goal='Confirmed all 31 test files pass locally', directory=d)
    b = Session('b', goal='build the parser', directory=d)
    for s in (a, b):
        s.check(s.d['goal'], 'advancing', 5, True, reason='goal-drift', phi=0.6)
    check('a narrating ground still records the fire it was given',
          a.d['checks'][-1]['drifting'] is True and a.d['checks'][-1]['reason'] == 'goal-drift',
          str(a.d['checks'][-1].get('reason')))
    check('  identically to an ordinary one',
          a.d['checks'][-1]['drifting'] == b.d['checks'][-1]['drifting']
          and a.d['checks'][-1]['reason'] == b.d['checks'][-1]['reason'])
    check('  and no shape flag leaked into the record',
          'reads_as_report' not in a.d['checks'][-1] and 'report' not in a.d['checks'][-1],
          str(sorted(a.d['checks'][-1].keys())))

print()
print('PARITY — the JS harness carries the same list, or it carries a different rule')
# Two hand-maintained copies of one list drift by construction. This project already holds
# five normalisers across three languages in parity for that reason, and the same argument
# applies to a rule an agent reads on every step. Compared as SETS of verbs: the two
# regexes are written in different dialects and only the vocabulary has to agree.
import re                                                        # noqa: E402

from laserbrain.runtime import _REPORT_RE                        # noqa: E402

JS = pathlib.Path(__file__).resolve().parent / 'mcp-server.mjs'
def verbs(s):
    """The vocabulary inside a report regex, in either dialect.

    Pulls words rather than splitting on delimiters: splitting left "(?:confirmed" glued to
    its group prefix in the Python source and dropped `confirmed` from one side only,
    which read as a parity break that was not one.
    """
    return {w for w in re.findall(r'[a-z]{3,}', s)} - {'blocked', 'failed'}
py_verbs = verbs(_REPORT_RE.pattern)

if not JS.exists():
    check('mcp-server.mjs present', False, 'cannot check parity without it')
else:
    m = re.search(r'const REPORT_RE = new RegExp\((.*?), *.i.\)', JS.read_text(), re.S)
    check('the JS list is findable', bool(m))
    if m:
        js_verbs = verbs(m.group(1))
        check('every Python report verb is in the JS list', not (py_verbs - js_verbs),
              f'missing from JS: {sorted(py_verbs - js_verbs)[:6]}')
        check('  and every JS one is in Python', not (js_verbs - py_verbs),
              f'missing from Python: {sorted(js_verbs - py_verbs)[:6]}')
        check(f'  ({len(py_verbs)} verbs held in both)', len(py_verbs) >= 30,
              str(len(py_verbs)))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — narration is named where it can be fixed, and nowhere else.')
