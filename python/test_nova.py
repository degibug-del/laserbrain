#!/usr/bin/env python3
"""nova — the agent, and the four things examination found wrong with it.

Written after building nova and then looking at it properly, which turned up three real
defects and one false claim in its own docstring. Each is an assertion here now:

  1. self_check() took a NEW reading. Six calls grew the trace from four to ten, and those
     synthetic readings feed the stall window and the cycle detector — so asking nova how
     it was doing could manufacture `stalled` out of nothing but the asking.
  2. The docstring claimed nova "holds no handle" to its ground. It does:
     nova._hz._run.ground is reachable and writable. The check behind the claim had been
     dir() for method names containing "ground", which tests vocabulary, not the object.
  3. learn() silently replaced an existing skill, so a second registration anywhere in a
     codebase quietly swaps what every later use() calls.
  4. run() must check every step, with no way to skip it — that is the only reason nova's
     coverage differs from the 12% a hand-instrumented agent actually achieves.
"""
import sys

from laserbrain import Nova

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:50} {got}")


def walk(goal='ship the parser', n=4):
    def act(ctx):
        return {'goal': goal, 'progress': 'advancing',
                'distance': max(0, n - ctx['steps'])}
    return act


# ── 1 · observation must not change the observed ─────────────────────────────────
print('self_check reports, it does not participate')
nv = Nova(goal='ship the parser')
check('nothing to report before the first step', nv.self_check(), None)
nv.run(walk(), max_steps=4)
before = len(nv._hz._run.trace)
for _ in range(6):
    nv.self_check()
check('six self_checks add no trace entries', len(nv._hz._run.trace), before)
check('and it still returns the real verdict', nv.self_check().reason in
      ('grounded', 'advancing', 'stalled', 'reground'), True)

# ── 2 · the ground: evidence, not a barrier ──────────────────────────────────────
print('\nthe ground is witnessed, not walled')
nv = Nova(goal='ship the parser')
check('no fingerprint before the first step', nv.ground_intact(), None)
nv.run(walk(), max_steps=3)
check('intact after a clean run', nv.ground_intact(), True)
# Python has no true private. The honest offering is detection, so this MUST be catchable.
nv._hz._run.ground = {'goal': 'something else entirely', 'progress': 'advancing', 'dist': 0}
check('tampering is detected', nv.ground_intact(), False)
check('and it is said out loud', 'GROUND TAMPERED' in nv.report(), True)
# It must not raise: a monitor that crashes gets removed, one that tells you gets read.
check('detection does not raise', isinstance(nv.report(), str), True)

# ── 3 · a skill must not change under its own name ───────────────────────────────
print('\nskills are not silently swapped')
nv = Nova(goal='x')
nv.learn('search', lambda: 'first')
try:
    nv.learn('search', lambda: 'second')
    check('re-registering raises', False, True)
except ValueError:
    check('re-registering raises', True, True)
check('the original survives', nv.use('search'), 'first')
nv.learn('search', lambda: 'second', replace=True)
check('an explicit replace works', nv.use('search'), 'second')

# ── 4 · the check cannot be skipped ──────────────────────────────────────────────
print('\ncoverage is 1 by construction')
nv = Nova(goal='ship the parser')
nv.run(walk(n=5), max_steps=5)
# Every step took a reading. That is the whole difference from hand-instrumenting an
# agent, where the measured coverage across real sessions is about 12%.
check('one reading per step', len(nv._hz._run.trace), nv.steps)
check('no flag exists to skip it',
      any('skip' in p or 'quiet' in p for p in Nova.run.__code__.co_varnames), False)

# ── supercode is a skill nova calls, not something nova is ───────────────────────
print('\nsupercode is a skill')
nv = Nova(goal='keep the fleet on their grounds')
check('preloaded', 'supercode' in nv.skills, True)
out = nv.use('supercode', observations=[
    {'agent': 'a', 'goal': 'fix the auth bug in session handling', 'progress': 'advancing', 'distance': 4},
    {'agent': 'b', 'goal': 'fix the session auth bug', 'progress': 'advancing', 'distance': 4}])
check('it reads across agents', len(out['collisions']), 1)
check('using it is recorded as an event', nv.skills['supercode'].calls, 1)
# nova is not supercode: nova has a ground and is measured; supercode has neither.
check('nova has its own ground', nv.goal, 'keep the fleet on their grounds')

# ── a failing skill is recorded and re-raised ────────────────────────────────────
print('\nfailures are recorded, not swallowed')
nv = Nova(goal='x')
nv.learn('boom', lambda: 1 / 0)
try:
    nv.use('boom')
    check('the error reaches the caller', False, True)
except ZeroDivisionError:
    check('the error reaches the caller', True, True)
check('and the failure is on the record', nv.skills['boom'].failures, 1)
# This assertion replaced one that could not fail: `isinstance(None, type(None))`, which
# is True whatever the code does. An unfalsifiable check in a test file is the exact
# signature `unfalsified` exists to catch, written an hour after shipping that catch.
try:
    nv.use('no_such_skill')
    check('an unknown skill raises', False, True)
except KeyError as e:
    check('an unknown skill raises', True, True)
    check('and the error lists what it does have', 'boom' in str(e), True)

# ── composition: capability from vantage, not from size ──────────────────────────
print('\nnova composes a fleet')


def worker(goal, n):
    st = {'i': 0}

    def act(ctx):
        st['i'] += 1
        return {'goal': goal, 'progress': 'advancing',
                'distance': max(0, n - st['i']), 'done': st['i'] >= n}
    return act


nv = Nova(goal='ship the auth fix and the benchmark')
out = nv.compose({'a': worker('fix the auth bug in session handling', 6),
                  'b': worker('fix the session auth bug', 6),
                  'c': worker('benchmark the cache layer', 4)}, max_steps=8)
me = out.pop('_nova')
check('every member ran', all(c['steps'] > 0 for c in out.values()), True)
# The claim composition actually supports: a finding no member could have produced. Two
# agents on one ground are each perfectly grounded and correct at every step, however
# capable they are — the duplication exists only as a relation.
check('it saw what no member could', me['seen_only_from_above'] >= 1, True)
check('and named the pair', sorted(me['collisions'][0]['agents']), ['a', 'b'])
# The manager is not exempt from the instrument it manages with.
check('nova stayed measured', me['verdict'].reason in ('grounded', 'advancing'), True)
check('and its ground held', nv.ground_intact(), True)
# Composing is a skill use like any other: supervision that leaves no trace is unauditable.
check('composing is on the record',
      any(e.name == 'compose' for e in nv.events), True)

# A fleet with nothing in common yields nothing from above — the metric must be able to
# read zero, or it is measuring the act of looking rather than what was seen.
nv2 = Nova(goal='x')
o2 = nv2.compose({'a': worker('write the parser', 3), 'b': worker('tune the cache', 3)},
                 max_steps=5)
check('unrelated work yields nothing from above', o2['_nova']['seen_only_from_above'], 0)

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
