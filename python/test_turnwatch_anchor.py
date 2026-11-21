"""turnwatch's first-tool arm (phase 2a: LASERBRAIN_TURNWATCH_TRIGGER=first_tool, quiet mode only).

The main session's FIRST TOOL CALL of any kind after a delivered user message starts turnwatch,
and research/eval/turn_anchor.py anchors the frozen turn_match_llm.build_row there, so a turn is
judged whether or not the agent makes a check_state. Pinned here, on synthetic transcripts only,
a mock reply, LASERBRAIN_TURNWATCH_DELAY=0 and no network:

  turn_anchor   its events are the frozen parse_records; a check_state that IS the first tool
                call gives the check arm's own event and row; any other first tool call gets a
                check event at its place, with the goal of a check_state within the first-words
                window after it (none after the window); a text-only turn gives no row; helper
                (sidechain) tool calls are not anchors; the bounded backwards reader builds the
                same row as parsing the whole file
  lb_coverage   (through fast.py, as the 2a wiring runs it) prompt -> Bash -> text gives ONE
                row, variant first-tool, anchored at the first tool call of a batch even when a
                later call ran the hook; check_state first gives the check arm's rendered prompt
                (same row_sha); a queued mid-turn message is judged at the next main tool call
                after it is delivered, and the marker stays while it is not; a text-only turn
                gives no row; a task notification gives no marker and no row; helper calls never
                trigger; the marker is cleared after a spawn and after 30 minutes; the check arm
                does not run for the main session in this mode; with the env unset, or outside
                quiet mode, no marker is written (and the turn line is WP1's)
  frozen        a changed turn_anchor.py, a block without the anchor pin and the check arm's own
                block are each 'skipped: frozen changed'; the real eval/turnwatch-anchor-frozen.json
                matches the current files and carries every pin of eval/turnwatch-frozen.json

usage: python3 test_turnwatch_anchor.py [dir holding the laserbrain package]"""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

PKG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
HOOKS = PKG / 'laserbrain' / 'hooks'
REPO = PKG.parent
EVAL = REPO / 'research' / 'eval'
PY = sys.executable

for k in [k for k in os.environ if k.startswith('LASERBRAIN_')]:
    os.environ.pop(k)

spec = importlib.util.spec_from_file_location('lb_turnwatch', str(HOOKS / 'lb_turnwatch.py'))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
sys.path.insert(0, str(EVAL))
import turn_match_llm as TM                              # noqa: E402
import turn_anchor as A                                  # noqa: E402

_sd = importlib.util.spec_from_file_location('turn_dev_eval_probe', str(EVAL / 'turn_dev_eval.py'))
DEV = importlib.util.module_from_spec(_sd)
_sd.loader.exec_module(DEV)
JUDGE_FILES = DEV.judge_files()

ok_all = True


def check(name, cond, detail=''):
    global ok_all
    ok_all &= bool(cond)
    print(f"  {'✓' if cond else '✗'} {name}" + (f'  — {detail}' if detail and not cond else ''))


REPLY = json.dumps({'asks': ['add the export button'], 'covered': ['add the export button'], 'missing': [],
                    'substituted': False, 'verdict': 'aligned', 'drift_score': 5,
                    'reason': 'Synthetic reply for the anchor tests.'})
CHECK = 'mcp__laserbrain__check_state'


def L(sid, **r):
    return json.dumps(dict(r, sessionId=sid)) + '\n'


def u_prompt(sid, ts, text):
    return L(sid, type='user', timestamp=ts, message={'role': 'user', 'content': text})


def a_text(sid, ts, text):
    return L(sid, type='assistant', timestamp=ts, message={'role': 'assistant', 'content': [{'type': 'text', 'text': text}]})


def a_tools(sid, ts, *blocks, sidechain=False):
    r = dict(type='assistant', timestamp=ts, message={'role': 'assistant', 'content': list(blocks)})
    if sidechain:
        r['isSidechain'] = True
    return L(sid, **r)


def tu(tid, name, inp):
    return {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}


def chk(tid, goal, doing='first step'):
    return tu(tid, CHECK, {'goal': goal, 'progress': 'advancing', 'distance': 6, 'doing': doing})


def tool_result(sid, ts, tid):
    return L(sid, type='user', timestamp=ts, toolUseResult={'ok': True},
             message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tid, 'content': 'ok'}]})


def queued(sid, ts, text):
    return L(sid, type='attachment', timestamp=ts,
             attachment={'type': 'queued_command', 'prompt': text, 'commandMode': 'prompt'})


def enqueue(sid, ts, text):
    return L(sid, type='queue-operation', operation='enqueue', timestamp=ts, content=text)


def write(p, parts):
    with open(p, 'a') as fh:
        for x in parts:
            fh.write(x)


def frozen_block(root, ed=EVAL, **over):
    """An anchor frozen block holding the CURRENT files' values (the mechanics are tested whatever
    the real block says; the real block is checked at the end)."""
    ed = pathlib.Path(ed)
    files = {n: hashlib.sha256((ed / n).read_bytes()).hexdigest() for n in list(JUDGE_FILES) + ['turn_anchor.py']}
    fz = {'model': TM.MODEL, 'prompt_hash': TM.prompt_hash(), 'thresholds': TM.THRESHOLDS,
          'first_words_window_s': TM.FIRST_WORDS_WINDOW_S, 'turn_match_llm_sha256': files['turn_match_llm.py'],
          'ask_match_llm_sha256': files['ask_match_llm.py'], 'eval_files_sha256': files, 'anchor': 'first_tool'}
    fz.update(over)
    p = pathlib.Path(root) / f'anchor-frozen-{len(list(pathlib.Path(root).glob("anchor-frozen-*")))}.json'
    p.write_text(json.dumps({'frozen': fz}))
    return p


# ── turn_anchor, in process ─────────────────────────────────────────────────────────
print('turn_anchor: the frozen row, anchored at the first tool call')
S0 = 'anchor-unit-0001'
U1, U2 = 'please add an export button to the report page', 'and make the button blue'
lines0 = [u_prompt(S0, '2026-11-20T09:00:00.000Z', 'earlier: set up the report page'),
          a_text(S0, '2026-11-20T09:00:10.000Z', 'Report page set up. Want an export button next?'),
          u_prompt(S0, '2026-11-20T09:01:00.000Z', U1),
          a_text(S0, '2026-11-20T09:01:05.000Z', 'Adding the export button now.'),
          a_tools(S0, '2026-11-20T09:01:06.000Z', tu('b1', 'Bash', {'command': 'ls src'}),
                  tu('r1', 'Read', {'file_path': '/src/report.js'})),
          tool_result(S0, '2026-11-20T09:01:07.000Z', 'b1'),
          a_tools(S0, '2026-11-20T09:01:08.000Z', tu('h1', 'Bash', {'command': 'helper'}), sidechain=True),
          a_tools(S0, '2026-11-20T09:01:30.000Z', chk('c1', 'add the export button')),
          a_text(S0, '2026-11-20T09:01:40.000Z', 'Button added.'),
          u_prompt(S0, '2026-11-20T09:02:00.000Z', U2),
          a_tools(S0, '2026-11-20T09:02:05.000Z', chk('c2', 'make the export button blue')),
          a_tools(S0, '2026-11-20T09:02:06.000Z', tu('e2', 'Edit', {'file_path': '/src/report.css'})),
          u_prompt(S0, '2026-11-20T09:03:00.000Z', 'thanks, that is all'),
          a_text(S0, '2026-11-20T09:03:05.000Z', 'You are welcome.'),
          u_prompt(S0, '2026-11-20T09:04:00.000Z', 'one more: rename the page'),
          a_tools(S0, '2026-11-20T09:04:05.000Z', tu('b4', 'Bash', {'command': 'git mv a b'})),
          a_tools(S0, '2026-11-20T09:06:00.000Z', chk('c4', 'rename the page'))]
ev0, tus0 = A.parse_lines(lines0)
check('parse_lines gives exactly the frozen parse_records events', ev0 == TM.parse_records(lines0))
check('helper (sidechain) tool calls are not tool calls of the main session',
      [t['id'] for t in tus0] == ['b1', 'r1', 'c1', 'c2', 'e2', 'b4', 'c4'], [t['id'] for t in tus0])
check('parse_tool_uses keeps every input; parse_lines keeps only check_state inputs',
      A.parse_tool_uses(lines0)[0]['input'] == {'command': 'ls src'} and 'input' not in tus0[0]
      and tus0[2]['input']['goal'] == 'add the export button')
users0 = [i for i, e in enumerate(ev0) if e['k'] == 'user']
r1 = A.anchored(ev0, tus0, users0[1])
check('Bash first: a check event is inserted at the Bash call, in a copy of the events',
      r1 is not None and r1[0] is not ev0 and r1[0][r1[1]]['id'] == 'b1' and len(r1[0]) == len(ev0) + 1
      and r1[0][r1[1]]['ts'] == '2026-11-20T09:01:06.000Z')
check('...whose input is the first check_state within 60 s after it',
      r1 is not None and r1[0][r1[1]]['input'].get('goal') == 'add the export button')
row1 = TM.build_row(r1[0], r1[1], S0)
check('...and build_row reads it as the turn of that message', row1['msg'] == U1
      and row1['goal'] == 'add the export button' and row1['first_text'].startswith('Adding the export'))
r2 = A.anchored(ev0, tus0, users0[2])
c2 = next(i for i, e in enumerate(ev0) if e['k'] == 'check' and e['id'] == 'c2')
check('check_state first: the check arm\'s own event, the same list', r2 == (ev0, c2) and r2[0] is ev0)
rowc = TM.build_row(ev0, c2, S0)
check('...so the row and the rendered prompt are the check arm\'s',
      A.row_at(ev0, tus0, users0[2], S0)[0] == rowc
      and A.rendered_sha(A.row_at(ev0, tus0, users0[2], S0)[0]) == A.rendered_sha(rowc))
check('a text-only turn gives no anchor and no row',
      A.anchored(ev0, tus0, users0[3]) is None
      and A.row_at(ev0, tus0, users0[3], S0)[1] == 'no tool call after the message')
r4 = A.anchored(ev0, tus0, users0[4])
check('a check_state later than the 60 s window gives no goal', r4 is not None
      and r4[0][r4[1]]['input'] == {} and TM.build_row(r4[0], r4[1], S0)['goal'] is None)
key1 = TM.msg_key(U1, '2026-11-20T09:01:00.000Z')
check('anchored_row(lines, msg_key, sid) is that row', A.anchored_row(lines0, key1, S0) == row1)
check('an unknown message key gives no row', A.anchored_row(lines0, 'f' * 24, S0) is None
      and A.row_for(ev0, tus0, 'f' * 24, S0)[1] == 'user message not in transcript')
check('the hook side and the anchor agree on the message key (lb_turnwatch.msg_key)',
      T.msg_key(U1, '2026-11-20T09:01:00.000Z') == key1)

with tempfile.TemporaryDirectory() as td:
    big = pathlib.Path(td) / 'long.jsonl'
    write(big, lines0[:4])
    filler = tool_result(S0, '2026-11-20T09:01:05.500Z', 'f').replace('"ok"}]', json.dumps('z' * 7000) + '}]')
    write(big, [filler] * 60)
    write(big, lines0[4:])
    whole_ev, whole_tus = A.parse_lines(big.read_text().split('\n'))
    want = A.row_for(whole_ev, whole_tus, key1, S0)[0]
    for blk in (4096, 65536, 1 << 20):
        evb, tub = T.read_anchor_events(TM, A, str(big), key1, block=blk)
        got = A.row_for(evb, tub, key1, S0)[0]
        check(f'the {blk}-byte backwards reader builds the same anchored row as the whole file',
              got is not None and got == want and want['check_id'] == 'b1')

# ── through lb_coverage, as the phase 2a wiring runs it ─────────────────────────────
print('through lb_coverage (fast.py -I -S): the first tool call after each user message')
TD = pathlib.Path(tempfile.mkdtemp(prefix='lb-anchor-'))
STATE, HOME = TD / 'state', TD / 'home'
STATE.mkdir()
HOME.mkdir()
(STATE / 'askllm-watch.off').write_text('')
MOCK = TD / 'reply.json'
MOCK.write_text(REPLY)
FRZ = frozen_block(TD)


def env_for(**over):
    e = {'PATH': '/usr/bin:/bin', 'HOME': str(HOME), 'LASERBRAIN_HOME': str(HOME),
         'LASERBRAIN_STATE_DIR': str(STATE), 'LASERBRAIN_AGENT': 'claude',
         'LASERBRAIN_ASKLLM_MODE': 'watch', 'LASERBRAIN_ASKLLM_WATCH': 'off',
         'LASERBRAIN_TURNS_HARVEST': '0', 'LASERBRAIN_TURNWATCH_MOCK_REPLY': str(MOCK),
         'LASERBRAIN_TURNWATCH_DELAY': '0', 'LASERBRAIN_TURNWATCH_TRIGGER': 'first_tool',
         'LASERBRAIN_TURNWATCH_ANCHOR_FROZEN': str(FRZ), 'PYTHONPATH': str(PKG), 'LANG': 'en_US.UTF-8'}
    for k, v in over.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return e


def hook(ev, **over):
    r = subprocess.run([PY, '-I', '-S', str(HOOKS / 'fast.py'), 'lb_coverage'], input=json.dumps(ev),
                       capture_output=True, text=True, env=env_for(**over), timeout=60)
    return r


def prompt_ev(sid, tp, text):
    return {'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'transcript_path': str(tp),
            'cwd': '/tmp', 'prompt': text}


def post_ev(sid, tp, tid, name='Bash', inp=None, agent=None, fail=False):
    ev = {'hook_event_name': 'PostToolUseFailure' if fail else 'PostToolUse', 'session_id': sid,
          'transcript_path': str(tp), 'cwd': '/tmp', 'tool_name': name, 'tool_use_id': tid,
          'tool_input': inp if inp is not None else {'command': 'ls'}}
    if fail:
        ev['error'] = 'Exit code 1'
    else:
        ev['tool_response'] = {'stdout': 'ok', 'stderr': ''}
    if agent:
        ev['agent_id'] = agent
    return ev


def rows(sid):
    p = STATE / 'turnwatch.jsonl'
    out = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
    return [r for r in out if r.get('session') == sid]


def wait_rows(sid, n, secs=25):
    t_end = time.time() + secs
    while time.time() < t_end:
        if len(rows(sid)) >= n:
            time.sleep(0.3)
            return rows(sid)
        time.sleep(0.1)
    return rows(sid)


def settle(secs=2.0):
    time.sleep(secs)


def marker(sid):
    return STATE / 'turnwatch-pending' / sid


# A: prompt, then a batch Bash + Read, then text: one row, anchored at Bash although Read ran the hook.
sa = 'anchor-sess-a'
ta = TD / f'{sa}.jsonl'
write(ta, [u_prompt(sa, '2026-11-20T10:00:00.000Z', U1)])
ra = hook(prompt_ev(sa, ta, U1))
check('a real prompt leaves the session\'s marker, and no turn line is printed in this mode',
      marker(sa).exists() and 'check_state' not in ra.stdout, ra.stdout[-200:])
write(ta, [a_text(sa, '2026-11-20T10:00:03.000Z', 'Adding the export button.'),
           a_tools(sa, '2026-11-20T10:00:04.000Z', tu('ab1', 'Bash', {'command': 'ls src'}),
                   tu('ar1', 'Read', {'file_path': '/src/a.js'}))])
hook(post_ev(sa, ta, 'ar1', 'Read', {'file_path': '/src/a.js'}))
got = wait_rows(sa, 1)
write(ta, [tool_result(sa, '2026-11-20T10:00:05.000Z', 'ab1'), tool_result(sa, '2026-11-20T10:00:05.100Z', 'ar1')])
hook(post_ev(sa, ta, 'ab1'))
write(ta, [a_text(sa, '2026-11-20T10:00:20.000Z', 'Done: the button is in.')])
settle()
got = rows(sa)
r0 = got[0] if got else {}
check('prompt -> Bash -> text: exactly one row, scored, variant first-tool, trigger first_tool',
      len(got) == 1 and r0.get('status') == 'scored' and r0.get('variant') == 'first-tool'
      and r0.get('trigger') == 'first_tool', got)
check('...for that message, anchored at the FIRST tool call of the batch (Bash), not the call '
      'that ran the hook (Read)', r0.get('msg_ts') == '2026-11-20T10:00:00.000Z'
      and (r0.get('anchor') or {}).get('tool') == 'Bash' and (r0.get('anchor') or {}).get('check_first') is False, r0)
check('...stamped with the quiet policy and a row_sha, no tool_use_id, the mock backend',
      r0.get('policy') == 'quiet-2026-11-19' and isinstance(r0.get('row_sha'), str) and len(r0['row_sha']) == 16
      and r0.get('tool_use_id') is None and r0.get('backend') == 'mock', r0)
check('the marker is cleared once the worker started', not marker(sa).exists())

# B: check_state is the first tool call: the check arm's rendered prompt.
sb = 'anchor-sess-b'
tb = TD / f'{sb}.jsonl'
write(tb, [u_prompt(sb, '2026-11-20T10:10:00.000Z', 'earlier: set up the report page'),
           a_text(sb, '2026-11-20T10:10:10.000Z', 'Set up. Shall I add an export button?'),
           u_prompt(sb, '2026-11-20T10:11:00.000Z', 'yes add the export button')])
hook(prompt_ev(sb, tb, 'yes add the export button'))
write(tb, [a_tools(sb, '2026-11-20T10:11:03.000Z', chk('bc1', 'add the export button', 'reading the page'))])
hook(post_ev(sb, tb, 'bc1', CHECK, {'goal': 'add the export button', 'progress': 'advancing', 'distance': 6}))
gb = wait_rows(sb, 1)
write(tb, [tool_result(sb, '2026-11-20T10:11:03.500Z', 'bc1'),
           a_tools(sb, '2026-11-20T10:11:04.000Z', tu('bb1', 'Bash', {'command': 'ls'}))])
lines_b = tb.read_text().split('\n')
ev_b = TM.parse_records(lines_b)
ci_b = next(i for i, e in enumerate(ev_b) if e['k'] == 'check' and e['id'] == 'bc1')
row_check = TM.build_row(ev_b, ci_b, sb, window_s=TM.FIRST_WORDS_WINDOW_S)
sha_check = T.row_sha(*TM.render(row_check)[:2])
rb = gb[0] if gb else {}
check('check_state first: the row\'s rendered prompt is the check arm\'s (same row_sha)',
      len(gb) == 1 and rb.get('row_sha') == sha_check and (rb.get('anchor') or {}).get('check_first') is True, gb)
hook(post_ev(sb, tb, 'bb1'))
write(tb, [a_tools(sb, '2026-11-20T10:11:30.000Z', chk('bc2', 'add the export button', 'half done'))])
hook(post_ev(sb, tb, 'bc2', CHECK, {'goal': 'add the export button', 'progress': 'advancing', 'distance': 3}))
settle()
check('in first-tool mode a later main check_state starts nothing (the check arm is off for the main '
      'session)', len(rows(sb)) == 1, rows(sb))

# C: a queued mid-turn message is judged at the next main tool call after it is delivered.
sc = 'anchor-sess-c'
tc = TD / f'{sc}.jsonl'
write(tc, [u_prompt(sc, '2026-11-20T10:20:00.000Z', U1)])
hook(prompt_ev(sc, tc, U1))
write(tc, [a_tools(sc, '2026-11-20T10:20:02.000Z', tu('cb1', 'Bash', {'command': 'ls'}))])
hook(post_ev(sc, tc, 'cb1'))
wait_rows(sc, 1)
write(tc, [tool_result(sc, '2026-11-20T10:20:03.000Z', 'cb1'),
           enqueue(sc, '2026-11-20T10:20:04.000Z', U2),
           a_tools(sc, '2026-11-20T10:20:05.000Z', tu('cb2', 'Bash', {'command': 'make'}))])
hook(post_ev(sc, tc, 'cb2'))
settle()
check('a user enqueue leaves the marker, and it stays while the message is not delivered',
      marker(sc).exists() and len(rows(sc)) == 1, rows(sc))
write(tc, [tool_result(sc, '2026-11-20T10:20:06.000Z', 'cb2'),
           queued(sc, '2026-11-20T10:20:07.000Z', U2),
           a_text(sc, '2026-11-20T10:20:08.000Z', 'Also making it blue.'),
           a_tools(sc, '2026-11-20T10:20:09.000Z', tu('cr3', 'Read', {'file_path': '/src/b.css'}))])
hook(post_ev(sc, tc, 'cr3', 'Read', {'file_path': '/src/b.css'}))
gc = wait_rows(sc, 2)
rq = gc[1] if len(gc) > 1 else {}
check('...and once delivered, the next main tool call judges it (msg_via queued, anchored at Read)',
      len(gc) == 2 and rq.get('msg_ts') == '2026-11-20T10:20:07.000Z' and rq.get('msg_via') == 'queued'
      and (rq.get('anchor') or {}).get('tool') == 'Read' and not marker(sc).exists(), gc)

# D: a text-only turn gives no row (and a task notification after it ends the turn).
sd = 'anchor-sess-d'
tdp = TD / f'{sd}.jsonl'
write(tdp, [u_prompt(sd, '2026-11-20T10:30:00.000Z', 'what does the export button do?'),
            a_text(sd, '2026-11-20T10:30:05.000Z', 'It downloads the report as CSV.')])
hook(prompt_ev(sd, tdp, 'what does the export button do?'))
note = '<task-notification>background job finished</task-notification>'
write(tdp, [u_prompt(sd, '2026-11-20T10:31:00.000Z', note)])
hook(prompt_ev(sd, tdp, note))
check('a task notification after a text-only turn clears the marker', not marker(sd).exists())
write(tdp, [a_tools(sd, '2026-11-20T10:31:02.000Z', tu('db1', 'Bash', {'command': 'cat log'}))])
hook(post_ev(sd, tdp, 'db1'))
settle()
check('a text-only turn gives no row, even when tools follow a task notification', rows(sd) == [], rows(sd))
write(tdp, [u_prompt(sd, '2026-11-20T10:32:00.000Z', 'explain the CSV columns'),
            a_text(sd, '2026-11-20T10:32:05.000Z', 'There are three columns.'),
            u_prompt(sd, '2026-11-20T10:33:00.000Z', 'now add a fourth column')])
hook(prompt_ev(sd, tdp, 'explain the CSV columns'))
hook(prompt_ev(sd, tdp, 'now add a fourth column'))
write(tdp, [a_tools(sd, '2026-11-20T10:33:02.000Z', tu('de1', 'Edit', {'file_path': '/src/csv.js'}))])
hook(post_ev(sd, tdp, 'de1', 'Edit', {'file_path': '/src/csv.js'}))
gd = wait_rows(sd, 1)
check('text-only, then a message with a tool call: one row, for the second message only',
      len(gd) == 1 and gd[0].get('msg_ts') == '2026-11-20T10:33:00.000Z', gd)

# E: a task notification on its own: no marker and no row.
se = 'anchor-sess-e'
te = TD / f'{se}.jsonl'
write(te, [u_prompt(se, '2026-11-20T10:40:00.000Z', note)])
hook(prompt_ev(se, te, note))
write(te, [a_tools(se, '2026-11-20T10:40:02.000Z', tu('eb1', 'Bash', {'command': 'cat log'}))])
hook(post_ev(se, te, 'eb1'))
settle()
check('a task notification writes no marker and gives no row', not marker(se).exists() and rows(se) == [])

# F: helper calls never trigger.
sf = 'anchor-sess-f'
tf = TD / f'{sf}.jsonl'
write(tf, [u_prompt(sf, '2026-11-20T10:50:00.000Z', U1),
           a_tools(sf, '2026-11-20T10:50:02.000Z', tu('fa1', 'Agent', {'prompt': 'write tests'}))])
hook(prompt_ev(sf, tf, U1))
hook(post_ev(sf, tf, 'fh1', 'Bash', {'command': 'pytest'}, agent='agent-f1'))
hook(post_ev(sf, tf, 'fh2', CHECK, {'goal': 'write tests', 'progress': 'advancing', 'distance': 5}, agent='agent-f1'))
hook(post_ev(sf, tf, 'fh3', 'Bash', {'command': 'false'}, agent='agent-f1', fail=True))
settle()
check('a helper\'s tool calls (an agent_id) never start turnwatch and keep the marker',
      rows(sf) == [] and marker(sf).exists(), rows(sf))
hook(post_ev(sf, tf, 'fa1', 'Agent', {'prompt': 'write tests'}))
gf = wait_rows(sf, 1)
check('...the main session\'s own call then does (anchored at its Agent call)',
      len(gf) == 1 and (gf[0].get('anchor') or {}).get('tool') == 'Agent', gf)

# G: a stale marker expires after 30 minutes.
sg = 'anchor-sess-g'
tg = TD / f'{sg}.jsonl'
write(tg, [u_prompt(sg, '2026-11-20T11:00:00.000Z', U1)])
hook(prompt_ev(sg, tg, U1))
old = time.time() - 1801
os.utime(marker(sg), (old, old))
write(tg, [a_tools(sg, '2026-11-20T11:00:02.000Z', tu('gb1', 'Bash', {'command': 'ls'}))])
hook(post_ev(sg, tg, 'gb1'))
settle()
check('a marker older than 1,800 s is removed and starts nothing', not marker(sg).exists() and rows(sg) == [])

# H: a failed first tool call counts (PostToolUseFailure).
sh = 'anchor-sess-h'
th = TD / f'{sh}.jsonl'
write(th, [u_prompt(sh, '2026-11-20T11:10:00.000Z', U1),
           a_tools(sh, '2026-11-20T11:10:02.000Z', tu('hb1', 'Bash', {'command': 'false'}))])
hook(prompt_ev(sh, th, U1))
hook(post_ev(sh, th, 'hb1', fail=True))
gh = wait_rows(sh, 1)
check('a failed first tool call (PostToolUseFailure) starts it too', len(gh) == 1 and gh[0].get('status') == 'scored', gh)

# I: with the env unset, or outside quiet mode, lb_coverage writes no marker.
for n_i, (label, over) in enumerate((('LASERBRAIN_TURNWATCH_TRIGGER unset', {'LASERBRAIN_TURNWATCH_TRIGGER': None}),
                                     ('LASERBRAIN_STUDY=1 (not quiet)', {'LASERBRAIN_STUDY': '1'}),
                                     ('LASERBRAIN_GATE_MODE=hard (not quiet)', {'LASERBRAIN_GATE_MODE': 'hard'}))):
    si = f'anchor-sess-i{n_i}'
    ti = TD / f'{si}.jsonl'
    write(ti, [u_prompt(si, '2026-11-20T11:20:00.000Z', U1)])
    rp = hook(prompt_ev(si, ti, U1), **over)
    write(ti, [a_tools(si, '2026-11-20T11:20:02.000Z', tu('ib1', 'Bash', {'command': 'ls'}))])
    hook(post_ev(si, ti, 'ib1'), **over)
    settle(1.0)
    extra = ''
    if label.endswith('unset'):
        extra = ' (and the quiet turn line is printed, as WP1 has it)'
        cond_line = 'laserbrain: new user message' in rp.stdout
    else:
        cond_line = True
    check(f'{label}: no marker and no row{extra}', not marker(si).exists() and rows(si) == [] and cond_line,
          rp.stdout[-200:])

# ── frozen: a changed turn_anchor.py is refused ─────────────────────────────────────
print('frozen: the anchor arm checks turn_anchor.py with every judge file')


def judge_copy(name, edit=None):
    root = TD / name
    (root / 'research' / 'eval').mkdir(parents=True)
    (root / 'python' / 'laserbrain' / 'hooks').mkdir(parents=True)
    for n in list(JUDGE_FILES) + ['turn_anchor.py']:
        shutil.copy2(EVAL / n, root / 'research' / 'eval' / n)
    shutil.copy2(HOOKS / 'lb_secrets.py', root / 'python' / 'laserbrain' / 'hooks' / 'lb_secrets.py')
    return root / 'research' / 'eval'


def worker(job, **over):
    e = env_for(**over)
    r = subprocess.run([PY, '-P', str(HOOKS / 'lb_turnwatch.py'), '--worker'], input=json.dumps(job),
                       capture_output=True, text=True, env=e, timeout=120)
    return r


sj = 'anchor-sess-j'
tj = TD / f'{sj}.jsonl'
write(tj, [u_prompt(sj, '2026-11-20T11:30:00.000Z', U1),
           a_tools(sj, '2026-11-20T11:30:02.000Z', tu('jb1', 'Bash', {'command': 'ls'}))])


def job(i):
    return {'session': f'{sj}-{i}', 'transcript_path': str(tj), 'tool_use_id': None, 'lane': None,
            'msg_key': T.msg_key(U1, '2026-11-20T11:30:00.000Z'), 'msg_ts': '2026-11-20T11:30:00.000Z',
            'hook_ts': 'T', 'hook_epoch': time.time(), 'state_dir': str(STATE), 'trigger': 'first_tool',
            'policy': 'quiet-2026-11-19', 'arm': 'anchor'}


ed_same = judge_copy('same')
frz_same = frozen_block(TD, ed=ed_same)
ed_chg = judge_copy('changed')
frz_chg = frozen_block(TD, ed=ed_chg)
(ed_chg / 'turn_anchor.py').write_text((ed_chg / 'turn_anchor.py').read_text() + '\n# changed\n')
frz_noanchor = frozen_block(TD, ed=ed_same, anchor=None)
check_block = json.loads((REPO / 'eval' / 'turnwatch-frozen.json').read_text()).get('frozen') or {}
frz_checkblock = TD / 'check-block-as-anchor.json'
frz_checkblock.write_text(json.dumps({'frozen': check_block}))
cases = {}
for i, (name, ed, fz) in enumerate((('same', ed_same, frz_same), ('changed', ed_chg, frz_chg),
                                    ('no anchor key', ed_same, frz_noanchor),
                                    ('the check arm\'s block', EVAL, frz_checkblock))):
    worker(job(i), LASERBRAIN_TURNWATCH_EVAL_DIR=str(ed), LASERBRAIN_TURNWATCH_ANCHOR_FROZEN=str(fz))
    cases[name] = (rows(f'{sj}-{i}') or [{}])[-1]
check('an unchanged copy of the judge and the anchor scores', cases['same'].get('status') == 'scored', cases['same'])
check('a changed turn_anchor.py: skipped, frozen changed, before it runs',
      cases['changed'].get('status') == 'skipped' and cases['changed'].get('reason') == 'frozen changed'
      and 'eval_files_sha256:turn_anchor.py' in (cases['changed'].get('frozen_bad') or []), cases['changed'])
check('a block without anchor=first_tool: skipped, frozen changed',
      cases['no anchor key'].get('reason') == 'frozen changed' and 'anchor' in (cases['no anchor key'].get('frozen_bad') or []),
      cases['no anchor key'])
check('the check arm\'s block (no turn_anchor.py pin) cannot run the anchor arm',
      cases['the check arm\'s block'].get('reason') == 'frozen changed'
      and 'anchor' in (cases['the check arm\'s block'].get('frozen_bad') or []), cases['the check arm\'s block'])
check('every skipped row is still variant first-tool, trigger first_tool',
      all(c.get('variant') == 'first-tool' and c.get('trigger') == 'first_tool' for c in cases.values()), cases)

real = REPO / 'eval' / 'turnwatch-anchor-frozen.json'
print('the real anchor frozen block')
check('eval/turnwatch-anchor-frozen.json exists', real.exists())
if real.exists():
    afz = json.loads(real.read_text()).get('frozen') or {}
    cpins = check_block.get('eval_files_sha256') or {}
    apins = afz.get('eval_files_sha256') or {}
    check('it carries every pin of eval/turnwatch-frozen.json unchanged, plus turn_anchor.py',
          all(apins.get(k) == v for k, v in cpins.items()) and set(apins) == set(cpins) | {'turn_anchor.py'})
    check('the same prompt hash, model, thresholds and first-words window as the check arm',
          all(afz.get(k) == check_block.get(k) for k in ('prompt_hash', 'model', 'thresholds',
                                                         'first_words_window_s', 'turn_match_llm_sha256',
                                                         'ask_match_llm_sha256')) and afz.get('anchor') == 'first_tool')
    check('it says the arm is unscored and its reach is DEV_NOT_HELD_OUT',
          'NOT been scored' in afz.get('note', '') and 'DEV_NOT_HELD_OUT' in afz.get('note', ''))
    m, why, info = T.load_frozen('anchor')
    check('the current research/eval files and turn_anchor.py match it', m is not None and why is None,
          f'{why} {info.get("bad")}')

shutil.rmtree(TD, ignore_errors=True)
print('  PASS' if ok_all else '  FAIL')
raise SystemExit(0 if ok_all else 1)
