"""Does the Python matcher agree with the TypeScript it was ported from?

    python3 test_rules.py

json/rule-vectors.json is generated FROM lib/logic.ts and the Worker's morphology.ts, which
are the reference for this computation. This file fails if Python disagrees with a single
vector. That is the arrangement drift already has — three implementations, sixteen vectors,
one gate — and it is the only honest way to hold the same computation in two languages.

WHY A VECTOR FILE AND NOT TWO TEST SUITES. Two suites can both pass while the two
implementations drift apart. That is exactly what happened to read() before
check-reading-parity compared them, and to `coherence` before anyone noticed it named three
different computations. A shared vector file is the only thing that fails when they diverge.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from laserbrain.rules import (  # noqa: E402
    Rule, Ruleset, classify, cue_fires, keyword_pattern, matches_keyword, why_not,
)

VECTORS = pathlib.Path(__file__).parent.parent / 'json' / 'rule-vectors.json'
failed = 0


def check(label, got, want):
    global failed
    if got == want:
        print(f'  ok   {label:<56} {str(got)[:18]}')
    else:
        print(f'  FAIL {label:<56} got {got!r} want {want!r}')
        failed += 1


def main() -> int:
    v = json.loads(VECTORS.read_text())
    print(f'\n  {len(v["matcher"])} matcher vectors, {len(v["classify"])} classify vectors')
    print('  reference: the TypeScript. This file follows it.\n')
    print('  matching — inflection and negation\n')
    for m in v['matcher']:
        kw, text = m['kw'], m['text']
        check(f'{kw!r} in {text!r}', matches_keyword(text, kw), m['matches'])
        check('  fires' if m['fires'] else '  does NOT fire', cue_fires(text, kw), m['fires'])

    print('\n  classification\n')
    r = v['ruleset']
    rs = Ruleset(
        name=r['name'], threshold=r.get('threshold', 1),
        rules=tuple(Rule(name=x['name'], any=tuple(x.get('any', ())),
                         all=tuple(x.get('all', ())), none=tuple(x.get('none', ())),
                         weight=x.get('weight', 1)) for x in r['rules']))
    for case in v['classify']:
        got = classify(case['text'], rs)
        t = case['text'][:32]
        check(f'{t!r}', got.category, case['category'])
        check('  score', got.score, case['score'])
        check('  margin', got.margin, case['margin'])
        for want in case['considered']:
            mine = next(c for c in got.considered if c.rule == want['rule'])
            check(f'  {want["rule"]} fired', mine.fired, want['fired'])
            check(f'  {want["rule"]} why', mine.why, want['why'])
        check('  why_not outage', why_not(got, 'outage'), case['whyNot_outage'])

    # The regex SOURCE differs between JS and Python — escaping and \b handling — so the
    # vectors pin behaviour and not the pattern text. Asserting the sources matched would
    # fail on a difference that changes nothing.
    print('\n  the regex source is deliberately not compared; behaviour is the contract')
    print(f'    python  {keyword_pattern("try").pattern}')
    print(f'    ts      {v["matcher"][6]["pattern"]}')

    if failed:
        print(f'\n  {failed} FAILED — Python and TypeScript disagree\n')
        return 1
    print('\n  PASS — one computation, two languages, pinned by vectors.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
