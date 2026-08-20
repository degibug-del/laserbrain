#!/usr/bin/env python3
"""
laserbrain × LangGraph — a real, runnable graph (verified against LangGraph on
Python 3.14). No LLM or key: the agent node deterministically drifts to a different
goal, and laserbrain's node catches it and routes it back.

    pip install laserbrain langgraph
    python example_langgraph.py
"""
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from laserbrain.adapters import langgraph_node


class State(TypedDict):
    goal: str
    dist: int
    step: int
    laserbrain: Optional[object]   # the Verdict the laserbrain node writes


def agent(state: State) -> dict:
    """A stand-in for your real agent node. It wanders to a different goal on step
       2; when laserbrain flags it, it returns to the goal and makes progress."""
    step = state.get("step", 0) + 1
    verdict = state.get("laserbrain")
    if verdict is not None and verdict.drifting:
        return {"goal": "build the parser", "dist": max(0, state["dist"] - 3), "step": step}   # ← heed the return
    if step == 2:
        return {"goal": "write the marketing site instead", "dist": state["dist"], "step": step}  # ← drift
    return {"goal": "build the parser", "dist": max(0, state.get("dist", 6) - 1), "step": step}


# laserbrain as a graph node: you map your state to (goal, progress, distance).
lb = langgraph_node(extract=lambda s: (s["goal"], "advancing", s["dist"]))


def route(state: State) -> str:
    return END if state["dist"] <= 0 else "agent"   # branch on state["laserbrain"].drifting in real graphs


g = StateGraph(State)
g.add_node("agent", agent)
g.add_node("laserbrain", lb)
g.set_entry_point("agent")
g.add_edge("agent", "laserbrain")                    # check after every agent step
g.add_conditional_edges("laserbrain", route, {"agent": "agent", END: END})
app = g.compile()

if __name__ == "__main__":
    out = app.invoke({"goal": "build the parser", "dist": 6, "step": 0}, {"recursion_limit": 40})
    print(f"finished in {out['step']} steps · goal={out['goal']!r} · dist={out['dist']} · {out['laserbrain'].reason}")
    print("the agent left its goal for one step; laserbrain caught it and returned it, so the graph resolved.")
