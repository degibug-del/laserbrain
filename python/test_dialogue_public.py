#!/usr/bin/env python3
"""The dialogue surface: public by name, and unchanged in what it decides.

Two claims, and the second is the one that could quietly cost the corpus.

  IT IS REACHABLE   `Team.run()` runs a whole scripted team. Until 0.41.0 there was no
                    public way to drive a conversation turn by turn — the shape of one
                    person talking to one agent — so the first outside consumer imported
                    `_Dialogue` and `_asdist` by their private names.

  IT DECIDES THE SAME   `self_echo` is additive. It is computed, returned, and never fed
                    into a verdict. Feeding it into echo-spiral would be a one-line change
                    and would make every reading taken before this version incomparable
                    with every reading after it, silently. The corpus is the asset; the
                    fields around it are cheap.
"""
import sys

import laserbrain as lb
from laserbrain import Dialogue, asdist

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


print('reachable without reaching into private names')
pub = [x for x in dir(lb) if not x.startswith('_')]
check('Dialogue is exported', 'Dialogue' in pub)
check('asdist is exported', 'asdist' in pub)
check('  and Dialogue IS the object Team uses', lb.Dialogue is lb._Dialogue,
      'an alias to a copy would drift from the thing under test')
check('  the private name still works', hasattr(lb, '_Dialogue'),
      'Team and the existing suite import it')
check('asdist clamps like the harness does', (asdist(99), asdist(-4), asdist('x')) == (10, 0, 5),
      str((asdist(99), asdist(-4), asdist('x'))))

print()
print('self_echo sees a speaker repeating THEMSELF')
# The blind spot: `echo` compares a speaker to the OTHERS, so with one speaker it is 0.00
# forever and echo-spiral can never fire in a two-party chat.
d = Dialogue('finish the drift paper')
d.step('you', 'the corpus is too small to say anything', 5)
r = d.step('you', 'the corpus is still too small to say anything', 5)
check('a near-repeat scores self_echo', r['self_echo'] > 0.5, str(r['self_echo']))
check('  while cross-agent echo stays 0', r['echo'] == 0.0, str(r['echo']),)

d2 = Dialogue('finish the drift paper')
d2.step('a', 'the corpus is too small', 5)
r2 = d2.step('b', 'the corpus is too small', 5)
check('two agents converging still scores echo', r2['echo'] > 0.5, str(r2['echo']))
check('  and that turn has no self_echo', r2['self_echo'] == 0.0, str(r2['self_echo']))

print()
print('every reading carries the field')
d3 = Dialogue('ship it')
check('present on a normal turn', 'self_echo' in d3.step('you', 'the tests are green', 4))
check('present on the grounding turn', 'self_echo' in Dialogue('').step('you', 'a goal', 5))

print()
print('NO VERDICT MOVED — the reason a corpus stays comparable')
# Replayed against the behaviour as of 0.40.0. If one of these flips, drift vectors from
# before this release stop meaning what they meant, and nothing in the data would say so.
CASES = [
    # (goal, [(agent, position, distance), ...], expected final reason)
    ('build the parser', [('you', 'build the parser', 5)], 'advancing'),
    ('build the parser', [('you', 'totally unrelated weather balloons', 5)], 'advancing'),
    ('', [('you', 'set the shared goal here', 5)], 'grounded'),
    ('build the parser', [('you', '', 5)], 'ungrammatical'),
    ('build the parser',
     [('a', 'the parser needs a tokenizer', 5), ('b', 'the parser needs a tokenizer', 5),
      ('a', 'the parser needs a tokenizer', 5), ('b', 'the parser needs a tokenizer', 5),
      ('a', 'the parser needs a tokenizer', 5)], 'echo-spiral'),
]
for goal, turns, want in CASES:
    dd = Dialogue(goal)
    got = None
    for agent, pos, dist in turns:
        got = dd.step(agent, pos, dist)['reason']
    check(f'{want:<18} still fires', got == want, f'got {got}')

print()
print('topic-drift still needs a restated goal, not a low-overlap turn')
d4 = Dialogue('build the parser')
plain = d4.step('you', 'weather balloons over kansas', 5)['reason']
d5 = Dialogue('build the parser')
declared = d5.step('you', 'weather balloons', 5, restated_goal='weather balloons over kansas')['reason']
check('a wandering turn alone is not drift', plain != 'topic-drift', plain)
check('  a restated goal below the floor is', declared == 'topic-drift', declared)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — reachable by name, richer by one field, and identical in what it decides.')
