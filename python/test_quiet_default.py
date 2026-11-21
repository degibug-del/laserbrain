"""Quiet by default (policy quiet-2026-11-19): in nudge mode lb_coverage says nothing unless
something was flagged, and a user message gets one turn line.

WHAT IS PINNED, each through lb_coverage as a subprocess the way the harness runs it, with every
LASERBRAIN_* variable stripped (the default environment) and a scratch HOME and state dir:

  1  an ordinary PostToolUse prints nothing, even past the old reminder's step count
  2  a main-session check_state prints nothing, even where the honesty note used to go out
  3  a helper's check_state is still counted in <sid>.agents.json (askllm reads it)
  4  a real prompt prints exactly one UserPromptSubmit additionalContext, TURN_LINE, and
     writes the user-turn flag
  5  a <task-notification> prompt prints nothing and writes no flag
  6  LASERBRAIN_TURN_LINE=off (and LASERBRAIN_TURNWATCH_TRIGGER=first_tool) print nothing
  7  askllm note mode: a pending note is still delivered, to the helper and to the parent
  8  check rows in the session file carry the policy and no token count
  9  LASERBRAIN_STUDY=1 brings back the step reminder, the gate line, the honesty note and the
     token count, and drops the policy stamp
 10  the embedded fallback (runtime import fails) follows the same two rules: no reminder, no
     flag for a <task-notification>; a real prompt still gets the one turn line, also when the
     runtime path raises on a broken session file
 11  hard, watch and signal are never quiet

No judge can start: both judges are switched off by environment and by their .off files, the
child PATH is /usr/bin:/bin, and CLAUDE* variables are dropped. All fixtures are synthetic.

Run:  python3 test_quiet_default.py
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
HOOK = ROOT / 'laserbrain' / 'hooks' / 'lb_coverage.py'
PY = sys.executable
CHECK = 'mcp__laserbrain__check_state'
POLICY = 'quiet-2026-11-19'
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Box:
    """One scratch HOME + state dir. `judges_off` writes both judges' .off files."""

    def __init__(self, judges_off=True):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix='lbquiet-'))
        self.home = self.root / 'home'
        self.state = self.root / 'state'
        self.home.mkdir()
        self.state.mkdir()
        if judges_off:
            for off in ('askllm-watch.off', 'turnwatch.off'):
                (self.state / off).write_text('')
        self.judges_off = judges_off
        self.transcript = self.root / 'transcript.jsonl'
        # Two assistant turns with usage, so a token count has something to add up.
        usage = {'input_tokens': 100, 'output_tokens': 10, 'cache_read_input_tokens': 1000,
                 'cache_creation_input_tokens': 0}
        self.transcript.write_text(''.join(
            json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'usage': usage,
                                                         'content': [{'type': 'text', 'text': 'x'}]}}) + '\n'
            for _ in range(2)))
        self.flag = self.home / '.config' / 'laserbrain' / 'user-turn'
        self.stub = None

    def env(self, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('LASERBRAIN', 'CLAUDE', 'ANTHROPIC'))}
        env.update(HOME=str(self.home), LASERBRAIN_STATE_DIR=str(self.state),
                   PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PATH='/usr/bin:/bin',
                   LASERBRAIN_TURNS_HARVEST='0', LASERBRAIN_TURNWATCH='off')
        if self.judges_off:
            env['LASERBRAIN_ASKLLM_WATCH'] = 'off'
        env.update(extra or {})
        return env

    def run(self, ev, extra=None, fallback=False):
        ev = dict({'session_id': 'quiet-s1', 'transcript_path': str(self.transcript),
                   'cwd': str(self.root)}, **ev)
        env = self.env(extra)
        if fallback:
            if self.stub is None:
                # The fallback runs only when `from laserbrain.runtime import ...` fails; a stub
                # package that raises on that import forces it without touching the code.
                self.stub = self.root / 'stub'
                (self.stub / 'laserbrain').mkdir(parents=True)
                (self.stub / 'laserbrain' / '__init__.py').write_text('')
                (self.stub / 'laserbrain' / 'runtime.py').write_text(
                    "raise ImportError('stub: force the embedded fallback')\n")
            env['PYTHONPATH'] = str(self.stub)
            cmd = [PY, '-P', str(HOOK)]
        else:
            cmd = [PY, '-P', '-m', 'laserbrain.hooks.lb_coverage']
        return subprocess.run(cmd, input=json.dumps(ev), capture_output=True, text=True, env=env,
                              cwd=str(self.root), timeout=60)

    def session(self, sid='quiet-s1'):
        try:
            return json.loads((self.state / f'{sid}.json').read_text())
        except Exception:
            return {}

    def agents(self, sid='quiet-s1'):
        try:
            return json.loads((self.state / f'{sid}.agents.json').read_text())
        except Exception:
            return {}


def bash(i=0, agent=None, event='PostToolUse'):
    ev = {'hook_event_name': event, 'tool_name': 'Bash', 'tool_input': {'command': f'make t{i}'},
          'tool_use_id': f'toolu_q{i}', 'tool_response': {'stdout': 'x', 'stderr': '', 'exit_code': 0}}
    if agent:
        ev.update(agent_id=agent, agent_type='general-purpose')
    return ev


def check(distance, agent=None, progress='advancing', i=0):
    resp = {'content': [{'type': 'text', 'text': json.dumps(
        {'drifting': False, 'reason': 'advancing', 'phi': 0.1, 'run': 'R1', 'step': i + 1,
         'arm': 'sighted'})}]}
    ev = {'hook_event_name': 'PostToolUse', 'tool_name': CHECK, 'tool_use_id': f'toolu_c{i}',
          'tool_input': {'goal': 'refactor the parser', 'progress': progress, 'distance': distance},
          'tool_response': resp}
    if agent:
        ev.update(agent_id=agent, agent_type='general-purpose')
    return ev


def prompt(text):
    return {'hook_event_name': 'UserPromptSubmit', 'prompt': text}


def contexts(r):
    """(hookEventName, additionalContext) for every JSON line printed."""
    out = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        try:
            h = json.loads(line).get('hookSpecificOutput') or {}
        except Exception:
            out.append((None, line))
            continue
        out.append((h.get('hookEventName'), h.get('additionalContext')))
    return out


def clean(rs):
    return all(r.returncode == 0 and not r.stderr.strip() for r in rs)


C = _load('lb_coverage_quiet_test', HOOK)
TURN_LINE = C.TURN_LINE
STUDY = {'LASERBRAIN_STUDY': '1'}
REMINDER = 'steps since your last check_state'
GATE_LINE = 'Gate: never batch'
HONESTY = 'distance has not fallen across the last two checks'

print('\n  quiet by default (nudge mode, LASERBRAIN_STUDY unset)')
show('TURN_LINE is one laserbrain line that asks for one check_state with the first tool call',
     TURN_LINE.startswith('laserbrain: ') and '\n' not in TURN_LINE and 'check_state' in TURN_LINE
     and 'first tool call' in TURN_LINE, TURN_LINE)

# 1. ordinary calls, past the old reminder's cadence (NUDGE_AFTER = 8)
b = Box()
rs = [b.run(bash(i)) for i in range(1, 2 * C.NUDGE_AFTER + 1)]
show(f'1  {len(rs)} ordinary PostToolUse calls with no check print nothing',
     all(r.stdout == '' for r in rs) and clean(rs), [r.stdout[:80] for r in rs if r.stdout][:2])
show('...and every step is still recorded in the session file',
     int(b.session().get('steps') or 0) == len(rs), b.session().get('steps'))

# 2. main check_state, twice at the same distance (where the honesty note used to go out)
b = Box()
rs = [b.run(check(3, i=0)), b.run(bash(1)), b.run(check(3, i=2))]
show('2  a main-session check_state prints nothing (equal distances: no honesty note either)',
     all(r.stdout == '' for r in rs) and clean(rs), [r.stdout[:120] for r in rs])
show('...both checks are recorded', len(b.session().get('checks') or []) == 2,
     len(b.session().get('checks') or []))

# 3. helper check_state still counted per agent
b = Box()
r1 = b.run(check(6, agent='helper-1', i=0))
r2 = b.run(bash(1, agent='helper-1'))
e = b.agents().get('helper-1') or {}
show('3  a helper check_state prints nothing', r1.stdout == '' and r2.stdout == '' and clean([r1, r2]),
     r1.stdout[:120])
show('...and increments <sid>.agents.json for that helper',
     e.get('checks') == 1 and e.get('check_step') == 1 and e.get('steps') == 2, e)

# 4. a real prompt: exactly one turn line, and the flag
b = Box()
r = b.run(prompt('please refactor the parser and add tests'))
cx = contexts(r)
show('4  a real prompt prints exactly one UserPromptSubmit additionalContext equal to TURN_LINE',
     cx == [('UserPromptSubmit', TURN_LINE)] and clean([r]), r.stdout[:300])
show('...and writes the user-turn flag', b.flag.exists(), str(b.flag))
b2 = Box()
r = b2.run({'hook_event_name': 'UserPromptSubmit', 'prompt': '   real text after spaces'})
show('...leading spaces do not hide a real prompt', contexts(r) == [('UserPromptSubmit', TURN_LINE)]
     and b2.flag.exists(), r.stdout[:200])

# 5. a <task-notification> is not the user
b = Box()
r = b.run(prompt('<task-notification><status>completed</status></task-notification>'))
show('5  a <task-notification> prompt prints nothing', r.stdout == '' and clean([r]), r.stdout[:200])
show('...and writes no user-turn flag', not b.flag.exists())
r = b.run(prompt('  \n<task-notification>job done</task-notification>'))
show('...also after leading whitespace', r.stdout == '' and not b.flag.exists(), r.stdout[:200])

# 6. the turn line's two off switches
for k, v in (('LASERBRAIN_TURN_LINE', 'off'), ('LASERBRAIN_TURN_LINE', '0'),
             ('LASERBRAIN_TURNWATCH_TRIGGER', 'first_tool')):
    b = Box()
    r = b.run(prompt('please refactor the parser'), extra={k: v})
    show(f'6  {k}={v}: a real prompt prints nothing', r.stdout == '' and clean([r]), r.stdout[:200])
    show('...the user-turn flag is still written', b.flag.exists())

# 7. askllm note mode: a flagged helper's note still goes out
b = Box(judges_off=False)            # note mode needs askllm on; only non-check calls run here
Wm = _load('lb_askllm_watch_quiet_test', ROOT / 'laserbrain' / 'hooks' / 'lb_askllm_watch.py')
Wm.write_note(b.state, {'session': 'quiet-s1', 'agent_id': 'helper-7'},
              {'label': 'review:css', 'workflow_name': 'audit-run', 'why': 'The goal names only the CSS.',
               'missing': ['review the auth module']})
note_env = {'LASERBRAIN_ASKLLM_MODE': 'note'}
r1 = b.run(bash(1, agent='helper-7'), extra=note_env)
cx = contexts(r1)
show('7  note mode: the flagged helper\'s next call carries its askllm note, and only that',
     len(cx) == 1 and cx[0][0] == 'PostToolUse' and (cx[0][1] or '').startswith('laserbrain (askllm):')
     and REMINDER not in (cx[0][1] or '') and clean([r1]), r1.stdout[:300])
r2 = b.run(prompt('what next'), extra=note_env)
cx = contexts(r2)
txt = cx[0][1] if len(cx) == 1 else ''
show('...the parent gets its note on the next prompt, with the turn line, labelled UserPromptSubmit',
     len(cx) == 1 and cx[0][0] == 'UserPromptSubmit' and txt.startswith(TURN_LINE)
     and 'helper review:css in audit-run may be off its task' in txt and GATE_LINE not in txt
     and clean([r2]), r2.stdout[:400])
r3 = b.run(bash(2), extra=note_env)
show('...once: the next main call prints nothing', r3.stdout == '' and clean([r3]), r3.stdout[:200])

# 8. check rows: policy, no tokens
b = Box()
b.run(check(5, i=0))
rows = b.session().get('checks') or []
show('8  a check row in the session file carries policy ' + POLICY,
     len(rows) == 1 and rows[0].get('policy') == POLICY, rows)
show('...and no token count', len(rows) == 1 and 'tokens' not in rows[0], rows)
b.run(check(4, agent='helper-2', i=1))
rows = b.session().get('checks') or []
show('...a helper\'s check row too', len(rows) == 2 and rows[1].get('policy') == POLICY
     and 'tokens' not in rows[1], rows[-1:])

# 9. LASERBRAIN_STUDY=1: the old text exactly where it used to go out
print('\n  LASERBRAIN_STUDY=1 restores the old output')
b = Box()
rs = [b.run(bash(i), extra=STUDY) for i in range(1, C.NUDGE_AFTER + 1)]
show('9  the step reminder returns at NUDGE_AFTER steps',
     all(r.stdout == '' for r in rs[:-1]) and REMINDER in rs[-1].stdout, rs[-1].stdout[:200])
r = b.run(prompt('please refactor the parser'), extra=STUDY)
show('...a prompt gets the gate line again, not the turn line',
     GATE_LINE in r.stdout and TURN_LINE not in r.stdout and b.flag.exists(), r.stdout[:200])
b = Box()
rs = [b.run(check(3, i=0), extra=STUDY), b.run(bash(1), extra=STUDY), b.run(check(3, i=2), extra=STUDY)]
show('...the honesty note returns on the second equal-distance check',
     HONESTY not in rs[0].stdout and HONESTY in rs[2].stdout, rs[2].stdout[:200])
rows = b.session().get('checks') or []
show('...check rows count tokens again and carry no policy',
     len(rows) == 2 and all(isinstance(x.get('tokens'), int) for x in rows)
     and not any('policy' in x for x in rows), rows)
b = Box()
r = b.run(prompt('<task-notification>job done</task-notification>'), extra=STUDY)
show('...and a <task-notification> prompt marks the turn as it did before',
     b.flag.exists() and GATE_LINE in r.stdout, r.stdout[:200])
for v in ('on', 'true', 'yes'):
    b = Box()
    r = b.run(prompt('please refactor the parser'), extra={'LASERBRAIN_STUDY': v})
    show(f'...LASERBRAIN_STUDY={v} is the same switch', GATE_LINE in r.stdout, r.stdout[:120])

# 10. the embedded fallback
print('\n  the embedded fallback (laserbrain.runtime cannot be imported)')
b = Box()
rs = [b.run(bash(i), fallback=True) for i in range(1, C.NUDGE_AFTER + 1)]
show('10 quiet: no reminder at NUDGE_AFTER steps', all(r.stdout == '' for r in rs) and clean(rs),
     rs[-1].stdout[:200])
show('...the steps are recorded', int(b.session().get('steps') or 0) == C.NUDGE_AFTER, b.session().get('steps'))
r = b.run(prompt('<task-notification>job done</task-notification>'), fallback=True)
show('...a <task-notification> prompt writes no flag', not b.flag.exists() and r.stdout == '', r.stdout[:120])
r = b.run(prompt('please refactor the parser'), fallback=True)
show('...a real prompt does', b.flag.exists() and clean([r]), r.stderr[-200:])
show('...and gets the turn line once, as on the runtime path',
     contexts(r) == [('UserPromptSubmit', TURN_LINE)], r.stdout[:300])
# The runtime path raising on a session file it cannot read (wrong-typed fields) must not cost
# the turn line either: exactly one, whichever path says it.
for shape in ({'checks': 'x', 'events': 5, 'goal': [], 'segments': 7}, ['not', 'a', 'dict']):
    b = Box()
    (b.state / 'quiet-s1.json').write_text(json.dumps(shape))
    r = b.run(prompt('please refactor the parser'))
    show(f'...a broken session file ({type(shape).__name__}) still gets exactly one turn line',
         contexts(r) == [('UserPromptSubmit', TURN_LINE)] and r.returncode == 0, r.stdout[:300])
b = Box()
rs = [b.run(bash(i), extra=STUDY, fallback=True) for i in range(1, C.NUDGE_AFTER + 1)]
show('...LASERBRAIN_STUDY=1: the fallback reminder returns', REMINDER in rs[-1].stdout, rs[-1].stdout[:200])

# 11. only nudge mode is quiet
print('\n  only nudge mode is quiet')
probe = ('import importlib.util, sys\n'
         's = importlib.util.spec_from_file_location("c", sys.argv[1]); c = importlib.util.module_from_spec(s)\n'
         's.loader.exec_module(c); print(c._quiet())\n')
want = {('', ''): 'True', ('nudge', ''): 'True', ('', '1'): 'False', ('nudge', 'yes'): 'False',
        ('', 'no'): 'True', ('hard', ''): 'False', ('watch', ''): 'False', ('signal', ''): 'False',
        ('bogus', ''): 'False'}
got = {}
b = Box()
for (mode, study), w in want.items():
    extra = {}
    if mode:
        extra['LASERBRAIN_GATE_MODE'] = mode
    if study:
        extra['LASERBRAIN_STUDY'] = study
    r = subprocess.run([PY, '-P', '-c', probe, str(HOOK)], capture_output=True, text=True,
                       env=b.env(extra), timeout=60)
    got[(mode, study)] = r.stdout.strip()
show('11 _quiet(): nudge (or unset) without LASERBRAIN_STUDY only; hard, watch, signal and unknown never',
     got == want, {f'{k[0] or "unset"}/{k[1] or "-"}': v for k, v in got.items() if want[k] != v})
b = Box()
r = b.run(prompt('please refactor the parser'), extra={'LASERBRAIN_GATE_MODE': 'hard'})
show('...hard mode keeps the old prompt text', GATE_LINE in r.stdout and TURN_LINE not in r.stdout,
     r.stdout[:200])

print('\n  PASS' if ok else '\n  FAIL — see above.')
raise SystemExit(0 if ok else 1)
