"""Catch signatures — drift in how an agent VERIFIES, not in what it says it is doing.

Written 2026-07-27 as a prototype, saying so here: "not exported from __init__, not
published." Fixed 2026-07-28 — everything below is in __all__ now, on both axes, after
an audit found the opposite failure this docstring used to warn about elsewhere: a set of
six split down the middle, three reachable only as `laserbrain.catches.unfalsified`. No
test failed on that split; the package still imported, every name still resolved, and the
only symptom was that three of them were invisible. This paragraph is the fix for the
same thing happening to this file's own claim about itself.

The eight modes read the state an agent spells for itself. That is self-report, and
laserbrain's own documentation says self-report is the weak signal — an agent that is
confidently wrong spells a perfectly grounded state. Everything here is computed from
OBSERVED events instead: what tools returned, whether a check ever failed, whether code
was executed before being described. An agent cannot spell its way past any of it.

All six signatures from phronesis-world/PROTOCOL.md are implemented. Three read an event
log — unfalsified, instrument_blind, unrun — and are reachable through catches(). The
other three need an input an event log does not carry, so they are called directly:
residue takes a transform, contaminated takes a piece of output, stale_gate takes a gate
and a mutation. Every one has a test that fires on the incident that produced it and a
test that stays silent on the clean case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Sequence

Kind = Literal['check', 'tool', 'claim', 'edit']


@dataclass
class Event:
    """One observed thing. Deliberately not the agent's opinion of it.

    kind='check'  name=<what was checked>  ok=<did it pass>
    kind='tool'   name=<tool>              result=<what came back>
    kind='claim'  name=<subject>           text=<the assertion made>
    kind='edit'   name=<file>              sites=<how many places changed>
    """
    kind: Kind
    name: str
    ok: bool | None = None
    result: Any = None
    text: str = ''
    sites: int = 0


@dataclass
class Catch:
    signature: str
    detail: str
    evidence: list[str] = field(default_factory=list)

    def __str__(self) -> str:                      # pragma: no cover - display only
        return f'{self.signature}: {self.detail}'


# A tool result that carries no information. The browser pane returned every one of
# these on 2026-07-27 while the page it was pointed at was fine.
_DEGENERATE = (None, '', 0, [], {}, 'blank', 'empty')


def _degenerate(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if v in _DEGENERATE:
        return True
    if isinstance(v, dict):
        # {'y': 0, 'vh': 0} — the shape that meant "no viewport", read four times as
        # "the page is broken".
        return bool(v) and all(x in (0, None, '') for x in v.values())
    return False


def unfalsified(events: Sequence[Event]) -> list[Catch]:
    """A check cited as evidence that has never once been red.

    Rule 1. The grain guard tested `'sheet-grain' in source` and matched a comment
    saying "see .sheet-grain below". It passed on a page with no grain. It had never
    failed, so nothing about it was evidence.
    """
    seen: dict[str, list[bool]] = {}
    for e in events:
        if e.kind == 'check' and e.ok is not None:
            seen.setdefault(e.name, []).append(e.ok)
    out = []
    for name, results in seen.items():
        if results and all(results):
            out.append(Catch(
                'unfalsified',
                f'{name!r} has passed {len(results)}× and never failed — break it and watch it go red',
                [f'{name}: {len(results)} pass, 0 fail'],
            ))
    return out


def instrument_blind(events: Sequence[Event], repeats: int = 3) -> list[Catch]:
    """The same tool returning the same empty answer, over and over, believed each time.

    Rule 4. Four blank screenshots in a row were each read as a fact about the page.
    The viewport was 0px tall.
    """
    runs: dict[str, int] = {}
    out: list[Catch] = []
    for e in events:
        if e.kind != 'tool':
            continue
        if _degenerate(e.result):
            runs[e.name] = runs.get(e.name, 0) + 1
            if runs[e.name] == repeats:
                out.append(Catch(
                    'instrument-blind',
                    f'{e.name!r} returned nothing {repeats}× running — check the instrument before the subject',
                    [f'{e.name} -> {e.result!r}'] * repeats,
                ))
        else:
            runs[e.name] = 0
    return out


def unrun(events: Sequence[Event]) -> list[Catch]:
    """A claim about what code does, with no execution of it anywhere in the log.

    Rule 5. I read the SDK and published "four hold, four interrupt" in three places.
    Running it showed two of the eight are two-strike.
    """
    ran = {e.name for e in events if e.kind == 'tool' and not _degenerate(e.result)}
    out = []
    for e in events:
        if e.kind == 'claim' and e.name not in ran:
            out.append(Catch(
                'unrun',
                f'claim about {e.name!r} with nothing executed against it — run behaviour, do not read it',
                [e.text[:120]],
            ))
    return out


DETECTORS = (unfalsified, instrument_blind, unrun)   # the event-log three; the
# other three each need an input an event log does not carry — a transform, a piece
# of output, or a gate — so they are called directly rather than from catches().


def catches(events: Iterable[Event]) -> list[Catch]:
    """Every catch signature present in an event log."""
    evs = list(events)
    return [c for d in DETECTORS for c in d(evs)]

# ── the three that were named and unimplemented ───────────────────────────────
# Written 2026-07-27. They were left as a comment saying "no idea how to compute this
# yet", which was honest and also a standing invitation to never look again. Two turned
# out to be computable once the input was the right shape; the third needed the question
# rephrased rather than answered.

import re as _re


def residue(before: str, after: str, pattern: str, flags: int = 0) -> list[Catch]:
    """What a bulk transform did NOT touch — rule 3.

    The input is the transform, not the event log, which is why this sat unimplemented:
    a detector over events cannot see what a sweep skipped. Given the text before, the
    text after, and the pattern the sweep matched, the residue is every occurrence that
    still matches — the ones the rule was right about three times in four.

    This is the `#3a93c9` case: a case-sensitive colour sweep that was correct for three
    uses and wrong for the fourth, which shipped at 3.03:1.
    """
    left = [m.group(0) for m in _re.finditer(pattern, after, flags)]
    if not left:
        return []
    changed = len(_re.findall(pattern, before, flags)) - len(left)
    uniq = sorted(set(left))
    return [Catch(
        'residue',
        f'the sweep changed {changed} and left {len(left)} still matching — justify each',
        uniq[:12],
    )]


# Anything that has no business being read by whoever receives the output. The build-gate
# version of this scans HTML; the shapes below are language-agnostic, so the same rule
# covers a commit message, a report, or a page.
_CONTAMINANTS = (
    (r'/\*[\s\S]{0,400}?\*/', 'a block comment'),
    (r'\b(?:TODO|FIXME|XXX|HACK)\b[:\s]', 'a work note'),
    (r'\blorem ipsum\b', 'placeholder text'),
    (r'\b(?:PLACEHOLDER|REPLACE ME|TBD)\b', 'an unreplaced placeholder'),
    (r'\[object Object\]', 'a stringified object'),
    (r'>\s*(?:undefined|null|NaN)\s*<', 'a leaked value'),
)


def contaminated(text: str) -> list[Catch]:
    """Authoring residue in something that gets shown to someone — rule 2.

    Generalised from the build gate that caught nine lines of my own commentary printing
    on a live page. The gate checks HTML; this checks any string, which is the version
    that applies to output an agent produces rather than to a site.
    """
    out = []
    for pat, why in _CONTAMINANTS:
        for m in _re.finditer(pat, text, _re.I):
            sample = ' '.join(m.group(0).split())[:64]
            out.append(Catch('contaminated', f'{why} is visible in the output', [sample]))
            break
    return out


def stale_gate(gate, mutate, sample) -> list[Catch]:
    """A check that survives a mutation it should have caught — rule 6.

    The original note said "needs the gate's model and the system's shape side by side.
    No idea how to compute this yet." That was the wrong question. You cannot compare a
    gate to reality, but you CAN break reality on purpose and see whether the gate
    notices — which is rule 1 turned into a function.

    `gate(x) -> bool` passes, `mutate(x)` returns a version that should fail. A gate that
    still passes the mutant has stopped watching the thing it names.
    """
    out = []
    if not gate(sample):
        return [Catch('stale-gate', 'the gate fails its own clean sample — it is broken, not stale', [])]
    mutant = mutate(sample)
    if gate(mutant):
        out.append(Catch(
            'stale-gate',
            'the gate still passes a deliberately broken input — it is green for a reason '
            'other than the thing being correct',
            [str(mutant)[:80]],
        ))
    return out
