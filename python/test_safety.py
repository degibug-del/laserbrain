#!/usr/bin/env python3
"""test_safety.py — irreversible shell actions denied under always-approve."""
import json, os, pathlib, subprocess, sys, tempfile

# See the note in test_gate_hosts.py: lasergear is a separate repo, this reaches into it,
# and CI on a clean runner is what made that visible. LASERGEAR_DIR overrides; absent, this
# skips with exit 77 rather than failing, because "could not run" and "ran and failed" are
# different facts.
_GEAR = pathlib.Path(os.environ.get('LASERGEAR_DIR') or (
    pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/lasergear'))
HOOK = _GEAR / 'lb_safety.py'
if not HOOK.exists():
    print(f'  SKIP  lb_safety.py not found at {HOOK} — set LASERGEAR_DIR to a lasergear checkout')
    raise SystemExit(77)
ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def run(tool, command, env_extra=None):
    env = dict(os.environ)
    env.pop('LASERBRAIN_SAFETY_OFF', None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({'tool_name': tool, 'tool_input': {'command': command}}),
        text=True, capture_output=True, env=env,
    )
    return proc.returncode, proc.stderr


def main():
    if not HOOK.exists():
        show('lb_safety exists', False, str(HOOK))
        return 1

    cases_deny = [
        ('run_terminal_command', 'git push --force origin main'),
        ('Bash', 'git push -f origin head'),
        ('bash', 'git push --force-with-lease'),
        ('run_terminal_command', 'git reset --hard HEAD~3'),
        ('run_terminal_command', 'rm -rf /tmp/foo'),
        ('run_terminal_command', 'wrangler deploy'),
        ('run_terminal_command', 'npm publish'),
    ]
    for tool, cmd in cases_deny:
        code, err = run(tool, cmd)
        show(f'deny: {cmd[:40]}', code == 2 and 'safety' in err, f'exit={code}')

    cases_allow = [
        ('run_terminal_command', 'git push origin main'),
        ('run_terminal_command', 'git status'),
        ('run_terminal_command', 'pytest -q'),
        ('search_replace', 'git push --force'),  # not a bash tool
        ('read_file', 'anything'),
    ]
    for tool, cmd in cases_allow:
        code, err = run(tool, cmd)
        show(f'allow: {tool} {cmd[:30]}', code == 0, f'exit={code} err={err[:80]!r}')

    code, err = run('run_terminal_command', 'git push --force',
                    env_extra={'LASERBRAIN_SAFETY_OFF': '1'})
    show('bypass LASERBRAIN_SAFETY_OFF', code == 0, f'exit={code}')

    print('\n  ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
