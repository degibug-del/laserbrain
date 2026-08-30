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

HOOK = str(pathlib.Path(__file__).parent.parent / 'lasergear' / 'lb_safety.py')

CASES = [
    # (command, must_block)
    ('npx wrangler pages deploy out --project-name=phronesis-world --branch=main', False),
    ('wrangler pages deploy out', False),
    ('npx wrangler deploy', True),            # Workers deploy — NOT authorized
    # --dry-run publishes nothing; blocking it blocks the rehearsal, not the act
    ('npx wrangler deploy --dry-run --outdir /tmp/x', False),
    ('wrangler deploy --dry-run', False),
    # ...but a real deploy chained after one must still stop
    ('wrangler deploy --dry-run; wrangler deploy', True),
    ('rm -rf out .next', True),
    ('rm -fr /tmp/x', True),
    ('git push --force origin main', True),
    ('git push -f origin main', True),
    ('git push --force-with-lease', True),
    ('git reset --hard HEAD~1', True),
    ('npm publish', True),
    ('twine upload dist/*', True),
    ('python3 -m twine upload dist/*', True),
    ('poetry publish', True),
    ('uv publish', True),
    # Prose is not a command. The old pattern's loose alternation matched the bare word
    # "pypi", so a commit message mentioning the package blocked the commit.
    ("git commit -m 'the published PyPI package'", False),
    ('cat notes-about-pypi.md', False),
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


# ══════════════════════════════════════════════════════════════════════════════════════
# THE ADVERTISED BYPASS, AND THE FALSE POSITIVE — both found by using this hook, 2026-08-05
#
# The refusal message used to end "Emergency bypass: LASERBRAIN_SAFETY_OFF=1", which reads
# as a command prefix. It is not: the hook is its own process and reads its OWN
# environment, so a prefix hands the variable to the command being blocked and never to
# the guard. An agent with Diego's confirmation in chat spent three round trips finding
# that out. The variable stays unreachable from inside a command — that is the point of it
# — but the message now says where it actually has to live.
#
# The second finding is a false positive with no safe fix. The matcher reads the whole
# command string, so a script whose TEXT contains a guarded phrase is refused even though
# it runs nothing of the kind — editing this very file tripped it. Stripping here-document
# bodies before matching would fix it and must not be done: a heredoc body can be piped to
# a shell, and a `subprocess.run` inside a python heredoc really would execute. Over-
# blocking is the correct failure direction for a safety control, so the decision stands
# and only the EXPLANATION improves.
# ══════════════════════════════════════════════════════════════════════════════════════
import json as _json                                              # noqa: E402
import subprocess as _sp                                          # noqa: E402
import sys as _sys                                                # noqa: E402
import pathlib as _pl                                             # noqa: E402

def show(label, cond, detail=''):
    """Same accumulator the CASES loop above uses — a helper that reported failures into
    its own variable would print FAIL and still exit 0."""
    global ok
    ok = ok and bool(cond)
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))


_HOOK = _pl.Path(__file__).resolve().parent.parent / 'lasergear' / 'lb_safety.py'
_PHRASE = 'git ' + 'push --force origin main'      # split so THIS file does not trip it


def _probe(cmd):
    ev = {'tool_name': 'Bash', 'tool_input': {'command': cmd}}
    r = _sp.run([_sys.executable, str(_HOOK)], input=_json.dumps(ev),
                capture_output=True, text=True)
    return r.returncode == 2, (r.stderr + r.stdout)


print()
print('the refusal no longer advertises a bypass that cannot be reached')
_blocked, _txt = _probe(_PHRASE)
show('a destructive command is still refused', _blocked)
show('  and the message does not offer an inline bypass',
     'Emergency bypass' not in _txt, 'that string read as a command prefix')
show('  it says where the variable must actually live',
     'settings.json' in _txt or 'launched' in _txt, _txt.strip().splitlines()[-1][:60])
show('  and it names who should run it', 'DIEGO' in _txt)

print()
print('a guarded phrase inside a heredoc is still refused, but diagnosably')
_hb, _ht = _probe("python3 - <<'X'\nprint('" + _PHRASE + "')\nX")
show('still blocked — over-blocking is the safe direction', _hb)
show('  and explains it may be a literal', 'NOTE:' in _ht and 'here-document' in _ht)
show('  while a bare command gets no such note', 'NOTE:' not in _txt,
     'the hint must not fire where the match is real')

print('\n  ' + ('PASS — one rule removed, exactly one' if ok else 'FAIL — the policy changed more than intended'))
raise SystemExit(0 if ok else 1)
