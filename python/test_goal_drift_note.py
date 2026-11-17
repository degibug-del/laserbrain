"""goal-drift is a note, not an interrupt (2026-11-15).

WHY THIS SUITE EXISTS. research/DAY-FIVE-REAL-SESSIONS.md §3: all 7 live goal-drift fires
from Oct 17 to Nov 15 were false (5 were Diego's next ask or a new phase, 1 a rewording, 1 a
redirect he made). In the July corpus goal-drift was 24 of 35 fires with 0 real. The
reground-on-user-turn rule already existed and did not stop them. Diego approved "B":
goal-drift stops returning drifting=True on its own.

WHAT IS PINNED, in the Python reference:

  1. A goal-overlap failure returns reason 'goal-drift' with drifting False — the reason is
     KEPT, so it is still recorded, counted and comparable with the old corpus.
  2. Same for the rejected-parent variant, which still reports parent_overlap.
  3. The advice is a note: the three readings (reset / parent_goal / compare with the
     ground) and no order to return.
  4. goal-drift is not a first strike: a first self-report after it warns (drifting False),
     where a first self-report after `ungrammatical` still interrupts.
  5. The existing escalation is the second signal, unchanged: three goal-drifts with no
     reground give phronesis() verdict wrong-problem and control decision reground.
  6. No live policy acts on it: grammar.modulation has no goal-drift, every depth's
     _style_return is False for it, mcp modulate answers return False, and the Python
     fallback lists match the grammar.

THIS SUITE CAN FAIL: put drifting=True back on either goal-drift emit, or 'goal-drift' back
into _DRIFT or any modulation depth, and it goes red.

Run:  python3 test_goal_drift_note.py
"""
import json
import os
import pathlib
import sys
import tempfile

# A private state root ABOVE the import: laserbrain binds its context store at import time,
# and these fixture runs must not reach the live corpus when this file is run by hand.
if not os.environ.get('LASERBRAIN_HOME'):
    _home = tempfile.mkdtemp(prefix='lb-test-gdnote-')
    os.makedirs(os.path.join(_home, 'config'), exist_ok=True)
    os.makedirs(os.path.join(_home, 'sessions'), exist_ok=True)
    os.environ['LASERBRAIN_HOME'] = _home

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import laserbrain  # noqa: E402
from laserbrain import Harness, PRESETS  # noqa: E402
from laserbrain import _DRIFT, _FALLBACK_DEPTH, _FALLBACK_MODES, _style_return  # noqa: E402

ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


G = 'build the JSON parser'

print('\n  1. the plain goal-overlap failure')
h = Harness()
h.check(G, 'advancing', 6)
v = h.check('write a poem about the sea', 'advancing', 5)
show('reason is still goal-drift', v.reason == 'goal-drift', v.reason)
show('drifting is False', v.drifting is False, v.drifting)
show('the ground is still returned beside it', v.ground == G, v.ground)

print('\n  2. the rejected-parent variant')
h = Harness()
h.check(G, 'advancing', 6)
vp = h.check('cook a vegan dinner', 'advancing', 5, parent_goal='paint the garden fence')
show('reason is still goal-drift', vp.reason == 'goal-drift', vp.reason)
show('drifting is False', vp.drifting is False, vp.drifting)
show('parent_overlap is still recorded', getattr(vp, 'parent_overlap', None) == 0.0,
     getattr(vp, 'parent_overlap', None))

print('\n  3. the advice is a note, not an order')
for name, verdict in (('plain', v), ('rejected parent', vp)):
    a = verdict.advice
    show(f'{name}: says it is recorded, not an interrupt', 'not an interrupt' in a, a)
    show(f'{name}: names reset for a redirect', 'redirected you, reset' in a, a)
    show(f'{name}: points at the ground', 'compare your goal with the ground' in a, a)
    show(f'{name}: does not tell the agent to return', 'return' not in a.lower(), a)
show('plain: still offers parent_goal for a sub-task', 'pass parent_goal' in v.advice, v.advice)
show('rejected parent: never tells an agent to do what it just did',
     'pass parent_goal' not in vp.advice, vp.advice)

print('\n  4. not a first strike for the warn-then-interrupt rule')
show("_DRIFT no longer lists 'goal-drift'", 'goal-drift' not in _DRIFT, _DRIFT)
h = Harness()
h.check(G, 'advancing', 5)
h.check('write a poem about the sea', 'advancing', 5)
s = h.check(G, 'stuck', 5)
show('a first self-report after goal-drift warns', s.reason == 'self-report:stuck'
     and s.drifting is False, f'{s.reason} {s.drifting}')
h = Harness()
h.check(G, 'advancing', 5)
h.check('', 'advancing', 5)                            # ungrammatical: still a strike
s = h.check(G, 'stuck', 5)
show('...where after ungrammatical it still interrupts (the rule itself is unchanged)',
     s.reason == 'self-report:stuck' and s.drifting is True, f'{s.reason} {s.drifting}')

print('\n  5. the second signal is the existing escalation, unchanged')
h = Harness()
h.check(G, 'advancing', 5)
for g in ('write a poem about the sea', 'paint the garden fence', 'cook a vegan dinner'):
    r = h.check(g, 'advancing', 5)
show('three goal-drifts, none of them drifting', r.reason == 'goal-drift' and not r.drifting)
j = h.phronesis()
show('phronesis verdict is wrong-problem', j.get('verdict') == 'wrong-problem', j.get('verdict'))
show('control decision is reground', (j.get('control') or {}).get('decision') == 'reground',
     j.get('control'))
show('control still counts them as goal_drifts',
     ((j.get('control') or {}).get('reads') or {}).get('goal_drifts') == 3, j.get('control'))

print('\n  6. no live policy returns on it')
mod = laserbrain._G.get('modulation') or {}
show('grammar.modulation.modes has no goal-drift', 'goal-drift' not in (mod.get('modes') or []))
show('no grammar depth lists goal-drift',
     all('goal-drift' not in d for d in (mod.get('depths') or {}).values()), mod.get('depths'))
for depth in ('deep', 'balanced', 'tight'):
    show(f'_style_return is False at {depth}',
         _style_return('goal-drift', {'role': 'x', 'recurse': depth}) is False)
for team, roles in PRESETS.items():
    for role in roles:
        show(f'{team}/{role["role"]} does not return on goal-drift',
             _style_return('goal-drift', role) is False)
show('the Python fallback modes match the grammar', _FALLBACK_MODES == list(mod.get('modes') or []),
     _FALLBACK_MODES)
show('the Python fallback depths match the grammar',
     {k: list(x) for k, x in _FALLBACK_DEPTH.items()} == (mod.get('depths') or {}), _FALLBACK_DEPTH)
verdicts = laserbrain._G.get('verdicts') or {}
show("grammar verdicts.interrupt no longer lists goal-drift",
     'goal-drift' not in (verdicts.get('interrupt') or []), verdicts.get('interrupt'))
show("grammar verdicts.note names goal-drift",
     (verdicts.get('note') or {}).get('names') == ['goal-drift'], verdicts.get('note'))
copies = [ROOT / 'laserbrain/grammar.json', ROOT.parent / 'json/grammar.json',
          ROOT.parent / 'typescript/src/grammar.json']
present = [p for p in copies if p.is_file()]
show('every grammar.json copy in this tree is byte-identical',
     len({p.read_bytes() for p in present}) == 1, [str(p) for p in present])

from laserbrain import mcp  # noqa: E402
mcp._state['harness'] = None
mcp._modulate({'goal': G, 'progress': 'advancing', 'distance': 6})
out = mcp._modulate({'goal': 'write a poem about the sea', 'progress': 'advancing', 'distance': 5})
show('mcp modulate: reason goal-drift, drifting False',
     out.get('reason') == 'goal-drift' and out.get('drifting') is False, json.dumps(out)[:160])
show('mcp modulate: return False, unstyled', (out.get('modulation') or {}).get('return') is False,
     out.get('modulation'))
out = mcp._modulate({'goal': 'paint the garden fence', 'progress': 'advancing', 'distance': 5,
                     'team': 'deep-search', 'role': 'checker'})
show('mcp modulate: return False for the tight checker role',
     (out.get('modulation') or {}).get('return') is False, out.get('modulation'))

print('\n  ' + ('PASS — goal-drift is recorded and counted, and interrupts nothing on its own.'
                if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
