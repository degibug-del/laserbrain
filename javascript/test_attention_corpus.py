#!/usr/bin/env python3
"""The calibration's user turns outlive the host's transcripts (added 2026-10-29).

WHY. Every band in attention.json is "time since the user last spoke", and those moments came
only from Claude Code's transcripts, which it deletes after cleanupPeriodDays. On 2026-10-29
the drift log was whole back to 2026-07-28 and none of the 3243 user turns behind the shipped
table were left: every band fell under MIN_N and --check called a sound table STALE. A plain
run would have replaced it with four nulls.

What must hold, all on temp files (nothing here reads or writes the live corpus):
  A  --harvest copies every enqueue the transcripts hold into laserbrain's record, once
  B  a turn survives its transcript: user_messages() reads the record as well
  C  shrinkage() tells deleted input from a grown corpus
  D  a band that lost its rate with fewer readings is "gone"; anything else is still stale

Run:  python3 test_attention_corpus.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(label)


def enq(ts, content='go'):
    return json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': ts,
                       'content': content}) + '\n'


def run(code, env):
    """Run a snippet against calibrate_attention with `env` (it reads its paths at import)."""
    full = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    full.update(env)
    p = subprocess.run([sys.executable, '-c', 'import sys, json; sys.path.insert(0, %r)\n'
                        'import calibrate_attention as C\n' % str(HERE) + code],
                       env=full, capture_output=True, text=True, cwd=str(HERE), timeout=120)
    if p.returncode:
        return {'error': (p.stderr or p.stdout)[-300:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


d = pathlib.Path(tempfile.mkdtemp())
(d / 'projects' / 'p1' / 'sub').mkdir(parents=True)
t1 = d / 'projects' / 'p1' / 's1.jsonl'
t2 = d / 'projects' / 'p1' / 'sub' / 'agent-1.jsonl'
t1.write_text('{"type": "user"}\n' + enq('2026-10-01T10:00:00.000Z')
              + enq('2026-10-01T10:05:00.000Z', '<task-notification>done</task-notification>')
              + '{"type": "queue-operation", "operation": "enqueue"\n')        # torn, ignored
t2.write_text(enq('2026-10-01T11:00:00.000Z'))
env = {'LASERBRAIN_HOME': str(d / 'home'), 'LASERBRAIN_TRANSCRIPTS': str(d / 'projects'),
       'LASERBRAIN_USER_TURNS': str(d / 'turns.jsonl'),
       'LASERBRAIN_DRIFT_LOG': str(d / 'drift-log.jsonl')}

print('A  --harvest')
p = subprocess.run([sys.executable, str(HERE / 'calibrate_attention.py'), '--harvest'],
                   env={**{k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}, **env},
                   capture_output=True, text=True, cwd=str(HERE), timeout=120)
rows = [json.loads(line) for line in (d / 'turns.jsonl').read_text().splitlines()]
check('it exits 0 and says how many it added', p.returncode == 0 and '3 user turn(s) added' in p.stdout,
      p.stdout + p.stderr)
check('every enqueue is kept, nested transcripts included',
      sorted(r['ts'] for r in rows) == ['2026-10-01T10:00:00.000Z', '2026-10-01T10:05:00.000Z',
                                        '2026-10-01T11:00:00.000Z'], str(rows))
check('...with its kind', {r['ts'][11:16]: r['kind'] for r in rows} ==
      {'10:00': 'user', '10:05': 'notification', '11:00': 'user'}, str(rows))
p = subprocess.run([sys.executable, str(HERE / 'calibrate_attention.py'), '--harvest'],
                   env={**{k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}, **env},
                   capture_output=True, text=True, cwd=str(HERE), timeout=120)
check('a second run adds nothing', '0 user turn(s) added' in p.stdout
      and len((d / 'turns.jsonl').read_text().splitlines()) == 3, p.stdout)

print('B  a turn outlives its transcript')
t1.unlink()                                       # the host's cleanup
t2.write_text(enq('2026-10-01T11:00:00.000Z') + enq('2026-10-02T09:00:00.000Z'))   # one new, unharvested
r = run('s = C.user_messages(); print(json.dumps({"n": len(s), "src": C.TURN_SOURCES, '
        '"first": s[0].isoformat()}))', env)
check('user_messages() still has the deleted transcript\'s turns', r.get('n') == 4
      and r.get('first', '').startswith('2026-10-01T10:00:00'), str(r))
check('...and counts where each came from', r.get('src') == {'logged': 3, 'transcripts': 2,
                                                            'transcripts_only': 1}, str(r))
r = run('import os; os.remove(C.TURNS); print(json.dumps(len(C.user_messages())))', env)
check('without the record, only the transcripts remain (the old behaviour)', r == 2, str(r))

print('C  shrinkage()')
code = ('import datetime as D\n'
        'mk = lambda s: D.datetime.fromisoformat(s)\n'
        'speaks = [mk("2026-08-20T10:00:00+00:00"), mk("2026-08-22T23:00:00+00:00"), '
        'mk("2026-09-01T00:00:00+00:00")]\n'
        'cur = lambda n, w: {"provenance": {"user_messages": n, "written": w}}\n'
        'print(json.dumps([C.shrinkage(cur(5, "2026-08-22"), speaks), C.shrinkage(cur(2, "2026-08-22"), speaks), '
        'C.shrinkage(cur(3, "2026-08-21"), speaks), C.shrinkage({}, speaks), '
        'C.shrinkage({"provenance": {"user_messages": "x", "written": 7}}, speaks)]))')
r = run(code, env)
check('fewer turns visible up to the written day than recorded: shrunk', r and r[0] == [2, 5, '2026-08-22'], str(r))
check('as many as recorded: not shrunk', r and r[1] is None, str(r))
check('turns after the written day do not count', r and r[2] == [1, 3, '2026-08-21'], str(r))
check('no provenance, or a malformed one: no claim', r and r[3] is None and r[4] is None, str(r))

print('D  gone vs stale')
code = ('band = lambda l, n, rate: {"label": l, "n": n, "rate": rate}\n'
        'cur = {"bands": [band("a", 300, 0.16), band("b", 400, 0.27), band("c", 10, None), band("d", 50, 0.5)]}\n'
        'new = {"bands": [band("a", 19, None), band("b", 420, 0.40), band("c", 40, 0.3), band("d", 60, None)]}\n'
        'ds = C.differences(cur, new, 0.05)\n'
        'print(json.dumps({d["label"]: [d["kind"], C._gone(d)] for d in ds} | '
        '{"compare": len(C.compare(cur, new, 0.05))}))')
r = run(code, env)
check('lost its rate with fewer readings: gone', r.get('a') == ['lost', True], str(r))
check('a rate that moved: stale', r.get('b') == ['moved', False], str(r))
check('gained a rate: stale', r.get('c') == ['gained', False], str(r))
check('lost its rate with MORE readings: stale, not gone', r.get('d') == ['lost', False], str(r))
check('compare() still lists every difference', r.get('compare') == 4, str(r))

print('E  --check and the write guards on a synthetic table (temp files only)')
CAL = HERE / 'calibrate_attention.py'


def corpus(root, n, drifts, turns_kept=None):
    """n days, each one user turn at 10:00 and one settled reading at 10:02 ('1-5 minutes'), in a run of
    its own; the first `drifts` readings are goal-drift. The record keeps `turns_kept` of the turns."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'home').mkdir(exist_ok=True)
    (root / 'projects').mkdir(exist_ok=True)
    rows, turns = [], []
    import datetime as _dt
    for i in range(n):
        day = (_dt.date(2026, 9, 1) + _dt.timedelta(days=i)).isoformat()
        turns.append(f'{day}T10:00:00.000Z')
        rows.append({'ts': f'{day}T10:02:00.000Z', 'run': f'r{i}', 'agent': 'claude', 'drifting': i < drifts,
                     'reason': 'goal-drift' if i < drifts else 'advancing'})
    (root / 'drift.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    keep = turns if turns_kept is None else turns[:turns_kept]
    (root / 'turns.jsonl').write_text(''.join(json.dumps({'ts': s, 'kind': 'user'}) + '\n' for s in keep))
    return {'LASERBRAIN_HOME': str(root / 'home'), 'LASERBRAIN_TRANSCRIPTS': str(root / 'projects'),
            'LASERBRAIN_USER_TURNS': str(root / 'turns.jsonl'), 'LASERBRAIN_DRIFT_LOG': str(root / 'drift.jsonl'),
            'LASERBRAIN_ATTENTION_OUT': str(root / 'out.json'), 'LASERBRAIN_ATTENTION_SHIPPED': str(root / 'shipped.json')}


def cal(env, *args):
    full = {k: v for k, v in os.environ.items() if not k.startswith('LASERBRAIN_')}
    full.update(env)
    p = subprocess.run([sys.executable, str(CAL), *args], env=full, capture_output=True, text=True,
                       cwd=str(HERE), timeout=120)
    return p.returncode, p.stdout + p.stderr


def band(env, label='1-5 minutes'):
    return next(b for b in json.loads(pathlib.Path(env['LASERBRAIN_ATTENTION_OUT']).read_text())['bands']
                if b['label'] == label)


base = pathlib.Path(tempfile.mkdtemp())
env = corpus(base / 'a', 40, 4)                                  # 4 of 40 = 10%
rc, out = cal(env)
check('a first write needs no guard and is measured on the corpus', rc == 0 and band(env)['n'] == 40
      and band(env)['rate'] == 0.1, out[-300:])
pathlib.Path(env['LASERBRAIN_ATTENTION_SHIPPED']).write_text(pathlib.Path(env['LASERBRAIN_ATTENTION_OUT']).read_text())
rc, out = cal(env, '--check')
check('--check passes on the corpus it was written from', rc == 0 and 'still describes' in out, out[-300:])

env_b = corpus(base / 'a', 40, 16)                               # same readings, 40% drift: really stale
rc, out = cal(env_b, '--check')
check('a moved rate on as many readings is STALE', rc == 1 and 'STALE' in out and '1-5 minutes' in out, out[-300:])
check('...and the advice is a plain run when nothing would get thinner',
      'Run: python3 calibrate_attention.py' in out and '--accept-thinner' not in out, out[-200:])

env_c = corpus(base / 'a', 40, 16, turns_kept=25)               # the host deleted 15 turns
rc, out = cal(env_c, '--check')
check('after deletion, a band measured on fewer readings is SHRUNK, not STALE, even if its rate moved',
      rc == 0 and 'SHRUNK' in out and 'STALE' not in out, out[-400:])
rc, out = cal(env_c)
check('...and a plain write refuses, per band, naming it', rc == 1 and 'REFUSING' in out
      and '1-5 minutes: n 40 -> 25' in out and band(env_c)['n'] == 40, out[-400:])
rc, out = cal(env_c, '--force')
check('--force does not silence the sample guard', rc == 1 and 'REFUSING' in out and band(env_c)['n'] == 40,
      out[-200:])
rc, out = cal(env_c, '--accept-thinner')
check('--accept-thinner writes the thinner table', rc == 0 and band(env_c)['n'] == 25, out[-200:])

env_d = corpus(base / 'd', 40, 4)
cal(env_d)
pathlib.Path(env_d['LASERBRAIN_ATTENTION_SHIPPED']).write_text(pathlib.Path(env_d['LASERBRAIN_ATTENTION_OUT']).read_text())
corpus(base / 'd', 30, 4)                                        # fewer readings now
rc, out = cal(env_d, '--accept-thinner')                          # only the json/ copy goes thin
check('(setup) the json/ copy is now the thinner one', rc == 0 and band(env_d)['n'] == 30, out[-200:])
rc, out = cal(env_d, '--ship')
shipped_n = next(b for b in json.loads(pathlib.Path(env_d['LASERBRAIN_ATTENTION_SHIPPED']).read_text())['bands']
                 if b['label'] == '1-5 minutes')['n']
check('--ship refuses when the packaged copy is the thicker one', rc == 1 and 'REFUSING' in out and shipped_n == 40,
      out[-300:])

env_e = corpus(base / 'e', 40, 4)
cal(env_e)
doc = json.loads(pathlib.Path(env_e['LASERBRAIN_ATTENTION_OUT']).read_text())
doc['bands'][1]['rate'] = 0.9                                    # edited by hand: drift/n says 0.1
pathlib.Path(env_e['LASERBRAIN_ATTENTION_OUT']).write_text(json.dumps(doc))
rc, out = cal(env_e, '--check')
check('a table whose rate contradicts its own drift/n is INCONSISTENT, deletion or not',
      rc == 1 and 'INCONSISTENT' in out and 'rate 0.9 but drift 4 of n 40' in out, out[-300:])

env_f = corpus(base / 'f', 25, 2)
with open(env_f['LASERBRAIN_USER_TURNS'], 'a') as fh:
    fh.write(json.dumps({'ts': '2026-10-30T18:00:00', 'kind': 'user'}) + '\n')   # no zone
    fh.write(json.dumps({'ts': '2026-10-30', 'kind': 'user'}) + '\n')
rc, out = cal(env_f, '--check')
check('a record line with no timezone is skipped, not a crash', rc in (0, 1) and 'Traceback' not in out, out[-300:])

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:4]))
    sys.exit(1)
print('  PASS — the user turns are laserbrain\'s own, and deletion is not staleness.')
