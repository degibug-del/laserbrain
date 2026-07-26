#!/usr/bin/env python3
"""test_segments.py — reset_task must archive the interval, not delete it.

This is the regression test for the bug that made the dogfood corpus impossible. The design
tells an agent to reset_task on every genuinely new task, and reset was a bare wipe, so a
working session destroyed its own evidence five or six times over. A ~100-step session sat
on disk as "steps: 4" and the whole corpus read 0 fires — while one transcript mentioned
check_state on 1695 lines.

Nothing caught it because nothing was looking: every existing test asserted things about a
session's live state, and the live state was correct. What was gone was everything before
the last reset.

Run against the installed laserbrain if there is one, and skip loudly rather than silently
if not — a skipped test that reads as a pass is how this class of bug survives.
"""
import json, os, sys, tempfile, pathlib

TMP = tempfile.mkdtemp()
ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'laserbrain-sdk'))
try:
    from laserbrain.runtime import Session
except Exception as e:
    print(f"  ✗ cannot import laserbrain.runtime: {e}")
    raise SystemExit(1)

# ── a session that works, resets, and works again ───────────────────────────
s = Session('seg-test', directory=TMP)
s.prompt('first task: fix the layout')
for i in range(6):
    s.tool('Bash', {'command': f'echo {i}'}, True)
s.check('fix the layout', 'advancing', 3, False)
s.check('fix the layout', 'advancing', 2, True)          # a fire
s.tool('Bash', {'command': 'false'}, False)              # a catch

before_steps = s.d.get('steps', 0)
before_checks = len(s.d.get('checks', []))
before_fires = sum(1 for c in s.d.get('checks', []) if c.get('drifting'))
show('a segment accumulates before the reset',
     before_steps > 0 and before_checks == 2 and before_fires == 1,
     f'{before_steps} steps, {before_checks} checks, {before_fires} fire')

s.reset()

show('reset clears the LIVE counters', s.d.get('steps', 0) == 0 and not s.d.get('checks'))
segs = s.d.get('segments') or []
show('and archives exactly one segment', len(segs) == 1, f'{len(segs)} archived')
if segs:
    a = segs[0]
    show('the archived segment kept its steps', a.get('steps') == before_steps,
         f"{a.get('steps')} vs {before_steps}")
    show('and its checks', len(a.get('checks') or []) == before_checks)
    show('and its fires — the number the corpus is FOR',
         sum(1 for c in (a.get('checks') or []) if c.get('drifting')) == before_fires)
    show('and its catches', len(a.get('catches') or []) >= 1,
         f"{len(a.get('catches') or [])} catch(es)")
    show('and the goal it was working on', bool(a.get('goal')), str(a.get('goal'))[:40])

# ── a second cycle must not clobber the first ───────────────────────────────
s.prompt('second task: port the scoring')
for i in range(4):
    s.tool('Bash', {'command': f'ls {i}'}, True)
s.check('port the scoring', 'advancing', 4, False)
s.reset()
segs = s.d.get('segments') or []
show('a second reset appends rather than replaces', len(segs) == 2, f'{len(segs)} archived')
show('and the first segment is still intact',
     len(segs) == 2 and segs[0].get('steps') == before_steps)

# ── it survives a round trip to disk ────────────────────────────────────────
reloaded = json.loads((pathlib.Path(TMP) / 'seg-test.json').read_text())
show('segments are persisted, not just in memory',
     len(reloaded.get('segments') or []) == 2)

# ── and the scorer can actually read them ───────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from dogfood import expand, score_session

rows = expand(reloaded)
show('dogfood expands the file into its segments', len(rows) == 2, f'{len(rows)} scoreable')
scored = [score_session(r) for r in rows]
show('and the archived fire is visible to the scorer',
     sum(r['fires'] for r in scored) == 1,
     f"{sum(r['fires'] for r in scored)} fire(s) across {len(scored)} segment(s)")

# ── the old corpus must still read ──────────────────────────────────────────
legacy = {'id': 'legacy', 'steps': 10, 'checks': [{'step': 2, 'drifting': True}], 'catches': []}
show('a pre-segments file still scores exactly as before',
     len(expand(legacy)) == 1 and score_session(expand(legacy)[0])['fires'] == 1)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
