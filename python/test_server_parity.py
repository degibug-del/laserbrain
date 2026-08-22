#!/usr/bin/env python3
"""The two servers must not be different products.

`laserbrain mcp` served 11 tools while mcp-server.mjs served 28 — not because the Python
SDK lacked the capability, but because eight operations lived in javascript/sdk_bridge.py,
reachable only by the JS server shelling out to Python. The capability was in the package
the whole time; the door was not. They live in laserbrain._ops now and both servers call
the same function.

Six tools are still JS-only and always will be: ask_alice, analyze_language,
compare_phrasings, remember_self, resume_self and forget_self reach a hosted service.
Verified by blocking sockets and calling them — six connection attempts to
laserbrain-mcp.degibug.workers.dev:443. The offline server refuses them on purpose and
`not_here` says where they live. This suite asserts that boundary rather than measuring
against 28, so a future attempt to "close the gap" by serving them fails here first.
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile

os.environ.setdefault('LASERBRAIN_HOME', tempfile.mkdtemp(prefix='lb-parity-'))

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def _serve(cmd, calls, env=None):
    msgs = ['{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":'
            '"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}']
    for i, (n, a) in enumerate(calls, 1):
        msgs.append(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                                'params': {'name': n, 'arguments': a}}))
    msgs.append('{"jsonrpc":"2.0","id":99,"method":"tools/list"}')
    r = subprocess.run(cmd, input='\n'.join(msgs) + '\n', capture_output=True, text=True,
                       timeout=180, env={**os.environ, **(env or {}),
                                         'LASERBRAIN_HOME': tempfile.mkdtemp()})
    out = {}
    for line in r.stdout.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and d.get('id') is not None:
            out[d['id']] = d
    return out


HOSTED = {'ask_alice', 'analyze_language', 'compare_phrasings',
          'remember_self', 'resume_self', 'forget_self'}

PY_CMD = [sys.executable, '-m', 'laserbrain.cli', 'mcp']
res = _serve(PY_CMD, [])
served = {t['name'] for t in res.get(99, {}).get('result', {}).get('tools', [])}

show('the offline server serves a real surface, not a stub', len(served) >= 20,
     f'{len(served)} tools')
show('and it serves the shared ops', {'explore', 'supercode', 'trailscore', 'find_bugs',
                                      'write_grounded'} <= served,
     'these were reachable only through the JS bridge before')
show('and phronesis and attention', {'phronesis', 'attention'} <= served)

# THE BOUNDARY. Not a gap to be closed — the property that makes this server worth having.
show('it serves NO tool that reaches a hosted service', not (served & HOSTED),
     f'leaked: {sorted(served & HOSTED)}' if served & HOSTED else 'the six stay out')

caps = res.get(99) and _serve(PY_CMD, [('capabilities', {})])
_cap = caps.get(1, {}).get('result', {}).get('content', [{}])[0].get('text', '{}')
try:
    _not_here = set(json.loads(_cap).get('not_here', {}).get('tools', []))
except Exception:
    _not_here = set()
show('and it names them, rather than staying silent', HOSTED <= _not_here,
     f'not_here lists {len(_not_here)}')

# ONE IMPLEMENTATION. Both doors must import the ops, not hold copies.
from laserbrain import _ops                                        # noqa: E402
# NOT A COUNT. The first version asserted len(OPS) == 8 and broke the moment four more were
# added — a test that fails on correct work teaches people to edit the test. The invariant
# is that the two servers agree on WHICH ops are bridged, which is what actually goes wrong.
_mjs_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'javascript', 'mcp-server.mjs')).read()
_b = _mjs_src[_mjs_src.index('BRIDGED = new Set('):]
_b = _b[:_b.index(')')]
_bridged = set(re.findall(r"'([a-z_]+)'", _b))
show('the shared ops live in the package', bool(_ops.OPS), f'{len(_ops.OPS)} ops')
show('  and the JS server bridges exactly them', _bridged == set(_ops.OPS),
     f'only in .mjs: {sorted(_bridged - set(_ops.OPS))}; '
     f'only in registry: {sorted(set(_ops.OPS) - _bridged)}')
_bridge = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'javascript', 'sdk_bridge.py')).read()
show('  and the bridge imports them rather than redefining them',
     'from laserbrain._ops import OPS' in _bridge and '\ndef op_' not in _bridge,
     'a second copy is the bug this file exists against')

# parent_goal must reach the engine — it did not, and excursion was unreachable here.
G = 'reconcile the March statement against the ledger'
r2 = _serve(PY_CMD, [(('check_state'), {'goal': G, 'progress': 'advancing', 'distance': 8}),
                     ('check_state', {'goal': 'check which statement lines have no matching '
                                              'ledger entry', 'progress': 'advancing',
                                      'distance': 4, 'parent_goal': G})])
_v = json.loads(r2.get(2, {}).get('result', {}).get('content', [{}])[0].get('text', '{}'))
show('check_state carries parent_goal, so excursion is reachable',
     _v.get('reason') == 'excursion', str(_v.get('reason')))

# and every op the server declares must actually answer when called with its own schema keys
_probe = [('trailscore', {'goals': ['a b', 'a c']}), ('explore', {'trail': ['a b', 'a c']}),
          ('find_bugs', {'events': []}), ('supercode', {'goal': 'x'}),
          ('attention', {'since_seconds': 900}), ('link_whoami', {})]
r3 = _serve(PY_CMD, _probe)
bad = []
for i, (n, _) in enumerate(_probe, 1):
    txt = r3.get(i, {}).get('result', {}).get('content', [{}])[0].get('text', '')
    if '"error"' in txt or not txt:
        bad.append(n)
show('every declared tool answers its OWN schema keys', not bad,
     f'refused: {bad}' if bad else 'a door that opens onto a wall is not a door')

# ── the shipped copies match their source ─────────────────────────────────────
# javascript/ is the source; the package ships copies so a pip install can run the richer
# server without a checkout. Copies that must agree with nothing enforcing it is the exact
# failure this package has hit repeatedly — grammar.json, attention.json, the hook copies.
import hashlib                                                     # noqa: E402
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pkg = os.path.join(_root, 'python', 'laserbrain')
for _f in ('mcp-server.mjs', 'lb_paths.mjs', 'sdk_bridge.py'):
    _a = os.path.join(_root, 'javascript', _f)
    _b = os.path.join(_pkg, _f)
    if not os.path.exists(_b):
        show(f'{_f} ships in the package', False, 'absent — a pip user cannot run the server')
        continue
    _h = lambda q: hashlib.sha256(open(q, 'rb').read()).hexdigest()[:12]
    show(f'{_f} matches javascript/', _h(_a) == _h(_b), f'{_h(_a)} vs {_h(_b)}')

# ── one drift-vectors, not several ────────────────────────────────────────────
# json/drift-vectors.json is what both parity suites read. A second copy existed at
# python/drift-vectors.json with 6 vectors against its 16, read by nothing — the third time
# this repo has grown a duplicate vector file, and grammar.ts:235 records the first two:
# "two drift-vectors.json files disagreeing 15 vs 9, one of them read by nothing".
_vec = [os.path.join(_root, p) for p in
        ('json/drift-vectors.json', 'python/drift-vectors.json',
         'typescript/test/drift-vectors.json')]
_present = [v for v in _vec if os.path.exists(v)]
_hashes = {hashlib.sha256(open(v, 'rb').read()).hexdigest()[:12] for v in _present}
show('every drift-vectors copy that exists agrees', len(_hashes) <= 1,
     ' '.join(f'{os.path.relpath(v, _root)}={hashlib.sha256(open(v,"rb").read()).hexdigest()[:12]}'
              for v in _present))

print('\n' + ('SERVER PARITY HOLDS ✓' if ok else 'SOME FAILED ✗'))
raise SystemExit(0 if ok else 1)
