"""goal-drift is a note, not an interrupt — in the stdio server, the one that runs live.

WHY. research/DAY-FIVE-REAL-SESSIONS.md §3: all 7 live goal-drift fires from Oct 17 to Nov 15
were false, and the July corpus had goal-drift at 24 of 35 fires with 0 real. Diego approved
change B on 2026-11-15: goal-drift stops returning drifting=true on its own.
python/test_goal_drift_note.py pins the same contract in the Python reference.

Driven over stdio the way a host drives it, in a private LASERBRAIN_HOME so nothing reaches
the live corpus. Pins:

  1. reason 'goal-drift' is kept, drifting is false, and the row is still logged;
  2. the rejected-parent variant likewise, and it still reports parent_overlap in the log;
  3. the advice keeps the three readings and gives no order to return;
  4. goal-drift is not a first strike (a self-report after it warns; after ungrammatical
     it still interrupts);
  5. the existing escalation is the second signal: three goal-drifts with no reground give
     judgment wrong-problem and control decision reground, unchanged;
  6. modulate answers return false for it, styled or not;
  7. the check_state description no longer calls a goal mismatch a drift;
  8. review_verdicts still lists goal-drift readings, so they can be labelled (it filtered
     on `drifting` first, which hid every goal-drift written after the change).

THIS TEST CAN FAIL: put `true` back on either goal-drift record(), or 'goal-drift' back into
either `_prev` list, or into grammar.modulation, and it goes red.

Run:  python3 test_goal_drift_note.py
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / 'mcp-server.mjs'

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail and not passed else ''))


class Server:
    def __init__(self):
        self.home = tempfile.mkdtemp(prefix='lb-gdnote-')
        env = dict(os.environ,
                   LASERBRAIN_HOME=self.home,
                   LASERBRAIN_DRIFT_LOG=str(pathlib.Path(self.home) / 'drift.jsonl'),
                   LASERBRAIN_HUB='http://127.0.0.1:9', LASERBRAIN_API='http://127.0.0.1:9',
                   LASERBRAIN_AGENT='goal-drift-note-test', LASERBRAIN_ARM='open')
        self.p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, env=env)
        self.n = 0
        self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                'clientInfo': {'name': 'gdnote', 'version': '1'}})

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n, 'method': method,
                                       'params': params}) + '\n')
        self.p.stdin.flush()
        while True:
            m = json.loads(self.p.stdout.readline())
            if m.get('id') == self.n:
                return m

    def call(self, name, args):
        t = self.rpc('tools/call', {'name': name, 'arguments': args})['result']['content'][0]['text']
        try:
            return json.loads(t)
        except ValueError:
            return t

    def check(self, **a):
        return self.call('check_state', a)

    def reset(self):
        self.call('reset_task', {})

    def rows(self, want=None, timeout=3.0):
        """The drift log. logDrift appends asynchronously, so a row written by the call just
        answered may land a moment later: poll until `want(rows)` holds or time runs out."""
        f = pathlib.Path(self.home) / 'drift.jsonl'
        end = time.monotonic() + timeout
        while True:
            rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
            if want is None or want(rows) or time.monotonic() > end:
                return rows
            time.sleep(0.05)

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.home, ignore_errors=True)


if not shutil.which('node'):
    print('  SKIP  node not found')
    raise SystemExit(77)

G = 'build the JSON parser'
s = Server()
try:
    print('\n  1. the plain goal-overlap failure')
    s.check(goal=G, progress='advancing', distance=6)
    v = s.check(goal='write a poem about the sea', progress='advancing', distance=5)
    show('reason is still goal-drift', v.get('reason') == 'goal-drift', v)
    show('drifting is false', v.get('drifting') is False, v)
    show('the ground is still returned beside it', v.get('ground') == G, v.get('ground'))
    gd = lambda rows: [r for r in rows if r.get('reason') == 'goal-drift']
    row = gd(s.rows(want=gd))
    show('the reading is still logged, with drifting false',
         len(row) == 1 and row[0].get('drifting') is False, row)

    print('\n  2. the rejected-parent variant')
    s.reset()
    s.check(goal=G, progress='advancing', distance=6)
    vp = s.check(goal='cook a vegan dinner', progress='advancing', distance=5,
                 parent_goal='paint the garden fence')
    show('reason is still goal-drift', vp.get('reason') == 'goal-drift', vp)
    show('drifting is false', vp.get('drifting') is False, vp)
    pd = lambda rows: [r for r in rows if r.get('reason') == 'goal-drift' and 'parent_overlap' in r]
    prow = pd(s.rows(want=pd))
    show('parent_overlap is still logged', len(prow) == 1 and prow[0]['parent_overlap'] == 0.0, prow)

    print('\n  3. the advice is a note, not an order')
    for name, verdict in (('plain', v), ('rejected parent', vp)):
        a = verdict.get('advice') or ''
        show(f'{name}: says it is recorded, not an interrupt', 'not an interrupt' in a, a)
        show(f'{name}: names reset_task for a redirect', 'redirected you, call reset_task' in a, a)
        show(f'{name}: points at the ground', 'compare your goal with the ground' in a, a)
        show(f'{name}: does not tell the agent to return', 'return' not in a.lower(), a)
    show('plain: still offers parent_goal for a sub-task', 'pass parent_goal' in v['advice'], v['advice'])
    show('rejected parent: never tells an agent to do what it just did',
         'pass parent_goal' not in vp['advice'], vp['advice'])

    print('\n  4. not a first strike for the warn-then-interrupt rule')
    s.reset()
    s.check(goal=G, progress='advancing', distance=5)
    s.check(goal='write a poem about the sea', progress='advancing', distance=5)
    r = s.check(goal=G, progress='stuck', distance=5)
    show('a first self-report after goal-drift warns',
         r.get('reason') == 'self-report:stuck' and r.get('drifting') is False, r)
    s.reset()
    s.check(goal=G, progress='advancing', distance=5)
    s.check(goal='', progress='advancing', distance=5)          # ungrammatical: still a strike
    r = s.check(goal=G, progress='stuck', distance=5)
    show('...where after ungrammatical it still interrupts (the rule itself is unchanged)',
         r.get('reason') == 'self-report:stuck' and r.get('drifting') is True, r)

    print('\n  5. the second signal is the existing escalation, unchanged')
    # A FRESH server and home: the same ground re-opened after each reset_task above counts
    # as earlier sessions of one context, and control's `stop` on prior sessions would answer
    # first — a different rule, not the one being pinned here.
    s.close()
    s = Server()
    s.check(goal=G, progress='advancing', distance=5)
    for g in ('write a poem about the sea', 'paint the garden fence', 'cook a vegan dinner'):
        r = s.check(goal=g, progress='advancing', distance=5)
    show('three goal-drifts, none of them drifting',
         r.get('reason') == 'goal-drift' and r.get('drifting') is False, r)
    j = r.get('judgment') or {}
    show('judgment verdict is wrong-problem', j.get('verdict') == 'wrong-problem', j)
    show('control decision is reground', (j.get('control') or {}).get('decision') == 'reground', j)
    show('control still counts them as goal_drifts',
         ((j.get('control') or {}).get('reads') or {}).get('goal_drifts') == 3, j)

    print('\n  6. modulate answers return false')
    s.reset()
    s.call('modulate', {'goal': G, 'progress': 'advancing', 'distance': 6})
    m = s.call('modulate', {'goal': 'write a poem about the sea', 'progress': 'advancing', 'distance': 5})
    show('unstyled: reason goal-drift, return false',
         m.get('reason') == 'goal-drift' and (m.get('modulation') or {}).get('return') is False, m)
    m = s.call('modulate', {'goal': 'paint the garden fence', 'progress': 'advancing', 'distance': 5,
                            'team': 'deep-search', 'role': 'checker'})
    show('the tight checker role: return false', (m.get('modulation') or {}).get('return') is False, m)

    print('\n  7. the tool says so')
    tools = s.rpc('tools/list', {})['result']['tools']
    desc = next(t['description'] for t in tools if t['name'] == 'check_state')
    show('check_state description: a goal mismatch is goal-drift with drifting false',
         'goal-drift with drifting false' in desc and 'not an order' in desc, desc)

    print('\n  8. goal-drift notes can still be reviewed and labelled')
    # review_verdicts filtered on `drifting` before `reason`, so after the change it could
    # only ever show goal-drift rows written before it. Sections 5 and 6 wrote them
    # (modulate logs its readings too), so the count comes from the log itself.
    n = len(gd(s.rows(want=lambda rows: len(gd(rows)) >= 3)))
    rv = s.call('review_verdicts', {'reason': 'goal-drift', 'all': True})
    show('review_verdicts({reason: goal-drift}) lists the new notes',
         n >= 3 and rv.get('fires') == n and len(rv.get('showing') or []) == n, (n, rv))
    show('...and says they are notes, not interruptions',
         rv.get('notes') == n and all(x.get('drifting') is False for x in rv['showing']), rv)
    show('the default listing includes them too',
         (s.call('review_verdicts', {}).get('unlabelled_by_reason') or {}).get('goal-drift') == n)
    show('a clean reading is still not reviewable',
         s.call('review_verdicts', {'reason': 'grounded', 'all': True}).get('fires') == 0)
    one = rv['showing'][0]
    mv = s.call('mark_verdict', {'run': one['run'], 'step': one['step'], 'outcome': 'false',
                                 'why': 'test: a note on a new phase'})
    show('mark_verdict labels a goal-drift note', mv.get('recorded') is True
         and mv.get('reason') == 'goal-drift', mv)
    after = s.call('review_verdicts', {'reason': 'goal-drift'})
    show('...and it leaves the unlabelled list', after.get('unlabelled') == n - 1, after)
finally:
    s.close()

print('\n' + ('PASS — goal-drift is recorded and counted, and interrupts nothing on its own.'
              if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
