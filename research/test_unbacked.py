#!/usr/bin/env python3
"""Half of Φ is the agent's own account of itself. Something has to say so.

THE GAP

`anchored` is 0.5 on the published calibration: the goal term is external — the ground is
frozen at first call and cannot be revised — and `distance` and `progress` are whatever the
agent typed. It has been reported on every verdict since it was added and read by nothing.

So an agent that simply reports its distance falling keeps Φ low while doing no work at
all, and collects `advancing` the whole way. That is not a hypothetical; it is what the
metric permits by construction.

`verify` already covers the neighbouring case — the observed trace DISAGREES with the
self-report. This covers the case where there is nothing to agree with: work was observed
in this run, so the machinery is live, and yet not one check had its report backed by it.

UNINSTRUMENTED IS NOT UNBACKED, which is the whole reason for `saw_any`. A harness used
bare — every test in this repo, and any user who skips an optional API — has zero
corroborations for a reason that says nothing about the agent. An instrument that cannot
tell those apart must stay quiet, so the rule requires that something was observed at
least once before it will speak.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                    # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


print('a bare harness is never accused — nothing was observed, so nothing is claimed')
h = Harness()
for d in (9, 8, 7, 6, 5, 4):
    h.check('ship the CSV export', 'advancing', d)
j = h.phronesis()
check('no unbacked verdict without instrumentation', j['verdict'] != 'unbacked',
      f"{j['verdict']} — uninstrumented must not read as dishonest")

print()
print('but an instrumented run that never corroborates IS told')
# ok=False is the point. Corroboration is "something was observed AND nothing observed
# failed outright", so a run whose every observed call FAILED has the machinery live and
# zero backing — while the agent reports its distance falling anyway. That is a sharper
# case than "nothing observed" and it is the one that actually occurs: the work is
# happening, it is not working, and the self-report says otherwise.
h2 = Harness()
for d in (9, 8, 7, 6, 5, 4):
    h2.saw('tool', 'Bash', ok=False)
    h2.check('ship the CSV export', 'advancing', d)
j2 = h2.phronesis()
print(f"    corroborated {h2._run.corroborated} of {len(h2._run.trace)}")
check('a run whose observed work all failed fires unbacked',
      j2['verdict'] == 'unbacked', f"{j2['verdict']} — {j2['because'][:88]}")
check('  and the counsel says what to do about it',
      'read the output' in j2['counsel'].lower(), j2['counsel'][:70])

print()
print('a run that is genuinely backed is not accused')
h3 = Harness()
for d in (9, 8, 7, 6, 5, 4):
    h3.saw('tool', 'Bash', ok=True)
    h3.check('ship the CSV export', 'advancing', d)
j3 = h3.phronesis()
check('corroborated work gets no unbacked verdict', j3['verdict'] != 'unbacked',
      f"{j3['verdict']} · corroborated {h3._run.corroborated}")

print()
print('and a run claiming NO progress is not accused either — there is no claim to back')
h4 = Harness()
for _ in range(6):
    h4.saw('tool', 'Read', ok=True)
    h4.check('ship the CSV export', 'advancing', 7)
j4 = h4.phronesis()
check('flat distance does not read as unbacked', j4['verdict'] != 'unbacked',
      f"{j4['verdict']} — that is a stall question, not an honesty one")

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the half of Φ that is self-report now has a verdict, and it stays silent')
print('  where silence is the only honest answer.')
