#!/usr/bin/env python3
"""test_safety_wiring.py — lb_safety exactly as the settings wiring runs it.

    python3 test_safety_wiring.py

test_safety.py and test_safety_b9.py pin the DECISION (which commands are refused). This pins
the WIRING around it: the shell command strings a host's settings put on PreToolUse and on
SessionStart, run through /bin/sh -c the way the host runs them. The decision can be perfect
and the guard still absent, because:

  - a hook that exits 2 on PreToolUse refuses the tool call. A Python that cannot find its
    script exits 2, so a moved or deleted lb_safety.py would refuse EVERY tool call. The
    wiring checks the file first and exits 1 (a hook error the host reports and continues
    past), never 2;
  - the configured interpreter can disappear (a version manager's "latest" moves). The
    wiring falls back to /usr/bin/python3 so the guard keeps refusing;
  - run as a plain script, Python puts the script's directory first on sys.path, honours
    PYTHONPATH, and runs site (including editable-install finders). A stray json.py next to
    the hook, or on PYTHONPATH, would replace the stdlib module the hook imports. The wiring
    runs `-I -S` on the file itself, which needs nothing from the laserbrain package;
  - a guard that silently stops refusing looks exactly like one with nothing to refuse. The
    SessionStart self-test feeds it one guarded command and says so, once, when it is not
    refused. Healthy, it prints nothing.

The command shapes below are the ones the settings use, with this repo's hooks directory and
the running interpreter in place of the installed paths. Guarded phrases are assembled by
concatenation so that this file never holds one whole (lb_safety reads the shell text).

LB_SAFETY_DIR points the wiring at another hooks directory (a scratch build); default is this
repo's python/laserbrain/hooks.
"""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
HOOKS = pathlib.Path(os.environ.get('LB_SAFETY_DIR') or HERE / 'laserbrain' / 'hooks')
SYSTEM_PY = '/usr/bin/python3'     # the wiring's fallback interpreter

ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


# ── the command shapes ──────────────────────────────────────────────────────────────────

def safety_command(py, hooks_dir, fallback=SYSTEM_PY):
    """PreToolUse: lb_safety alone, as a plain file, -I -S, missing file -> exit 1."""
    q = shlex.quote
    return (f'P={q(str(py))}; [ -x "$P" ] || P={q(str(fallback))}; F={q(str(hooks_dir) + "/lb_safety.py")}; '
            '[ -r "$F" ] || { echo "laserbrain: safety hook file missing: $F" >&2; exit 1; }; '
            'exec "$P" -I -S "$F"')


def selftest_command(py, hooks_dir, fallback=SYSTEM_PY, who='the user'):
    """SessionStart: feed lb_safety one guarded command; silent when it is refused."""
    q = shlex.quote
    return (
        f'P={q(str(py))}; [ -x "$P" ] || P={q(str(fallback))}; F={q(str(hooks_dir) + "/lb_safety.py")}; '
        "O=$(printf '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git reset --ha%s HEAD\"}}' rd"
        ' | "$P" -I -S "$F" 2>/dev/null; echo " rc=$?"); '
        "case \"$O\" in *'\"deny\"'*' rc=2') exit 0;; esac; "
        "printf '%s\\n' '{\"systemMessage\":\"laserbrain: the safety hook did not refuse its test "
        "command, so force pushes, hard resets, recursive deletes, deploys and publishes are NOT "
        "guarded in this session.\",\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\","
        "\"additionalContext\":\"laserbrain: the safety hook is not working in this session. Ask "
        f"{who} before any force push, hard reset, recursive delete, deploy or publish.\"}}}}'; exit 0"
    )


# Guarded commands, one per rule family, never spelled whole in this file.
GUARDED = [
    ('force push', 'git push --' + 'force origin main'),
    ('hard reset', 'git reset --' + 'hard HEAD~1'),
    ('recursive delete', 'rm -' + 'rf build/'),
    ('package publish', 'npm ' + 'publish'),
    ('Workers deploy', 'wrangler ' + 'deploy'),
    ('registry upload', 'twine ' + 'upload dist/*'),
]


def _env(extra=None):
    env = dict(os.environ)
    env.pop('LASERBRAIN_SAFETY_OFF', None)
    if extra:
        env.update(extra)
    return env


def pre_tool(tool, tool_input):
    return json.dumps({'session_id': 'wiring-test', 'hook_event_name': 'PreToolUse',
                       'tool_name': tool, 'tool_input': tool_input, 'cwd': '/'})


def sh(cmd, stdin='', cwd=None, env=None):
    p = subprocess.run(['/bin/sh', '-c', cmd], input=stdin, capture_output=True, text=True,
                       cwd=cwd, env=env if env is not None else _env(), timeout=60)
    return p.returncode, p.stdout, p.stderr


def decision(stdout):
    try:
        h = json.loads(stdout).get('hookSpecificOutput') or {}
    except Exception:
        return None
    return (h.get('hookEventName'), h.get('permissionDecision'))


def denied(rc, out):
    return rc == 2 and decision(out) == ('PreToolUse', 'deny')


def runs_python3(path):
    """True when `path` is a working Python 3 (the fallback is only exercised where it is)."""
    if not os.access(path, os.X_OK):
        return False
    try:
        p = subprocess.run([path, '-I', '-S', '-c', 'import sys; print(sys.version_info[0])'],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return False
    return p.returncode == 0 and p.stdout.strip() == '3'


# ── checks ──────────────────────────────────────────────────────────────────────────────

def check_decisions(py, hooks):
    cmd = safety_command(py, hooks)
    for name, g in GUARDED:
        rc, out, err = sh(cmd, pre_tool('Bash', {'command': g}))
        show(f'guarded call refused: {name}', denied(rc, out), f'rc={rc} out={out[:120]!r}')
    rc, out, err = sh(cmd, pre_tool('Bash', {'command': 'ls'}))
    show('ls: exit 0, nothing printed', rc == 0 and not out.strip(), f'rc={rc} out={out[:120]!r}')
    rc, out, err = sh(cmd, pre_tool('Read', {'file_path': '/etc/hosts'}))
    show('non-shell tool: exit 0, nothing printed', rc == 0 and not out.strip(), f'rc={rc} out={out[:120]!r}')
    rc, out, err = sh(cmd, pre_tool('Edit', {'command': GUARDED[0][1]}))
    show('non-shell tool naming a guarded phrase: exit 0', rc == 0 and not out.strip(), f'rc={rc}')
    rc, out, err = sh(cmd, '')
    show('empty stdin: exit 0 (fail open)', rc == 0 and not out.strip(), f'rc={rc}')
    rc, out, err = sh(cmd, 'not json')
    show('unparseable stdin: exit 0 (fail open)', rc == 0 and not out.strip(), f'rc={rc}')
    # The escape hatch is read from the HOOK's environment; -I must not hide it.
    rc, out, err = sh(cmd, pre_tool('Bash', {'command': GUARDED[0][1]}), env=_env({'LASERBRAIN_SAFETY_OFF': '1'}))
    show('LASERBRAIN_SAFETY_OFF in the hook env still switches it off', rc == 0 and not out.strip(), f'rc={rc}')


def check_missing_file(py, tmp):
    empty = tmp / 'no-hooks-here'
    empty.mkdir()
    cmd = safety_command(py, empty)
    for label, payload in (('ls', pre_tool('Bash', {'command': 'ls'})),
                           ('guarded', pre_tool('Bash', {'command': GUARDED[0][1]}))):
        rc, out, err = sh(cmd, payload)
        show(f'missing lb_safety.py, {label} call: exit 1, never 2',
             rc == 1 and not out.strip() and 'safety hook file missing' in err, f'rc={rc} err={err[:120]!r}')
    rc, out, err = sh(safety_command(tmp / 'nope' / 'python3', empty, fallback=tmp / 'nope' / 'python3b'),
                      pre_tool('Bash', {'command': GUARDED[0][1]}))
    show('missing file AND missing interpreter: exit 1, never 2', rc == 1, f'rc={rc}')


def check_fallback(py, hooks, tmp):
    gone = tmp / 'gone' / 'bin' / 'python3'
    # The fallback logic, independent of what this machine has at /usr/bin/python3.
    cmd = safety_command(gone, hooks, fallback=py)
    rc, out, err = sh(cmd, pre_tool('Bash', {'command': GUARDED[1][1]}))
    show('interpreter missing: falls back and still refuses', denied(rc, out), f'rc={rc} err={err[:160]!r}')
    rc, out, err = sh(cmd, pre_tool('Bash', {'command': 'ls'}))
    show('interpreter missing: ls still exit 0', rc == 0 and not out.strip(), f'rc={rc}')
    # The real fallback the settings name.
    if runs_python3(SYSTEM_PY):
        cmd = safety_command(gone, hooks)
        for name, g in (GUARDED[0], GUARDED[2]):
            rc, out, err = sh(cmd, pre_tool('Bash', {'command': g}))
            show(f'fallback {SYSTEM_PY} refuses: {name}', denied(rc, out), f'rc={rc} err={err[:160]!r}')
        rc, out, err = sh(cmd, pre_tool('Bash', {'command': 'ls'}))
        show(f'fallback {SYSTEM_PY}: ls exit 0', rc == 0 and not out.strip(), f'rc={rc} err={err[:160]!r}')
    else:
        print(f'  note {SYSTEM_PY} is not a working Python 3 here; fallback checked with {py} only')
    # Neither interpreter: the shell cannot exec, and that must not read as a refusal.
    rc, out, err = sh(safety_command(gone, hooks, fallback=tmp / 'gone' / 'python3b'),
                      pre_tool('Bash', {'command': 'ls'}))
    show('no interpreter at all: not exit 2', rc != 2, f'rc={rc}')


POISON = '''import os, sys
open(os.environ["LB_POISON_MARK"], "a").write(__file__ + "\\n")
sys.exit(0)
'''


def check_isolation(py, hooks, tmp):
    """lb_safety alone in a directory, next to and under a poisoned json.py, still refuses."""
    alone = tmp / 'alone'
    alone.mkdir()
    shutil.copy2(hooks / 'lb_safety.py', alone / 'lb_safety.py')
    (alone / 'json.py').write_text(POISON)          # beside the script: sys.path[0] without -I
    cwd = tmp / 'cwd'
    cwd.mkdir()
    (cwd / 'json.py').write_text(POISON)            # the working directory
    path_dir = tmp / 'pythonpath'
    path_dir.mkdir()
    (path_dir / 'json.py').write_text(POISON)       # PYTHONPATH, honoured without -I
    mark = tmp / 'poison-ran.txt'
    env = _env({'LB_POISON_MARK': str(mark), 'PYTHONPATH': str(path_dir)})

    # Control: the same file run as a plain script imports the poison and fails open. Without
    # this the check below could pass on a poison that never worked.
    p = subprocess.run([py, str(alone / 'lb_safety.py')], input=pre_tool('Bash', {'command': GUARDED[0][1]}),
                       capture_output=True, text=True, cwd=cwd, env=env, timeout=60)
    show('control: plain `python3 lb_safety.py` imports a stray json.py and lets the call through',
         mark.exists() and p.returncode == 0 and decision(p.stdout) is None, f'rc={p.returncode} mark={mark.exists()}')
    if mark.exists():
        mark.unlink()

    cmd = safety_command(py, alone)
    for name, g in (GUARDED[0], GUARDED[3]):
        rc, out, err = sh(cmd, pre_tool('Bash', {'command': g}), cwd=cwd, env=env)
        show(f'-I -S, alone with poisoned json.py (script dir, cwd, PYTHONPATH): refuses {name}',
             denied(rc, out) and not mark.exists(), f'rc={rc} poison_ran={mark.exists()} err={err[:160]!r}')
    rc, out, err = sh(cmd, pre_tool('Bash', {'command': 'ls'}), cwd=cwd, env=env)
    show('-I -S, alone with poisoned json.py: ls exit 0', rc == 0 and not out.strip() and not mark.exists(), f'rc={rc}')
    # No laserbrain package anywhere near it: the hook needs only the stdlib.
    p = subprocess.run([py, '-I', '-S', '-c', 'import sys; sys.argv = ["x"]; '
                        f'exec(compile(open({str(alone / "lb_safety.py")!r}).read(), "lb_safety", "exec"), '
                        '{"__name__": "probe"}); print(sorted(m for m in sys.modules if "laserbrain" in m))'],
                       capture_output=True, text=True, cwd=cwd, env=env, timeout=60)
    show('lb_safety imports nothing from the laserbrain package',
         p.returncode == 0 and p.stdout.strip() == '[]' and not mark.exists(), f'rc={p.returncode} out={p.stdout[:120]!r}')


def selftest_output(stdout):
    try:
        d = json.loads(stdout)
    except Exception:
        return None
    h = d.get('hookSpecificOutput') or {}
    return (bool(d.get('systemMessage')) and 'safety hook' in d['systemMessage']
            and h.get('hookEventName') == 'SessionStart' and 'safety hook' in (h.get('additionalContext') or ''))


def check_selftest(py, hooks, tmp):
    rc, out, err = sh(selftest_command(py, hooks), '')
    show('SessionStart self-test, healthy: exit 0, silent', rc == 0 and not out.strip() and not err.strip(),
         f'rc={rc} out={out[:120]!r} err={err[:120]!r}')
    rc, out, err = sh(selftest_command(tmp / 'gone' / 'python3', hooks, fallback=py), '')
    show('self-test, interpreter missing: falls back, silent', rc == 0 and not out.strip(), f'rc={rc} out={out[:120]!r}')
    missing = tmp / 'selftest-missing'
    missing.mkdir()
    rc, out, err = sh(selftest_command(py, missing), '')
    show('self-test, lb_safety.py missing: exit 0, prints the warning', rc == 0 and selftest_output(out) is True,
         f'rc={rc} out={out[:160]!r}')
    # A file that is there but refuses nothing (fails open on every call) must also warn.
    inert = tmp / 'selftest-inert'
    inert.mkdir()
    (inert / 'lb_safety.py').write_text('import sys\nsys.exit(0)\n')
    rc, out, err = sh(selftest_command(py, inert), '')
    show('self-test, lb_safety refuses nothing: prints the warning', rc == 0 and selftest_output(out) is True,
         f'rc={rc} out={out[:160]!r}')
    rc, out, err = sh(selftest_command(tmp / 'gone' / 'python3', missing, fallback=tmp / 'gone' / 'python3b'), '')
    show('self-test, no interpreter and no file: exit 0, prints the warning', rc == 0 and selftest_output(out) is True,
         f'rc={rc} out={out[:160]!r}')
    # Claude Code reads a refusal only from exit 2: a hook that prints the deny JSON but exits 1
    # refuses nothing, so the self-test must warn on the exit status, not only on the text.
    exit1 = tmp / 'selftest-deny-exit1'
    exit1.mkdir()
    (exit1 / 'lb_safety.py').write_text(
        'import json, sys\nsys.stdin.read()\n'
        'print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", '
        '"permissionDecision": "deny", "permissionDecisionReason": "x"}}))\nsys.exit(1)\n')
    rc, out, err = sh(selftest_command(py, exit1), '')
    show('self-test, lb_safety prints a refusal but exits 1: prints the warning',
         rc == 0 and selftest_output(out) is True, f'rc={rc} out={out[:160]!r}')


def main():
    py = sys.executable
    if not (HOOKS / 'lb_safety.py').exists():
        show('lb_safety.py exists', False, str(HOOKS / 'lb_safety.py'))
        return 1
    with tempfile.TemporaryDirectory(prefix='lb-safety-wiring-') as t:
        tmp = pathlib.Path(t)
        print('PreToolUse wiring: decisions')
        check_decisions(py, HOOKS)
        print('PreToolUse wiring: missing file')
        check_missing_file(py, tmp)
        print('PreToolUse wiring: missing interpreter')
        check_fallback(py, HOOKS, tmp)
        print('PreToolUse wiring: isolation')
        check_isolation(py, HOOKS, tmp)
        print('SessionStart self-test')
        check_selftest(py, HOOKS, tmp)
    print('\n  ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
