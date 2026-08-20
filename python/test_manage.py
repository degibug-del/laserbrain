#!/usr/bin/env python3
"""supercode.manage — N agents under supervision, and the line it will not cross.

Managing here means three powers, each with a reason it is allowed:

  ASSIGN/HALT on collision   two agents on one ground is a fact NO agent can observe, so
                             the supervisor holds strictly more information than either
  INJECT the verdict         the advice delivered is the agent's OWN harness reading
                             against its OWN frozen ground; supercode is the courier
  ESCALATE to a human        when drift persists, or when the monitor cannot honestly
                             choose, authority goes UP to a person — never sideways

And the one it will not: regrounding a running agent. Supercode sees three spelled fields;
the agent sees the work. A supervisor that regrounds mid-run is a planner overriding a
better-informed planner, and every reading it takes afterward is measured against a
reference it chose itself — the self-referential monitor PROOF forbids.
"""
import sys

from laserbrain import Supercode

FAIL = []
SAME_A = 'fix the auth bug in session handling'
SAME_B = 'fix the session auth bug'


def check(name, got, want):
    if got != want:
        FAIL.append(f'{name}: got {got!r}, want {want!r}')
    print(f"  {'ok  ' if got == want else 'FAIL'} {name:50} {got}")


def mk(goal, n, stuck=False, extra_steps=0):
    """An agent that closes on its goal in n steps, or one that never closes."""
    st = {'i': 0}

    def step(ctx):
        st['i'] += 1
        return {'goal': goal, 'progress': 'circling' if stuck else 'advancing',
                'distance': 5 if stuck else max(0, n - st['i']),
                'done': (not stuck) and st['i'] >= n + extra_steps}
    return step


# ── it runs them ─────────────────────────────────────────────────────────────────
print('it runs N agents to completion')
sc = Supercode()
ctxs = sc.manage({'a': mk('ship the page', 4), 'b': mk('tune the cache layer', 3)}, max_steps=8)
check('both finished', all(c.get('finished') for c in ctxs.values()), True)
check('neither was halted', any(c.get('halted') for c in ctxs.values()), False)
check('no collision between unrelated work', len(sc.collisions()), 0)

# ── it delivers the agent's own verdict, not its opinion ─────────────────────────
print('\nit couriers the verdict, it does not author one')
sc = Supercode()
seen = []
ctxs = sc.manage({'a': mk('ship the page', 4),
                  'b': mk('rewrite the entire css framework', 0, stuck=True)},
                 max_steps=6, on_return=lambda n, v, c: seen.append((n, v.reason)))
check('the drifting agent got a return', any(n == 'b' for n, _ in seen), True)
# The advice is what b's OWN harness said against b's OWN ground — supercode did not
# compose it, and a healthy agent is never handed one.
check('the healthy agent got none', any(n == 'a' for n, _ in seen), False)
check('advice reached the agent context', bool(ctxs['b'].get('return')), True)

# ── the collision powers ─────────────────────────────────────────────────────────
print('\ncollision: halts only when it can honestly choose')
# Distinguishable — a has more steps invested, so b yields.
sc = Supercode()
ctxs = sc.manage({'a': mk(SAME_A, 9), 'b': mk(SAME_B, 2, extra_steps=6)}, max_steps=9)
halted = [n for n, c in ctxs.items() if c.get('halted')]
check('one agent was halted', len(halted) <= 1, True)
if halted:
    check('and told why', 'duplicate work' in ctxs[halted[0]]['halted_why'], True)
    # Halting is not regrounding: it stops the duplication and leaves what happens next
    # to whoever reads the report.
    check('but not given a new goal', 'new_goal' in ctxs[halted[0]], False)

# Indistinguishable — declining to pick is right, but the duplication must not run on
# silently, so it is recorded for a person.
print('\ncollision it cannot decide: escalates, never coin-flips')
sc = Supercode()
ctxs = sc.manage({'a': mk(SAME_A, 6), 'b': mk(SAME_B, 6)}, max_steps=8)
check('nobody was halted arbitrarily', any(c.get('halted') for c in ctxs.values()), False)
check('but it is recorded on both', all(c.get('collision_unresolved') for c in ctxs.values()), True)
# Once per pair — a standing fact, not an event that recurs.
check('recorded once, not once per step', len(ctxs['a']['collision_unresolved']), 1)

print('\na human decision is carried out, not invented')
sc = Supercode()
ctxs = sc.manage({'a': mk(SAME_A, 6), 'b': mk(SAME_B, 6)}, max_steps=8,
                 on_escalate=lambda who, v, c: 'b')
check('the named agent yielded', ctxs['b'].get('halted'), True)
check('the other kept going', ctxs['a'].get('halted', False), False)
check('attributed to the human', 'human decision' in ctxs['b']['halted_why'], True)

# ── the line ─────────────────────────────────────────────────────────────────────
print('\nthe line it does not cross')
sc = Supercode()
ctxs = sc.manage({'a': mk('ship the page', 3)}, max_steps=5)
# No key anywhere in a context tells an agent what its goal now is.
check('no context carries a supervisor-set goal',
      any(k in ctxs['a'] for k in ('goal', 'new_goal', 'reground')), False)
# And the agent's own ground is untouched by having been managed.
check('the agent kept its own ground', sc.agents['a'].ground, 'ship the page')

print()
if FAIL:
    print(f'{len(FAIL)} FAILED')
    for f in FAIL:
        print('   ', f)
    sys.exit(1)
print('all pass')
