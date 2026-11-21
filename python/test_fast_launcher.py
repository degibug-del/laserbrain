"""hooks/fast.py, the launcher that starts lb_coverage without the package __init__ (2026-11-19).

WHY. `python3 -P -m laserbrain.hooks.lb_coverage` runs laserbrain/__init__.py first: 2,557
lines and 18 modules the hook never uses, on every tool call. fast.py registers the package
directory as a bare package and imports the hook from it, under `-I -S`, so neither the
editable-install finder nor the agent's working directory decides which code runs. A launcher
that changed what the hook does would be worse than the milliseconds it saves, so this pins:

  A  the same 10-event session through `-P -m` and through fast.py gives the same exit codes,
     the same stdout and the same state files (timestamps normalised)
  B  a copy whose laserbrain/__init__.py raises still runs lb_coverage through fast.py
     (and `-P -m` on that copy does not: the __init__ really is skipped, not just survived)
  C  a decoy laserbrain package in the working directory, or on PYTHONPATH, is ignored
  D  `fast.py lb_safety`, `fast.py nothing` and `fast.py` with no name exit 0 and print
     nothing: only lb_coverage is allowed, and lb_safety runs as its own file
  E  fails open: an exception inside the hook exits 0 silently; a SystemExit passes through

-B on every run here only keeps a test run from leaving bytecode in the checkout; it does not
change where any module is loaded from.

Run:  python3 test_fast_launcher.py
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
PKG = ROOT / 'laserbrain'
FAST = PKG / 'hooks' / 'fast.py'
SAFETY = PKG / 'hooks' / 'lb_safety.py'
CHECK = 'mcp__laserbrain__check_state'
# A command lb_safety must refuse, assembled so this file never holds the phrase.
GUARDED = 'git push --' + 'force origin main'
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


MADE = []


def fresh(tag):
    d = pathlib.Path(tempfile.mkdtemp(prefix=f'lb-fast-{tag}-'))
    MADE.append(d)
    for sub in ('state', 'home/config'):
        (d / sub).mkdir(parents=True)
    # Judges off twice over (env and file), as the other hook suites do: no detached workers,
    # no model calls, nothing that could finish after the comparison below.
    for off in ('askllm-watch.off', 'turnwatch.off'):
        (d / 'state' / off).touch()
    return d


def env_for(d, pythonpath=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LASERBRAIN_', 'PYTHON'))}
    env.update(HOME=str(d / 'home'), LASERBRAIN_HOME=str(d / 'home'),
               LASERBRAIN_STATE_DIR=str(d / 'state'), LASERBRAIN_AGENT='claude',
               LASERBRAIN_LINK_LOG=str(d / 'link.jsonl'), LASERBRAIN_PROBE_SHARE='0',
               LASERBRAIN_TURNS_HARVEST='0', LASERBRAIN_ASKLLM_WATCH='off',
               LASERBRAIN_ASKLLM_MODE='off', LASERBRAIN_TURNWATCH='off')
    if pythonpath is not None:
        env['PYTHONPATH'] = str(pythonpath)
    return env


def via_module(d, ev, pythonpath=ROOT, cwd=None):
    return subprocess.run([sys.executable, '-B', '-P', '-m', 'laserbrain.hooks.lb_coverage'],
                          input=json.dumps(ev), capture_output=True, text=True, timeout=60,
                          env=env_for(d, pythonpath), cwd=str(cwd or d))


def via_fast(d, ev, fast=FAST, name='lb_coverage', cwd=None, pythonpath=None):
    argv = [sys.executable, '-B', '-I', '-S', str(fast)] + ([name] if name is not None else [])
    return subprocess.run(argv, input=json.dumps(ev) if ev is not None else '',
                          capture_output=True, text=True, timeout=60,
                          env=env_for(d, pythonpath), cwd=str(cwd or d))


def enqueue(ts, content):
    return json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': ts,
                       'content': content}) + '\n'


def sequence(d):
    """Ten hook events of one synthetic session: a prompt, a check, reads and shell calls, a
    failure, a helper with its own first check, a task notification and a second prompt that
    also lands in the transcript as an enqueue. Returns (event, transcript text to append)."""
    tr = str(d / 'transcript.jsonl')
    sid = 'fast-launcher-1'
    reply = {'content': [{'type': 'text', 'text': json.dumps({'drifting': False,
                                                             'reason': 'grounded'})}]}

    def E(name, **kw):
        e = {'session_id': sid, 'transcript_path': tr, 'cwd': str(d),
             'hook_event_name': name, 'permission_mode': 'default'}
        e.update(kw)
        return e

    def post(tool, tin, n, agent=None, resp=None, fail=False):
        extra = {'agent_id': agent, 'agent_type': 'general-purpose'} if agent else {}
        if fail:
            return E('PostToolUseFailure', tool_name=tool, tool_input=tin, tool_use_id=f'toolu_f{n}',
                     error='Exit code 1\nfailed', **extra)
        return E('PostToolUse', tool_name=tool, tool_input=tin, tool_use_id=f'toolu_f{n}',
                 tool_response=resp or {'stdout': 'x', 'stderr': ''}, **extra)

    return [
        (E('UserPromptSubmit', prompt='refactor the parser and add tests'),
         enqueue('2026-11-19T10:00:00.000Z', 'refactor the parser and add tests')),
        (post(CHECK, {'goal': 'refactor the parser', 'progress': 'advancing', 'distance': 8}, 1,
              resp=reply), ''),
        (post('Read', {'file_path': '/src/parser.py'}, 2), ''),
        (post('Bash', {'command': 'make test'}, 3), ''),
        (post('Bash', {'command': 'make lint'}, 4, fail=True), ''),
        (post('Agent', {'prompt': 'write the parser tests', 'description': 'tests'}, 5), ''),
        (post(CHECK, {'goal': 'write parser tests', 'progress': 'advancing', 'distance': 7,
                      'session': 'tests'}, 6, agent='agent-f1', resp=reply), ''),
        (post('Read', {'file_path': '/src/test_parser.py'}, 7, agent='agent-f1'), ''),
        (E('UserPromptSubmit', prompt='<task-notification>job done</task-notification>'),
         enqueue('2026-11-19T10:05:00.000Z', '<task-notification>job done</task-notification>')),
        (E('UserPromptSubmit', prompt='also update the README'),
         enqueue('2026-11-19T10:06:00.000Z', 'also update the README')),
    ]


def normalised_state(d):
    out = {}
    for root in (d / 'state', d / 'home'):
        for p in sorted(root.rglob('*')):
            if p.is_dir() or p.name.endswith('.off'):
                continue
            x = p.read_text(errors='replace').replace(str(d), 'RUN')
            x = re.sub(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[^"\n]*', 'T', x)
            x = re.sub(r'"(t|ms|elapsed|duration_ms|mtime)": [0-9.e+-]+', r'"\1": 0', x)
            out[str(p.relative_to(d))] = x
    return out


def replay(runner, d):
    results = []
    tr = d / 'transcript.jsonl'
    tr.touch()
    for ev, append in sequence(d):
        if append:
            with tr.open('a') as fh:
                fh.write(append)
        p = runner(d, ev)
        results.append((ev['hook_event_name'], p.returncode, p.stdout.replace(str(d), 'RUN'),
                        p.stderr.replace(str(d), 'RUN')))
    return results


def copy_package(tag):
    """A copy of python/laserbrain (no bytecode) to break on purpose."""
    d = fresh(tag)
    shutil.copytree(PKG, d / 'src' / 'laserbrain', ignore=shutil.ignore_patterns('__pycache__'))
    return d, d / 'src'


print('\n  A. the same session through -P -m and through fast.py')
dm, df = fresh('m'), fresh('f')
rm, rf = replay(via_module, dm), replay(via_fast, df)
show('10 events each', len(rm) == len(rf) == 10, f'{len(rm)} {len(rf)}')
show('every exit code matches (and is 0)', [r[1] for r in rm] == [r[1] for r in rf]
     and set(r[1] for r in rf) == {0}, f'{[r[1] for r in rm]} vs {[r[1] for r in rf]}')
diff_out = [i for i, (a, b) in enumerate(zip(rm, rf)) if a[2] != b[2]]
show('stdout matches event by event', not diff_out,
     f'events {diff_out}: {rm[diff_out[0]][2][:120]!r} vs {rf[diff_out[0]][2][:120]!r}' if diff_out else '')
show('...and the session printed something to compare (not two silent runs)',
     any(r[2].strip() for r in rf), str([r[2][:40] for r in rf]))
show('neither form wrote to stderr', not any(r[3] for r in rm + rf),
     next((r[3][:160] for r in rm + rf if r[3]), ''))
sm, sf = normalised_state(dm), normalised_state(df)
show('the same state files are written', sorted(sm) == sorted(sf),
     f'only -m: {sorted(set(sm) - set(sf))}, only fast: {sorted(set(sf) - set(sm))}')
diff_files = sorted(k for k in set(sm) & set(sf) if sm[k] != sf[k])
show('...with the same contents once timestamps are normalised', not diff_files, str(diff_files))
try:
    goals = [c.get('goal') for c in
             json.loads((df / 'state' / 'fast-launcher-1.json').read_text()).get('checks', [])]
except Exception as e:                               # noqa: BLE001
    goals = [repr(e)]
show('...including the session file, with the main and the helper check recorded',
     goals == ['refactor the parser', 'write parser tests'], str(goals))

print('\n  B. a package whose __init__ raises')
d, src = copy_package('b')
(src / 'laserbrain' / '__init__.py').write_text(
    "raise RuntimeError('laserbrain/__init__.py ran')\n")
evs = sequence(d)
(d / 'transcript.jsonl').write_text(evs[0][1])
p0 = via_fast(d, evs[0][0], fast=src / 'laserbrain' / 'hooks' / 'fast.py')
p1 = via_fast(d, evs[1][0], fast=src / 'laserbrain' / 'hooks' / 'fast.py')
show('fast.py exits 0 on a prompt and on a check_state', p0.returncode == 0 and p1.returncode == 0,
     f'{p0.returncode} {p1.returncode} {p1.stderr[-200:]}')
sess = d / 'state' / 'fast-launcher-1.json'
recorded = sess.exists() and 'refactor the parser' in sess.read_text()
show('...and lb_coverage really ran: the check is in the session file (runtime imported)',
     recorded, sorted(x.name for x in (d / 'state').iterdir()))
show('...without a word on stderr', p0.stderr == '' and p1.stderr == '', (p0.stderr + p1.stderr)[-200:])
pm = via_module(fresh('bm'), evs[1][0], pythonpath=src)
show('control: -P -m on the same copy does run the __init__ (and fails)',
     pm.returncode != 0 and 'laserbrain/__init__.py ran' in pm.stderr, f'{pm.returncode} {pm.stderr[-160:]}')

print('\n  C. a decoy laserbrain in the working directory or on PYTHONPATH')
d = fresh('c')
decoy = d / 'decoy'
marker = d / 'decoy-ran'
for rel in ('laserbrain/__init__.py', 'laserbrain/runtime.py', 'laserbrain/hooks/__init__.py',
            'laserbrain/hooks/lb_coverage.py'):
    f = decoy / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"open({str(marker)!r}, 'a').write({rel!r} + '\\n')\ndef main():\n    pass\n")
ctl = subprocess.run([sys.executable, '-B', '-S', '-c', 'import laserbrain.hooks.lb_coverage'],
                     cwd=str(decoy), capture_output=True, text=True, env=env_for(d), timeout=60)
show('control: the decoy is importable from its own directory', marker.exists(),
     f'{ctl.returncode} {ctl.stderr[-160:]}')
if marker.exists():
    marker.unlink()
evs = sequence(d)
(d / 'transcript.jsonl').write_text(evs[0][1])
p0 = via_fast(d, evs[0][0], cwd=decoy, pythonpath=decoy)
p1 = via_fast(d, evs[1][0], cwd=decoy, pythonpath=decoy)
show('fast.py from the decoy directory, decoy on PYTHONPATH: exit 0',
     p0.returncode == 0 and p1.returncode == 0, f'{p0.returncode} {p1.returncode}')
show('...not one decoy module ran', not marker.exists(),
     marker.read_text() if marker.exists() else '')
sess = d / 'state' / 'fast-launcher-1.json'
show('...the real lb_coverage ran instead', sess.exists() and 'refactor the parser' in sess.read_text(),
     sorted(x.name for x in (d / 'state').iterdir()))

print('\n  D. only lb_coverage is started')
guarded = {'session_id': 'fast-launcher-1', 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
           'tool_input': {'command': GUARDED}}
d = fresh('d')
real = subprocess.run([sys.executable, '-B', '-I', '-S', str(SAFETY)], input=json.dumps(guarded),
                      capture_output=True, text=True, timeout=60, env=env_for(d), cwd=str(d))
show('control: lb_safety run as its own file refuses the guarded command (exit 2, deny)',
     real.returncode == 2 and '"deny"' in real.stdout, f'{real.returncode} {real.stdout[:120]}')
for name in ('lb_safety', 'nothing', 'lb_gate', '../lb_coverage', None):
    d = fresh('d')
    p = via_fast(d, guarded, name=name)
    left = sorted(str(x.relative_to(d)) for x in d.rglob('*')
                  if x.is_file() and not x.name.endswith('.off'))
    show(f'fast.py {name if name is not None else "(no name)"}: exit 0, no output, nothing written',
         p.returncode == 0 and p.stdout == '' and p.stderr == '' and not left,
         f'{p.returncode} {p.stdout[:80]!r} {p.stderr[-80:]!r} {left}')

print('\n  E. fails open, passes SystemExit through')
for tag, body, want in (('raise', "def main():\n    raise ValueError('boom')\n", 0),
                        ('exit', "import sys\ndef main():\n    sys.exit(3)\n", 3)):
    d, src = copy_package(f'e{tag}')
    (src / 'laserbrain' / 'hooks' / 'lb_coverage.py').write_text(body)
    p = via_fast(d, {}, fast=src / 'laserbrain' / 'hooks' / 'fast.py')
    show(f'a hook that does {"raise ValueError" if tag == "raise" else "sys.exit(3)"}: exit {want}'
         + (', silent' if want == 0 else ''),
         p.returncode == want and (want != 0 or (p.stdout == '' and p.stderr == '')),
         f'{p.returncode} {p.stderr[-120:]!r}')

for d in MADE:
    shutil.rmtree(d, ignore_errors=True)
print('\n  ' + ('PASS' if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
