"""Round-2 product bugs B3 and B4 stay fixed (research/DAY-FOUR-ROUND2.md, section 7).

  B3  Claude Code skips PostToolUse for a failed call and nothing was registered on
      PostToolUseFailure, so 40 of 887 lbq calls in round 2 never reached lb_coverage. The
      event is now wired, and the instrument's own refusals, the user's Esc and failed
      laserbrain bookkeeping stay out of catches and evidence when it arrives.
  B4  every one of round 2's 28 "build catches" came from a command that exited 0 and
      merely PRINTED something like "fatal:" or "AssertionError". Text now fails a call only
      when the decoded output ends in a red test or build verdict, which a pipe hides from
      every host (108 lbq calls exited 0 with a red unittest verdict).

Drives the real hook (python -P -m laserbrain.hooks.lb_coverage) under a throwaway HOME,
with LASERBRAIN_* stripped, so nothing outside a temp dir is written. Two checks also run
the hook's embedded fallback, by shadowing laserbrain.runtime with a stub that cannot be
imported.

Run:  python3 test_round2_b3b4.py
"""
import json, os, pathlib, subprocess, sys, tempfile
R = pathlib.Path(__file__).resolve().parent.parent
HOOK = R / 'python' / 'laserbrain' / 'hooks' / 'lb_coverage.py'
H = pathlib.Path(tempfile.mkdtemp(prefix='lbb34-'))
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN')}
ENV.update(HOME=str(H), PYTHONPATH=str(R / 'python'), PYTHONDONTWRITEBYTECODE='1', LASERBRAIN_AGENT='claude')
# The fallback runs only when `from laserbrain.runtime import ...` fails. A stub package
# earlier on the path than any installed copy makes it fail, without touching the code.
STUB = H / 'stub'
(STUB / 'laserbrain').mkdir(parents=True)
(STUB / 'laserbrain' / '__init__.py').write_text('')
(STUB / 'laserbrain' / 'runtime.py').write_text("raise ImportError('stub: force the embedded fallback')\n")
FALLBACK_ENV = dict(ENV, PYTHONPATH=str(STUB))
CFG = H / '.config' / 'laserbrain'
STATE = H / '.claude' / 'laserbrain'
res = {}
rcs = []

GATE = ('laserbrain gate: 9 steps since your last check_state (coverage 10% over 40 steps, floor 20%).\n'
        'THIS CALL DID NOT RUN. Nothing was written, executed or sent.')
DRIFT = 'laserbrain drift gate: goal-drift (phi 0.81).\nTHIS CALL DID NOT RUN. Nothing was written, executed or sent.'
SAFETY = 'laserbrain safety: blocked rm -rf.\nTHIS CALL DID NOT RUN.\nIf this delete is intended, have DIEGO run it.'
RED = ('test_a (t.T.test_a) ... FAIL\n\n' + '=' * 70 + '\nFAIL: test_a (t.T.test_a)\n' + '-' * 70 + '\n'
       'Traceback (most recent call last):\nAssertionError: 1 != 2\n\n' + '-' * 70 + '\n'
       'Ran 3 tests in 0.010s\n\nFAILED (failures=1)\n')
RED_THEN_GREEN = RED + '\n# fixed the parser, ran again\n...\n' + '-' * 70 + '\nRan 3 tests in 0.010s\n\nOK\n'


def hook(p, fallback=False):
    p = dict({'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)}, **p)
    cmd = [sys.executable, '-P', str(HOOK)] if fallback else [sys.executable, '-P', '-m', 'laserbrain.hooks.lb_coverage']
    r = subprocess.run(cmd, input=json.dumps(p), capture_output=True, text=True,
                       env=FALLBACK_ENV if fallback else ENV, cwd=str(H), timeout=60)
    rcs.append(r.returncode)
    return r.stdout.strip()


def evidence():
    try:
        d = json.loads((CFG / 'evidence.json').read_text())
    except Exception:
        d = {}
    return int(d.get('ok', 0)), int(d.get('fail', 0))


def session(sid):
    try:
        return json.loads((STATE / f'{sid}.json').read_text())
    except Exception:
        return {}


def catches(sid):
    return session(sid).get('catches') or []


def agents(sid):
    try:
        return json.loads((STATE / f'{sid}.agents.json').read_text())
    except Exception:
        return {}


def labels(out):
    got = []
    for line in out.splitlines():
        try:
            got.append(json.loads(line).get('hookSpecificOutput', {}).get('hookEventName'))
        except Exception:
            pass
    return got


def bash(sid, cmd, stdout='', stderr='', event='PostToolUse', fallback=False, **extra):
    p = {'hook_event_name': event, 'session_id': sid, 'tool_name': 'Bash', 'tool_input': {'command': cmd},
         'tool_use_id': f'toolu_{abs(hash((sid, cmd))) % 10**10}'}
    if event == 'PostToolUse':
        p['tool_response'] = {'stdout': stdout, 'stderr': stderr, 'interrupted': False, 'isImage': False,
                              'noOutputExpected': False}
    p.update(extra)
    return hook(p, fallback=fallback)


def failed(sid, cmd, error, fallback=False, **extra):
    """Claude Code's PostToolUseFailure: the failure text in `error`, no tool_response."""
    kw = dict(error_type='tool_error', is_interrupt=False, is_timeout=False)
    kw.update(extra)
    return bash(sid, cmd, event='PostToolUseFailure', fallback=fallback, error=error, **kw)


def delta(before):
    o, f = evidence()
    return o - before[0], f - before[1]


hook({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt': 'fix the csv parser and make its tests pass'})

# ── B3 ────────────────────────────────────────────────────────────────────────────────
# 1. A failed call is a catch (via 'event') and an evidence failure.
e0 = evidence()
failed('s', 'python3 -m unittest', 'Exit code 1\nFAILED (failures=1)')
c = catches('s')
res['B3-1 failure event -> 1 catch, via event'] = (len(c) == 1 and c[-1].get('via') == 'event'
                                                  and c[-1].get('clean') is True, c)
res['B3-1 failure event -> evidence fail +1, ok +0'] = (delta(e0) == (0, 1), delta(e0))

# 2. A reply to a failure event is labelled PostToolUseFailure, or Claude Code drops it. On
#    the primary path and on the embedded fallback.
for name, fb in (('primary', False), ('fallback', True)):
    outs = [failed(f'n-{name}', f'make target{i}', f'Exit code 2\nmake: *** [target{i}] Error 2', fallback=fb)
            for i in range(1, 9)]
    replies = [(i + 1, labels(o)) for i, o in enumerate(outs) if o]
    res[f'B3-2 {name}: 8 failures -> one reply, at step 8, labelled PostToolUseFailure'] = (
        replies == [(8, ['PostToolUseFailure'])], replies)

# 3. The coverage gate's refusal, carried only in `error`: no catch, no evidence.
n, e0 = len(catches('s')), evidence()
failed('s', 'npm run build', GATE)
res['B3-3 gate refusal in error -> no catch'] = (len(catches('s')) == n, catches('s')[n:])
res['B3-3 gate refusal in error -> no evidence'] = (delta(e0) == (0, 0), delta(e0))

# 4. The enforced drift gate's refusal is the instrument too.
n, e0 = len(catches('s')), evidence()
failed('s', 'npm run build --again', DRIFT)
res['B3-4 drift-gate refusal in error -> no catch, no evidence'] = (
    len(catches('s')) == n and delta(e0) == (0, 0), (catches('s')[n:], delta(e0)))

# 5. The user pressing Esc: the step counts; no catch, no evidence. On the primary path and
#    on the embedded fallback, whose catch has its own `not _is_interrupt(ev)`.
for name, fb in (('primary', False), ('fallback', True)):
    sid = f'i-{name}'
    hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': 'fix the csv parser'}, fallback=fb)
    bash(sid, 'ls', stdout='a\nb', fallback=fb)
    n, e0, st0 = len(catches(sid)), evidence(), int(session(sid).get('steps') or 0)
    failed(sid, 'sleep 100', 'Interrupted by user', fallback=fb, is_interrupt=True)
    st1 = int(session(sid).get('steps') or 0)
    res[f'B3-5 {name}: interrupt -> step counted, no catch, no evidence'] = (
        st0 >= 1 and len(catches(sid)) == n and delta(e0) == (0, 0) and st1 == st0 + 1,
        (catches(sid)[n:], delta(e0), st0, st1))

# 6. lb_safety's block, if it arrives, stays a catch, tagged so a scorer can split it out.
n = len(catches('s'))
failed('s', 'rm -rf build', SAFETY)
c = catches('s')
res['B3-6 safety block in error -> 1 catch, via denied'] = (len(c) == n + 1 and c[-1].get('via') == 'denied', c[n:])

# 7. Failed laserbrain bookkeeping is ignored, as it was before failures arrived: no check
#    row, no reset or archived segment, no step, no catch, no per-agent count, no evidence.
for name, fb in (('primary', False), ('fallback', True)):
    sid = f'k-{name}'
    hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': 'tidy the build scripts'}, fallback=fb)
    bash(sid, 'ls', stdout='a\nb', fallback=fb)
    s0, a0, e0 = session(sid), agents(sid), evidence()
    for tool, args in (('mcp__laserbrain__check_state', {'goal': 'tidy the build scripts', 'progress': 'advancing', 'distance': 5}),
                       ('mcp__laserbrain__reset_task', {}),
                       ('mcp__laserbrain__get_history', {})):
        hook({'hook_event_name': 'PostToolUseFailure', 'session_id': sid, 'tool_name': tool, 'tool_input': args,
              'tool_use_id': f'toolu_{tool[-6:]}', 'error': 'MCP error -32000: Connection closed',
              'error_type': 'tool_error', 'is_interrupt': False, 'is_timeout': False}, fallback=fb)
    s1, a1 = session(sid), agents(sid)
    same = (s1.get('steps') == s0.get('steps') == 1 and not s1.get('checks') and not s1.get('segments')
            and not s1.get('catches') and s1.get('goal') == s0.get('goal') and delta(e0) == (0, 0)
            and a1 == a0)
    res[f'B3-7 {name}: failed check_state/reset_task/get_history -> ignored'] = (
        same, {'steps': (s0.get('steps'), s1.get('steps')), 'checks': s1.get('checks'),
               'segments': len(s1.get('segments') or []), 'catches': s1.get('catches'),
               'goal': s1.get('goal'), 'evidence': delta(e0), 'agents': (a0, a1)})

# 8. Grok's spelling: a failure event with an exit code is a catch; a gate refusal in
#    `error` is not.
hook({'hookEventName': 'post_tool_use_failure', 'sessionId': 'g', 'toolName': 'run_terminal_command',
      'toolInput': {'command': 'make'}, 'toolResult': {'exit_code': 2, 'output': 'make: *** [all] Error 2'}})
hook({'hookEventName': 'post_tool_use_failure', 'sessionId': 'g', 'toolName': 'run_terminal_command',
      'toolInput': {'command': 'make again'}, 'error': GATE})
cg = catches('g')
res['B3-8 Grok failure event -> 1 catch; gate text in error -> none'] = (
    len(cg) == 1 and cg[0].get('via') == 'exit', cg)

# ── B4 ────────────────────────────────────────────────────────────────────────────────
# 9. Exit 0 with failure-sounding text is not a catch, and it is an `ok`.
n, e0 = len(catches('s')), evidence()
bash('s', 'git status --short | head -5; ls', stdout='fatal: not a git repository (or any of the parent directories): .git\na\nb')
bash('s', 'w export --format xml; echo rc=$?', stderr="waterlog export: error: argument --format: invalid choice: 'xml'\nrc=2")
bash('s', 'for f in pkg/*.py; do cat $f; done', stdout='def main():\n    if bad:\n        raise AssertionError(command)\n')
bash('s', 'ls nothing 2>&1; true', stdout='ls: nothing: No such file or directory')
bash('s', 'python3 -m unittest 2>&1 | tail -40', stdout=RED_THEN_GREEN)
res['B4-9 failure-sounding text on exit 0 -> no catch'] = (len(catches('s')) == n, catches('s')[n:])
res['B4-9 ... and evidence ok +5, fail +0'] = (delta(e0) == (5, 0), delta(e0))

# 10. A red suite behind a pipe is a catch, with its verdict past the old 4000-char cut.
n, e0 = len(catches('s')), evidence()
piped = ('.' * 70 + '\n') * 80 + RED
assert piped.index('FAILED (failures=1)') > 4000
bash('s', 'python3 -m unittest 2>&1 | tail -15', stdout=piped)
c = catches('s')
res['B4-10 piped red verdict -> 1 catch, via verdict'] = (len(c) == n + 1 and c[-1].get('via') == 'verdict', c[n:])
res['B4-10 ... and evidence fail +1'] = (delta(e0) == (0, 1), delta(e0))

# 11. File-content tools are never text-scanned: reading or writing a red log is not a failure.
n = len(catches('s'))
hook({'hook_event_name': 'PostToolUse', 'session_id': 's', 'tool_name': 'Read', 'tool_input': {'file_path': '/x/log.txt'},
      'tool_response': {'type': 'text', 'file': {'filePath': '/x/log.txt', 'content': RED}}})
hook({'hook_event_name': 'PostToolUse', 'session_id': 's', 'tool_name': 'Write',
      'tool_input': {'file_path': '/x/f.txt', 'content': RED},
      'tool_response': {'type': 'create', 'filePath': '/x/f.txt', 'content': RED}})
res['B4-11 Read/Write of red text -> no catch'] = (len(catches('s')) == n, catches('s')[n:])
# The two above document the shapes but cannot fail: a Read or Write result carries no
# stdout, content list or output string, so it decodes to '' with or without _NO_TEXT_SCAN.
# A subagent's report and a Grok read_file do decode to text, and only _NO_TEXT_SCAN keeps
# a quoted red run in them from failing the call.
n, ng = len(catches('s')), len(catches('g'))
hook({'hook_event_name': 'PostToolUse', 'session_id': 's', 'tool_name': 'Agent', 'tool_input': {'prompt': 'run the suite'},
      'tool_response': {'status': 'completed', 'content': [{'type': 'text', 'text': 'The suite went red:\n' + RED}]}})
hook({'hook_event_name': 'PostToolUse', 'session_id': 's', 'tool_name': 'Task', 'tool_input': {'prompt': 'run the suite'},
      'tool_response': {'content': [{'type': 'text', 'text': RED}]}})
hook({'hookEventName': 'post_tool_use', 'sessionId': 'g', 'toolName': 'read_file',
      'toolInput': {'path': '/x/log.txt'}, 'toolResult': {'output': RED}})
res['B4-11 Agent/Task report and Grok read_file of red text -> no catch'] = (
    len(catches('s')) == n and len(catches('g')) == ng, (catches('s')[n:], catches('g')[ng:]))

# 12. Grok's exit-0 git noise is not a catch either.
n = len(catches('g'))
hook({'hookEventName': 'post_tool_use', 'sessionId': 'g', 'toolName': 'run_terminal_command',
      'toolInput': {'command': 'git log'}, 'toolResult': {'output': 'fatal: not a git repository'}})
res['B4-12 Grok exit-0 git fatal -> no catch'] = (len(catches('g')) == n, catches('g')[n:])

# ── B3/B4 review (2026-11-14): a refusal is known by its HEAD ─────────────────────────
# Text that QUOTES a deny line is not a refusal. laserbrain's own source, logs and suites
# quote all of them, and a whole-text search made successful reads of them lose their
# evidence, a successful grep become a 'denied' catch, and a red suite lose its catch.
QUOTE_GATE = ("lb_gate.py:1540:        f'laserbrain gate: {why} '\n"
              "lb_gate.py:1541:        f'(coverage {cov:.0%} over {steps} steps, floor {floor:.0%}).\\n'\n"
              "lb_gate.py:1544:        f'THIS CALL DID NOT RUN. Nothing was written, executed or sent'\n")
SRC = ('"""lb_gate.py"""\n' + 'x = 1\n' * 40 + 'reason = (\n    f"' + GATE.replace('\n', '\\n') + '")\n'
       + "lines = [f'laserbrain drift gate: {detail}.']\n")
GATE_LOG = ('test_proportional_gate\n'
            '  ok   hard mode refuses: laserbrain gate: 9 steps since your last check_state '
            '(coverage 0% over 9 steps, floor 50%)\n'
            '  ok   the deny text says: THIS CALL DID NOT RUN\n')

# R1. Successful calls whose output quotes gate text are work: evidence ok, no catch. On both
#     paths, since the evidence writer and _is_self_refusal serve both.
for name, fb in (('primary', False), ('fallback', True)):
    sid = f'q-{name}'
    hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': 'read the gate source'}, fallback=fb)
    n, e0 = len(catches(sid)), evidence()
    hook({'hook_event_name': 'PostToolUse', 'session_id': sid, 'tool_name': 'Edit',
          'tool_input': {'file_path': '/x/runtime.py', 'old_string': 'x = 1', 'new_string': 'x = 2'},
          'tool_response': {'filePath': '/x/runtime.py', 'oldString': 'x = 1', 'newString': 'x = 2',
                            'originalFile': SRC, 'structuredPatch': [], 'userModified': False,
                            'replaceAll': False}}, fallback=fb)
    hook({'hook_event_name': 'PostToolUse', 'session_id': sid, 'tool_name': 'Read',
          'tool_input': {'file_path': '/x/lb_gate.py'},
          'tool_response': {'type': 'text', 'file': {'filePath': '/x/lb_gate.py', 'content': SRC}}}, fallback=fb)
    bash(sid, 'grep -n "laserbrain gate:" lb_gate.py', stdout=QUOTE_GATE, fallback=fb)
    bash(sid, 'grep -n "THIS CALL DID NOT RUN" lb_safety.py', stdout="181:                f'THIS CALL DID NOT RUN.\\n'",
         fallback=fb)
    bash(sid, 'cat lb_gate.py', stdout=SRC, fallback=fb)
    bash(sid, 'python3 test_proportional_gate.py 2>&1 | tail -3', stdout=GATE_LOG + 'PASS\n', fallback=fb)
    # Running the gate by hand and carrying on: its stderr BEGINS with the deny text, but the
    # call succeeded, and a successful call cannot be the gate refusing it.
    bash(sid, 'python3 -m laserbrain.hooks.lb_gate < denied.json; true',
         stdout='{"hookSpecificOutput": {"permissionDecision": "deny"}}', stderr=GATE, fallback=fb)
    res[f'R1 {name}: successful calls quoting deny text -> no catch'] = (len(catches(sid)) == n, catches(sid)[n:])
    res[f'R1 {name}: ... and evidence ok +7, fail +0'] = (delta(e0) == (7, 0), delta(e0))

# R2. A command that really failed and quotes gate text is a catch and an evidence failure.
#     Its `error` begins "Exit code N", which no refusal does.
for name, fb in (('primary', False), ('fallback', True)):
    sid = f'r-{name}'
    hook({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': 'make the gate suite pass'}, fallback=fb)
    n, e0 = len(catches(sid)), evidence()
    failed(sid, 'python3 test_proportional_gate.py', 'Exit code 1\n' + GATE_LOG + 'FAIL nudge mode must not block\n',
           fallback=fb)
    failed(sid, 'python3 -m unittest test_drift_gate', 'Exit code 1\n  deny text: ' + DRIFT + '\n' + RED, fallback=fb)
    c = catches(sid)
    res[f'R2 {name}: red suites quoting gate/drift-gate text -> 2 catches'] = (len(c) == n + 2, c[n:])
    res[f'R2 {name}: ... and evidence fail +2'] = (delta(e0) == (0, 2), delta(e0))
c = catches('r-primary')
res['R2 ... via event, not denied'] = ([x.get('via') for x in c] == ['event', 'event'], c)

# R3. An exit-0 piped red suite whose output quotes the gate is still a verdict catch.
n, e0 = len(catches('s')), evidence()
bash('s', 'python3 test_gate_modes.py 2>&1 | tail -20', stdout=GATE_LOG + RED)
c = catches('s')
res['R3 piped red suite quoting the gate -> 1 catch, via verdict, evidence fail +1'] = (
    len(c) == n + 1 and c[-1].get('via') == 'verdict' and delta(e0) == (0, 1), (c[n:], delta(e0)))

# R4. A real failure that prints THIS CALL DID NOT RUN mid-output is via 'event', not
#     'denied', so a scorer that splits denials out keeps it.
n = len(catches('s'))
failed('s', 'wc -c hook_samples.json', 'Exit code 1\n    1742 hook_samples.json\n  ' + SAFETY)
c = catches('s')
res['R4 exit-1 output quoting a denial -> via event'] = (len(c) == n + 1 and c[-1].get('via') == 'event', c[n:])

# R5. Claude Code's wrapped denial ("PreToolUse:Bash hook error: [cmd]: ...") is read the same.
n, e0 = len(catches('s')), evidence()
failed('s', 'npm run build --wrapped', 'PreToolUse:Bash hook error: [python3 -m laserbrain.hooks.lb_gate]: ' + GATE)
res['R5 wrapped gate refusal -> no catch, no evidence'] = (
    len(catches('s')) == n and delta(e0) == (0, 0), (catches('s')[n:], delta(e0)))
n2, e2 = len(catches('s')), evidence()
failed('s', 'npm run build --plugin-wrapped', 'PreToolUse:Bash hook error: [export X=1; if [ -n "$LB_PY" ] && "$LB_PY" -P -m laserbrain.hooks.lb_gate]: ' + GATE)
res['R5 gate refusal wrapped in a command holding ] -> no catch, no evidence'] = (
    len(catches('s')) == n2 and delta(e2) == (0, 0), (catches('s')[n2:], delta(e2)))
n = len(catches('s'))
failed('s', 'rm -rf build --wrapped', 'PreToolUse:Bash hook error: ' + SAFETY)
c = catches('s')
res['R5 wrapped safety block -> 1 catch, via denied'] = (len(c) == n + 1 and c[-1].get('via') == 'denied', c[n:])

# R6. The fallback's copy of the refusal test is the runtime's, field for field.
parity = r'''
import json, sys
import laserbrain.runtime as rt
import laserbrain.hooks.lb_coverage as cov
GATE, DRIFT, SAFETY, QUOTE, LOG, RED = json.loads(sys.stdin.read())
evs = [
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'error': GATE},
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'error': 'PreToolUse:Bash hook error: [x]: ' + GATE},
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'error': '  ' + DRIFT},
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'error': SAFETY},
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'error': 'Exit code 1\n' + LOG + GATE},
    {'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash', 'errorMessage': GATE},
    {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'tool_response': {'stdout': QUOTE, 'stderr': GATE}},
    {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'tool_response': {'stdout': LOG + RED, 'stderr': ''}},
    {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'tool_response': {'isError': True, 'content': GATE}},
    {'hook_event_name': 'PostToolUse', 'tool_name': 'mcp__x__y', 'tool_response': [{'type': 'text', 'text': GATE}]},
    {'hook_event_name': 'PostToolUse', 'tool_name': 'mcp__x__y', 'tool_response': {'content': [{'type': 'text', 'text': DRIFT}]}},
    {'name': 'Bash', 'arguments': {}, 'output': {'error': GATE}},
    {'name': 'Bash', 'arguments': {}, 'output': GATE},
    {'sessionId': 'g', 'toolName': 'run_terminal_command', 'toolResult': {'output': LOG}},
    {'hookEventName': 'post_tool_use_failure', 'toolName': 'x', 'error': 'laserbrain gate: FAILED OPEN'},
    # A failed run whose output opens with lb_gate's non-blocking WARNING: a real failure,
    # because a warning is not a refusal (it has no THIS CALL DID NOT RUN).
    {'hookEventName': 'post_tool_use_failure', 'toolName': 'run_terminal_command',
     'toolResult': {'exit_code': 1, 'output': 'laserbrain gate: 9 steps since your last check_state '
                                              '(coverage 0%, floor 50%). Reads still pass.\nFAIL x'}},
]
out = {'pattern': cov._SELF_REFUSAL_HEAD_RE.pattern == rt._SELF_REFUSAL_HEAD_RE.pattern
                  and cov._SELF_REFUSAL_HEAD_RE.flags == rt._SELF_REFUSAL_HEAD_RE.flags,
       'texts': [cov._message_texts(e) == rt._message_texts(e, rt._tool_parts(e)[2]) for e in evs],
       'refused': [[cov._is_self_refusal(e), rt.self_refused(e)] for e in evs]}
print(json.dumps(out))
'''
r = subprocess.run([sys.executable, '-P', '-c', parity], input=json.dumps([GATE, DRIFT, SAFETY, QUOTE_GATE, GATE_LOG, RED]),
                   capture_output=True, text=True, env=ENV, cwd=str(H), timeout=60)
try:
    p = json.loads(r.stdout)
except Exception:
    p = {'error': r.stderr[-400:]}
want = [True, True, True, False, False, True, True, False, True, True, True, True, True, False, False, False]
res['R6 lb_coverage refusal regex is runtime\'s'] = (p.get('pattern') is True, p)
res['R6 ... same message fields on every shape'] = (p.get('texts') and all(p['texts']), p.get('texts'))
res['R6 ... same verdict on every shape, and the expected one'] = (
    [a for a, b in p.get('refused') or []] == want and all(a == b for a, b in p.get('refused') or []),
    p.get('refused'))

# R7. Latency. Two outputs that cost seconds before the review: 30,000 characters that an
#     overlapping jest pattern read in quadratic time (5 s per hook call), and 200,000
#     characters of quoted "laserbrain gate:" lines with no "coverage" (10.5 s). Base takes
#     0.06 s on both. The bound is generous so a loaded machine does not flake.
import time                                                        # noqa: E402
for label, out in (('jest-like 30k', 'Tests:' + ' ' * 30000 + 'x'),
                   ('gate-quote 200k', '\n'.join(f'log {i}: laserbrain gate: would refuse' for i in range(5000)))):
    t0 = time.time()
    bash('s', f'perf {label}', stdout=out)
    dt = time.time() - t0
    res[f'R7 one hook call on {label} output < 3 s'] = (dt < 3.0, f'{dt:.2f} s')
# The same, one scan at a time, where the quadratic forms took seconds and the linear ones
# take milliseconds; and the rewritten patterns still give the verdicts they gave.
timing = r'''
import json, time
import laserbrain.runtime as rt
gate_quotes = '\n'.join(f'log {i}: laserbrain gate: would refuse' for i in range(5000))
probes = {
    'jest 30k': lambda: rt.red_verdict('Tests:' + ' ' * 30000 + 'x'),
    'green after a blank run 30k': lambda: rt.red_verdict('FAILED (failures=1)\nRan 3 tests in 0.1s' + '\n' * 30000 + 'x'),
    'self_refused 200k': lambda: rt.self_refused({'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash',
                                                  'error': gate_quotes}),
    'red_verdict 200k': lambda: rt.red_verdict(gate_quotes),
}
out = {}
for k, f in probes.items():
    t = time.time(); f(); out[k] = time.time() - t
out['verdicts'] = [rt.red_verdict('Tests:       1 failed, 3 passed, 4 total'),
                   rt.red_verdict('Tests:       4 passed, 4 total'),
                   rt.red_verdict('FAILED (failures=1)\nRan 3 tests in 0.1s\n \n\nOK\n'),
                   rt.red_verdict('FAILED (failures=1)\nRan 3 tests in 0.1s\n\nOK\n'),
                   rt.red_verdict('Ran 3 tests in 0.1s\nOK\nFAILED (failures=1)\n')]
print(json.dumps(out))
'''
r = subprocess.run([sys.executable, '-P', '-c', timing], capture_output=True, text=True, env=ENV, cwd=str(H), timeout=300)
try:
    tm = json.loads(r.stdout)
except Exception:
    tm = {'error': r.stderr[-400:]}
for k in ('jest 30k', 'green after a blank run 30k', 'self_refused 200k', 'red_verdict 200k'):
    res[f'R7 {k} scan < 0.25 s'] = (isinstance(tm.get(k), float) and tm[k] < 0.25, tm.get(k, tm))
res['R7 rewritten jest/unittest patterns keep their verdicts'] = (
    tm.get('verdicts') == [True, False, False, False, True], tm.get('verdicts', tm))

# ── wiring ────────────────────────────────────────────────────────────────────────────
# 13. The installer carries the new event, and an install made before it gains just that.
live_shape = {
    'mcpServers': {'laserbrain': {'type': 'stdio', 'command': 'laserbrain', 'args': ['mcp']}},
    'hooks': {
        'PostToolUse': [{'matcher': '*', 'hooks': [{'type': 'command',
                         'command': f'LASERBRAIN_AGENT=claude {sys.executable} -P -m laserbrain.hooks.lb_coverage'}]}],
        'UserPromptSubmit': [{'hooks': [{'type': 'command',
                              'command': f'LASERBRAIN_AGENT=claude {sys.executable} -P -m laserbrain.hooks.lb_coverage'}]}],
        'PreToolUse': [{'matcher': '*', 'hooks': [
            {'type': 'command', 'command': f'LASERBRAIN_AGENT=claude {sys.executable} -P -m laserbrain.hooks.lb_gate'},
            {'type': 'command', 'command': f'LASERBRAIN_AGENT=claude {sys.executable} -P -m laserbrain.hooks.lb_safety'}]}],
    }}
settings = H / '.claude' / 'settings.json'
settings.parent.mkdir(parents=True, exist_ok=True)
settings.write_text(json.dumps(live_shape, indent=2))
before = settings.read_text()
code = ("import sys\nfrom laserbrain.install import HOOKS, main\n"
        "assert ('PostToolUseFailure', 'lb_coverage', '*') in HOOKS, HOOKS\n"
        "sys.exit(main(['--dry-run', '--server', 'python']))\n")
r = subprocess.run([sys.executable, '-P', '-c', code], capture_output=True, text=True, env=ENV, cwd=str(H), timeout=60)
would = [ln.split('would change:', 1)[1].strip() for ln in r.stdout.splitlines() if 'would change:' in ln]
items = [x.strip() for x in would[0].split(',')] if would else []
res['wiring-13 install HOOKS has PostToolUseFailure/lb_coverage/*'] = (r.returncode == 0, (r.returncode, r.stderr[-300:]))
res['wiring-13 dry run on the live shape adds PostToolUseFailure/lb_coverage only'] = (
    items == ['PostToolUseFailure/lb_coverage'], (items, r.stdout[-300:]))
res['wiring-13 dry run writes nothing'] = (settings.read_text() == before, 'settings.json changed')

# Every hook call failed open.
res['every hook call exited 0'] = (all(x == 0 for x in rcs), rcs)
# `via` is only ever one of the five documented values.
vias = {c.get('via') for sid in ('s', 'g', 'n-primary') for c in catches(sid)}
res['via is one of event/exit/flag/verdict/denied'] = (vias <= {'event', 'exit', 'flag', 'verdict', 'denied'}, vias)

bad = 0
for k, (ok, detail) in res.items():
    print(('ok  ' if ok else 'FAIL'), k, '' if ok else detail)
    bad += not ok
sys.exit(1 if bad else 0)
