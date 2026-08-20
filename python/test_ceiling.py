"""The introspection ceiling, read off an agent's own words.

The claim this file has to prove is not "the regex matches words" — that is trivially
true and worth nothing. It is that this reading is INDEPENDENT of `anchored`: that the
two disagree in both directions, so the new slot is carrying information the old one
cannot. A second signal that only ever agrees with the first is decoration.

Also guarded: the None case. A step whose text matched nothing must report None and not
0.0, because 0.0 means "entirely cause-claims" and would be a fabricated finding about
something the marker never read.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain import Harness           # noqa: E402
from laserbrain.ceiling import mark      # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


print('the marker itself')

claim = mark('advancing because the fix should work')
check('a pure claim scores 0.0 grounded', claim['grounded'] == 0.0, str(claim['grounded']))
check('  and counts both phrases', claim['cause'] == 2, str(claim['cause']))

report = mark('ran the suite, exit 0, 31 tests passed')
check('a pure report scores 1.0 grounded', report['grounded'] == 1.0, str(report['grounded']))

mixed = mark('tests passed so that means the parser is fixed')
check('a mixed account lands between', 0 < mixed['grounded'] < 1, str(mixed['grounded']))

# THE ONE THAT MATTERS MOST. Silence is not a score.
silent = mark('edited the file and moved on')
check('text with no marked phrase reports None, never 0.0',
      silent['grounded'] is None, repr(silent['grounded']))
check('  which is distinguishable from a real 0.0',
      claim['grounded'] == 0.0 and silent['grounded'] is None)

check('it shows what it matched, so a score can be argued with',
      claim['hits'] == [('cause', 'because'), ('cause', 'should work')], str(claim['hits']))

# Declared limitation, tested so it stays declared rather than quietly becoming a bug
# report later: the browser instrument says it reads "since" in both senses, and so does
# this. A temporal 'since' is counted as a cause-claim. Known, not hidden.
temporal = mark('nothing has changed since the last commit')
check('the documented "since" ambiguity is real and counted as cause',
      temporal['cause'] == 1, str(temporal['cause']))

print()
print('independence from `anchored` — the claim that justifies a second slot')

# Direction 1: no events behind it, but the agent is REPORTING rather than claiming.
# anchored stays at its floor; the language reading is high. They disagree.
h1 = Harness('read the config')
v1 = h1.check('read the config', 'advancing', 4,
              doing='i read the file, saw 3 rows, exit 0')
check('unanchored by events', v1.anchored == 0.5, str(v1.anchored))
check('  yet grounded in language', v1.claims['grounded'] == 1.0, str(v1.claims['grounded']))
check('  so the two readings disagree', v1.anchored < 1.0 and v1.claims['grounded'] == 1.0)

# Direction 2: same event evidence, but the agent is GUESSING in words.
h2 = Harness('fix the parser')
v2 = h2.check('fix the parser', 'advancing', 4,
              doing='this should fix it because the regex was probably wrong')
check('same anchored value as the honest reporter',
      v2.anchored == v1.anchored, f'{v2.anchored} vs {v1.anchored}')
check('  but the language reading separates them',
      v2.claims['grounded'] == 0.0 and v1.claims['grounded'] == 1.0,
      f"{v2.claims['grounded']} vs {v1.claims['grounded']}")

print()
print('wiring')

h3 = Harness('ship it')
v3 = h3.check('ship it', 'advancing', 3)
check('a step with no free text carries no claims reading', v3.claims is None, str(v3.claims))
check('  and scores omits the key entirely rather than reporting a number',
      'language' not in v3.scores, str(v3.scores))

v4 = h3.check('ship it', 'advancing', 2, doing='ran it, tests passed')
check('a step with free text carries one', v4.claims is not None)
check('  and scores surfaces it', v4.scores.get('language') == 1.0, str(v4.scores))

# Φ is the published instrument. This must not have moved it.
h5 = Harness('same run')
a = h5.check('same run', 'advancing', 5)
h6 = Harness('same run')
b = h6.check('same run', 'advancing', 5, doing='because it should work', blocked='probably nothing')
check('the reading does NOT move Φ', a.phi == b.phi, f'{a.phi} vs {b.phi}')
check('  nor the verdict', a.reason == b.reason, f'{a.reason} vs {b.reason}')

print()
print('the traps this shipped with — pinned so they cannot come back')

# Found in the pre-publish audit, not by reasoning about the code. Both are about the
# same thing: a caller reaching the reading the easy way and getting the wrong answer.
h7 = Harness('positional')
try:
    h7.check('positional', 'advancing', 5, None, False, False, None, False, 'sneaky-doing')
    check('doing cannot be set positionally', False, 'a 9th positional argument reached it')
except TypeError:
    check('doing cannot be set positionally', True)

# The worst of the three, found by executing the failure rather than reasoning about it:
# empty pattern lists compile to `\b(?:()|())\b`, which matches the empty string at every
# word boundary — sixteen phantom cause-claims on one ordinary sentence, reported as a
# confident 0.0. A valid regex, no error, a wholly fabricated finding.
import laserbrain.ceiling as _c
_saved = (_c.CAUSE_PATTERNS, _c.OBSERVATION_PATTERNS, _c._RE)
try:
    _c.CAUSE_PATTERNS, _c.OBSERVATION_PATTERNS = [], []
    _c._RE = _c._compile()
    broken = _c.mark('the parser was fixed and nothing else happened')
    check('empty patterns report None, not a fabricated 0.0',
          broken['grounded'] is None, repr(broken['grounded']))
    check('  and no phantom hits', broken['hits'] == [] and broken['cause'] == 0,
          str(broken))
finally:
    _c.CAUSE_PATTERNS, _c.OBSERVATION_PATTERNS, _c._RE = _saved
check('  and the guard did not damage normal operation',
      mark('because')['grounded'] == 0.0 and _c.AVAILABLE)

nothing = mark('edited the file')['grounded']
claim_only = mark('because')['grounded']
check('None and 0.0 are DIFFERENT values', nothing is None and claim_only == 0.0,
      f'{nothing!r} vs {claim_only!r}')
check('  and both are falsy — which is why callers must use `is None`',
      (not nothing) and (not claim_only),
      'a truthiness test cannot tell them apart; this is documented, not fixed')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a second, independent reading of the same ceiling, and Φ is untouched.')
