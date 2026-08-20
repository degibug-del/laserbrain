"""The shipped MCP server — offline, stdlib, and correct on the wire.

Until 0.25.0 `pip install laserbrain` gave a library and a CLI, and the only way to reach
the instrument over MCP was the hosted Worker. The stdio server the author actually uses
is a Node file on one machine. So the way laserbrain is used by the person who made it was
the one way a user could not use it.

WHAT EACH CASE GUARDS

  handshake     an MCP client that cannot initialize sees a broken server, not a broken
                tool. Wrong protocol string or missing serverInfo and nothing connects.
  silence       a NOTIFICATION must produce no response. Answering one desynchronises the
                stream against clients that match responses to ids by position.
  the ground    the whole product: the first check freezes a reference, a later unrelated
                goal reads as drift, and returning reads as advancing. If this passes but
                the verdicts are wrong, the server works and the instrument does not.
  stdout purity anything printed to stdout that is not JSON-RPC corrupts the session. This
                is why the check runs in a SUBPROCESS: an in-process test cannot catch a
                stray print from a module imported at the wrong moment.
  offline       the headline claim. Sockets are disabled outright, and the server must
                still answer — otherwise 'free, local, no account' is marketing.
  survival      a tool that raises must return isError, not kill the session. An MCP
                server that dies on one bad call takes the agent's whole conversation.
"""
import json
import subprocess
import sys

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def run(msgs, code=None):
    """Drive the server as a real client would: a subprocess, over pipes."""
    inp = '\n'.join(json.dumps(m) for m in msgs) + '\n'
    argv = [sys.executable, '-c', code] if code else [sys.executable, '-m', 'laserbrain.cli', 'mcp']
    r = subprocess.run(argv, input=inp, capture_output=True, text=True, timeout=90)
    out = []
    for line in r.stdout.splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out, r


def call(name, args, mid):
    return {'jsonrpc': '2.0', 'id': mid, 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}


INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                   'clientInfo': {'name': 'test', 'version': '1'}}}
NOTE = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}

# ── handshake, and the notification that must stay silent ────────────────────────────
out, r = run([INIT, NOTE, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}])
check('initialize returns serverInfo', out and out[0]['result']['serverInfo']['name'] == 'laserbrain')
check('protocol version is declared', out[0]['result']['protocolVersion'] == '2024-11-05')
check('a notification produces NO response', len(out) == 2, f'{len(out)} responses for 2 requests')
names = [t['name'] for t in out[1]['result']['tools']]
check('tools are listed with schemas',
      'check_state' in names and all('inputSchema' in t for t in out[1]['result']['tools']),
      f'{len(names)} tools')

# ── the instrument itself, over the wire ─────────────────────────────────────────────
out, r = run([INIT,
              call('check_state', {'goal': 'build the JSON parser', 'progress': 'advancing', 'distance': 6}, 2),
              call('check_state', {'goal': 'also add caching and logging', 'progress': 'advancing', 'distance': 4}, 3),
              call('check_state', {'goal': 'build the JSON parser', 'progress': 'advancing', 'distance': 1}, 4),
              call('get_history', {}, 5)])
v = [json.loads(o['result']['content'][0]['text']) for o in out[1:4]]
check('first check freezes the ground', v[0]['reason'] == 'grounded', v[0]['reason'])
check('an unrelated goal reads as drift', v[1]['drifting'] and v[1]['reason'] == 'goal-drift',
      f"{v[1]['reason']} phi={v[1]['phi']}")
check('returning to the ground clears it', not v[2]['drifting'], v[2]['reason'])
h = json.loads(out[4]['result']['content'][0]['text'])
check('history records the run', h['total'] == 3 and h['drifting'] == 1, str(h['total']))

# ── reset must clear the ground, or a new task is measured against an old one ────────
out, _ = run([INIT,
              call('check_state', {'goal': 'write the docs', 'progress': 'advancing', 'distance': 5}, 2),
              call('reset_task', {}, 3),
              call('check_state', {'goal': 'ship the release', 'progress': 'advancing', 'distance': 5}, 4)])
after = json.loads(out[3]['result']['content'][0]['text'])
check('after reset the next check is a NEW ground', after['reason'] == 'grounded', after['reason'])

# ── the store, over the wire — the same gap this whole file exists to close, one layer
# up: Store shipped in 0.29.0 with no MCP tool, so the most common way an agent reaches
# this package still could not discover a single prefabricated workflow or team preset ──
out, _ = run([INIT,
              call('store_list', {}, 2),
              call('store_list', {'kind': 'team'}, 3),
              call('store_find', {'task': 'debate toward a resolved answer', 'kind': 'team'}, 4),
              call('store_vend', {'name': 'build-and-ship'}, 5),
              call('store_vend', {'name': 'deep-search', 'kind': 'team'}, 6),
              call('store_vend', {'name': 'not-a-real-name'}, 7)])
wf = json.loads(out[1]['result']['content'][0]['text'])
check('store_list defaults to workflows and includes a shipped one',
      'build-and-ship' in wf['names'], wf['names'])
tm = json.loads(out[2]['result']['content'][0]['text'])
check('store_list(kind=team) lists the three presets',
      tm['names'] == ['adversarial-deliberation', 'deep-search', 'iterative-refinement'])
found = json.loads(out[3]['result']['content'][0]['text'])
check('store_find(kind=team) matches on task, not name',
      found['matches'] and found['matches'][0]['name'] == 'adversarial-deliberation',
      found['matches'])
spec = json.loads(out[4]['result']['content'][0]['text'])
check('store_vend returns an unbound workflow spec',
      spec['kind'] == 'workflow' and bool(spec['spec']['steps']), spec)
tspec = json.loads(out[5]['result']['content'][0]['text'])
check('store_vend(kind=team) returns roles, not steps',
      tspec['kind'] == 'team' and tspec['spec']['roles'][0]['role'] == 'explorer', tspec)
err = json.loads(out[6]['result']['content'][0]['text'])
check('an unknown name is a clean error, not a dead call', 'error' in err, err)

# ── stdout carries JSON-RPC and nothing else ─────────────────────────────────────────
_, r = run([INIT, call('capabilities', {}, 2)])
bad = [l for l in r.stdout.splitlines() if l.strip() and not l.lstrip().startswith('{')]
check('stdout is pure JSON-RPC', not bad, str(bad[:1]))
check('stderr is not used for protocol', 'jsonrpc' not in r.stderr)

# ── a raising tool must not take the session down ────────────────────────────────────
out, _ = run([INIT, call('check_state', {}, 2), call('capabilities', {}, 3)])
check('a bad call returns an error, not a dead server', len(out) == 3, f'{len(out)} responses')

# ── THE claim: it works with the network unplugged ───────────────────────────────────
OFFLINE = (
    'import socket, urllib.request\n'
    'def blocked(*a, **k): raise AssertionError("NETWORK")\n'
    'urllib.request.urlopen = blocked\n'
    'socket.socket = blocked\n'
    'from laserbrain.mcp import serve\n'
    'serve()\n')
out, r = run([INIT,
              call('check_state', {'goal': 'run with no network', 'progress': 'advancing', 'distance': 3}, 2)],
             code=OFFLINE)
check('serves with sockets disabled', len(out) == 2 and 'result' in out[1],
      r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '')
if len(out) == 2:
    off = json.loads(out[1]['result']['content'][0]['text'])
    check('and the verdict is real, not a stub', off['reason'] == 'grounded', off['reason'])

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — laserbrain serves MCP from the pip package, offline, with no account.')
