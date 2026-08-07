#!/usr/bin/env python3
"""test_vocab_conformance.py — two implementations of one theorem must agree.

laserbrain exists twice: mcp-server.mjs (what an agent actually calls) and laserbrain-sdk
(what anyone installs from PyPI). Until 2026-07-26 they normalised goals DIFFERENTLY — the
server split raw words, the SDK dropped stopwords and stemmed — so the same goal pair
scored 0.46 in one and 0.56 in the other.

Neither was wrong. Nothing enforced either. That is the worst of the three available
states, and it produced a real failure the same day: a test hard-coded 0.46, the SDK
returned 0.56, and the assertion failed for a reason that had nothing to do with the
behaviour under test. A constant copied between implementations asserts only that somebody
copied it.

So this file runs BOTH on identical input and requires the same answer. It is the thing
that makes "the vocabulary is swappable" safe to say: swap it, and this fails until you
swap it in both places.

Requires node. Skips loudly rather than silently if node is missing — a conformance test
that quietly does not run is how the divergence lasted this long.

HOW THE SERVER SIDE IS READ (changed 2026-08-01)

This used to pull `toWords` out of the server with a regex and eval it. The regex ran from
`const _STOP = new Set([` to the next closing brace, non-greedily, and it covered `toWords`
right up until a function was inserted between the two. After that it matched nothing, the
test exited 2, and it stayed red — silently, for days, guarding nothing. A conformance test
defeated by moving code around inside a file was never testing conformance; it was testing
source layout.

Now it asks the running server, through `server_probe`. The normalization is already
published: `laserscore` is the canonical form `⟨tokens, sorted, |-joined⟩`, so nothing
private needs extracting. This tests what agents actually receive, and cannot be broken by
rearranging the file.
"""
import pathlib
import shutil
import sys
# ONE STATE ROOT — a private tree, so this suite cannot write into the live corpus.
#
# It could, and it did. On 2026-08-05 the live drift log held 2,644 rows of which 1,058 —
# 40% — were written by suites spawning the server against the real ~/.config/laserbrain.
# Synthetic runs are pathological ON PURPOSE (flat distance, repeated goals, abandon bait),
# so they do not dilute the corpus evenly: `stalled` is 39.7% of the test rows against 3.2%
# of the real ones, which makes the whole-log rate 5.6x the truth. Every threshold ever read
# off this log was read off that mixture.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()


sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'laserbrain-sdk'))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from laserbrain import norm                                        # noqa: E402
from server_probe import Server                                    # noqa: E402


ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


if not shutil.which('node'):
    print('  ✗ node not found — cannot compare implementations. NOT a pass.')
    raise SystemExit(1)

CASES = [
    'build the sky billboard',
    'building billboards',
    'build a billboard',
    'verify the 7 leaderboard ids in App Store Connect match the code',
    "fix SOLO's display name from Best Score to Solo",
    'ship the thing',
    'Ship The Things',
    'refactor the particle renderer to use instanced geometry',
    '',
    'a an the of and',                 # stopwords only — must normalise to nothing
    "don't stop believing",            # apostrophes survive tokenising
    'RUNNING runner runs run',         # stemming, including the <=4 char exemption
    'deployment deploys deployed',
]

# Ask the running server, over the same wire an agent uses.
with Server() as srv:
    server_out = [srv.tokens(c) for c in CASES]

for case, got in zip(CASES, server_out):
    want = sorted(norm(case))
    label = repr(case)[:44]
    if got is None:
        # No laserscore at all. Per the grammar that null is not a missing field — it is
        # the first detection, and it happens before any arithmetic exists. The SDK's
        # agreement here is that it also finds nothing to measure, which is a claim about
        # grammaticality rather than about tokenisation, so it is asserted as its own case
        # instead of being compared against a token list it does not have.
        show(f'{label:<46} ungrammatical in both', want == [],
             f'server: no laserscore · sdk: {want}')
        continue
    show(f'{label:<46} agree', got == want,
         '' if got == want else f'server {got} vs sdk {want}')

# The case that motivated all of this: inflection is not drift.
show('inflection collapses in BOTH — "building billboards" == "build a billboard"',
     sorted(norm('building billboards')) == sorted(norm('build a billboard')),
     str(sorted(norm('building billboards'))))

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
