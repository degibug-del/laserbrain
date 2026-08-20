#!/usr/bin/env python3
"""test_cli.py — the entry point a new user touches first, which nothing tested.

cli.py sat at 0% coverage while the library around it reached 79%. That is the wrong way
round: a broken import or a changed flag in here is the first thing a new user meets, and
it would have shipped green. The exit codes matter too — `laserbrain check` is documented
as scriptable, returning nonzero on drift, so the codes are part of the contract.
"""
import io, json, sys, tempfile, pathlib, contextlib
from laserbrain.cli import main
from laserbrain import Harness

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def run(*argv):
    """Returns (exit_code, stdout). argparse writes usage to stderr on bad input and
    raises SystemExit, so that is caught rather than allowed to kill the test."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return code, buf.getvalue()


# ── version ──────────────────────────────────────────────────────────────────
from laserbrain import __version__
code, out = run('version')
show('version exits 0', code == 0)
show('version prints the real version', __version__ in out, out.strip())

# ── demo ─────────────────────────────────────────────────────────────────────
code, out = run('demo')
show('demo exits 0', code == 0)
show('demo actually shows a drift and a return',
     'goal-drift' in out and 'JSON parser' in out)

# ── check: the documented exit-code contract ─────────────────────────────────
code, out = run('check', '--goal', 'ship the billboard')
show('check on a fresh goal exits 0 (grounded is not drift)', code == 0, f'exit={code}')

code, out = run('check', '--goal', 'refactor the parser', '--against', 'ship the billboard')
show('check against a different goal exits 1 — scriptable', code == 1, f'exit={code}')

code, out = run('check', '--goal', 'ship the billboard', '--against', 'ship the billboard')
show('check against the same goal exits 0', code == 0, f'exit={code}')

code, out = run('check', '--goal', '')
show('an empty goal is ungrammatical and exits nonzero', code != 0, f'exit={code}')

code, out = run('check', '--goal', 'x', '--progress', 'nonsense')
show('an invalid progress word exits nonzero', code != 0, f'exit={code}')

# ── verify: a real audit chain, and a tampered one ───────────────────────────
h = Harness()
h.check(goal='ship the billboard', progress='advancing', distance=5)
h.check(goal='ship the billboard', progress='advancing', distance=3)

with tempfile.TemporaryDirectory() as d:
    good = pathlib.Path(d) / 'run.json'
    h.export_audit(str(good))       # writes the chain; returns the path, not the chain
    code, out = run('verify', str(good))
    show('verify accepts an untampered chain', code == 0, f'exit={code}')

    obj = json.loads(good.read_text())
    entries = obj['entries'] if isinstance(obj, dict) and 'entries' in obj else obj
    entries[0]['goal'] = 'a goal that was never checked'
    tampered = pathlib.Path(d) / 'bad.json'
    tampered.write_text(json.dumps(obj))
    code, out = run('verify', str(tampered))
    show('verify REJECTS a tampered chain', code == 1, f'exit={code}')

    code, out = run('verify', str(pathlib.Path(d) / 'nope.json'))
    show('a missing file exits nonzero rather than raising', code != 0, f'exit={code}')

# ── coverage: the exit code is the contract (nonzero = not scorable) ─────────
with tempfile.TemporaryDirectory() as d:
    code, out = run('coverage', '--dir', d)
    show('coverage on an empty dir exits 2 and says the hook may be missing',
         code == 2 and 'hook' in out, f'exit={code}')

    thin = {'id': 'thin', 'steps': 40,
            'checks': [{'step': 1}], 'inferred': [{'step': i} for i in range(40)],
            'catches': [{'step': 5, 'what': 'x', 'by': 'build'}]}
    (pathlib.Path(d) / 'thin.json').write_text(json.dumps(thin))
    code, out = run('coverage', '--dir', d)
    show('a 2%-covered session exits 1 — not scorable', code == 1, f'exit={code}')
    show('and inferred checks do not open the gate', '40' in out and 'lower bound' in out)

    (pathlib.Path(d) / 'thin.json').unlink()
    good = {'id': 'good', 'steps': 10, 'checks': [{'step': i} for i in range(10)],
            'inferred': [], 'catches': []}
    (pathlib.Path(d) / 'good.json').write_text(json.dumps(good))
    code, out = run('coverage', '--dir', d)
    show('a fully covered session exits 0 and reads as scorable',
         code == 0 and 'Scorable' in out, f'exit={code}')

# ── store: the third surface (Python and MCP already had one) ────────────────
code, out = run('store')
show('bare store defaults to listing workflows', code == 0)
show('  and includes a shipped one', 'build-and-ship' in out, out.strip()[:80])

code, out = run('store', 'list', '--kind', 'team')
show('store list --kind team lists the three presets',
     code == 0 and 'deep-search' in out and 'adversarial-deliberation' in out)

code, out = run('store', 'find', 'debate toward a resolved answer', '--kind', 'team')
show('store find --kind team matches on task', code == 0 and 'adversarial-deliberation' in out)

code, out = run('store', 'find', 'xyzzy plugh frotz')
show('store find on nonsense exits nonzero and says so',
     code == 1 and 'nothing matched' in out, f'exit={code}')

code, out = run('store', 'find')
show('store find with no task exits nonzero rather than raising', code == 2, f'exit={code}')

code, out = run('store', 'vend', 'build-and-ship')
show('store vend prints the spec as JSON',
     code == 0 and json.loads(out).get('goal') == 'build something and put it in front of people')

code, out = run('store', 'vend', 'deep-search', '--kind', 'team')
show('store vend --kind team prints roles, not steps',
     code == 0 and json.loads(out)['roles'][0]['role'] == 'explorer')

code, out = run('store', 'vend', 'not-a-real-name')
show('store vend on an unknown name exits nonzero rather than raising',
     code == 2 and 'not-a-real-name' in out, f'exit={code}')

# ── no command ───────────────────────────────────────────────────────────────
code, out = run()
show('bare invocation exits 0 with help rather than a traceback', code == 0, f'exit={code}')

print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
