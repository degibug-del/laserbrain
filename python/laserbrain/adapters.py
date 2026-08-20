"""
laserbrain.adapters — attach the harness to the popular agent frameworks.

laserbrain checks a fixed reference, so it needs the agent to *spell* its state.
Frameworks don't hand you that, so every adapter takes an `extract` you provide:

    extract(x) -> (goal:str, progress:'advancing'|'stuck'|'circling', distance:0..10)

Nothing here imports a framework. Each adapter returns a plain callable you pass
to the framework's own hook — a graph node, a step_callback, a per-step check — so
the frameworks stay optional: install only the one you use. The check still runs
locally and free; pass key=/run_id= (or your own Harness) to also retain history.

    from laserbrain.adapters import guard, langgraph_node, crewai_step_callback

    @guard                                  # step returns dict(goal=, progress=, distance=)
    def step(state): ...

    g.add_node('laserbrain', langgraph_node(extract=my_extract))     # LangGraph
    Agent(..., step_callback=crewai_step_callback(my_extract))        # CrewAI
    v = middleware(my_extract)(obj)          # anything else: one call per step
"""
from __future__ import annotations
from . import Harness, Verdict

__all__ = ['guard', 'langgraph_node', 'crewai_step_callback', 'middleware', 'dict_extract']

STATE_KEY = 'laserbrain'


def _harness(harness, key, run_id):
    return harness if harness is not None else Harness(key=key, run_id=run_id or 'run')


def dict_extract(x):
    """Default extractor: read (goal, progress, distance) from a dict or an object
       carrying those keys/attributes."""
    get = x.get if isinstance(x, dict) else (lambda k, d=None: getattr(x, k, d))
    return get('goal', ''), get('progress', 'advancing'), get('distance', 5)


# ── 1. generic decorator — the framework-agnostic core ─────────────────────────
def guard(fn=None, *, extract=None, harness=None, key=None, run_id=None, on_return=None):
    """Wrap any agent step. After it runs, laserbrain checks the result; the Verdict
       is attached (result['laserbrain'] when the result is a dict), and on drift
       on_return(verdict, result) is called if given.

           @guard                                    # result is dict(goal, progress, distance)
           def step(state): ...

           @guard(extract=lambda out: (out.goal, out.status, out.dist))
           def step(state): ...

       The wrapped function gains a `.harness` attribute for reset()/history."""
    hz = _harness(harness, key, run_id)
    ex = extract or dict_extract

    def wrap(f):
        def wrapped(*a, **k):
            out = f(*a, **k)
            g, p, d = ex(out)
            v = hz.check(g, p, d)
            if isinstance(out, dict):
                out[STATE_KEY] = v
            if v.drifting and on_return:
                on_return(v, out)
            return out
        wrapped.harness = hz
        return wrapped

    return wrap(fn) if callable(fn) else wrap


# ── 2. LangGraph — a node that writes the Verdict into graph state ─────────────
def langgraph_node(extract=None, harness=None, key=None, run_id=None, state_key=STATE_KEY):
    """Return a LangGraph node: state -> {state_key: Verdict}. Add it after your
       agent node and branch on the verdict with a conditional edge.

           g.add_node('laserbrain', langgraph_node(extract=my_extract))
           g.add_edge('agent', 'laserbrain')
           g.add_conditional_edges('laserbrain',
               lambda s: 'return' if s['laserbrain'].drifting else 'agent')

       On drift, state['laserbrain'].advice is the return-to-ground message to feed
       back into your agent node (your 'return' branch)."""
    hz = _harness(harness, key, run_id)
    ex = extract or dict_extract

    def node(state):
        g, p, d = ex(state)
        return {state_key: hz.check(g, p, d)}

    node.harness = hz
    return node


# ── 3. CrewAI — a step_callback that fires each agent step ─────────────────────
def crewai_step_callback(extract, harness=None, key=None, run_id=None, on_return=None):
    """Return a callback for CrewAI's step_callback=. It fires on each agent step;
       extract(step_output) -> (goal, progress, distance). On drift it calls
       on_return(verdict, step_output) — default prints the return advice.

           Agent(..., step_callback=crewai_step_callback(my_extract))
           Crew(...,  step_callback=crewai_step_callback(my_extract))"""
    hz = _harness(harness, key, run_id)
    on_return = on_return or (lambda v, o: print(f'[laserbrain] ↩ {v.reason}: {v.advice}'))

    def cb(step_output):
        try:
            g, p, d = extract(step_output)
        except Exception:
            return None
        v = hz.check(g, p, d)
        if v.drifting:
            on_return(v, step_output)
        return v

    cb.harness = hz
    return cb


# ── 4. generic middleware — one call per step, for anything else ───────────────
def middleware(extract=None, harness=None, key=None, run_id=None):
    """Return a per-step checker `check(x) -> Verdict` for any framework that gives
       you a hook (AutoGen reply functions, the OpenAI Agents SDK, a custom loop).
       Call it wherever a step completes; branch on verdict.drifting and feed
       verdict.advice back to steer the agent.

           lb = middleware(extract=my_extract)
           v = lb(step_output)
           if v.drifting: reinject(v.advice)"""
    hz = _harness(harness, key, run_id)
    ex = extract or dict_extract

    def check(x):
        g, p, d = ex(x)
        return hz.check(g, p, d)

    check.harness = hz
    return check
