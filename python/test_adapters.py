#!/usr/bin/env python3
"""Offline tests for the framework adapters — each simulates how its framework
would drive the adapter (no framework installed, no key, no model calls)."""
from laserbrain import guard, langgraph_node, crewai_step_callback, middleware

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# 1) @guard — a plain step that drifts off its goal. Verdict is attached; on_return fires.
print("== 1) @guard (generic decorator) ==")
seen = []


@guard(on_return=lambda v, out: seen.append(v.reason))
def step(state):
    return dict(goal=state['goal'], progress='advancing', distance=state['d'])


step({'goal': 'build the parser', 'd': 6})            # ground
r1 = step({'goal': 'build the parser', 'd': 5})       # advancing
r2 = step({'goal': 'write a poem instead', 'd': 5})   # goal-drift
show('verdict attached to result', 'laserbrain' in r1 and r1['laserbrain'].reason == 'advancing')
show('drift caught + on_return fired', r2['laserbrain'].drifting and seen == ['goal-drift'],
     f"reason={r2['laserbrain'].reason}")

# 2) langgraph_node — drive the node by hand as a graph would, branching on the verdict.
print("\n== 2) langgraph_node (LangGraph) ==")
node = langgraph_node(extract=lambda s: (s['goal'], 'advancing', s['distance']))
route = lambda s: 'return' if s['laserbrain'].drifting else 'agent'
state = {'goal': 'index the corpus', 'distance': 7}
state.update(node(state))                              # ground
show('node returns a Verdict', hasattr(state['laserbrain'], 'drifting'))
state = {'goal': 'reorganize my inbox', 'distance': 7}  # a different goal → drift
state.update(node(state))
show('conditional edge routes to return on drift', route(state) == 'return',
     f"advice={state['laserbrain'].advice[:32]}…")

# 3) crewai_step_callback — CrewAI calls the callback with each step's output.
print("\n== 3) crewai_step_callback (CrewAI) ==")
fired = []
cb = crewai_step_callback(
    extract=lambda o: (o['goal'], o['status'], o['dist']),
    on_return=lambda v, o: fired.append(v.reason))
cb({'goal': 'summarize the deck', 'status': 'advancing', 'dist': 5})    # ground
cb({'goal': 'summarize the deck', 'status': 'circling', 'dist': 5})     # self-report
cb({'goal': 'summarize the deck', 'status': 'circling', 'dist': 5})     # sustained → return
show('callback fired on sustained self-report', any('self-report' in r for r in fired),
     f"fired={fired}")

# 4) middleware — a bare per-step checker for AutoGen / OpenAI Agents / a custom loop.
print("\n== 4) middleware (generic) ==")
lb = middleware(extract=lambda x: (x.goal, 'advancing', x.dist))


class Out:                                             # an arbitrary framework object
    def __init__(self, goal, dist): self.goal, self.dist = goal, dist


lb(Out('draft the RFC', 6))                            # ground
v = lb(Out('draft the RFC', 4))                        # advancing
show('reads goal/dist off an object', not v.drifting and v.reason == 'advancing')

print("\n" + ("ALL ADAPTERS PASS ✓" if ok else "SOME FAILED ✗"))
raise SystemExit(0 if ok else 1)
