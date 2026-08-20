"""The observed channel, fed by the runtime instead of by the caller remembering.

WHY, 2026-08-06

`saw()` was built so a self-report could be corroborated by observed work, shipped, and then
called by almost nothing. The consequence was not a missing feature — it was that `anchored`
sat structurally broken for its entire life, returning 0.5 forever, and nobody noticed
because nothing depended on it enough to look. An opt-in mechanism is a mechanism that is
off.

The information was never missing. `runtime.Session` records every tool call and whether it
failed; it simply had no wire to the harness's evidence channel. Two halves of one package
that did not talk.

THE SAME FILE THE SERVER ALREADY USES. lasermind/mcp-server.mjs solved this a week earlier
with a counter at `<root>/config/evidence.json`, filled by a PostToolUse hook and read by
`anchored()`. Sharing the path and the shape means a machine running both surfaces has ONE
observed channel rather than two that disagree, and the SDK inherits a channel that is
already being filled.

CORROBORATION IS AN ADVANCE, NOT A TOTAL, and that is what makes this safe to default on. A
stale file corroborates nothing: the harness records the count it saw at the previous check
and asks whether it has moved since. A counter left over from other work on the same machine
cannot lend credibility to a run that is doing nothing — only work happening BETWEEN two
checks counts, which is exactly the claim `anchored` makes.

FAIL OPEN, ALWAYS. Every function here swallows its errors and reports "nothing observed".
An unreadable counter must degrade to the old behaviour — the agent's own account, honestly
labelled as such — and never to an exception in the middle of someone's agent loop.
"""
import json
import os

from ._paths import config


def _path():
    return config('evidence.json')


def bump(ok=True):
    """Record one observed outcome. Called by the runtime, not by the agent."""
    p = _path()
    try:
        try:
            d = json.loads(p.read_text())
        except Exception:
            d = {}
        d['ok'] = int(d.get('ok', 0)) + (1 if ok else 0)
        d['fail'] = int(d.get('fail', 0)) + (0 if ok else 1)
        # Written whole and replaced, not appended: two writers racing on a counter lose an
        # increment at worst, and an increment is not a judgment. The contexts store needed a
        # lock because a dropped write there SUPPRESSES a verdict; here it delays one.
        tmp = p.with_suffix('.tmp')
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(d))
        os.replace(tmp, p)
    except Exception:
        pass
    return None


def count():
    """(ok, fail) as recorded so far, or (0, 0) when the channel is dark."""
    try:
        d = json.loads(_path().read_text())
        return int(d.get('ok', 0)), int(d.get('fail', 0))
    except Exception:
        return 0, 0


def live():
    """Has anything ever been recorded here? Distinguishes 'dark' from 'observed nothing'."""
    ok, fail = count()
    return (ok + fail) > 0
