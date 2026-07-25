#!/usr/bin/env python3
"""test_safety.py — lb_safety.py still blocks everything it should.

Written on 2026-07-25 when exactly one rule was removed (production Pages deploys, on
Diego's standing authorization). A policy change is the moment a safety hook most needs a
test: it is easy to widen a hole past the one you meant to open, and nothing would report
it — the hook simply stops firing and work appears to go smoothly.

Note the shape of this file. The cases live in a FILE rather than in a `python3 -c` string
because the hook matches on the command text, and a one-liner containing "rm -rf" as test
data gets itself blocked. The guard reading its own test as an attack is correct behaviour.
"""
import json, subprocess, sys, pathlib

HOOK = str(pathlib.Path(__file__).parent / 'hooks' / 'lb_safety.py')

CASES = [
    # (command, must_block)
    ('npx wrangler pages deploy out --project-name=phronesis-world --branch=main', False),
    ('wrangler pages deploy out', False),
    ('npx wrangler deploy', True),            # Workers deploy — NOT authorized
    ('rm -rf out .next', True),
    ('rm -fr /tmp/x', True),
    ('git push --force origin main', True),
    ('git push -f origin main', True),
    ('git push --force-with-lease', True),
    ('git reset --hard HEAD~1', True),
    ('npm publish', True),
    ('twine upload dist/*', True),
    # things that must never have been blocked
    ('npm run build', False),
    ('git push origin main', False),
    ('git status', False),
]

ok = True
for cmd, must_block in CASES:
    ev = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
    p = subprocess.run([sys.executable, HOOK], input=ev, capture_output=True, text=True)
    blocked = p.returncode == 2
    good = blocked == must_block
    ok = ok and good
    print(f"  {'✓' if good else '✗'} {'BLOCK' if blocked else 'allow':<5} "
          f"{'(want block)' if must_block else '(want allow)':<14} {cmd[:58]}")

print('\n  ' + ('PASS — one rule removed, exactly one' if ok else 'FAIL — the policy changed more than intended'))
raise SystemExit(0 if ok else 1)
