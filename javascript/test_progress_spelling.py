#!/usr/bin/env python3
"""progress is ONE word, and the server now says so: a note is told where it goes, never read as on track.

    python3 test_progress_spelling.py

WHY. On 2026-10-25 every Claude check_state came back `ungrammatical` for an evening, goal
after goal, including straight after reset_task. The goals were fine. Every failing call had
put a progress note in `progress` ("Backend /api/send route done, Send sheet UI added; now
verifying endpoint"), because the schema declared a bare string and the hook nudges asked
for "goal, progress and distance". The verdict named no slot, so the agent retried the same
shape, and because the ungrammatical return precedes the reground the ground stayed on a
task from hours earlier. 13 of the 19 ungrammatical rows in the corpus (as of 2026-10-25) are such notes.

This drives the real stdio server, isolated (LASERBRAIN_HOME in a temp dir, hub pointed at
a dead port, LASERBRAIN_ARM=open), and pins the fix:
  - the contract declares the enum and documents `doing` for the note
  - the four observed calls are still ungrammatical (a sentence is not a word) but now say WHICH
    slot failed and where the note goes; with the word in `progress` and the note in `doing`
    they ground
  - notes that report trouble ("going nowhere", "blocked", "advancing - but stuck ...") are never
    read as on track (the first draft of this fix did that; a skeptic caught it)
  - spelling is forgiven: 'Advancing', ' stuck ', 'advancing.'
  - the detector is not neutered: self-report and stalled still fire, and goal-drift is still
    recorded (as a note with drifting False since 2026-11-15).

THIS TEST CAN FAIL: drop the enum, the `why`, or the case spelling and it goes red; make
spellProgress read notes as 'advancing' and the trouble-note checks go red.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / 'mcp-server.mjs'

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail and not passed else ''))


class Server:
    def __init__(self):
        self.home = tempfile.mkdtemp(prefix='lb-spell-')
        env = dict(os.environ,
                   LASERBRAIN_HOME=self.home,
                   LASERBRAIN_DRIFT_LOG=str(pathlib.Path(self.home) / 'drift.jsonl'),
                   LASERBRAIN_HUB='http://127.0.0.1:9', LASERBRAIN_API='http://127.0.0.1:9',
                   LASERBRAIN_AGENT='spelling-test', LASERBRAIN_ARM='open',
                   # modulate's schema is read from tools/list, and since 0.58.0 the
                   # default listing is the 3-tool core; ask for the full surface.
                   LASERBRAIN_TOOLS='all')
        self.p = subprocess.Popen(['node', str(SERVER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, env=env)
        self.n = 0
        self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                'clientInfo': {'name': 'spell', 'version': '1'}})
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        self.p.stdin.flush()

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
            return t          # reset_task answers in prose

    def check(self, **a):
        return self.call('check_state', a)

    def reset(self):
        self.call('reset_task', {})

    def user_turn(self):
        d = pathlib.Path(self.home) / 'config'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'user-turn').write_text('1')

    def rows(self):
        f = pathlib.Path(self.home) / 'drift.jsonl'
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []

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

# Four calls with the shape of those observed on 2026-10-25; the project details are invented.
OBSERVED = {
    'A': ("Do the report items: get tonight's export rendered and auto-clean raw uploads once their renders are done",
          'Cleanup built and wired into the watcher, two cropped exports re-rendered and sent back; left: tests, an independent review, then report', 3),
    'B': ('Show the user what is filling the build server disk and help delete large things safely (to an archive, with confirmation)',
          'Measured the build volume: cached images, old artifacts, logs, the package mirror, and temp folders identified; drilling the last few before listing', 3),
    'C': ('Finish the invoice app Send button so the user can send an invoice with a saved template from the app',
          'Backend send_invoice and /api/send route done, Send sheet UI added and server restarted; now verifying endpoint, then reporting', 2),
    'D': ("Answer the user: how the importer knows an upload finished, and make sure tonight's batch gets imported",
          "Watcher detected end at 00:08 and is fetching; checking it pulls the right batch and that the 17:54 batch that failed on 'thumbnail' gets reprocessed", 5),
}
OLD_GOAL = 'Build a logo design deck in the invoice app that refines the brand from user swipes'
G = 'Finish the invoice app Send button so the user can send an invoice'

s = Server()
try:
    print('the contract')
    tools = {t['name']: t for t in s.rpc('tools/list', {})['result']['tools']}
    for name in ('check_state', 'modulate'):
        enum = tools[name]['inputSchema']['properties']['progress'].get('enum')
        show(f'{name} declares progress as an enum, as python/laserbrain/mcp.py does',
             enum == ['advancing', 'stuck', 'circling'], repr(enum))
    show('check_state documents `doing` as the place for a note',
         'note' in tools['check_state']['inputSchema']['properties']['doing'].get('description', ''))

    print('the observed calls are told which slot, not read as on track')
    for k, (goal, note, d) in OBSERVED.items():
        s.reset()
        v = s.check(goal=goal, progress=note, distance=d)
        show(f'{k}: a note in progress is still ungrammatical', v['reason'] == 'ungrammatical'
             and v['drifting'] is True and v['laserscore'] is None, v)
        show(f'{k}: and the verdict names the slot and where the note goes',
             'not one of' in (v.get('why') or '') and '`doing`' in v['advice'], (v.get('why'), v['advice']))
        s.reset()
        v = s.check(goal=goal, progress='advancing', doing=note, distance=d)
        show(f'{k}: the word in progress and the note in doing grounds', v['reason'] == 'grounded'
             and v['drifting'] is False and v['laserscore'] and 'spelled' not in v, v)

    print('spelling is forgiven, sentences are not')
    for raw in ('Advancing', '  advancing ', 'advancing.', 'ADVANCING!'):
        s.reset()
        v = s.check(goal=G, progress=raw, distance=4)
        show(f'{raw!r} reads as advancing and says so', v['reason'] == 'grounded'
             and (v.get('spelled') or {}).get('from') == 'case', v)
    s.reset()
    s.check(goal=G, progress='advancing', distance=6)
    for note in ('going nowhere, the same error again and again',
                 'blocked: cannot continue without the API key',
                 'not advancing at all, no progress for an hour',
                 'advancing - but stuck on the same failing test, going in circles',
                 'Send route done; now wiring the sheet UI'):
        v = s.check(goal=G, progress=note, distance=5)
        show(f'{note[:40]!r}... is never "On track"', v['reason'] == 'ungrammatical'
             and v['drifting'] is True and 'On track' not in v['advice'], v)
    s.reset()
    v = s.check(goal=OBSERVED['C'][0], progress='advancing', distance=2)
    show('the exact word is untouched and carries no `spelled`', v['reason'] == 'grounded'
         and 'spelled' not in v, v)

    print('garbage is still ungrammatical, and now says which slot')
    for label, args in [
        ('empty goal', dict(goal='', progress='advancing', distance=3)),
        ('blank goal', dict(goal='   ', progress='advancing', distance=3)),
        ('missing progress', dict(goal='Ship the parser', distance=3)),
        ('empty progress', dict(goal='Ship the parser', progress='', distance=3)),
        ("'sideways' (drift-vectors.json seq 6)", dict(goal='fix the gate', progress='sideways', distance=3)),
        ("'starting' (the corpus row)", dict(goal='Ship the parser', progress='starting', distance=3)),
        ("'progressing'", dict(goal='Ship the parser', progress='progressing', distance=3)),
        ('keyboard mash', dict(goal='Ship the parser', progress='asdf qwer zxcv uiop', distance=3)),
        ("'the the the the'", dict(goal='Ship the parser', progress='the the the the', distance=3)),
        ("'lol idk'", dict(goal='Ship the parser', progress='lol idk', distance=3)),
        ('a number', dict(goal='Ship the parser', progress=42, distance=3)),
    ]:
        s.reset()
        v = s.check(**args)
        show(f'{label}: ungrammatical, drifting, no score', v['reason'] == 'ungrammatical'
             and v['drifting'] is True and v['laserscore'] is None, v)
        show(f'{label}: names the failing slot', bool(v.get('why')) and
             (('goal' in v['why']) if not str(args.get('goal', '')).strip() else ('progress' in v['why'] or 'not one of' in v['why'])),
             v.get('why'))
    for note, word in [('No idea, I am stuck on the lexer', 'stuck'),
                       ('Tried the same fix again and I keep going in circles', 'circles')]:
        s.reset()
        v = s.check(goal='Ship the parser', progress=note, distance=3)
        show(f'a note that says "{word}" points at the word', v['reason'] == 'ungrammatical'
             and word in (v.get('why') or ''), v)

    print('the detector still fires with the note in doing')
    s.reset()
    s.check(goal=G, progress='advancing', distance=6)
    v = s.check(goal=G, progress='advancing', doing='Send route done; now wiring the sheet UI', distance=5)
    show('an on-task step after ground reads advancing', v['reason'] == 'advancing'
         and not v['drifting'], v)
    v = s.check(goal='Refactor the chart renderer shaders for speed', progress='advancing',
                doing='Profiled the shaders and rewrote the blur pass for the renderer', distance=5)
    show('a different goal with no user turn is still goal-drift, as a note (drifting False)',
         v['reason'] == 'goal-drift' and v['drifting'] is False, v)

    s.reset()
    s.check(goal=G, progress='advancing', distance=6)
    a = s.check(goal=G + ' and a whole new sharing flow', progress='circling', doing='rewrote the share sheet again', distance=6)
    b = s.check(goal=G + ' and a whole new sharing flow', progress='Circling', doing='same share sheet bug as before', distance=6)
    show('"circling" is the self-report it says', a['reason'] == 'self-report:circling', a)
    show('and the two-strike rule still interrupts', b['reason'] == 'self-report:circling'
         and b['drifting'] is True, b)

    s.reset()
    s.check(goal=G, progress='advancing', distance=5)
    seen = [s.check(goal=G, progress='advancing', doing='Still checking the endpoint again with the same request', distance=5)
            for _ in range(6)]
    reasons = [v['reason'] for v in seen]
    show('a flat distance still reads stalled', 'stalled' in reasons, reasons)
    show('and escalates to drifting', any(v['reason'] == 'stalled' and v['drifting'] for v in seen), reasons)

    rows = s.rows()
finally:
    s.close()

# A FRESH PROCESS for the re-anchor checks. reset_task on the shared lane SUSPENDS a ground
# rather than deleting it, and a later check whose goal matches a suspended one resumes it —
# so reusing the goals above in the same process would test resumeShared, not the reground.
s2 = Server()
try:
    print('the ground re-anchors')
    s2.check(goal=OLD_GOAL, progress='advancing', distance=8)
    s2.user_turn()
    v = s2.check(goal=OBSERVED['C'][0], progress='advancing', doing=OBSERVED['C'][1], distance=2)
    show('a new ask after the user spoke regrounds',
         v['reason'] == 'reground' and v['ground'] == OBSERVED['C'][0], v)
    v = s2.check(goal=OBSERVED['D'][0], progress='wip', distance=5)
    show('an ungrammatical call whose goal left the ground points at reset_task',
         v['reason'] == 'ungrammatical' and 'reset_task' in v['advice'], v.get('advice'))
    v = s2.check(goal=OBSERVED['C'][0], progress='wip', distance=2)
    show('and does not when the goal is the ground', v['reason'] == 'ungrammatical'
         and 'reset_task' not in v['advice'], v.get('advice'))
finally:
    s2.close()

print('the corpus can count it')
cased = [r for r in rows if r.get('spelled') == 'case']
show('respelled rows carry spelled + the raw value', bool(cased) and all(
    r['progress'] in ('advancing', 'stuck', 'circling') and r.get('progress_raw') for r in cased), cased[:1])
show('no row was ever read from a note', not any(r.get('spelled') == 'note' for r in rows))
show('ungrammatical rows carry why', all(r.get('why') for r in rows
                                         if r.get('reason') == 'ungrammatical'))
show('spelled and progress_raw appear together or not at all',
     all(('spelled' in r) == ('progress_raw' in r) for r in rows))
show('an exact word is never marked translated',
     not any(r.get('spelled') and r.get('progress_raw') in ('advancing', 'stuck', 'circling') for r in rows))

print('\nPASS — the contract is clear, a note is told where it goes, and the detector still fires.' if ok else '\nFAIL')
raise SystemExit(0 if ok else 1)
