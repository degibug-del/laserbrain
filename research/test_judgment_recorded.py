#!/usr/bin/env python3
"""The corpus must hold the judgment, not only the reading.

WHY, AND IT IS THE SAME LESSON TWICE

_verdict() already carries a long note about the first time this went wrong: the response
was pattern-matched instead of parsed, every fire recorded False, and the cost was "the
whole corpus — 204 checks across 10 sessions recorded zero fires". The verdicts had to be
rebuilt from chat transcripts because the session files never held them.

`judgment` was the same shape of hole, one layer up. `reason` names the READING —
advancing, goal-drift, reground. `judgment` names what the harness told the agent to DO
about the run: abandon, wrong-problem, repeating, narrow. It is the strongest advice the
instrument gives, and nothing stored it.

The bill arrived 2026-08-04. A bug attached `abandon` — "stop, this is not reachable" — to
the FIRST check of a goal the user had just handed over. It was found only because it
happened to me while I was watching, and the obvious follow-up, "how often has this
fired?", could not be answered from 224 recorded runs. With the field present the same
question is one query: 64 regrounds at step >= 13, 3.5% of every recorded check.

WHAT THIS PINS

  the wrapped shape        an MCP response arrives {"content":[{"text":"{...}"}]} with the
                           payload as an ESCAPED JSON STRING. That exact wrapper is what
                           defeated the original matcher, so it is what this tests. A test
                           against a bare dict would pass while the real path stayed blind.
  absent, not null         a server that sends no judgment must leave the key OFF the row.
                           A stored null reads like a measured "no judgment was given",
                           which is a different claim from "this row predates the field",
                           and the corpus has to be able to tell those apart.
  anchored survives 0.0    it is a fraction and 0.0 is meaningful — an agent whose every
                           term is self-reported. `if v['anchored']` would drop exactly the
                           reading that matters most, so the guard tests `is not None`.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'lasergear'))

from lb_coverage import _verdict                                 # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def wrapped(payload):
    """A real MCP tool response: the payload as an escaped JSON string inside content."""
    return {'content': [{'type': 'text', 'text': json.dumps(payload)}]}


FULL = {
    'drifting': True, 'reason': 'goal-drift', 'phi': 0.49, 'run': 'r1', 'step': 14,
    'goal_score': 0.14, 'anchored': 0.5,
    'judgment': {'verdict': 'abandon', 'because': '14 checks...', 'counsel': 'Stop.'},
}

print('the judgment survives the wrapper that defeated the first matcher')
v = _verdict(wrapped(FULL))
check('reason still read', v['reason'] == 'goal-drift', v['reason'])
check('judgment read', v['judgment'] == 'abandon', str(v['judgment']))
check('anchored read', v['anchored'] == 0.5, str(v['anchored']))
check('goal_score read', v['goal_score'] == 0.14, str(v['goal_score']))

print()
print('a healthy check has no judgment, and that is not an error')
HEALTHY = {'drifting': False, 'reason': 'advancing', 'phi': 0.12, 'anchored': 0.5}
v2 = _verdict(wrapped(HEALTHY))
check('judgment is None when the server sent none', v2['judgment'] is None, str(v2['judgment']))
check('  and the reading is still recorded', v2['reason'] == 'advancing')

print()
print('anchored 0.0 is a reading, not an absence — the case a truthy guard would drop')
v3 = _verdict(wrapped({'drifting': False, 'reason': 'advancing', 'anchored': 0.0}))
check('anchored 0.0 survives extraction', v3['anchored'] == 0.0, repr(v3['anchored']))
check('  and it is not None', v3['anchored'] is not None,
      'an agent with NO corroborated term is exactly the row worth keeping')

print()
print('an older server drops the keys rather than storing nulls')
OLD = {'drifting': True, 'reason': 'stalled', 'phi': 0.2}
v4 = _verdict(wrapped(OLD))
row = {'step': 1, 'reason': v4['reason'],
       **({'judgment': v4['judgment']} if v4['judgment'] else {}),
       **({'anchored': v4['anchored']} if v4['anchored'] is not None else {}),
       **({'goal_score': v4['goal_score']} if v4['goal_score'] is not None else {})}
check('no judgment key on a pre-field row', 'judgment' not in row, str(sorted(row)))
check('no anchored key either', 'anchored' not in row, str(sorted(row)))
check('  but the row is still written', row['reason'] == 'stalled')

print()
print('and the same payload unwrapped still works — both shapes reach the corpus')
check('bare dict', _verdict(FULL)['judgment'] == 'abandon')
check('raw JSON string', _verdict(json.dumps(FULL))['judgment'] == 'abandon')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the corpus now records what the harness told the agent to do, and can')
print('  tell "no judgment" apart from "this row is older than the field".')


# ══════════════════════════════════════════════════════════════════════════════════════
# AND NOW THE STORED ROW, which is the thing that was actually broken.
#
# Everything above tests lb_coverage._verdict(), and all of it passed on 2026-08-04 while
# the corpus recorded NOTHING. A full day of checks — 1,891 of them — carried no anchored,
# no goal_score, no judgment.
#
# Two reasons, and both are the same reason:
#
#   runtime.verdict_of()   a SECOND copy of the extractor, unedited. lb_coverage pulled the
#                          fields out next door and this one threw them away.
#   Session.check()        the writer that WINS. Session owns the session path, holds its
#                          dict across the hook's writes and saves the whole thing back, so
#                          a richer row written elsewhere is overwritten by this one. The
#                          same race is documented against probe_arm — it is why arms.jsonl
#                          exists — and it ate these fields for a day.
#
# THE LESSON IS ABOUT THE TEST, not the code. Asserting on the extractor proved a function
# returned a value. It could not notice that nothing downstream stored it. What follows
# drives a real hook event through Session and reads the ROW — the artifact, not the step —
# which is the only assertion that would have failed on the day it mattered.
# ══════════════════════════════════════════════════════════════════════════════════════
import tempfile as _tf                                            # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'))
from laserbrain.runtime import Session                            # noqa: E402

print()
print('the stored row carries them — the artifact, not just the extractor')
_PAY = {'drifting': False, 'reason': 'advancing', 'phi': 0.06, 'run': 'r1', 'step': 9,
        'goal_score': 1, 'anchored': 0.5,
        'judgment': {'verdict': 'unbacked', 'because': '...', 'counsel': '...'}}
with _tf.TemporaryDirectory() as _d:
    _s = Session('t-row', goal='ship it', directory=_d)
    _s.feed({'hook_event_name': 'PostToolUse',
             'tool_name': 'mcp__laserbrain__check_state',
             'tool_input': {'goal': 'ship it', 'progress': 'advancing', 'distance': 4},
             'tool_response': {'content': [{'type': 'text', 'text': json.dumps(_PAY)}]}})
    _row = _s.d['checks'][-1]
    check('the row stores anchored', _row.get('anchored') == 0.5, repr(_row.get('anchored')))
    check('the row stores goal_score', _row.get('goal_score') == 1, repr(_row.get('goal_score')))
    check('the row stores judgment', _row.get('judgment') == 'unbacked', repr(_row.get('judgment')))

print()
print('and a healthy check stores no judgment key at all')
_HEALTHY = {'drifting': False, 'reason': 'advancing', 'phi': 0.1, 'anchored': 0.5, 'goal_score': 1}
with _tf.TemporaryDirectory() as _d:
    _s2 = Session('t-row2', goal='ship it', directory=_d)
    _s2.feed({'hook_event_name': 'PostToolUse',
              'tool_name': 'mcp__laserbrain__check_state',
              'tool_input': {'goal': 'ship it', 'progress': 'advancing', 'distance': 4},
              'tool_response': {'content': [{'type': 'text', 'text': json.dumps(_HEALTHY)}]}})
    _r2 = _s2.d['checks'][-1]
    check('no judgment key when none was given', 'judgment' not in _r2, str(sorted(_r2)))
    check('  but anchored is still stored', _r2.get('anchored') == 0.5,
          'a run with no judgment still has an anchoring worth keeping')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the fields reach the file, which is where the corpus reads them from.')
