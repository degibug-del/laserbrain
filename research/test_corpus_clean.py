#!/usr/bin/env python3
"""The live corpus holds observations, and only observations.

WHY THIS EXISTS

On 2026-08-05 the live drift log held 2,644 rows of which 1,058 — 40% — had been written
by test suites. They spawned the MCP server against the real ~/.config/laserbrain and their
runs were recorded as if an agent had been working.

The damage is not dilution, it is BIAS, because a test run is pathological on purpose:

    reason        observed agents     test suites
    stalled              3.2%             39.7%     flat distance, to provoke it
    goal-drift          17.6%              0.1%     tests rarely redirect
    reground            19.2%              4.8%

The whole-log `stalled` rate read 17.8% against a true 3.2% — off by 5.6x. Every threshold
ever taken from this log was taken from that mixture, including the one mcp-server.mjs
documents as "THRESHOLD FROM THE CORPUS, not from taste."

It was found by accident. Chasing why `judgment` had never been recorded, a count of the
log by agent showed `test-parity` with 527 rows. Nothing was watching, and the corpus is
the one artifact where nobody would notice: it only ever grows, and a row that looks like
every other row is invisible.

WHAT THIS ASSERTS

  no synthetic agent in the live log    the corpus itself, not a proxy for it
  every row is attributed               an unattributed row cannot be compared across hosts
  the suites still isolate              a spot check that _testhome is wired into every
                                        suite that spawns a server, because the isolation
                                        is what keeps the first assertion true

It reads the REAL file. A gate over a temporary copy would pass while the live corpus
rotted, which is the exact failure it exists to prevent.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _root                                                       # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent

# THE LIVE PATHS, resolved deliberately AROUND the isolation every other suite gets.
#
# run-tests.sh exports LASERBRAIN_HOME so no suite can touch the real corpus. This suite's
# SUBJECT is the real corpus, so honouring that would point it at an empty temp directory
# where it would find no synthetic rows, report PASS, and mean nothing — the vacuous-check
# failure this repo has now paid for several times over.
#
# So it reads $HOME directly. The specific override (LASERBRAIN_STATE_DIR and friends) is
# not consulted either: this is not asking "where would state go", it is asking "what is in
# the file people actually accumulate".
LIVE = pathlib.Path.home() / '.config' / 'laserbrain'   # one-root: live
LOG = LIVE / 'drift-log.jsonl'
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def is_synthetic(a):
    a = str(a or '').strip().lower()
    return a.startswith('test') or a.endswith('-test') or '-test-' in a


print('the live drift log holds observations only\n')
rows = []
if LOG.exists():
    for line in LOG.read_text().split('\n'):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass

if not rows:
    # Not a pass. An empty corpus satisfies "no synthetic rows" vacuously, and this suite
    # would then be green forever on a machine where nothing is being recorded.
    print('  SKIP  no live drift log on this machine — nothing to check')
    sys.exit(0)

synth = [r for r in rows if is_synthetic(r.get('agent'))]
unattr = [r for r in rows if not str(r.get('agent') or '').strip()]

import collections                                                 # noqa: E402
check('no synthetic rows', not synth,
      f'{len(synth)} of {len(rows)} from {sorted(set(str(r.get("agent")) for r in synth))}'
      if synth else f'{len(rows)} rows, all observed')
if synth:
    print('        run: python3 lasermind/hooks/quarantine_drift_log.py --apply')

check('every row is attributed', not unattr,
      f'{len(unattr)} unattributed' if unattr else
      f'agents: {dict(collections.Counter(r.get("agent") for r in rows).most_common(4))}')

print()
print('and contexts.json holds only observed contexts')
# contexts carry no agent field, so the join is against the drift log: a real context lists
# full run UUIDs in `sessions`, the suites use short synthetic ids. 248 of 680 were fixtures
# when this was found — including a conformance probe with 14,508 checks, which sat on
# exactly the repeat tail the `repetition >= 3` threshold is read from.
CTX = LIVE / 'contexts.json'
if CTX.exists():
    cx = json.loads(CTX.read_text())
    runs = set()
    if LOG.exists():
        for line in LOG.read_text().split('\n'):
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('run'):
                    runs.add(r['run'])
    fixture = [k for k, v in cx.items()
               if not ((set(v.get('sessions') or []) & runs)
                       or any(len(x) == 36 and x.count('-') == 4 for x in (v.get('sessions') or [])))]
    check('no fixture contexts', not fixture,
          f'{len(fixture)} of {len(cx)}' if fixture else f'{len(cx)} contexts, all observed')
    if fixture:
        print('        run: python3 lasermind/hooks/quarantine_contexts.py --apply')

print()
print('and the suites that spawn a server still take a private root')
# ISOLATION IS THE PROPERTY, not the import. A suite can get a private root two ways:
# _testhome.isolate() sets it for the whole process, or it builds the env itself and passes
# LASERBRAIN_HOME to each server it spawns — which is finer-grained, since every server gets
# its own tree. test_lanes does the second and was flagged by an earlier version of this
# check that looked only for the marker. Requiring the marker would have taught the next
# author to import a module they do not use rather than to isolate, which is the wrong
# lesson from a gate whose whole subject is not writing to the live corpus.
missing = []
for f in sorted(HERE.glob('test_*.py')):
    src = f.read_text()
    if 'mcp-server.mjs' not in src:
        continue
    if '_testhome' in src or 'LASERBRAIN_HOME' in src:
        continue
    missing.append(f.name)
check('every server-spawning suite isolates', not missing,
      '; '.join(missing) if missing else 'all of them')

# AND IT ISOLATES SOON ENOUGH, which is a separate failure and has now happened twice.
#
# laserbrain/__init__.py binds CONTEXTS at IMPORT time — `CONTEXTS = _P.config(...)` runs
# once, when the module loads. An isolate() below that line sets LASERBRAIN_HOME for a
# resolver that has already answered, so the suite reads as isolated, passes every check
# that looks for _testhome, and writes its contexts to the live corpus anyway.
#
# First occurrence: test_windup, caught by reading. Second: four suites at once, caught
# only because test_corpus_clean counted 92 fixture contexts that had not been there an
# hour earlier. Nothing about the SUITE looks wrong in either case, which is why this
# checks the order rather than the presence.
import re                                                          # noqa: E402
late = []
for f in sorted(HERE.glob('test_*.py')):
    src = f.read_text()
    if '_testhome.isolate()' not in src:
        continue
    head = src[:src.index('_testhome.isolate()')]
    if re.search(r'^(?:from laserbrain[\w.]*|import laserbrain)\b', head, re.M):
        late.append(f.name)
check('  and does it BEFORE importing the package', not late,
      '; '.join(late) if late else 'CONTEXTS binds at import — order is the whole fix')

print()
print('and every SHELL script that runs the suite carries its own root')
# THE THIRD WAY IN, and it cost a corpus twice.
#
# run-tests.sh and publish.sh were both given a private root. mutate.sh was not, and
# publish.sh calls it from line 24 — ten lines ABOVE its own export. So the 0.45.0 release
# ran the entire suite twice on deliberately broken constants, unprotected, and put 84
# fixture contexts back into a corpus that had been quarantined clean four hours earlier.
# 82 of them were contexts already quarantined once.
#
# Isolating a script from its caller only protects the call sites someone remembered. The
# root belongs IN the script that writes state, so it holds however it is invoked — which
# is what this checks, on the scripts rather than on the suites.
#
# publish-<version>.sh is EXCLUDED, and the exclusion is named rather than quietly written
# into the glob: those are frozen snapshots of how each past release actually went out, and
# editing one to add an export would falsify the record it exists to keep. The cost is real
# and accepted — run publish-0.6.0.sh today and it will write fixtures to the live corpus.
# Nothing does; releases go through publish.sh, which is in scope below.
SH = [p for d in (HERE, HERE.parent, HERE.parent / 'laserbrain-sdk')
      for p in sorted(d.glob('*.sh'))
      if not re.match(r'publish-\d', p.name)
      and ('test_*.py' in p.read_text() or 'run-tests' in p.read_text())]
bare = [p.name for p in SH if 'LASERBRAIN_HOME' not in p.read_text()]
check('every suite-running script exports LASERBRAIN_HOME', not bare,
      '; '.join(bare) if bare else ', '.join(p.name for p in SH))

# AND THE GENERATORS, which is the fourth way in and the one that reached furthest.
#
# The three above are all in this repo. gen-drift-vectors.py lives in phronesis-world and
# drives fourteen Harnesses through sixty-four deliberately pathological steps — that is
# what a vector file IS — so it is as bad a writer as mutate.sh, in a directory no gate here
# was looking at. One run on 2026-08-06 put 14 fixture contexts into the live store.
#
# Scanned by BEHAVIOUR rather than by name: anything that imports laserbrain outside a test
# file is a potential state writer and needs its own root. Skips cleanly when the sibling
# repo is not checked out, because a gate that fails on a missing neighbour teaches people
# to ignore gates.
SITE = pathlib.Path.home() / 'phronesis-world'
if not SITE.is_dir():
    print('  ....  generator scripts   SKIPPED: ~/phronesis-world not present')
else:
    gens, unrooted = [], []
    for p in sorted(SITE.rglob('*.py')):
        if 'node_modules' in p.parts or p.name.startswith('test'):
            continue
        try:
            src = p.read_text()
        except Exception:
            continue
        if 'from laserbrain import' not in src and 'import laserbrain' not in src:
            continue
        gens.append(p)
        if 'LASERBRAIN_HOME' not in src:
            unrooted.append(str(p.relative_to(SITE)))
    check('every laserbrain-importing generator carries its own root', not unrooted,
          '; '.join(unrooted) if unrooted else f'{len(gens)} scanned, all rooted')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — the corpus is what it claims to be: rows observed from agents working,')
print('  each attributable to the host that produced it.')
