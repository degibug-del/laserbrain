#!/usr/bin/env python3
"""The two surfaces must judge a run the same way.

WHY THIS EXISTS

`check-drift-parity.ts` drives drift.ts and the Python SDK through 64 shared vectors and
compares every VERDICT. Nothing did that for the JUDGMENT layer, and nothing compared the
local MCP server to anything but constants — which is the surface an attached agent
actually talks to.

Two bugs came out of that gap in two days, and both were found by luck rather than by a
gate:

  2026-08-04  the server's prior-runs `abandon` was missing the `judged` guard the SDK
              has had all along. Without it the rule reduces to `closed <= 0`, which is
              trivially true on the first check of any new setpoint — so a context opened
              before and not closed was told to abandon the instant a user redirected to
              it. Found because a test happened to drive the server rather than the
              package.
  2026-08-05  `unbacked` shipped in 0.43.0 on the SDK only. It was written, tested and
              released, and could not fire for anyone who was not importing the package —
              which is to say, not for the agent that wrote it.

The second one is worse than the first: the divergence was introduced deliberately, by
someone who had fixed the first one that morning. A rule kept in two places diverges; the
only question is whether anything notices.

WHAT IS COMPARED

The judgment verdict at the end of identical runs. Not the wording — `because` carries
counts and names that legitimately differ in phrasing — but the VERDICT, which is the part
that changes what an agent does next.

WHAT IS NOT COMPARED, AND WHY THAT IS NOT A LOOPHOLE

`verify` is server-only by design: it fires when an OBSERVED runtime trace disagrees with
the self-report, and the SDK has no runtime watcher feeding it. drift.ts documents the same
exemption for the Worker. So the assertion is one-directional where it has to be — the
server may return a verdict the SDK cannot reach — but never the reverse: anything the SDK
can say, the server must be able to say too. That is the direction the two real bugs went.
"""
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
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

sys.path.insert(0, str(HERE.parent / 'laserbrain-sdk'))

from laserbrain import Harness                                    # noqa: E402


SERVER = HERE / 'mcp-server.mjs'
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


# ── driving the server over stdio ────────────────────────────────────────────────────
def _call(p, payload):
    p.stdin.write(json.dumps(payload) + '\n')
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            return {}
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('id') == payload['id']:
            return d


def server_run(steps):
    """Play `steps` through a fresh server and return its judgment verdicts, per step."""
    env = {**os.environ, 'LASERBRAIN_AGENT': 'test-parity'}
    p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    try:
        _call(p, {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                  'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                             'clientInfo': {'name': 't', 'version': '1'}}})
        _call(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                  'params': {'name': 'reset_task', 'arguments': {}}})
        out = []
        for n, (goal, prog, dist) in enumerate(steps):
            r = _call(p, {'jsonrpc': '2.0', 'id': 100 + n, 'method': 'tools/call',
                          'params': {'name': 'check_state',
                                     'arguments': {'goal': goal, 'progress': prog,
                                                   'distance': dist}}})
            try:
                m = json.loads(r['result']['content'][0]['text'])
            except Exception:
                m = {}
            out.append((m.get('judgment') or {}).get('verdict'))
        return out
    finally:
        p.terminate()


def sdk_run(steps):
    """The same run through the package. Judgment is asked for at every step, as the
    server volunteers it, so the two sequences are comparable position by position."""
    h = Harness()
    out = []
    for goal, prog, dist in steps:
        h.check(goal, prog, dist)
        j = h.phronesis()
        v = j.get('verdict')
        # The server attaches judgment only when it is worth acting on; the SDK's tool
        # always answers. `continue` and `finish` are the SDK's way of saying "nothing to
        # report", so they map to the server's absence.
        out.append(None if v in ('continue', 'finish', 'ungrounded') else v)
    return out


SCENARIOS = {
    'flat run — the abandon case': [('ship the CSV export', 'advancing', 7)] * 14,
    'closing cleanly': [('add rate limiting to the upload endpoint', 'advancing', d)
                        for d in (8, 7, 6, 5, 4, 3, 2, 1)],
    'stalled then flat': [('make the flaky test pass', 'advancing', d)
                          for d in (6, 5, 5, 5, 5, 5, 5, 5)],
    'a long healthy run': [('write the release notes', 'advancing', d)
                           for d in (9, 8, 8, 7, 6, 6, 5, 4, 3, 2)],
}

print('the same run must produce the same judgment on both surfaces\n')
for name, steps in SCENARIOS.items():
    got_s = server_run(steps)
    got_k = sdk_run(steps)
    # Compare the FINAL judgment: the intermediate sequence legitimately differs in
    # timing, because the server keeps cross-session memory the SDK's fresh Harness has
    # not got. The end state is the claim both make about the run.
    fs, fk = got_s[-1], got_k[-1]
    same = fs == fk
    check(f'{name}', same, f'server={fs}  sdk={fk}')
    if not same:
        print(f'        server: {got_s}')
        print(f'        sdk:    {got_k}')

print()
print('and the SDK may not hold a judgment the server cannot reach')
sdk_src = (HERE.parent / 'laserbrain-sdk' / 'laserbrain' / '__init__.py').read_text()
srv_src = (HERE / 'mcp-server.mjs').read_text()
import re                                                          # noqa: E402
sdk_v = set(re.findall(r"verdict = '([a-z-]+)'", sdk_src)) | {'ungrounded', 'continue', 'finish'}
srv_v = set(re.findall(r"verdict = '([a-z-]+)'", srv_src))
missing = sorted(sdk_v - srv_v - {'continue', 'finish', 'ungrounded'})
check('every SDK judgment exists on the server', not missing,
      f'server is missing: {missing}' if missing else f'{len(sdk_v)} judgments, all reachable')

# The reverse is allowed, and named, so an unexplained extra still shows up.
SERVER_ONLY = {'verify'}          # needs a runtime trace the SDK has no watcher for
extra = sorted(srv_v - sdk_v - SERVER_ONLY)
check('and the server holds no UNEXPLAINED extra', not extra,
      f'undocumented server-only: {extra}' if extra else f'server-only by design: {sorted(SERVER_ONLY)}')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:3]))
    sys.exit(1)
print('  PASS — the package and the server judge a run the same way, and neither can gain')
print('  a verdict the other cannot reach without this saying so.')
