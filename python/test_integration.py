"""The whole thing, wired together.

One author writes a method and stores it. A different agent — with no access to the
author's code — vends it, binds its OWN skills to the declared steps, and runs it under
measurement with the operator gating whatever cannot be taken back.

That path is the product. Each piece has its own tests; this asserts they compose.
"""
import sys
import tempfile

sys.path.insert(0, '.')

from laserbrain import Nova, Operator, Refused, Store, Workflow   # noqa: E402

ok = True


def check(label, cond):
    global ok
    print(f'  {"ok  " if cond else "FAIL"}  {label}')
    ok = ok and bool(cond)


print('integration — author → store → vend → nova → operator')

with tempfile.TemporaryDirectory() as shelf:
    # ── the author ─────────────────────────────────────────────────────────────────────
    # Writes the METHOD. Note these callables never leave this scope.
    author = Workflow(goal='ship the release')
    author.step('test', lambda c: None, goal='the test suite passes')
    author.step('build', lambda c: None, goal='build the release wheel')
    author.step('publish', lambda c: None, goal='upload the release to PyPI',
                irreversible=True, outward=True)

    store = Store(root=shelf, shipped=False)  # isolate the local shelf
    store.put(author, 'release')
    check('the author stores a method', store.list() == ['release'])

    shelved = store.vend('release')
    check('what is on the shelf is data, not code',
          isinstance(shelved, dict) and all(
              set(s) <= {'name', 'goal', 'irreversible', 'outward'} for s in shelved['steps']))
    check('  and it still says which step cannot be taken back',
          [s['name'] for s in shelved['steps'] if s['irreversible']] == ['publish'])

    # ── the consumer, somewhere else entirely ──────────────────────────────────────────
    did = []
    n = Nova(goal='ship the release')
    n.learn('test', lambda c: did.append('ran my own tests') or
            {'progress': 'advancing', 'distance': 2, 'goal': 'the test suite passes'})
    n.learn('build', lambda c: did.append('built my own way') or
            {'progress': 'advancing', 'distance': 1, 'goal': 'build the release wheel'})
    n.learn('publish', lambda c: did.append('uploaded') or
            {'progress': 'advancing', 'distance': 0, 'goal': 'upload the release to PyPI'})

    w = store.get('release')
    check('a vended method arrives with nothing bound', w.unbound() == ['test', 'build', 'publish'])

    op = Operator(authorize=lambda a: True)
    out = n.follow(w, operator=op)

    check('nova binds its own skills to the declared steps',
          out['bound'] == ['test', 'build', 'publish'] and out['unbound'] == [])
    check('the method runs to completion', out['completed'] is True)
    check('  using the consumer\'s implementations, not the author\'s',
          did == ['ran my own tests', 'built my own way', 'uploaded'])
    check('  and no step departed from what it was declared for', out['wandered'] == [])
    check('following leaves a trace on nova', any(e.name == 'follow' for e in n.events))
    check('  and each step counted as a skill call',
          all(n.skills[k].calls == 1 for k in ('test', 'build', 'publish')))

    # ── the operator is not decoration ─────────────────────────────────────────────────
    did.clear()
    w2 = store.get('release')
    n2 = Nova(goal='ship the release')
    for k in ('test', 'build', 'publish'):
        n2.learn(k, lambda c, _k=k: did.append(_k) or {'progress': 'advancing', 'distance': 1})

    out2 = n2.follow(w2)                       # no operator supplied at all
    check('the irreversible step is refused with no operator', out2['refused_at'] == 'publish')
    check('  the reversible steps still ran', did == ['test', 'build'])
    check('  and nothing was published', 'publish' not in did)

    did.clear()
    w3 = store.get('release')
    n3 = Nova(goal='ship the release')
    for k in ('test', 'build', 'publish'):
        n3.learn(k, lambda c, _k=k: did.append(_k) or {'progress': 'advancing', 'distance': 1})
    out3 = n3.follow(w3, operator=Operator(authorize=lambda a: False))
    check('a refusing operator stops the release', out3['refused_at'] == 'publish'
          and 'publish' not in did)

    # ── a method you cannot actually perform fails up front ────────────────────────────
    w4 = store.get('release')
    n4 = Nova(goal='ship the release')
    n4.learn('test', lambda c: None)           # knows one step of three
    try:
        n4.follow(w4)
        check('following a method you cannot perform raises up front', False)
    except KeyError as e:
        check('following a method you cannot perform raises up front', True)
        check('  and names what is missing', 'build' in str(e) and 'publish' in str(e))

    # ── the reading that a task runner cannot produce ──────────────────────────────────
    w5 = store.get('release')
    n5 = Nova(goal='ship the release')
    n5.learn('test', lambda c: {'progress': 'advancing', 'distance': 1})
    n5.learn('build', lambda c: {'progress': 'advancing', 'distance': 1,
                                 'goal': 'refactoring the parser'})
    n5.learn('publish', lambda c: {'progress': 'advancing', 'distance': 0})
    out5 = n5.follow(w5, operator=Operator(authorize=lambda a: True))
    departed = {r['step'] for r in out5['wandered']}
    check('a step that did something else is caught', departed == {'build'})
    row = [r for r in out5['wandered'] if r['step'] == 'build'][0]
    check('  declared vs reported are both reported',
          row['declared'] == 'build the release wheel'
          and row['reported'] == 'refactoring the parser')
    check('  and it halted rather than publishing anyway', out5['completed'] is False)

print()
raise SystemExit(0 if ok else 1)
