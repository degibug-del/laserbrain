"""The coverage hook keeps every moment the user spoke (user-turns.jsonl), added 2026-10-29.

WHY. attention.json measures drift against the time since the user last spoke. Those moments
lived only in the host's transcripts, and Claude Code deletes transcripts after
cleanupPeriodDays: on 2026-10-29 none of the 3243 user turns behind the shipped table were left,
while the drift log, which laserbrain owns, was whole. So lb_coverage now appends every enqueue
record it scans to a file laserbrain owns, with its own timestamp and its kind.

What must hold:
  A  a new session's history is recorded on first sight, and never re-grounded on
  B  an enqueue that arrives later is recorded, and a user one still re-grounds
  C  a <task-notification> is recorded as one, and in nudge mode still does not re-ground
  D  a transcript too big to read in a hook is skipped on first sight, then followed
  E  junk lines and records without a timestamp are ignored; the hook still exits 0
  F  nothing new means nothing written
  G  parallel hooks (a workflow's subagents) leave whole lines, none torn or lost
  H  the offsets file keeps the sessions in use (it evicted the smallest offsets until 2026-10-30),
     drops deleted transcripts, is written atomically, and an odd JSON line does not end a scan
  I  a prompt starts a background catch-up at most once a day, never for a relocated test root

Run:  python3 test_user_turns.py
"""
import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
HOOK = pathlib.Path(os.environ.get('LB_COVERAGE') or ROOT / 'laserbrain/hooks/lb_coverage.py')
# A hook copy without its sibling lb_paths.py falls back to the HISTORICAL paths and ignores
# LASERBRAIN_HOME (lb_coverage says so on stderr), so every write below would land in the real
# ~/.config/laserbrain. A review run did exactly that on 2026-10-29: fixture turns in the live record.
if not (HOOK.parent / 'lb_paths.py').exists():
    raise SystemExit(f'{HOOK} has no lb_paths.py beside it: run against a copy of the whole hooks folder')
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def env_for(d, mode=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    env.update(LASERBRAIN_STATE_DIR=str(d), LASERBRAIN_HOME=str(d / 'home'),
               LASERBRAIN_AGENT='claude', LASERBRAIN_LINK_LOG=str(d / 'link.jsonl'),
               PYTHONPATH=str(ROOT), LASERBRAIN_PROBE_SHARE='0')
    if mode is not None:
        env['LASERBRAIN_GATE_MODE'] = mode
    return env


def post(d, transcript, mode=None):
    ev = {'hook_event_name': 'PostToolUse', 'session_id': 'S1', 'tool_name': 'Read',
          'tool_input': {}, 'tool_response': {}, 'transcript_path': str(transcript)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), capture_output=True,
                          text=True, env=env_for(d, mode), cwd=str(ROOT), timeout=60)


def enq(ts, content='do the thing'):
    return json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': ts,
                       'content': content}) + '\n'


def note(ts):
    return enq(ts, '<task-notification>\n<task-id>w1</task-id>\n</task-notification>')


def other(i):
    return json.dumps({'type': 'assistant', 'uuid': f'u{i}', 'message': {'content': 'x' * 40}}) + '\n'


def log(d):
    f = d / 'home' / 'config' / 'user-turns.jsonl'
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines()]


def flag(d):
    return d / 'home' / 'config' / 'user-turn'


print('A  first sight of a new session')
d = pathlib.Path(tempfile.mkdtemp())
t = d / 'sess-a.jsonl'
t.write_text(other(0) + enq('2026-10-29T10:00:00.000Z') + other(1) + note('2026-10-29T10:01:00.000Z'))
p = post(d, t)
rows = log(d)
show('the hook exits 0', p.returncode == 0, p.stderr[-200:])
show('both enqueues are recorded', [r['ts'] for r in rows] ==
     ['2026-10-29T10:00:00.000Z', '2026-10-29T10:01:00.000Z'], str(rows))
show('...each with its kind', [r['kind'] for r in rows] == ['user', 'notification'], str(rows))
show('...its session, and where it came from', all(r['sid'] == 'sess-a' and r['src'] == 'hook' for r in rows))
show('history is never re-grounded on (no user-turn flag)', not flag(d).exists())

print('B  an enqueue that arrives later')
with t.open('a') as fh:
    fh.write(other(2) + enq('2026-10-29T10:05:00.000Z', 'actually, make it blue'))
p = post(d, t)
rows = log(d)
show('it is recorded once, after the history', [r['ts'] for r in rows][-1] == '2026-10-29T10:05:00.000Z'
     and len(rows) == 3, str(rows))
show('and a user message still re-grounds', flag(d).exists())

print('C  a task notification')
flag(d).unlink()
with t.open('a') as fh:
    fh.write(note('2026-10-29T10:06:00.000Z'))
post(d, t)
rows = log(d)
show('it is recorded as a notification', rows[-1]['kind'] == 'notification' and len(rows) == 4, str(rows[-1:]))
show('...and in nudge mode it does not re-ground', not flag(d).exists())
with t.open('a') as fh:
    fh.write(note('2026-10-29T10:07:00.000Z'))
post(d, t, mode='hard')
show('in hard mode it re-grounds as before, and is still recorded',
     flag(d).exists() and log(d)[-1]['ts'] == '2026-10-29T10:07:00.000Z')

print('D  a transcript too big to read in a hook')
big = d / 'sess-big.jsonl'
with big.open('w') as fh:
    fh.write(enq('2026-10-20T09:00:00.000Z'))
    pad = other(9)
    while fh.tell() < 4 * 1024 * 1024 + 4096:
        fh.write(pad)
before = len(log(d))
p = post(d, big)
show('first sight records nothing and exits 0', len(log(d)) == before and p.returncode == 0)
with big.open('a') as fh:
    fh.write(enq('2026-10-29T11:00:00.000Z'))
post(d, big)
show('...then follows it from there', log(d)[-1]['ts'] == '2026-10-29T11:00:00.000Z'
     and len(log(d)) == before + 1)

print('E  junk')
j = d / 'sess-junk.jsonl'
j.write_text('{"type": "queue-operation", "operation": "enqueue"\n'          # torn
             + json.dumps({'type': 'queue-operation', 'operation': 'enqueue'}) + '\n'   # no timestamp
             + json.dumps({'type': 'queue-operation', 'operation': 'dequeue', 'timestamp': 'x'}) + '\n'
             + enq('2026-10-29T12:00:00.000Z'))
before = len(log(d))
p = post(d, j)
show('only the well-formed enqueue is recorded', [r['ts'] for r in log(d)[before:]] ==
     ['2026-10-29T12:00:00.000Z'], str(log(d)[before:]))
show('...and the hook exits 0', p.returncode == 0)
p = post(d, d / 'no-such-transcript.jsonl')
show('a missing transcript is a no-op', p.returncode == 0)

print('F  nothing new')
size = (d / 'home' / 'config' / 'user-turns.jsonl').stat().st_size
post(d, t)
show('nothing is written', (d / 'home' / 'config' / 'user-turns.jsonl').stat().st_size == size)

print('G  parallel hooks')
d2 = pathlib.Path(tempfile.mkdtemp())
paths = []
for i in range(8):
    tp = d2 / f'kid-{i}.jsonl'
    tp.write_text(''.join(enq(f'2026-10-29T13:{i:02d}:{s:02d}.000Z') for s in range(50)))
    paths.append(tp)
with concurrent.futures.ThreadPoolExecutor(8) as ex:
    list(ex.map(lambda tp: post(d2, tp), paths))
raw = (d2 / 'home' / 'config' / 'user-turns.jsonl').read_text().splitlines()
parsed = []
for line in raw:
    try:
        parsed.append(json.loads(line))
    except ValueError:
        pass
show('every line is whole', len(parsed) == len(raw), f'{len(raw) - len(parsed)} torn')
show('and none is lost', len({r['ts'] for r in parsed}) == 400, f'{len({r["ts"] for r in parsed})} of 400')

print('H  the offsets file keeps the sessions in use')
d3 = pathlib.Path(tempfile.mkdtemp())
scan = d3 / 'home' / 'config' / 'queue-scan.json'
scan.parent.mkdir(parents=True)
scan.write_text(json.dumps({f'/gone/session-{i}.jsonl': 10_000_000 + i for i in range(40)}))   # deleted, huge
small = d3 / 'small.jsonl'
small.write_text(''.join(enq(f'2026-10-29T14:00:{s:02d}.000Z') for s in range(5)))
for _ in range(4):
    post(d3, small)
state = json.loads(scan.read_text())
rec = (d3 / 'home' / 'config' / 'user-turns.jsonl').read_text().splitlines()
show('a new small session stays tracked once the file is full', str(small) in state, str(len(state)))
show('...so its history is recorded once, not on every call', len(rec) == 5, f'{len(rec)} lines')
show('deleted transcripts are dropped first', not any(k.startswith('/gone/') for k in state) or len(state) <= 40)
show('no temp file is left behind', not list(scan.parent.glob('.queue-scan.json.*.tmp')))
with small.open('a') as fh:
    fh.write('["queue-operation"]\n' + enq('2026-10-29T14:01:00.000Z', 'switch to the poster'))
post(d3, small)
show('a JSON line that is not a record does not end the scan', flag(d3).exists()
     and (d3 / 'home' / 'config' / 'user-turns.jsonl').read_text().count('14:01:00') == 1)

print('I  the daily catch-up')
d4 = pathlib.Path(tempfile.mkdtemp())
(d4 / 'projects' / 'p').mkdir(parents=True)
(d4 / 'projects' / 'p' / 'never-scanned.jsonl').write_text(enq('2026-10-28T08:00:00.000Z'))


def prompt(d, extra):
    env = env_for(d)
    env.update(extra)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
        {'hook_event_name': 'UserPromptSubmit', 'session_id': 'S9', 'prompt': 'hi'}),
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)


prompt(d4, {'LASERBRAIN_TRANSCRIPTS': str(d4 / 'projects')})
show('a relocated LASERBRAIN_HOME (a test) starts no catch-up', not (d4 / 'home' / 'config' / 'turns-harvest.day').exists())
p = prompt(d4, {'LASERBRAIN_TRANSCRIPTS': str(d4 / 'projects'), 'LASERBRAIN_TURNS_HARVEST': '1'})
import time
recf = d4 / 'home' / 'config' / 'user-turns.jsonl'
for _ in range(100):
    if recf.exists() and '2026-10-28T08:00:00.000Z' in recf.read_text():
        break
    time.sleep(0.1)
show('with it on, a prompt starts the catch-up in the background and the hook returns', p.returncode == 0
     and recf.exists() and '"src": "harvest"' in recf.read_text(), p.stderr[-200:])
day = (d4 / 'home' / 'config' / 'turns-harvest.day').read_text()
recf.write_text('')
prompt(d4, {'LASERBRAIN_TRANSCRIPTS': str(d4 / 'projects'), 'LASERBRAIN_TURNS_HARVEST': '1'})
time.sleep(1.5)
show('...once a day', recf.read_text() == '' and (d4 / 'home' / 'config' / 'turns-harvest.day').read_text() == day)

print('\n  ' + ('PASS' if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
