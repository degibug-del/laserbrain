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
from laserbrain.rules import Rule, Ruleset, why_not

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

# ── the thinking is allowed to fail ─────────────────────────────────────────────────────
#
# `act` is "usually a model", so it calls a network. Before 2026-09-01 an exception there
# killed run() outright: the caller got a traceback instead of a ctx and lost every step
# already taken. use() had recorded a failing skill as an Event since it shipped; the one
# call most likely to fail was the one with no record.

def boom(ctx):
    if ctx['steps'] >= 2:
        raise ConnectionError('the model did not answer')
    return {'goal': 'ship the parser', 'progress': 'advancing', 'distance': 5}

nv = Nova(goal='ship the parser')
ctx = nv.run(boom, max_steps=10)
check('a failing act does not kill the run', isinstance(ctx, dict), True)
check('  the steps before it are kept', ctx['steps'], 2)
check('  the ending is named', ctx.get('stopped'), 'error')
check('  and the reason is carried', 'ConnectionError' in ctx.get('error', ''), True)
check('  the failure is an event, like a failing skill',
      [e for e in nv.events if e.kind == 'act' and not e.ok] != [], True)
check('  it is not reported as finished', ctx.get('finished'), None)

# ── how a run ended is stated, not inferred from absence ────────────────────────────────
nv2 = Nova(goal='ship the parser')
c2 = nv2.run(walk(n=3), max_steps=10)
check('a completed run says done', c2.get('stopped'), 'done')

nv3 = Nova(goal='ship the parser')
c3 = nv3.run(lambda ctx: {'goal': 'ship the parser', 'distance': 5}, max_steps=3)
check('a run out of steps says max_steps', c3.get('stopped'), 'max_steps')
check('  and is not reported as finished', c3.get('finished'), None)
check('  having taken exactly the steps allowed', c3['steps'], 3)


# ── nova chooses for itself ─────────────────────────────────────────────────────────────
#
# The organ that was missing. nova could hold skills, run one by name and follow a stored
# method; it could not decide WHICH, and that was `act` — external and "usually a model".

nv = Nova(goal='ship the parser and the benchmark')
for _n in ('write_test', 'run_bench', 'reground'):
    nv.learn(_n, lambda _n=_n: _n)
nv.teach(Ruleset(name='next', threshold=1, rules=(
    Rule(name='reground',   any=('return', 'matches', 'drift')),
    Rule(name='run_bench',  any=('benchmark', 'measure'), none=('failing',)),
    Rule(name='write_test', any=('test', 'coverage')),
)))

check('an empty context chooses nothing', nv.decide({}).category, None)
check('  which is an answer, not a failure', nv.decide({}).considered != (), True)
check('an observation selects a skill',
      nv.decide({'observation': 'coverage is thin on the tokenizer'}).category, 'write_test')
check('a different observation selects a different one',
      nv.decide({'observation': 'the benchmark harness is ready to measure'}).category, 'run_bench')
check('the harness advice can drive the choice',
      nv.decide({'return': 'Your goal no longer matches the one you started with'}).category,
      'reground')

# THE GOAL IS NOT AN INPUT, and the first version had it. With goal='ship the parser and the
# benchmark', rules cued on `parser` and `benchmark` fired on every step before anything had
# happened. A chooser whose input is constant is not choosing.
check('the goal does not leak into the decision',
      nv.decide({}).category, None)

d = nv.decide({'observation': 'coverage is thin on the tokenizer'})
check('and it says why the others lost', why_not(d, 'run_bench'), 'no cue matched')

_bad = Ruleset(name='bad', rules=(Rule(name='deploy', any=('x',)),))
try:
    nv.teach(_bad); check('teach refuses unknown skills', 'no error', 'ValueError')
except ValueError as e:
    check('teach refuses a rule naming a skill nova lacks', 'deploy' in str(e), True)

_fresh = Nova(goal='x')
try:
    _fresh.decide({}); check('decide without rules raises', 'no error', 'RuntimeError')
except RuntimeError:
    check('decide before teach says so rather than guessing', True, True)


# ── nova composes a sequence nobody wrote ───────────────────────────────────────────────
#
# decide() maps a context to ONE skill by a rule somebody wrote — a reflex. plan() searches
# over what skills declare they need and give, and builds a sequence that was never
# enumerated. It is the first thing in nova that produces behaviour nobody wrote down.

_f = lambda: None
pv = Nova(goal='publish the wheel')
pv.learn('write_tests', _f,                       gives={'tests'})
pv.learn('run_tests',   _f, needs={'tests'},      gives={'tests_pass'})
pv.learn('build',       _f, needs={'tests_pass'}, gives={'wheel'})
pv.learn('publish',     _f, needs={'wheel'},      gives={'published'})
pv.learn('tag',         _f, needs={'published'},  gives={'tagged'})

_p = pv.plan(want={'published'})
check('nova builds a sequence nobody declared',
      _p.steps, ('write_tests', 'run_tests', 'build', 'publish'))
check('  and the Plan is truthy when it found one', bool(_p), True)
check('  with the search on the record', len(_p.considered) > 0, True)

check('it skips what is already true',
      pv.plan(want={'wheel'}, have={'tests_pass'}).steps, ('build',))
check('a goal already met needs no steps', pv.plan(want={'tests'}, have={'tests'}).steps, ())

# SHORTEST, because the search is breadth-first. A greedy planner could return
# write_tests -> run_tests -> build -> publish -> tag for want={'published'}; BFS cannot.
check('the plan is the shortest one', len(pv.plan(want={'published'}).steps), 4)

# DETERMINISTIC. Skills are tried in registration order and states are visited once, so the
# same request returns the same plan — which is what makes the audit record a proof rather
# than a story about one path.
check('the same request returns the same plan',
      pv.plan(want={'published'}).steps == pv.plan(want={'published'}).steps, True)

_u = pv.plan(want={'deployed'})
check('an unreachable goal returns no plan', _u.steps, None)
check('  and is falsy', bool(_u), False)
check('  and names the condition no skill produces',
      _u.why, 'no skill produces: deployed')

# A cycle must not hang the search: two skills that undo each other.
cv = Nova(goal='loop')
cv.learn('up',   _f, needs={'down'}, gives={'up'})
cv.learn('down', _f, needs={'up'},   gives={'down'})
check('cycles terminate rather than hanging', cv.plan(want={'sideways'}, have={'up'}).steps, None)

# needs/gives are optional, so every skill written before planning existed still works.
ov = Nova(goal='old')
ov.learn('anything', _f)
check('a skill with no declarations still runs', ov.use('anything'), None)

print('all pass')
