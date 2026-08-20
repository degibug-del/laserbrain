#!/usr/bin/env python3
"""test_vocab.py — what the default grammar already does, and the one thing it cannot.

Written after a mistake worth keeping: this file first asserted that the default trips on
inflected restatements. It does not. `norm()` stems and strips stopwords, so those score
1.0. The assertion failed, the number was checked, and a redundant `stemmed_similarity`
was deleted rather than shipped. The tests below record where the real boundary is.
"""
from laserbrain import Harness, norm
from laserbrain.vocab import embedding_similarity

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def verdict(first, later, sim=None):
    h = Harness(similarity=sim)
    h.check(goal=first, progress='advancing', distance=5)
    return h.check(goal=later, progress='advancing', distance=5)


def jac(a, b):
    x, y = norm(a), norm(b)
    return len(x & y) / len(x | y) if (x | y) else 0.0


# what the default ALREADY handles — asserted so nobody "fixes" it again
show('inflections collapse: building billboards == build a billboard',
     jac('building billboards', 'build a billboard') == 1.0)
show('and so it does not read as drift',
     verdict('building billboards', 'build a billboard').reason != 'goal-drift')

# the real remaining gap: synonyms share no stem
S1, S2 = 'build the sky billboard', 'construct the aerial hoarding'
show('synonyms score 0.0 under the default grammar', jac(S1, S2) == 0.0)
show('so a faithful restatement in other words DOES read as drift',
     verdict(S1, S2).reason == 'goal-drift',
     'this is the false positive embeddings exist to fix')

# and genuine drift must still be caught, whatever the grammar
show('a genuinely different goal reads as drift',
     verdict(S1, 'refactor the parser and migrate the database').reason == 'goal-drift')

# the embedding path must fail with a USEFUL message when the extra is absent
try:
    embedding_similarity()('a', 'b')
    show('embedding path works (extra installed)', True)
except ImportError as e:
    show('embedding path names the fix when the extra is missing',
         'laserbrain[semantic]' in str(e))

show('Harness() with no similarity leaves the frozen path in place',
     Harness()._run.sim is None)

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
