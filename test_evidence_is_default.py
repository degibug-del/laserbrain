#!/usr/bin/env python3
"""The observed channel fills itself when a runtime is attached, and stays quiet when not.

WHY, 2026-08-06

`saw()` was built so a self-report could be corroborated by observed work, shipped, and then
called by almost nothing. The cost was not an unused feature. `anchored` sat structurally
broken for its entire life — returning 0.5 forever — and nobody noticed, because nothing
depended on it enough to look. An opt-in mechanism is a mechanism that is off, and that was
said out loud when `max_checks` shipped one release earlier: *if this is still unarmed in a
month, that is the finding.*

The information was never missing. `runtime.Session` has recorded every tool call and its
outcome the whole time; it simply had no wire to the harness's evidence channel. Two halves
of one package that did not talk. This is that wire, and the default it inverts is: assume
nothing is observed unless the caller remembers to say so -> observe whatever the runtime
already knows.

THE TWO FAILURES IT MUST NOT HAVE, which pull in opposite directions:

  false credit        a counter carrying thousands of outcomes from earlier work must not
                      make a run that does nothing look corroborated. Corroboration is an
                      ADVANCE between two checks, never a total.

  false accusation    an ordinary Harness with no runtime attached must not read as
                      dishonest. `unbacked` says "you claim progress and nothing backs it";
                      said to someone who never installed the backing channel it is simply
                      wrong. The first version of this file's subject broke exactly that:
                      the counter is shared across the machine, so a Harness in one process
                      saw counts written by another and reported itself instrumented. Caught
                      by test_unbacked, which exists for that one sentence — uninstrumented
                      is not the same as unbacked.

The rule that satisfies both: the channel is live for a run only if it advanced DURING that
run. A count already present when the run began proves nothing about it.
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault('LASERBRAIN_HOME', tempfile.mkdtemp(prefix='lb-evidence-'))
sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                      # noqa: E402
from laserbrain.runtime import Session                              # noqa: E402
import laserbrain._evidence as _evidence                            # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def run(session=None, n=6, ok=True, goal='ship the thing'):
    h = Harness()
    for i in range(n):
        if session is not None:
            session.tool('Bash', {'command': 'npm test'}, ok=ok)
        h.check(goal, 'advancing', 9 - i)
    return h.phronesis()


print('a runtime fills the channel without anyone calling saw()\n')
p = run(Session('run-fed', goal='ship the thing'), goal='fed by a runtime')
check('the channel reads live', p['control']['observed'] is True)
check('  and every check is corroborated', p['scores']['evidence'] == 1.0,
      f"evidence={p['scores']['evidence']}")
check('  so control proceeds on observed work, not on the typed number',
      p['control']['decision'] == 'proceed'
      and 'corroborated by observed work' in p['control']['because'],
      p['control']['because'][:56])

print()
print('and a bare Harness stays quiet — uninstrumented is not dishonest')
q = run(None, goal='no runtime at all')
check('the channel reads dark', q['control']['observed'] is False)
check('  and no verdict accuses it', q['verdict'] != 'unbacked', q['verdict'])
check('  and the reason names the absence rather than implying an all-clear',
      'absence of a signal' in q['control']['because'])

print()
print('a counter from earlier work lends this run nothing')
# The file is shared with lasermind/mcp-server.mjs by design — one observed channel per
# machine. That is exactly why a total cannot be evidence: most of it belongs to somebody
# else's run.
before = _evidence.count()[0]
for _ in range(500):
    _evidence.bump(ok=True)
check(f'the counter really is loaded ({before} -> {_evidence.count()[0]})',
      _evidence.count()[0] >= before + 500)
r = run(None, goal='rich counter, idle run')
check('a run that observes nothing is still dark', r['control']['observed'] is False,
      f"observed={r['control']['observed']}")
check('  and earns no corroboration', r['scores']['evidence'] == 0.0,
      f"evidence={r['scores']['evidence']}")

print()
print('and work that FAILS is observed but does not corroborate')
f = run(Session('run-red', goal='ship the thing'), ok=False, goal='everything failing')
check('the channel is live', f['control']['observed'] is True)
check('  but nothing is corroborated', f['scores']['evidence'] == 0.0,
      f"evidence={f['scores']['evidence']}")
check('  and control asks for verification rather than proceeding',
      f['control']['decision'] == 'verify', f['control']['decision'])

print()
print('the scores field reports the run, not the empty moment phronesis is called in')
# It used to call _anchor() a second time, here, and _anchor answers "was the interval since
# the LAST CHECK observed" — an interval that is empty by construction, because phronesis
# runs after the last check. So it returned 0.5 on a run with 6 of 6 corroborated, and
# incremented `checks` while doing it, inflating the denominator of the rate it should have
# been reporting. Same shape as the server's anchored() memo bug.
h = Harness()
s = Session('run-rate', goal='ship the thing')
for i in range(4):
    s.tool('Bash', {'command': 'npm test'}, ok=True)
    h.check('half and half', 'advancing', 9 - i)
for i in range(4):
    h.check('half and half', 'advancing', 5 - i)        # no observed work behind these
p2 = h.phronesis()
check('a half-corroborated run reports about half', 0.35 <= p2['scores']['evidence'] <= 0.65,
      f"evidence={p2['scores']['evidence']}")
check('  and phronesis did not add a check that never happened',
      h._run.checks == 8, f'checks={h._run.checks}, expected 8')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the channel fills itself, credits only what happened during the run,')
print('  and accuses nobody for never having attached it.')
