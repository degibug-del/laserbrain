#!/usr/bin/env python3
"""Offline tests for the async act layer + the run report (no key, no model calls)."""
import asyncio
from laserbrain import Harness

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


async def agent(ctx):
    if ctx.get("return"):
        ctx["returned"] = True
    if ctx.get("returned"):
        ctx["d"] = max(0, ctx.get("d", 5) - 2)               # recovering after the return
    else:
        i = ctx.get("i", 0); ctx["i"] = i + 1
        ctx["d"] = [7, 6, 5][min(i, 2)]                       # then plateaus at 5 → stalls
    await asyncio.sleep(0)                                    # real async agents await here
    return dict(goal="build the JSON parser", progress="advancing", distance=ctx["d"])


async def _main():
    hz = Harness()
    fired = []

    async def on_return(v, ctx):                              # a coroutine callback
        fired.append(v.reason)

    ctx = await hz.arun(agent, max_steps=15, on_return=on_return)
    show("arun closes the loop (async step + async callback)", ctx["d"] == 0 and ctx["returns"] == 1,
         f"finished at {ctx['d']} after {ctx['returns']} return(s)")
    show("async on_return fired", len(fired) == 1, f"fired={fired}")
    rep = hz.report()
    show("report summarizes the run", "drift(s)" in rep and "Φ" in rep and "▁" in rep or "█" in rep)
    show("report is empty on a fresh harness", Harness().report() == "laserbrain · no checks yet")


asyncio.run(_main())
print("\n" + ("ALL ASYNC TESTS PASS ✓" if ok else "SOME FAILED ✗"))
raise SystemExit(0 if ok else 1)
