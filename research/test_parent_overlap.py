#!/usr/bin/env python3
"""A declared parent must record its overlap whether it was accepted or rejected.

WHY THIS FILE EXISTS

parent_goal turns a narrower sub-task into an `excursion` instead of `goal-drift`, provided
the sub-goal shares at least GOAL_MIN of its tokens with the parent. Where that floor
belongs is an open question, and mcp-server.mjs says so in as many words: "The THRESHOLD is
deliberately not touched: three rejected declarations cannot choose a replacement measure,
and making the rejection legible is what generates the data to settle it."

That was right, and the data still could not arrive. `parent_overlap` was written only on
the REJECTED path. Across 1,198 readings the corpus therefore held two values, both
failures, both 0.16 — and a threshold cannot be chosen from failures alone. You need the
distribution of declarations that WORKED at least as much as the ones that did not, or the
only honest move is to leave the floor where it is forever.

So both paths record it now, and this pins that. It is the same defect twice over: a field
that is computed, shown to the agent in prose, and then dropped before anything can count
it — which is how parent_goal itself sat at 0.2% adoption while looking implemented.

WHAT THIS DOES NOT DO

It does not move GOAL_MIN. Two rejections and ten unrecorded acceptances still cannot
choose a floor; this is the instrumentation that makes the question answerable later, and
answering it early from the same thin sample would repeat the mistake it documents.
"""
import json
import os
import pathlib
import sys

# Above every resolver, because they read the environment at import time. This suite used
# to clear the REAL ~/.config/laserbrain/user-turn — the running agent's own flag — on
# every run, and read a user-turn any other suite could have set. That is the two-day
# flake this file's own header describes.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _testhome                                                   # noqa: E402
_testhome.isolate()

# THE USER-TURN FLAG IS GLOBAL, AND THIS SUITE ASSUMES IT IS CLEAR.
#
# ~/.config/laserbrain/user-turn is a single file at a hardcoded path, shared by every
# suite and by the server itself. When it is set, a goal that leaves ground reads as
# `reground` — the user changed the subject — instead of `excursion`. So a predecessor
# that sets it and does not clean up turns this suite's first three assertions red, and
# the failure looks exactly like a broken excursion rule.
#
# That is the whole of the "parent_overlap flake" chased since 2026-08-04: intermittent,
# never reproducible alone, and healed by the rerun that destroyed the evidence. Caught on
# 2026-08-05 only once the runner started keeping failing output — the log read "the
# verdict is excursion, not drift   reground", which names the cause outright.
#
# Cleared here rather than fixed upstream: the path is hardcoded in four places across two
# languages, so isolation is a larger change than this suite should make. A suite that
# depends on global state should assert that state, not hope for it.
_testhome.config('user-turn').unlink(missing_ok=True)
import os
import pathlib
import subprocess
import sys
import tempfile


HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / 'mcp-server.mjs'

fails = []

# Every raw response, kept so a failure can show what the server actually said.
#
# This file has failed twice inside a full suite run and passed every time it was run
# alone or in a short loop — so the cause is load-dependent and could not be reproduced on
# demand. Two rounds of guessing produced two fixes (wait for the handshake; never return
# {} from a call) and neither was demonstrably the cause, because there was nothing to
# demonstrate against: the failure printed five assertions about parent_overlap and not
# one byte of what came back.
#
# So the next occurrence explains itself. A test that fails intermittently and says
# nothing about why is a test that gets ignored, which is worse than not having it.
transcript = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def call(p, i, name, args):
    """One tool call, or a loud death.

    THE SILENT-{} VERSION COST TWO DEBUGGING PASSES. When the server was slow — this file
    runs after three calibrations that each scan thousands of transcripts — readline()
    returned '' and this handed back an empty dict. Every assertion below then read None
    off it and reported five confident failures about parent_overlap, none of which were
    about parent_overlap. Hardening the handshake fixed the first symptom and left this
    one, because the same hole exists per-call.

    A test that cannot get an answer must say THAT, not invent one. Nothing here returns a
    value it did not receive.
    """
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                              'params': {'name': name, 'arguments': args}}) + '\n')
    p.stdin.flush()
    for _ in range(500):
        line = p.stdout.readline()
        if not line:
            break
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get('id') == i:
            try:
                out = json.loads(m['result']['content'][0]['text'])
            except Exception:
                out = m.get('result')
            transcript.append((name, args, out))
            return out
    print(f'  FAIL  no response to {name!r} (id {i}); server exit={p.poll()}')
    print('        nothing below this point was measured')
    sys.exit(1)


if not SERVER.exists():
    print(f'  SKIPPED: no server at {SERVER}')
    sys.exit(0)

with tempfile.TemporaryDirectory() as td:
    log = pathlib.Path(td) / 'drift.jsonl'
    env = dict(os.environ, LASERBRAIN_DRIFT_LOG=str(log), LASERBRAIN_AGENT='test-parent')
    p = subprocess.Popen([os.environ.get('NODE', 'node'), str(SERVER)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    try:
        p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                                  'params': {'protocolVersion': '2024-11-05',
                                             'capabilities': {},
                                             'clientInfo': {'name': 't', 'version': '1'}}}) + '\n')
        p.stdin.flush()
        # WAIT FOR THE HANDSHAKE, rather than assuming one readline() is it.
        #
        # This file went red once inside a suite run and passed alone every time after.
        # The cause was here: a bare readline() that returns '' when the server has not
        # answered yet — which happened when the run followed three calibrations scanning
        # ~5,000 transcripts and the machine was loaded. Every later assertion then read
        # `None` off an empty dict and reported five confident failures about
        # parent_overlap, none of which were about parent_overlap.
        #
        # A flaky test is worse than no test: it teaches you to read red as noise. So the
        # handshake is waited for explicitly, and a server that never comes up says so.
        ready = False
        for _ in range(200):
            line = p.stdout.readline()
            if not line:
                break
            try:
                if json.loads(line).get('id') == 0:
                    ready = True
                    break
            except ValueError:
                continue
        if not ready:
            print('  FAIL  the MCP server never completed the handshake')
            print(f'        (exit code {p.poll()}) — nothing below was measured')
            sys.exit(1)

        GROUND = 'build the spectral parser and ship it to the site'
        call(p, 1, 'check_state', {'goal': GROUND, 'progress': 'advancing', 'distance': 6})

        print('an ACCEPTED parent records its overlap')
        # WHAT panchor ACTUALLY MEASURES, since getting this wrong wrote a test that could
        # not reach the code it was testing: it is the overlap of the declared PARENT with
        # the GROUND — not of the sub-goal with the parent. So acceptance needs a goal that
        # has left the ground while the parent it names still matches it. A first draft
        # here used a sub-goal close to the ground and simply got `advancing`, never
        # entering the branch at all.
        acc = call(p, 2, 'check_state', {
            'goal': 'render the marketing brochure in figma', 'progress': 'advancing',
            'distance': 4, 'parent_goal': GROUND})
        check('the verdict is excursion, not drift', acc.get('reason') == 'excursion',
              str(acc.get('reason')))
        check('  and parent_overlap is on the reading',
              isinstance(acc.get('parent_overlap'), (int, float)), str(acc.get('parent_overlap')))
        check('  at or above the floor it was accepted by',
              isinstance(acc.get('parent_overlap'), (int, float)) and acc['parent_overlap'] >= 0.30,
              str(acc.get('parent_overlap')))

        print()
        print('a REJECTED parent still records its overlap, as it always did')
        # Same shape, except the parent named does not match the ground either — the case
        # the rejection branch was written for, and the only one the corpus has ever held.
        rej = call(p, 3, 'check_state', {
            'goal': 'unrelated weather balloons over kansas', 'progress': 'advancing',
            'distance': 5, 'parent_goal': 'organise the kitchen shelves'})
        check('the verdict is goal-drift', rej.get('reason') == 'goal-drift',
              str(rej.get('reason')))
        check('  and parent_overlap is on the reading',
              isinstance(rej.get('parent_overlap'), (int, float)), str(rej.get('parent_overlap')))
        check('  below the floor that rejected it',
              isinstance(rej.get('parent_overlap'), (int, float)) and rej['parent_overlap'] < 0.30,
              str(rej.get('parent_overlap')))

        print()
        print('no parent declared means no field — absence stays meaningful')
        # If the field appeared as 0 on every reading, "declared and scored badly" would be
        # indistinguishable from "never declared", and the corpus could not be filtered.
        non = call(p, 4, 'check_state', {'goal': GROUND, 'progress': 'advancing', 'distance': 3})
        check('no parent_overlap on an ordinary reading', 'parent_overlap' not in non,
              str(non.get('parent_overlap')))

        print()
        print('and it reaches the DRIFT LOG, not just the response')
        # The response is what the agent reads; the log is what any analysis reads. A field
        # present in one and absent from the other is the exact failure being repaired.
        p.stdin.close()
        p.wait(timeout=20)
        rows = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] \
            if log.exists() else []
        with_po = [r for r in rows if 'parent_overlap' in r]
        check(f'the log holds both readings ({len(rows)} rows)', len(with_po) == 2,
              f'{len(with_po)} carry parent_overlap')
        check('  one excursion and one goal-drift',
              sorted(r.get('reason') for r in with_po) == ['excursion', 'goal-drift'],
              str(sorted(r.get('reason') for r in with_po)))
    finally:
        if p.poll() is None:
            p.kill()

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    print('\n  what the server actually returned:')
    for nm, a, out in transcript:
        goal = str(a.get('goal', ''))[:38]
        par = ' +parent' if a.get('parent_goal') else ''
        print(f'    {nm}({goal!r}{par}) -> {json.dumps(out)[:110] if out is not None else "None"}')
    sys.exit(1)
print('  PASS — every declared parent leaves a number behind, accepted or not.')
