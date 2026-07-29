#!/usr/bin/env python3
"""test_verdict_recording.py — a fire must survive the trip to disk.

THE BUG THIS PINS. lb_coverage recorded whether a check drifted by substring-matching the
serialised response for '"drifting": true'. An MCP response arrives wrapped —
{"content":[{"type":"text","text":"{...}"}]} — and json.dumps escapes the inner quotes, so
the text contains \\"drifting\\" and the pattern never matches. Every fire was written to
disk as drifting=false, silently.

The damage was the entire corpus: 204 checks over 10 sessions, zero fires recorded, and
104 of those checks sat BELOW the 0.30 overlap threshold that defines goal-drift. The
agent was told it had drifted and the session file said it had not. The corpus had to be
rebuilt from chat transcripts, and every session after the rebuild was being lost the
same way.

Nothing caught it because nothing compared the two. The hook was tested for whether it
wrote a check; no test asked whether the check it wrote said the same thing the agent was
told. That is the gap this file closes.

The last test is the one that matters: it runs the OLD matcher and asserts it FAILS. Every
other assertion here would also pass against a function that returned True unconditionally,
so without a case that legitimately fails, a green run proves nothing.
"""
import json
import pathlib
import sys

# lb_coverage moved to lasergear/ on 2026-07-27 when the instruction layer got its own
# home. This still pointed at lasermind/hooks/, so the file has raised ImportError ever
# since — a test written because "nothing compared the two" spent two days comparing
# nothing. Found 2026-07-29 by running every python file rather than trusting green.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'lasergear'))
from lb_coverage import _verdict                                    # noqa: E402

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


FIRE = {'drifting': True, 'reason': 'goal-drift', 'phi': 0.46,
        'advice': 'Your goal no longer matches the one you started with (overlap 0.19).'}
CALM = {'drifting': False, 'reason': 'advancing', 'phi': 0.09, 'advice': 'On track.'}


def wrapped(v):
    """How an MCP response actually arrives — the shape that broke it."""
    return {'content': [{'type': 'text', 'text': json.dumps(v)}]}


# ── every shape a response can take ─────────────────────────────────────────
shapes = {
    'a bare dict': FIRE,
    'a raw JSON string': json.dumps(FIRE),
    'the MCP content wrapper': wrapped(FIRE),
    'the wrapper, already stringified': json.dumps(wrapped(FIRE)),
    'the wrapper nested one deeper': {'result': wrapped(FIRE)},
}
for name, resp in shapes.items():
    show(f'a fire is seen through {name}', _verdict(resp)['drifting'] is True)

# ── and calm must not read as a fire ────────────────────────────────────────
for name, resp in {'a bare dict': CALM, 'the MCP content wrapper': wrapped(CALM)}.items():
    show(f'calm stays calm through {name}', _verdict(resp)['drifting'] is False)

show('nothing at all is not a fire', _verdict({})['drifting'] is False)
show('garbage is not a fire', _verdict('not json at all')['drifting'] is False)

# ── the reason survives, because "which signal fired" is the corpus's job ───
v = _verdict(wrapped(FIRE))
show('the reason is kept, not "see response"', v['reason'] == 'goal-drift', v['reason'])
show('Φ is kept too', v['phi'] == 0.46, str(v['phi']))
show('an unreadable response says so rather than guessing',
     _verdict('garbage')['reason'] == 'no-reading')


# ── the proof that this test can fail ───────────────────────────────────────
# The old implementation, verbatim. If this ever starts passing, the test above has
# stopped being a regression test and is asserting nothing.
def old_matcher(resp):
    text = json.dumps(resp) if not isinstance(resp, str) else resp
    return '"drifting": true' in text.lower() or '"drifting":true' in text.lower()


show('the OLD matcher does see a bare dict (so it was not simply broken)',
     old_matcher(FIRE) is True)
show('the OLD matcher MISSES the wrapped fire — the bug, reproduced',
     old_matcher(wrapped(FIRE)) is False)
show('and misses it stringified too',
     old_matcher(json.dumps(wrapped(FIRE))) is False)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
