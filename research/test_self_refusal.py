#!/usr/bin/env python3
"""The instrument must not grade itself against noise it generated.

WHAT THIS PINS, AND THE MEASUREMENT THAT FORCED IT

On 2026-08-02 sensitivity.py reported 0 hits, 8 misses, a 0.0% hit rate. Every one of the
eight was the coverage gate blocking a call in the very session doing the analysis.

That number could not have come out any other way. The coverage gate fires BECAUSE the
instrument has been quiet — a lapse is defined as too many steps since check_state — and
the block exits non-zero, and a non-zero exit was recorded as a catch. So the reading live
under a gate-block catch is a quiet one by construction, a gate-block catch can never
coincide with a fire, and the hit rate is 0% before any data is collected. It was an
identity wearing a measurement's clothes.

runtime.py already stated the rule this broke, in the comment above _FAIL_PATTERNS: "a
false catch is strictly worse than a missed one: it would let the instrument grade itself
against noise it generated."

THE LINE THIS DRAWS, which is narrower than "ignore laserbrain's own blocks"

  laserbrain gate:        the coverage gate. Self-generated. NOT a catch.
  laserbrain claim gate:  another agent holds the path. The instrument did not create that
                          condition and the agent was genuinely about to collide. A catch.
  laserbrain safety:      rm -rf and friends. A real destructive command, really stopped.
                          A catch — and the one this suite would most regret losing.

All three print THIS CALL DID NOT RUN, so a filter keyed on that phrase would silently
delete the two that matter. The discriminator is the coverage clause.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))

from laserbrain.runtime import (Session, _looks_failed,          # noqa: E402
                                is_self_refusal)

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


GATE = ('laserbrain gate: 4 steps since your last check_state (coverage 20% over 65 '
        'steps, floor 20%).\nBlocked because nudging did not work.\n'
        'THIS CALL DID NOT RUN. Nothing was written, executed or sent.')
CLAIM = ('laserbrain claim gate: app/page.tsx is claimed by nova in the open wave.\n'
         'THIS CALL DID NOT RUN — nothing was written.')
SAFETY = ('laserbrain safety: blocked rm -rf.\nTHIS CALL DID NOT RUN.\n'
          'permission_mode may be always-approve, but destructive actions still need '
          "Diego's explicit OK in chat.")
REAL = 'Traceback (most recent call last):\n  File "x.py", line 1\nAssertionError'

print('the coverage gate is recognised as the instrument refusing')
check('the gate block is a self-refusal', is_self_refusal(GATE))
check('  so it is not a failure', not _looks_failed(GATE))

print()
print('and the two blocks that ARE independent survive')
check('the claim gate is not a self-refusal', not is_self_refusal(CLAIM))
check('  and still reads as a failure', _looks_failed(CLAIM))
check('the safety block is not a self-refusal', not is_self_refusal(SAFETY))
check('  and still reads as a failure', _looks_failed(SAFETY),
      'losing this one would mean an rm -rf stopped in the dark')
check('an ordinary traceback is untouched', _looks_failed(REAL) and not is_self_refusal(REAL))

print()
print('no catch is written for a gate block — the whole point')
import tempfile                                                  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    s = Session('t1', goal='ship the parser', directory=d)
    s.tool('Bash', {'command': 'npm run build'}, ok=False, self_refusal=True)
    check('a gate-blocked call records no catch', len(s.d['catches']) == 0,
          str(s.d['catches']))
    check('  but the step still counts', s.d['steps'] == 1, f"steps={s.d['steps']}")

    s.tool('Bash', {'command': 'npm test'}, ok=False)
    check('a genuinely failed call still records one', len(s.d['catches']) == 1,
          str(len(s.d['catches'])))

print()
print('end to end, through feed() — the path the hook actually uses')
with tempfile.TemporaryDirectory() as d:
    s = Session('t2', goal='ship the parser', directory=d)
    # Shaped like a real PostToolUse event carrying the gate's text.
    s.feed({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': 'npm run build'},
            'tool_response': {'isError': True, 'content': GATE}})
    check('feed() writes no catch for the gate', len(s.d['catches']) == 0,
          str(s.d['catches']))
    s.feed({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': 'rm -rf /'},
            'tool_response': {'isError': True, 'content': SAFETY}})
    check('  and does write one for the safety block', len(s.d['catches']) == 1,
          str(len(s.d['catches'])))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the gate no longer counts as evidence against itself, and the two')
print('  blocks that catch something real still do.')
