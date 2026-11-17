"""Round-2 bugs B6 and B7 stay fixed (research/DAY-FOUR-ROUND2.md, section 7).

  B6  Session rebuilt its Observer in every hook process without the trace it had saved, so
      the inferred progress only ever saw the current call: all 698 inferred rows in round 2
      read "advancing, 1 recent call(s)", and the saved trace was cut back to one entry.
  B7  The hook signed a call as tool + the first 200 characters of str(args), so different
      heredoc edits that begin the same way looked like the same call repeated. A run that
      was finishing read as `observed: circling`, which can also turn the judgment to
      `verify`.

Drives the real hook (python -m laserbrain.hooks.lb_coverage) under a throwaway HOME, so
nothing outside a temp dir is written. Also checks the signature rule is the same in the
hook and in observe.py, which the hook duplicates on purpose.

Run:  python3 test_round2_b6b7.py
"""
import importlib.util, json, os, pathlib, random, subprocess, sys, tempfile
R = pathlib.Path(__file__).resolve().parent.parent
H = pathlib.Path(tempfile.mkdtemp(prefix='lbb6b7-'))
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN')}
ENV.update(HOME=str(H), PYTHONPATH=str(R / 'python'), PYTHONDONTWRITEBYTECODE='1', LASERBRAIN_AGENT='claude')
CFG = H / '.config' / 'laserbrain'
STATE = H / '.claude' / 'laserbrain'
res = {}


def hook(payload):
    p = subprocess.run([sys.executable, '-P', '-m', 'laserbrain.hooks.lb_coverage'], input=json.dumps(payload),
                       capture_output=True, text=True, env=ENV, cwd=str(H), timeout=60)
    return p.stdout.strip()


def bash(sid, cmd, code=0):
    hook({'hook_event_name': 'PostToolUse', 'session_id': sid, 'tool_name': 'Bash',
          'tool_input': {'command': cmd}, 'tool_response': {'stdout': 'ok', 'stderr': '', 'exit_code': code},
          'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})


def session(sid):
    try:
        return json.loads((STATE / f'{sid}.json').read_text())
    except Exception:
        return {}


def evidence():
    try:
        return json.loads((CFG / 'evidence.json').read_text())
    except Exception:
        return {}


def start(sid):
    hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid,
          'prompt': 'please refactor the parser module and add unit tests for it',
          'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})


# ── B6: the trace survives from one hook process to the next ──────────────────────────
start('b6')
for _ in range(3):
    bash('b6', 'npm run build')
s = session('b6')
last = (s.get('inferred') or [{}])[-1]
res['B6 three identical calls, three processes: inferred circling'] = (last.get('progress') == 'circling', last)
res['B6 the saved trace keeps every call'] = (len(s.get('events') or []) == 3, len(s.get('events') or []))
bash('b6', 'npm test')
last = (session('b6').get('inferred') or [{}])[-1]
res['B6 a different call recovers at once'] = (last.get('progress') == 'advancing', last)

# ── B7: calls that differ after 200 characters are different calls ────────────────────
HEAD = "cat > src/report.py <<'EOF'\n" + "# shared header line for the generated module\n" * 6
tails = ['def a():\n    return 1\nEOF', 'def b():\n    return 2\nEOF', 'def c():\n    return 3\nEOF']
assert len(HEAD) > 250, len(HEAD)
start('b7')
for t in tails:
    bash('b7', HEAD + t)
ev = evidence()
res['B7 three different long edits: observed advancing'] = (ev.get('progress') == 'advancing', ev.get('progress'))
last = (session('b7').get('inferred') or [{}])[-1]
res['B7 three different long edits: inferred advancing'] = (last.get('progress') == 'advancing', last)
for _ in range(3):
    bash('b7', HEAD + tails[0])
ev = evidence()
res['B7 the same long edit three times: observed circling'] = (ev.get('progress') == 'circling', ev.get('progress'))

# ── the signature rule is one rule, in both copies ────────────────────────────────────
sys.path.insert(0, str(R / 'python'))
from laserbrain.observe import _sig  # noqa: E402
spec = importlib.util.spec_from_file_location('lb_hook', R / 'python' / 'laserbrain' / 'hooks' / 'lb_coverage.py')
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)
random.seed(20261116)
diff = None
call_sig = getattr(hk, '_call_sig', None)
for i in range(300):
    tool = random.choice(['Bash', 'Edit', 'Write'])
    body = ''.join(random.choice('ab \né日\x00') for _ in range(random.randint(0, 900)))
    args = random.choice([{'command': body}, {'command': body, 'description': body[:20]},
                          {'file_path': 'x.py', 'new_string': body}, None, {}, [], ''])
    if call_sig is None or call_sig(tool, args) != _sig(tool, args):
        diff = 'the hook has no _call_sig' if call_sig is None else (tool, args)
        break
res['hook and observe.py sign every call the same way'] = (diff is None, diff)
a = {'command': HEAD + tails[0]}
b = {'command': HEAD + tails[1]}
res['same start, different end: different signatures'] = (_sig('Bash', a) != _sig('Bash', b), None)
res['identical calls: identical signatures'] = (_sig('Bash', dict(a)) == _sig('Bash', a), None)
res['signature stays short'] = (len(_sig('Bash', {'command': 'x' * 100000})) < 260, len(_sig('Bash', {'command': 'x' * 100000})))
res['a new description on the same command is the same call'] = (
    _sig('Bash', {'command': HEAD, 'description': 'first try'}) == _sig('Bash', {'command': HEAD, 'description': 'again'}), None)

# ── points from the review of this fix ────────────────────────────────────────────────
from laserbrain.observe import Observer  # noqa: E402
o = Observer('g')
for i, ok in enumerate((False, True, False, False)):     # distinct commands: not a loop
    o.record('Bash', {'command': f'make step{i}'}, ok=ok)
res['stuck explains the failures at the end, not all of them'] = (
    o.progress() == 'stuck' and o.why().startswith('2 consecutive'), (o.progress(), o.why()))
marker = {'step': 1, 'kind': 'check-unobserved', 'goal': 'g'}
try:
    got = hk.infer_progress([marker, {'sig': 'a', 'ok': True}, marker])
    res['a check marker in the trace is not read as a call'] = (got == 'advancing', got)
except Exception as e:  # noqa: BLE001
    res['a check marker in the trace is not read as a call'] = (False, repr(e))
from laserbrain.runtime import Session  # noqa: E402
sd = pathlib.Path(tempfile.mkdtemp(prefix='lbb6b7-sess-'))
(sd / 'm.json').write_text(json.dumps({'id': 'm', 'goal': 'g', 'steps': 2, 'checks': [], 'inferred': [],
                                       'catches': [], 'events': [{'sig': 'Bash|x#1', 'ok': True}, marker]}))
seeded = Session('m', directory=str(sd))._obs.events
res['a check marker never seeds a fake failure'] = (seeded == [{'sig': 'Bash|x#1', 'ok': True}], seeded)

bad = [k for k, (ok, _) in res.items() if not ok]
for k, (ok, detail) in res.items():
    print(('PASS ' if ok else 'FAIL ') + k + ('' if ok else f'   -> {detail}'))
print(f'\n{len(res) - len(bad)}/{len(res)} pass')
sys.exit(1 if bad else 0)
