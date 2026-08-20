#!/usr/bin/env python3
"""test_hook_parity.py — the hook's copy of the progress rules must match observe.py's.

A hook cannot import laserbrain: it runs against whatever python3 is on
PATH, and that interpreter has the PUBLISHED version from PyPI while observe.py lives in
the working tree. An import there fails on version skew, inside a process whose entire
job is to never break. So the rules are duplicated — deliberately, and dangerously.

This is the test that makes the duplication safe. It runs both implementations over
randomised traces and fails on the first disagreement. If it goes red, the two copies
have drifted apart, which is precisely the failure mode the product is named after.
"""
import os, random, pathlib, importlib.util
from laserbrain.observe import Observer, _WINDOW, _REPEAT, _FAILS

# lasergear, not lasermind/hooks — the instruction layer got its own home on 2026-07-27.
#
# The old path now holds a shim that exits non-zero and says where to look, so this test
# went red the moment the file moved rather than quietly comparing against nothing. That
# was the point of the shim: a moved file should break what depends on it, loudly, instead
# of leaving it measuring air. A silent pass here would have meant the duplicated progress
# rules were ungated and nothing would have said so.
_ROOT = pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis'
HOOK = pathlib.Path(os.environ.get('LASERGEAR_COVERAGE') or _ROOT / 'lasergear/lb_coverage.py')

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


if not HOOK.exists():
    # SKIP, not FAIL — see the note in test_gate_hosts.py. A suite that cannot find the
    # thing it tests has not failed the thing; it has failed to run, and those are
    # different facts that must not print the same.
    print(f'  SKIP  lb_coverage.py not found at {HOOK} — set LASERGEAR_COVERAGE or LASERGEAR_DIR')
    raise SystemExit(77)
    raise SystemExit(1)

spec = importlib.util.spec_from_file_location('lb_hook', HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

show('the constants agree',
     (hook.WINDOW, hook.REPEAT, hook.FAILS) == (_WINDOW, _REPEAT, _FAILS),
     f'hook={(hook.WINDOW, hook.REPEAT, hook.FAILS)} observe={(_WINDOW, _REPEAT, _FAILS)}')

random.seed(20260724)
TOOLS = ['Bash', 'Read', 'Edit']
CMDS = ['build', 'test', 'lint']
mismatch = None
checked = 0
for trial in range(400):
    obs = Observer('a fixed goal')
    events = []
    for _ in range(random.randint(1, 14)):
        tool = random.choice(TOOLS)
        args = {'command': random.choice(CMDS)}
        good = random.random() > 0.35
        obs.record(tool, args, ok=good)
        import json
        events.append({'sig': f"{tool}|{json.dumps(args, sort_keys=True, default=str)[:400]}", 'ok': good})
        checked += 1
        a, b = obs.progress(), hook.infer_progress(events)
        if a != b and mismatch is None:
            mismatch = (trial, a, b, [e['sig'] for e in events], [e['ok'] for e in events])

show('both implementations agree on every randomised trace',
     mismatch is None, f'{checked} states compared' if mismatch is None else f'first disagreement: {mismatch}')

# the specific behaviour that motivated the last change
obs = Observer('g'); ev = []
import json
def both(tool, cmd, good):
    obs.record(tool, {'command': cmd}, ok=good)
    ev.append({'sig': f"{tool}|{json.dumps({'command': cmd}, sort_keys=True)[:400]}", 'ok': good})
    return obs.progress(), hook.infer_progress(ev)

for _ in range(3):
    both('Bash', 'npm run build', False)
show('three identical calls read as circling in both', both('Bash', 'npm run build', False) == ('circling', 'circling'))
show('one different call recovers immediately in both', both('Bash', 'echo hi', True) == ('advancing', 'advancing'))

# ── the ground rules, duplicated 2026-07-29 ────────────────────────────────────────
# clean_prompt and is_groundable are the SECOND pair to be copied into the hook, and the
# reason they exist is a drift of exactly this kind: the fallback stored the prompt raw
# while the SDK path cleaned it, so which code path ran decided whether a session's ground
# was a task or a lump of markup. A session on 2026-07-28 grounded on 'hello there'.
from laserbrain.runtime import clean_prompt as sdk_clean, is_groundable as sdk_ground

CASES = [
    '<user_query>\n/hello\n</user_query>', 'hello there', 'hi', '/hello', '/clear',
    'ok', 'thanks', 'Hello There.', '  ', '',
    # terse-but-real: these are actual first prompts from this project's history and every
    # one of them must remain groundable. A minimum-length rule would reject the lot.
    'map all', 'reconcile', 'publish', 'fix them', 'go for it', 'u run it',
    'both, repo first', 'Computer = Operator', 'AI native workflows',
    'do we need to update the worker?', 'what should we do today?',
]
bad_clean = [c for c in CASES if sdk_clean(c) != hook.clean_prompt(c)]
bad_ground = [c for c in CASES if sdk_ground(c) != hook.is_groundable(c)]
show('clean_prompt agrees in both copies', not bad_clean, f'differs on {bad_clean}' if bad_clean else f'{len(CASES)} cases')
show('is_groundable agrees in both copies', not bad_ground, f'differs on {bad_ground}' if bad_ground else f'{len(CASES)} cases')

# and prove the rule itself is right, not merely consistent — two identical wrong copies
# would pass every parity check above.
show('a greeting cannot be a ground', not sdk_ground('hello there'))
show('a slash command cannot be a ground', not sdk_ground('/hello'))
show('a two-word task CAN be a ground', sdk_ground('map all') and sdk_ground('fix them'))
show('wrapped markup unwraps before judging', sdk_clean('<user_query>\nmap all\n</user_query>') == 'map all')

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
