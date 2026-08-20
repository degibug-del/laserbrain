#!/usr/bin/env python3
"""`wrong-problem` may only COMMAND when something independent agrees.

    python3 test_corroboration.py

WHY. On 2026-08-16 this verdict told an agent "You are not solving what you set out to
solve" while it was solving exactly that. A subagent's reset_task had destroyed the
parent's ground, so the parent's byte-identical goal string scored 0.02 five times over,
and the control layer escalated. Every input to the rule was true; every one was an
artifact of the fault.

The asymmetry is the point: goal_drifts, regrounds and pace are all computed by this
instrument from the agent's own words, so a single fault can satisfy all three at once.
`corroborated` counts checks backed by output something INDEPENDENT produced — the one
signal laserbrain cannot manufacture. Diego's call: a verdict that can halt an agent has
to pass it.

Uncorroborated, the finding is still reported and still named. What changes is that it
asks the agent to check its ground rather than telling it to abandon its work.

Shipped in lasermind's mcp-server.mjs first; 0.51.0 went out without it, so the wheel and
the server disagreed for one release. This is the wheel catching up, and this file is why
they cannot drift apart again silently.

THIS TEST CAN FAIL: restore the unconditional counsel and the first two assertions go red.
"""
# ISOLATED BEFORE THE IMPORT, and it has to be before: laserbrain resolves its state tree
# at import time. Without this the judgment reads prior-session history from the real
# config directory, and the verdict depends on how much work happened on this machine
# today — the first run of this file came back `abandon` instead of `wrong-problem`,
# because two earlier runs of the same goal had been recorded. Exactly the failure the
# Node test hit this morning, repeated here.
import os, tempfile
os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='lb-test-')

from laserbrain import Harness

GROUND = 'restore the paid billing tiers and rekey the payment links'
# A DIFFERENT subject for the second half. Reusing GROUND made the corroborated
# run read the uncorroborated one as a prior session and escalate past the branch
# under test.
GROUND2 = 'draft the winter catalogue and price the reprints'
AWAY = [
    'compile the kernel scheduler benchmark harness',
    'photograph migrating herons beside the estuary',
    'translate medieval lute tablature into modern notation',
    'repair the greenhouse irrigation timer',
    'catalogue mineral samples from the quarry floor',
    'rehearse the string quartet second movement',
]

ok = True


def check(label, cond, saw=None):
    global ok
    ok = ok and cond
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}"
          + ('' if cond or saw is None else f"   saw: {str(saw)[:150]}"))


def drive():
    """Ground on one subject, then walk away from it until the branch fires."""
    h = Harness()
    h.check(GROUND, 'advancing', 5)
    for g in AWAY:
        h.check(g, 'advancing', 5)          # distance never falls, so pace <= 0
        j = h.phronesis()
        if j.get('verdict') == 'wrong-problem':
            return h, j
    return h, h.phronesis()


print('\n  wrong-problem may only command with corroboration\n')
h, j = drive()

check('the pattern is still detected and named',
      j.get('verdict') == 'wrong-problem', j.get('verdict'))

# Nothing in this run was corroborated: no command was run, nothing independent produced
# output. So the verdict must ask rather than instruct.
check('uncorroborated, it does NOT tell the agent it is not solving its problem',
      'not solving what you set out to solve' not in (j.get('counsel') or ''),
      j.get('counsel'))
check('uncorroborated, it asks the agent to check its ground first',
      'Check the ground' in (j.get('counsel') or ''), j.get('counsel'))
check('and it says why the reading might be about the instrument',
      'ground having moved underneath you' in (j.get('because') or ''), j.get('because'))
check('the finding itself is not suppressed',
      'failed its overlap check' in (j.get('because') or ''), j.get('because'))
check('corroborated count is actually zero here',
      h._run.corroborated == 0, h._run.corroborated)

# THE OTHER HALF. With corroboration the verdict keeps its teeth — otherwise this change
# would have quietly disarmed a rule that is right most of the time.
h2 = Harness()
h2.check(GROUND2, 'advancing', 5)
for g in AWAY:
    h2.check(g, 'advancing', 5)
    if h2.phronesis().get('verdict') == 'wrong-problem':
        break
h2._run.corroborated = 3          # as if three checks had been backed by observed work
j2 = h2.phronesis()
check('corroborated, it DOES instruct',
      'not solving what you set out to solve' in (j2.get('counsel') or ''), j2.get('counsel'))
check('corroborated, the instrument-fault caveat is dropped',
      'ground having moved underneath you' not in (j2.get('because') or ''), j2.get('because'))

print('\n  ' + ('PASS — it reports without corroboration, and only commands with it.'
                if ok else 'FAILED'))
raise SystemExit(0 if ok else 1)
