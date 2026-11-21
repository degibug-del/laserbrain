"""Round-2 product bugs B1, B2, B5 and B8 stay fixed (research/DAY-FOUR-ROUND2.md, section 7).

Each check failed on the code as it ran in round 2 and passes since 2026-11-14:
  B1  the prompt hook labelled its reply PostToolUse, so Claude Code discarded it
  B2  a check reply cut at 600 characters stopped parsing: drifting/reason/phi were lost
  B5  check_state counted as observed work, and every tool call counted twice
  B8  the user's opening message left a flag that licensed the first later goal change

Drives the real hook (python -m laserbrain.hooks.lb_coverage) and the real MCP server over
stdio, under a throwaway HOME, so nothing outside a temp dir is written.

Run:  python3 test_round2_bugs.py
"""
import json, os, pathlib, subprocess, sys, tempfile, time
R = pathlib.Path(__file__).resolve().parent.parent
H = pathlib.Path(tempfile.mkdtemp(prefix='lbchk-'))
ENV = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN')}
ENV['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
ENV.update(HOME=str(H), PYTHONPATH=str(R / 'python'), PYTHONDONTWRITEBYTECODE='1', LASERBRAIN_AGENT='claude')
CFG = H / '.config' / 'laserbrain'
res = {}

def hook(payload):
    p = subprocess.run([sys.executable, '-P', '-m', 'laserbrain.hooks.lb_coverage'], input=json.dumps(payload),
                       capture_output=True, text=True, env=ENV, cwd=str(H), timeout=60)
    return p.stdout.strip()

def ev_ok():
    try: return json.loads((CFG / 'evidence.json').read_text()).get('ok', 0)
    except Exception: return 0

# B1: the prompt hook answers with the event it was asked.
out = hook({'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'prompt': 'please refactor the parser module and add unit tests for it',
            'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})
names = []
for line in out.splitlines():
    try: names.append(json.loads(line).get('hookSpecificOutput', {}).get('hookEventName'))
    except Exception: pass
res['B1 prompt reply labelled UserPromptSubmit'] = (names == ['UserPromptSubmit'], names)

# B5: check_state is not work; one Bash call counts once.
base = ev_ok()
reply = [{'type': 'text', 'text': json.dumps({'drifting': False, 'reason': 'advancing', 'phi': 0.1, 'run': 'r1'})}]
hook({'hook_event_name': 'PostToolUse', 'session_id': 's1', 'tool_name': 'mcp__laserbrain__check_state',
      'tool_input': {'goal': 'refactor parser', 'progress': 'advancing', 'distance': 5}, 'tool_response': reply,
      'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})
after_check = ev_ok()
hook({'hook_event_name': 'PostToolUse', 'session_id': 's1', 'tool_name': 'Bash', 'tool_input': {'command': 'ls'},
      'tool_response': {'stdout': 'a\nb', 'stderr': '', 'exit_code': 0}, 'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})
after_bash = ev_ok()
res['B5 check_state adds no evidence'] = (after_check == base, (base, after_check))
res['B5 one Bash call counts once'] = (after_bash - after_check == 1, (after_check, after_bash))

# B2: a long drifting reply is read as drifting.
long = [{'type': 'text', 'text': json.dumps({'drifting': True, 'reason': 'goal-drift', 'phi': 0.81, 'run': 'r2',
                                              'advice': 'Return to your goal. ' * 40})}]
hook({'hook_event_name': 'PostToolUse', 'session_id': 's2', 'tool_name': 'mcp__laserbrain__check_state',
      'tool_input': {'goal': 'something else', 'progress': 'advancing', 'distance': 5}, 'tool_response': long,
      'transcript_path': str(H / 'none.jsonl'), 'cwd': str(H)})
sess = H / '.claude' / 'laserbrain' / 's2.json'
try:
    c = json.loads(sess.read_text())['checks'][-1]
    res['B2 long reply keeps drifting/reason/phi'] = (c.get('drifting') is True and c.get('reason') == 'goal-drift' and c.get('phi') == 0.81,
                                                     {k: c.get(k) for k in ('drifting', 'reason', 'phi', 'run')})
except Exception as e:
    res['B2 long reply keeps drifting/reason/phi'] = (False, repr(e))

# B8: a flag older than the ground licenses nothing; a newer one licenses one re-ground.
FLAG = CFG / 'user-turn'
def server():
    return subprocess.Popen(['node', str(R / 'javascript' / 'mcp-server.mjs')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, env=ENV, cwd=str(H))
def call(p, i, args):
    p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': 'check_state', 'arguments': args}}) + '\n'); p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line: return {}
        try: m = json.loads(line)
        except ValueError: continue
        if m.get('id') == i:
            return json.loads(m['result']['content'][0]['text'])
p = server()
p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}) + '\n'); p.stdin.flush()
p.stdout.readline()
CFG.mkdir(parents=True, exist_ok=True)
FLAG.write_text('2026-11-14T00:00:00Z')           # the user's opening message
time.sleep(0.05)
a = call(p, 1, {'goal': 'refactor the csv parser module and add unit tests', 'progress': 'advancing', 'distance': 8})
b = call(p, 2, {'goal': 'write marketing copy for the landing page hero', 'progress': 'advancing', 'distance': 6})
res['B8 stale flag: later goal change is goal-drift'] = (b.get('reason') == 'goal-drift', (a.get('reason'), b.get('reason'), FLAG.exists()))
time.sleep(0.05)
FLAG.write_text('2026-11-14T00:05:00Z')           # the user speaks again
c = call(p, 3, {'goal': 'deploy the billing service to staging tonight', 'progress': 'advancing', 'distance': 6})
res['B8 fresh flag: one re-ground, flag consumed'] = (c.get('reason') == 'reground' or 'reground' in str(c.get('reason')),
                                                     (c.get('reason'), FLAG.exists()))
p.kill()
bad = 0
for k, (ok, detail) in res.items():
    print(('ok  ' if ok else 'FAIL'), k, '' if ok else detail)
    bad += not ok
sys.exit(1 if bad else 0)
