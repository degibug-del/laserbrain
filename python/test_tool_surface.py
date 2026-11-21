#!/usr/bin/env python3
"""What an agent is shown, and what it is told: the local server config (2026-11-19).

    python3 test_tool_surface.py

WHY. The stdio server listed all of its tools to every session, and an agent pays for every
definition in context on every turn: 32 tools, about 16,800 characters of definitions. Most
sessions call three of them. The check_state text asked for a check on EACH step, and the
first reply repeated it, so a large share of responses held a check and nothing else. And
two parts of every reply, the observed/observed_over contrast and the judgment block, read
machine-global evidence, so on a busy machine they quoted other sessions' work back.

<config dir>/server.json (lb_paths configDir, so LASERBRAIN_HOME moves it) now decides:
  tools     'core' or absent: check_state, reset_task, get_history (the default since
            0.58.0). 'all': every tool. A comma list of names ('core' and 'all' may be in
            it). Anything that names no known tool: the core.
  judgment  'off' leaves the contrast and the judgment out of check_state replies.
  policy    stamped on every drift-log row.
LASERBRAIN_TOOLS, LASERBRAIN_JUDGMENT and LASERBRAIN_POLICY override the file.

WITH NO FILE AN AGENT SEES THE CORE (0.58.0), and that is the first thing pinned: an outside
install has no server.json, so the default is what almost everyone gets. The full surface is
one setting away, and the parity gate (scripts/check-tool-parity.mjs) asks for it with
LASERBRAIN_TOOLS=all, so section 1 also pins that LASERBRAIN_TOOLS=all lists every tool.

This drives the real stdio server, isolated (LASERBRAIN_HOME in a temp dir, hub and API at a
dead port, LASERBRAIN_ARM=open), on the javascript/ source and on the copy the package ships.

THIS TEST CAN FAIL: return TOOLS unfiltered and the core checks go red (with no file too);
filter tools/call too
and the hidden-tool check goes red; drop the env override and LASERBRAIN_TOOLS=all goes red;
let judgment off still compute the contrast or the judgment and those go red; restore "each
step" in the first reply or the description and those go red.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'javascript' / 'mcp-server.mjs'
SHIPPED = ROOT / 'python' / 'laserbrain' / 'mcp-server.mjs'
CORE = ['check_state', 'reset_task', 'get_history']
# Inherited values must not decide the result; each case sets what it tests.
SCRUB = ('LASERBRAIN_TOOLS', 'LASERBRAIN_JUDGMENT', 'LASERBRAIN_POLICY', 'LASERBRAIN_DRIFT_LOG',
         'LASERBRAIN_HOME', 'LASERBRAIN_STATE_DIR', 'LASERBRAIN_OUTCOMES_LOG')

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail and not passed else ''))


class Server:
    def __init__(self, server=SOURCE, config=None, env=None, raw_config=None, evidence=None):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix='lb-surface-'))
        (self.home / 'config').mkdir()
        (self.home / 'sessions').mkdir()
        if config is not None:
            (self.home / 'config' / 'server.json').write_text(json.dumps(config))
        if raw_config is not None:
            (self.home / 'config' / 'server.json').write_text(raw_config)
        if evidence is not None:
            (self.home / 'config' / 'evidence.json').write_text(json.dumps(evidence))
        base = {k: v for k, v in os.environ.items() if k not in SCRUB}
        e = dict(base,
                 LASERBRAIN_HOME=str(self.home),
                 LASERBRAIN_STATE_DIR=str(self.home / 'sessions'),
                 LASERBRAIN_DRIFT_LOG=str(self.home / 'drift.jsonl'),
                 LASERBRAIN_HUB='http://127.0.0.1:9', LASERBRAIN_API='http://127.0.0.1:9',
                 LASERBRAIN_AGENT='tool-surface-test', LASERBRAIN_ARM='open', **(env or {}))
        self.p = subprocess.Popen(['node', str(server)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, env=e)
        self.n = 0
        self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                'clientInfo': {'name': 'surface', 'version': '1'}})

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n, 'method': method,
                                       'params': params}) + '\n')
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError(f'server closed stdout during {method}')
            m = json.loads(line)
            if m.get('id') == self.n:
                return m

    def names(self):
        return [t['name'] for t in self.rpc('tools/list', {})['result']['tools']]

    def tools(self):
        return self.rpc('tools/list', {})['result']['tools']

    def call_raw(self, name, args):
        return self.rpc('tools/call', {'name': name, 'arguments': args})

    def call(self, name, args):
        t = self.call_raw(name, args)['result']['content'][0]['text']
        try:
            return json.loads(t)
        except ValueError:
            return t

    def check(self, **a):
        return self.call('check_state', a)

    def rows(self, want=None, timeout=3.0):
        """The drift log. logDrift appends asynchronously: poll until `want(rows)` holds."""
        f = self.home / 'drift.jsonl'
        end = time.monotonic() + timeout
        while True:
            rows = [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
            if (want is None and rows) or (want is not None and want(rows)) or time.monotonic() > end:
                return rows
            time.sleep(0.05)

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.home, ignore_errors=True)


def listing(**kw):
    s = Server(**kw)
    try:
        return s.names()
    finally:
        s.close()


if not shutil.which('node'):
    print('  SKIP  node not found')
    raise SystemExit(77)

contract = json.loads((ROOT / 'json' / 'tools.json').read_text())
FULL = set(contract['universal']['tools']) | set(contract['local_only']['tools'])

print('\n  1. no server.json: the 3-tool core; LASERBRAIN_TOOLS=all: the full surface')
for label, path in (('javascript/', SOURCE), ('the shipped copy', SHIPPED)):
    got = listing(server=path)
    show(f'{label}: no file lists exactly check_state, reset_task, get_history', got == CORE, got)
    got = listing(server=path, env={'LASERBRAIN_TOOLS': 'all'})
    show(f'{label}: LASERBRAIN_TOOLS=all lists every tool in json/tools.json ({len(FULL)})',
         set(got) == FULL and len(got) == len(FULL), (len(got), sorted(set(got) ^ FULL)))
    got = listing(server=path, config={'tools': 'all'})
    show(f'{label}: server.json tools all lists every tool', set(got) == FULL and len(got) == len(FULL),
         len(got))
show('the package copy is byte-identical to javascript/',
     SOURCE.read_bytes() == SHIPPED.read_bytes(), 'cp javascript/mcp-server.mjs python/laserbrain/')

print('\n  2. tools: core, all, a list, a typo, a broken file')
for label, path in (('javascript/', SOURCE), ('the shipped copy', SHIPPED)):
    got = listing(server=path, config={'tools': 'core'})
    show(f'{label}: core lists exactly check_state, reset_task, get_history', got == CORE, got)
got = listing(config={'tools': 'core'}, env={'LASERBRAIN_TOOLS': 'all'})
show('LASERBRAIN_TOOLS=all overrides a core file', set(got) == FULL, len(got))
got = listing(env={'LASERBRAIN_TOOLS': 'core'})
show('LASERBRAIN_TOOLS=core works with no file at all', got == CORE, got)
got = listing(config={'tools': 'typo'})
show("'typo' falls back to the core, never an empty surface", got == CORE, got)
got = listing(config={'tools': ''})
show('an empty value is the core', got == CORE, got)
got = listing(env={'LASERBRAIN_TOOLS': '  '})
show('a blank LASERBRAIN_TOOLS is ignored (the core)', got == CORE, got)
got = listing(config={'tools': 'core'})
show("'core' is the core", got == CORE, got)
got = listing(config={'tools': 'check_state, drift_grammar'})
show('a comma list lists those names, in server order',
     got == ['check_state', 'drift_grammar'], got)
got = listing(config={'tools': 'core,drift_grammar'})
show("'core' inside a list expands", got == CORE + ['drift_grammar'], got)
got = listing(config={'tools': 'all'})
show("'all' is every tool", set(got) == FULL, len(got))
got = listing(config={'tools': 'drift_grammar,all'})
show("'all' inside a list is every tool", set(got) == FULL, len(got))
got = listing(config={'tools': ['check_state', 'drift_grammar']})
show('a JSON list of names works like a comma list', got == ['check_state', 'drift_grammar'], got)
got = listing(raw_config='{"tools": "all"')
show('an unreadable server.json reads as {} (the core)', got == CORE, got)
got = listing(raw_config='["all"]')
show('a server.json that is not an object reads as {} (the core)', got == CORE, got)

print('\n  3. a hidden tool still answers by name')
s = Server()
try:
    show('core is in effect (no file)', s.names() == CORE)
    r = s.call_raw('drift_grammar', {})
    txt = (r.get('result') or {}).get('content', [{}])[0].get('text', '')
    show('drift_grammar answers tools/call with core listed',
         'result' in r and not r['result'].get('isError') and len(txt) > 20, r)
finally:
    s.close()

print('\n  4. the text: when a task starts and when it changes, never "each step"')
s = Server()
try:
    cs = next(t for t in s.tools() if t['name'] == 'check_state')
    d = cs['description']
    show('description does not ask for every step', 'each step' not in d.lower(), d)
    show('description asks for one check, batched with other tool calls',
         'once' in d and 'same response' in d, d)
    show('description says when a task starts and when it changes, not every step',
         'when a task starts and when it changes' in d and 'not on every step' in d, d)
    show('description stays short (<= 600 chars)', len(d) <= 600, len(d))
    show('description keeps the goal-drift note', 'goal-drift with drifting false' in d
         and 'not an order' in d, d)
    show('the input schema still declares the progress enum',
         cs['inputSchema']['properties']['progress'].get('enum') == ['advancing', 'stuck', 'circling'])
    first = s.check(goal='index the sample corpus', progress='advancing', distance=6)
    a = first.get('advice') or ''
    show('first reply is grounded', first.get('reason') == 'grounded', first)
    show('first reply does not say "each step"', 'each step' not in json.dumps(first).lower(), a)
    show('first reply says further checks are only for a change', 'only if' in a, a)
finally:
    s.close()

print('\n  5. judgment off: no observed contrast, no judgment')
G = 'build the sample parser'
EVIDENCE = {'progress': 'stuck', 'steps': 4, 'ok': 0, 'fail': 0}


def drive(s):
    """A contrast on every step (evidence says stuck, the agent says advancing), then three
    goal changes, which is the recipe that attaches a wrong-problem judgment."""
    out = [s.check(goal=G, progress='advancing', distance=5)]
    for g in ('write a sample poem', 'paint a sample fence', 'cook a sample dinner'):
        out.append(s.check(goal=g, progress='advancing', distance=5))
    return out


s = Server(evidence=EVIDENCE)
try:
    on = drive(s)
    show('control: with judgment on, a reply carries observed',
         any('observed' in r for r in on), [sorted(r) for r in on])
    show('control: with judgment on, a reply carries judgment',
         any('judgment' in r for r in on), [sorted(r) for r in on])
finally:
    s.close()
for label, kw in (('server.json judgment off', {'config': {'judgment': 'off'}}),
                  ('LASERBRAIN_JUDGMENT=off', {'env': {'LASERBRAIN_JUDGMENT': 'off'}})):
    s = Server(evidence=EVIDENCE, **kw)
    try:
        off = drive(s)
        keys = set().union(*(set(r) for r in off))
        show(f'{label}: no reply carries observed or observed_over',
             not ({'observed', 'observed_over'} & keys), sorted(keys))
        show(f'{label}: no reply carries judgment', 'judgment' not in keys, sorted(keys))
        show(f'{label}: the readings themselves are unchanged',
             [r.get('reason') for r in off] == [r.get('reason') for r in on],
             ([r.get('reason') for r in off], [r.get('reason') for r in on]))
        rows = s.rows(want=lambda rs: len(rs) >= len(off))
        show(f'{label}: no judgment row is logged', not any(r.get('kind') == 'judgment' for r in rows),
             [r.get('kind') for r in rows])
    finally:
        s.close()

print('\n  6. policy: stamped on drift-log rows')
s = Server(config={'policy': 'test-policy-1'})
try:
    s.check(goal=G, progress='advancing', distance=5)
    rows = s.rows()
    show('a drift-log row carries the configured policy',
         bool(rows) and all(r.get('policy') == 'test-policy-1' for r in rows), rows)
finally:
    s.close()
s = Server(config={'policy': 'from-file'}, env={'LASERBRAIN_POLICY': 'from-env'})
try:
    s.check(goal=G, progress='advancing', distance=5)
    rows = s.rows()
    show('LASERBRAIN_POLICY overrides the file', bool(rows) and rows[-1].get('policy') == 'from-env', rows)
finally:
    s.close()
s = Server()
try:
    s.check(goal=G, progress='advancing', distance=5)
    rows = s.rows()
    show('with no policy, a row has no policy field', bool(rows) and 'policy' not in rows[-1], rows)
finally:
    s.close()
s = Server(config={'policy': 'test-policy-2'})
try:
    drive(s)
    rows = s.rows(want=lambda rs: any(r.get('kind') == 'judgment' for r in rs))
    j = [r for r in rows if r.get('kind') == 'judgment']
    show('a judgment row carries the policy too', bool(j) and all(r.get('policy') == 'test-policy-2' for r in j),
         j)
finally:
    s.close()

print('\n' + ('TOOL SURFACE HOLDS ✓' if ok else 'SOME FAILED ✗'))
raise SystemExit(0 if ok else 1)
