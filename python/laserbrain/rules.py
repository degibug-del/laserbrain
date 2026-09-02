"""rules.py — English cue matching and rule classification, so nova can choose.

WHY THIS EXISTS. nova could hold skills, run one by name, execute a stored method and be
measured. It could not decide WHAT to do next: that was `act`, supplied by the caller and
"usually a model". This is the deterministic alternative — read the context, score it against
rules the caller declared, pick a skill, and be able to say why every other rule lost.

A SECOND IMPLEMENTATION, DELIBERATELY, and pinned like the first one. The reference is the
TypeScript in phronesis-world (lib/logic.ts and the Worker's morphology.ts), because that is
where it was written and tested. json/rule-vectors.json is generated FROM it, and
test_rules.py fails if this file disagrees with a single vector. That is the same arrangement
drift already has — three implementations, sixteen vectors, one gate — and it is the only
honest way to have the same computation in two languages. The alternative is two things with
one name, which this project has been bitten by five times.

Note the direction differs from drift: there Python is the reference and JS/TS follow. Here
TypeScript is the reference and Python follows. What matters is that ONE of them is named.

WHAT THE MATCHING IS. Real English morphology, not suffix-stripping:

    silent-e drop      move -> moving, moved, but only before a vowel-initial ending
    consonant doubling stop -> stopping, restricted to a consonant-vowel-consonant tail
                       and never on w/x/y, which do not double
    y -> i             try -> tried, but only after a consonant, so `play` keeps its y

and one syntactic check, negation scope: "I cannot see why" does not fire `see`.

Stemming was rejected for a reason worth keeping: strip the e from 'see' and 'se' matches
second, sense, seven. Suffixes are added to a whole cue instead of cutting it to a fragment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── the matcher ────────────────────────────────────────────────────────────────────────

#: Inflections only. `-ly` and `-ness` are included because cues are semantic rather than
#: syntactic: "stillness" is the ground cue as surely as "still" is.
SUFFIX = '(?:s|es|d|ed|ing|er|est|ly|ness)?'

#: Words that flip the cue after them. Contractions are spelled out because the tokenizer
#: splits on non-letters, so "cannot"/"can't"/"cant" all arrive as `cannot` or `can` + `t`.
NEGATORS = frozenset({
    'not', 'no', 'never', 'cannot', 'cant', 'dont', 'doesnt', 'didnt', 'wont', 'couldnt',
    'wouldnt', 'shouldnt', 'isnt', 'arent', 'wasnt', 'werent', 'without', 'nothing', 'nobody',
})

#: How far back a negator reaches. Three tokens covers "cannot see", "can not really see",
#: "don't ever see" — and stops before it starts swallowing the previous clause.
NEG_WINDOW = 3


def keyword_pattern(kw: str) -> re.Pattern:
    """The regex for one cue and its inflections. Mirrors keywordPattern in morphology.ts."""
    k = re.escape(kw.lower())
    forms = [f'{k}{SUFFIX}']
    if len(kw) > 2 and kw.endswith('e'):
        forms.append(f'{re.escape(kw[:-1])}(?:ing|ed|er|est)')
    if re.search(r'[^aeiou][aeiou][^aeiouwxy]$', kw, re.I):
        forms.append(f'{k}{re.escape(kw[-1])}(?:ing|ed|er|est)')
    if len(kw) > 2 and re.search(r'[^aeiou]y$', kw, re.I):
        forms.append(f'{re.escape(kw[:-1])}i(?:es|ed|er|est|ly|ness)')
    return re.compile(rf'\b(?:{"|".join(forms)})\b', re.I)


def matches_keyword(text: str, kw: str) -> bool:
    """Does the cue appear at all, in any inflection? Says nothing about negation."""
    return bool(keyword_pattern(kw).search(text or ''))


def cue_fires(text: str, kw: str) -> bool:
    """Does the cue appear UN-NEGATED? One un-negated occurrence is enough.

    "I cannot see why" contains `see` and does not fire it. Matching without this reads a
    sentence as evidence of the thing it denies.
    """
    if not matches_keyword(text, kw):
        return False
    tokens = [w.replace("'", '') for w in re.findall(r"[a-z']+", (text or '').lower())]
    pat = keyword_pattern(kw)
    for i, tok in enumerate(tokens):
        if not pat.fullmatch(tok):
            continue
        before = tokens[max(0, i - NEG_WINDOW):i]
        if not any(w in NEGATORS for w in before):
            return True
    return False


# ── rules ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    name: str
    any: tuple[str, ...] = ()      #: at least one must appear
    all: tuple[str, ...] = ()      #: every one must appear
    none: tuple[str, ...] = ()     #: any of these vetoes the rule
    weight: float = 1.0


@dataclass(frozen=True)
class Ruleset:
    name: str
    rules: tuple[Rule, ...]
    threshold: float = 1.0


@dataclass(frozen=True)
class Consideration:
    """Why a rule did or did not fire. EVERY rule gets one, fired or not — that is the whole
    point, and the thing a model cannot produce."""
    rule: str
    fired: bool
    score: float
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    blocked: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class Verdict:
    category: str | None
    score: float
    #: Gap to the runner-up. NOT a probability and deliberately not dressed as one. A margin
    #: of 0 means two rules tied and the tie was broken by declaration order.
    margin: float
    considered: tuple[Consideration, ...] = field(default=())


def _consider(text: str, rule: Rule) -> Consideration:
    # ORDER OF REPORTING IS THE ORDER OF DISQUALIFICATION, so `why` names the FIRST reason the
    # rule failed rather than a summary. A reviewer asking "why not this one" wants the
    # blocking term, not a list of everything that was fine.
    blocked = tuple(c for c in rule.none if matches_keyword(text, c))
    missing = tuple(c for c in rule.all if not matches_keyword(text, c))
    matched = tuple(c for c in rule.any if matches_keyword(text, c))
    all_hit = tuple(c for c in rule.all if matches_keyword(text, c))

    fired = False
    if blocked:
        why = f'excluded: {", ".join(blocked)} present'
    elif missing:
        why = f'required: {", ".join(missing)} absent'
    elif rule.any and not matched:
        why = 'no cue matched'
    elif not rule.any and not rule.all:
        # A rule with only exclusions fires on anything not vetoed. Legal, and worth saying
        # out loud, because it is usually a mistake in the ruleset rather than an intent.
        fired = True
        why = 'no positive condition — fires unless excluded'
    else:
        fired = True
        why = f'matched: {", ".join(matched + all_hit)}'

    score = (len(matched) + len(all_hit)) * rule.weight if fired else 0
    return Consideration(rule.name, fired, score, matched, missing, blocked, why)


def classify(text: str, ruleset: Ruleset) -> Verdict:
    """Deterministic: same text, same rules, same verdict, with no network and no model.

    Ties break by declaration order and `margin` reports 0, so the tie is visible rather than
    silently resolved. A ruleset whose top two rules keep tying needs another term, and
    hiding that is how a classifier drifts without anyone noticing.
    """
    considered = tuple(_consider(text or '', r) for r in ruleset.rules)
    ranked = sorted((c for c in considered if c.fired), key=lambda c: -c.score)
    top = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    if top is None or top.score < ruleset.threshold:
        return Verdict(None, top.score if top else 0, 0, considered)
    return Verdict(top.rule, top.score, top.score - (runner_up.score if runner_up else 0), considered)


def why_not(verdict: Verdict, rule_name: str) -> str | None:
    """The question a model cannot answer: why was this NOT classified as X?

    A lookup against a trace, not a generated explanation, so it is the same answer every time
    and it is the actual cause rather than a plausible one. None if it WAS classified as X.
    """
    if verdict.category == rule_name:
        return None
    c = next((x for x in verdict.considered if x.rule == rule_name), None)
    if c is None:
        return f'no rule named "{rule_name}" in this ruleset'
    if not c.fired:
        return c.why
    # A TIE IS NOT A LOSS. Saying "scored higher" when the scores are equal is the exact
    # dishonesty this engine exists to avoid — a rule that lost on declaration order deserves
    # to be told so.
    # WORDING IS PART OF THE CONTRACT. These strings are what a compliance reviewer reads,
    # so they are matched to the TypeScript character for character rather than paraphrased.
    # test_rules.py caught exactly that: the first version of this line said "fired at 1,
    # below degraded at 2", which is true, differently worded, and therefore a divergence.
    winner = next((x for x in verdict.considered if x.rule == verdict.category), None)
    if winner and winner.score == c.score:
        return (f'it tied "{verdict.category}" at {c.score}; the tie broke on declaration '
                f'order, not on the merits — add a distinguishing term if that is wrong')
    return (f'it fired (score {c.score}) but "{verdict.category}" scored higher '
            f'at {verdict.score}')
