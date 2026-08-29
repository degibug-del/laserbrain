# demos

Three of them, smallest first. None needs a key. Two need no network at all.

```bash
python3 demos/01_two_references.py    # the argument
python3 demos/02_refused.py           # the intervention
bash    demos/03_hosted.sh            # the hosted service, no account
```

## Why these three

laserbrain is hard to demonstrate for a reason worth stating plainly: **drift has no moment.**
Every frame of a drifting agent looks like an agent working, because it is one. The wrongness
is not in any step — it lives in the relation between the step in front of you and an
instruction that scrolled off the screen twenty minutes ago. You cannot film that.

So none of these tries to. What they show instead is the **reference**, and what changes when
you keep it.

### 01 — the same measurement, two references, opposite answers

One agent, five steps, sliding from *fix the failing auth test* to *redesign the session store
schema*. Scored twice by the same detector: once against the goal it started with, once
against the goal from the previous step, which is what any sliding-window monitor is really
doing.

The frozen reference climbs and fires. The neighbour reference sits flat around Φ 0.30 and
never fires — it reports the same mild displacement for the session-store redesign as it did
while the agent was still fixing the auth test. That is not a window that needs tuning. A
reference that moves with the work cannot measure the work.

This is the only artifact here that is an argument rather than an anecdote, and it is the one
to run first.

### 02 — a write that does not happen

The same slide, with an `Operator` holding the hands and an authorizer that **says yes to
everything**. The third write still does not happen: `Operator` reads the ground before it
reads the policy, so an irreversible act proposed off-ground is refused without the question
ever reaching whoever would have approved it. Watch the counter — the authorizer is asked
twice, not three times.

### 03 — the hosted detector, with no account

01 and 02 run entirely on your machine, which proves nothing about whether the service is up.
This calls it: `POST /v1/check`, no `Authorization` header, ground passed in the body, nothing
retained. A hundred calls a day from one address.

If it reports HTTP 401 the Worker predates the endpoint and has not been redeployed; the
script says so and tells you how to point it at a local build instead.

## What these demos do not claim

Measured precision on `goal-drift` is **14.6%**, and the one controlled study run on laserbrain
returned a null result — both published at <https://phronesis.world/laserbrain/evidence>.

That number is why the free and offline paths exist. Every demo here is reproducible on your
own inputs precisely so the question stops being *do you believe the vendor* and becomes *what
does it do on my work*. Edit the `RUN` list at the top of 01 and 02 and run them again; that is
the intended use, not a workaround.

One distinction the site used to blur, kept straight here: `Operator` refuses on the verdict.
The `PreToolUse` hook that ships with this package (`laserbrain.hooks.lb_gate`) has
historically refused on **coverage** — have you checked recently enough — and not on the
verdict at all. Since 2026-08-27 it reads the verdict too, but in shadow mode by default: it
records what it would have refused and blocks nothing. `LASERBRAIN_GATE_ON_DRIFT=deny`
enforces it. Two surfaces, two behaviours.

## Reference

- API reference — <https://phronesis.world/laserbrain/api>
- OpenAPI 3.1 — <https://api.phronesis.world/v1/openapi.json>
- Evidence, including the null — <https://phronesis.world/laserbrain/evidence>
