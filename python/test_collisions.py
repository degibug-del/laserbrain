#!/usr/bin/env python3
"""Two agents on the same ground — the reading only a supervisor can take.

Every one of the nine verdicts is about ONE agent against ONE ground. So two agents handed
the same task are both perfectly grounded, both advancing, and both correct at every single
step. The duplication is invisible from inside either harness by construction, and no
threshold on Φ will ever surface it, because nothing has drifted. It exists only as a
relation between two runs.

That is what makes supercode a distinct job rather than a convenience wrapper around N
harnesses — and the first assertion below is the whole argument: zero findings, one
collision, on the same set of observations.
"""
import sys

from laserbrain import Supercode

FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:52} {got}")


def run(jobs, steps=2):
    sc = Supercode()
    for _ in range(steps):
        for agent, goal in jobs:
            sc.observe(agent=agent, goal=goal, progress='advancing', distance=4)
    return sc


# ── the argument ─────────────────────────────────────────────────────────────────
print('the same job, given to two agents')
sc = run([('a', 'fix the auth bug in session handling'),
          ('b', 'fix the session auth bug'),
          ('c', 'benchmark the cache layer')])
# Agent names here are 'a'/'b'/'c' on purpose: a fixture should not borrow the name of a
# real agent, or a reader cannot tell which parts of it are claims about this system.
cols = sc.collisions()
check('no single-agent finding — nothing has drifted', len(sc.findings()), 0)
check('one collision', len(cols), 1)
check('it names the right pair', sorted(cols[0]['agents']), ['a', 'b'])
check('and not the unrelated agent', 'c' in cols[0]['agents'], False)

# ── what must NOT read as a collision ────────────────────────────────────────────
print('\nnot collisions')
# Sharing vocabulary is not sharing a job. These both concern the parser and are still
# two different pieces of work — the threshold sits at 0.60 for exactly this case.
check('shared words, different jobs',
      len(run([('a', 'write the parser tests'), ('b', 'write the parser docs')])
          .collisions()), 0)
check('unrelated work', len(run([('a', 'ship the page'), ('b', 'tune the cache')]).collisions()), 0)
check('one agent alone', len(run([('a', 'ship the page')]).collisions()), 0)
check('no agents at all', len(Supercode().collisions()), 0)

# A goal that normalises to nothing cannot collide with anything — every word is a
# stopword, so the overlap is undefined rather than total.
sc = Supercode()
sc.observe(agent='a', goal='the a an of', progress='advancing', distance=4)
sc.observe(agent='b', goal='to and or for', progress='advancing', distance=4)
check('goals that normalise to nothing', len(sc.collisions()), 0)

# ── the ground is what counts, not the current goal ──────────────────────────────
print('\ncompared on grounds, not on current goals')
# Two agents whose CURRENT goals touch for one step are just two agents in the same file.
# A collision is a fact about how the work was divided, so it reads the fixed ground.
sc = Supercode()
sc.observe(agent='a', goal='write the parser', progress='advancing', distance=5)
sc.observe(agent='b', goal='tune the cache layer', progress='advancing', distance=5)
sc.observe(agent='a', goal='write the parser', progress='advancing', distance=4)
sc.observe(agent='b', goal='write the parser', progress='advancing', distance=4)   # wandered in
check('a momentary overlap is not a collision', len(sc.collisions()), 0)
# ...though b HAS now left its own ground, which is the single-agent verdict's job.
check('the single-agent instrument catches that instead',
      any(r['agent'] == 'b' for r in sc.findings()), True)

# ── it is reported, never acted on ───────────────────────────────────────────────
print('\nadvisory')
sc = run([('a', 'fix the auth bug in session handling'), ('b', 'fix the session auth bug')])
check('collision appears in the report', 'same job' in sc.report(), True)
check('report says the run is otherwise clean',
      'every agent on its own ground' in sc.report(), True)
# The supervisor never gains authority to reground: findings stay findings.
check('no verdict was changed', sc.agents['a'].last.reason in ('grounded', 'advancing'), True)

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
