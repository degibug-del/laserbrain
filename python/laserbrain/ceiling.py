"""ceiling.py — the introspection ceiling, as a reading on an agent's own words.

    from laserbrain.ceiling import mark

    mark('advancing because the fix should work')
    # {'cause': 2, 'observation': 0, 'grounded': 0.0, ...}

WHAT THIS IS
------------
The instrument at phronesis.world/field/ceiling tints two kinds of language in a human
self-explanation: CAUSE-CLAIMS (because, that's why, must have been) and OBSERVATIONS
(i noticed, i felt, at the time). The distinction is Nisbett & Wilson (1977): people
report causes for their own behaviour confidently and wrongly. A cause-claim can be
true — introspection just cannot certify it. Observations are where the speaker's
authority actually is.

An agent has exactly the same ceiling, and the harness already names it. `anchored` says
how much of Φ rests outside the agent's own account of itself, and its `corroborated`
rule reads: "An agent reporting `advancing` with a falling distance and no successful
work behind it is making a claim with nothing under it." That is a cause-claim, detected
through events. This detects the same thing through LANGUAGE, which is available a step
earlier — before any event evidence exists, and when no events will ever exist.

WHY IT IS A SECOND SIGNAL AND NOT A REPLACEMENT
----------------------------------------------
`anchored` and this reading disagree in both directions, and the disagreements are the
useful part:

  · an agent that ran nothing but wrote pure observation ("read the file, saw 3 rows")
    is unanchored by events and grounded in language — it is reporting, not claiming.
  · an agent whose tests genuinely passed but who writes "this should fix it" is
    corroborated by events and making a claim in language.

Neither is wrong. They measure different things, which is why this gets its own slot
rather than being folded into `anchored` — and why, like `anchored`, it is REPORTED AND
NEVER FOLDED INTO Φ. Moving Φ would invalidate every published calibration and drift
vector, and there is no data yet behind any particular weight.

WHAT IT CANNOT DO
-----------------
It is a regex over a fixed phrase list, and it inherits every limitation the browser
instrument already declares about itself. It reads "since" in both its causal and its
temporal sense and cannot tell them apart. It misses paraphrase entirely. It marks
LANGUAGE, NOT TRUTH: a cause-claim can be correct and an observation can be fabricated.
A low `grounded` score is a prompt to look, never a finding on its own.

THE LISTS LIVE IN grammar.json
------------------------------
Because a SECOND implementation reads them: lasermind/mcp-server.mjs runs the same marker
in JavaScript. That is the rule operator_patterns set — a list stays local until two
things need it, then it moves rather than becoming two lists that drift.

They were promoted once before this and moved straight back, on a reader that had not
been written yet. A canonical list with one reader buys nothing and costs a version bump,
a four-way sync and two deploys; the build gate went red on exactly that. The reader
exists now.

The SDK reads purely from the grammar, with no local fallback, because grammar.json ships
INSIDE the wheel — it cannot be absent. The MCP server keeps a built-in floor instead,
because it must run with no grammar file at all.
"""
from __future__ import annotations

import re

__all__ = ['mark', 'CAUSE_PATTERNS', 'OBSERVATION_PATTERNS']

# Read from the grammar, never retyped. `_G` is the parsed grammar.json that ships inside
# the wheel, so the package always carries its own copy — no filesystem lookup, and no
# offline case to fall back for.
def _patterns():
    from . import _G
    raw = _G.get('ceiling_patterns') or {}
    return list(raw.get('cause') or []), list(raw.get('observation') or [])


CAUSE_PATTERNS, OBSERVATION_PATTERNS = _patterns()


def _compile():
    """None when either list is empty — deliberately, and this is the important case.

    An empty list joins to '' and `\b(?:()|())\b` is a PERFECTLY VALID regex that matches
    the empty string at every word boundary. On one ordinary sentence that is sixteen
    matches, every one of them scored as a cause-claim, producing `grounded: 0.0` — a
    confident "this agent is making pure cause-claims" about text containing none. Not an
    error, not a crash, just a fabricated finding.

    The MCP server's normaliser carries a built-in floor for exactly this reason and says
    why: "a fallback that degrades to nothing is not a fallback." The same trap is here,
    and the honest answer is different in this file — the SDK's grammar.json ships inside
    the wheel, so its absence means a broken install rather than an offline run, and
    inventing a floor would quietly paper over that. So the marker reports what is
    actually true: it read nothing.
    """
    if not CAUSE_PATTERNS or not OBSERVATION_PATTERNS:
        return None
    cause = '|'.join(CAUSE_PATTERNS)
    obs = '|'.join(OBSERVATION_PATTERNS)
    return re.compile(rf'\b(?:({cause})|({obs}))\b', re.I)


_RE = _compile()

#: False when the shipped grammar carried no ceiling_patterns — the reading is unavailable
#: rather than zero. Exposed so a caller can tell "no patterns to read with" apart from
#: "nothing matched", which `mark` cannot distinguish in its return value alone.
AVAILABLE = _RE is not None


def mark(*texts) -> dict:
    """Count cause-claims and observations across one or more free-text fields.

    Pure: same text in, same counts out. Accepts several fields (doing, next, blocked)
    because the reading is about the agent's whole account of this step, not any one slot.

    `grounded` is observations / (causes + observations) — 1.0 is pure report, 0.0 is
    pure claim. It is None when neither fires, and that None is deliberate: a step whose
    text contains no marked phrase at all has not been measured, and reporting 0.0 for it
    would say "entirely cause-claims" about something the marker simply did not read.
    Silence is not a score.

    CHECK IT WITH `is None`. None and 0.0 are both falsy, so a truthiness test collapses
    "read nothing" into "pure claim" and loses the one distinction this return value
    exists to make.
    """
    if _RE is None:
        # No patterns, so nothing was read. Same shape as "nothing matched", because that
        # is what happened — reporting counts here would be inventing them.
        return {'cause': 0, 'observation': 0, 'grounded': None, 'hits': []}
    joined = ' '.join(str(t) for t in texts if t)
    cause = obs = 0
    hits = []
    for m in _RE.finditer(joined):
        if m.group(1) is not None:
            cause += 1
            hits.append(('cause', m.group(0).lower()))
        else:
            obs += 1
            hits.append(('observation', m.group(0).lower()))
    total = cause + obs
    return {
        'cause': cause,
        'observation': obs,
        'grounded': round(obs / total, 2) if total else None,
        # What it actually matched, so a surprising score can be argued with rather than
        # taken on faith. Same reason Verdict carries `why`.
        'hits': hits,
    }
