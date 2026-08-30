#!/usr/bin/env python3
"""test_verdict_parity.py — the two implementations must decide the same way.

THE DEFECT THIS PINS. On 2026-07-26 the MCP server and the PyPI SDK disagreed about when
to fire, and had for as long as both existed:

    self-report floor   server Φ > 0        SDK Φ > 0.15
    stall window        server 3            SDK 4
    reground            server had it       SDK did not

So the same agent, spelling the same state, got a different verdict depending on whether
it called the server or imported the package — and the server disagreed with the numbers
published on phronesis.world/laserbrain/how as well. Nothing compared them, so nothing
said.

WHAT THIS FILE CHECKS, AND WHAT IT DOES NOT. It compares the three calibration constants
and the verdict VOCABULARY of each single-agent implementation. It does not execute the
server's decision procedure — that lives inside a stateful MCP handler and driving it
would mean reimplementing it here, which would test the reimplementation. So this is a
narrower claim than "identical behaviour", and it is the claim that would have caught
every divergence actually found. Where it is silent, it says so rather than implying
coverage it does not have.

_Dialogue's extra verdicts (topic-drift, echo-spiral, deliberation-stall) are excluded on
purpose: they belong to the multi-agent case, which the server does not implement. That is
scope, not divergence, and conflating the two would make this test lie.
"""
import pathlib
import re
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
import laserbrain as lb                                              # noqa: E402
from server_probe import Server                                      # noqa: E402


SERVER = pathlib.Path(__file__).parent / 'mcp-server.mjs'
ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


src = SERVER.read_text()

# ── the three numbers ───────────────────────────────────────────────────────
#
# Read from the RUNNING server, not from its source. This used to match
# `^const GOAL_MIN = ([\d.]+)$`, which held until the constants moved from inline literals
# to `_CAL.goal_min ?? 0.30` — config with a fallback. After that the regex found nothing
# and the test reported "not found — is it still inline?" on all three, then stayed red.
#
# The failure mode that matters is the one it would have had if it HAD still matched: it
# would have asserted the FALLBACK while the server ran a different number from
# grammar.json, and reported parity that did not exist. Source is where a value is written;
# the grammar the server publishes is the value it is using.
cal = lb.PUBLISHED
with Server() as srv:
    server_cal = srv.calibration()
for key, attr in (('goal_min', 'goal_min'),
                  ('self_report_min', 'self_report_min'),
                  ('stall_window', 'stall_window')):
    if key not in server_cal:
        show(f'server publishes {key}', False, f'absent from drift_grammar.calibration')
        continue
    server_val, sdk_val = float(server_cal[key]), float(getattr(cal, attr))
    show(f'{key} agrees', server_val == sdk_val,
         f'server {server_val} vs sdk {sdk_val}')

# ── and that they are the numbers the site publishes ────────────────────────
HOW = pathlib.Path.home() / 'phronesis-world' / 'app' / 'laserbrain' / 'how' / 'page.tsx'
if HOW.exists():
    how = HOW.read_text()
    for label, value in (('goal_min', cal.goal_min),
                         ('self_report_min', cal.self_report_min),
                         ('stall_window', cal.stall_window)):
        # Compared as numbers, not strings: the page writes 0.30 and the SDK holds 0.3,
        # which are the same figure. The first draft of this check string-matched and
        # failed on that, which is a test reporting a divergence that does not exist —
        # exactly as bad as missing one that does.
        m = re.search(rf'{label}\s+([\d.]+)', how)
        got = float(m.group(1)) if m else None
        show(f'the site publishes {label} = {value:g}', got == float(value),
             'not found on the page' if got is None else f'page says {got:g}')
else:
    show('the how page could be read', False, f'missing: {HOW}')

# ── the vocabulary ──────────────────────────────────────────────────────────
server_verdicts = set(re.findall(r"record\((?:true|false), '([a-z-]+)'", src))
server_verdicts |= {'self-report'} if 'self-report:${progress}' in src else set()

run_src = lb.__file__ and pathlib.Path(lb.__file__).read_text()
run_block = run_src[run_src.index('class _Run'):run_src.index('class _Dialogue')]
sdk_verdicts = set(re.findall(r"emit\(f?'([a-z-]+)", run_block))
sdk_verdicts = {v.split(':')[0] if v.startswith('self-report') else v for v in sdk_verdicts}

show('the single-agent verdict vocabularies match',
     server_verdicts == sdk_verdicts,
     f'server-only {sorted(server_verdicts - sdk_verdicts)} · '
     f'sdk-only {sorted(sdk_verdicts - server_verdicts)}')

# ── the rule the corpus says matters most ───────────────────────────────────
# goal-drift was 24 of 35 graded fires with 0 true catches, and 22 of those 24 were the
# first check after the user spoke. reground is what turns those into a correct no-fire,
# so if either implementation loses it the instrument's precision problem comes straight
# back. Checked by name in both, and by behaviour in the SDK.
show('server can emit reground', 'reground' in server_verdicts)
show('sdk can emit reground', 'reground' in sdk_verdicts)

h = lb.Harness()
h.check(goal='write a JSON parser in Python', progress='advancing', distance=8)
drift = lb.Harness()
drift.check(goal='write a JSON parser in Python', progress='advancing', distance=8)
v_drift = drift.check(goal='add an LRU cache', progress='advancing', distance=5)
v_reg = h.check(goal='add an LRU cache', progress='advancing', distance=5, user_turn=True)
show('without a user turn the same move is goal-drift', v_drift.reason == 'goal-drift',
     v_drift.reason)
show('with one it is reground, and does not count as drift',
     v_reg.reason == 'reground' and not v_reg.drifting, v_reg.reason)
after = h.check(goal='add an LRU cache', progress='advancing', distance=4)
show('reground actually moves ground, not just the label',
     after.reason == 'advancing' and after.phi < 0.10, f'Φ={after.phi}')

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
