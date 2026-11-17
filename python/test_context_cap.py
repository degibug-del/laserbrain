"""contexts.json stays small: the contexts seen most recently are kept, the rest archived.

WHY. Every check reads the whole store and writes it back, so its size is paid on every check.
On 2026-11-16 the live store held 6,265 contexts (5.4 MB): ~23 ms of a check that takes ~0.25 ms
on an empty store, which is what kept test_mirror.py red since September. The store now keeps
CONTEXTS_MAX (1,000) contexts by last_seen and appends the rest to contexts-archive.jsonl.

Pins, in a private LASERBRAIN_HOME (nothing reaches the live store):
  1. under the cap nothing moves and no archive is written;
  2. over the cap the oldest by last_seen go, whole, to the archive, and the one being written
     stays even when its own last_seen was the oldest;
  3. Python ('+00:00') and JS ('.123Z') timestamps sort as one clock;
  4. the stdio server (the one that runs live) keeps exactly the same contexts as Python;
  5. if the archive cannot be written nothing is dropped;
  6. a full store stays at the cap as new contexts arrive.

THIS TEST CAN FAIL: drop the _cap_contexts call, or capContexts in mcp-server.mjs, or sort
newest-first, and it goes red.

Run:  python3 test_context_cap.py
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

HOME = tempfile.mkdtemp(prefix='lb-ctxcap-')
os.environ['LASERBRAIN_HOME'] = HOME
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laserbrain as lb  # noqa: E402

CAP = lb.CONTEXTS_MAX
ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and bool(passed)
    print(f"  {'ok  ' if passed else 'FAIL'}  {name}" + (f'   {detail}' if detail and not passed else ''))


def entry(i, js=False):
    # 2026-01-01 plus i minutes; every fifth one written in the JS format
    t = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(1767225600 + 60 * i))
    stamp = t + ('.123Z' if js else '+00:00')
    return {'id': f'ctx_{i:05d}', 'tokens': ['a', 'b'], 'first_seen': stamp, 'last_seen': stamp,
            'sessions': ['r'], 'session_count': 1, 'checks': 1, 'best_distance': 5,
            'outcomes': {'advancing': 1}, 'spellings': {f's{i}': 1}}


def seed(n, home=None):
    cfg = pathlib.Path(home or HOME) / 'config'
    cfg.mkdir(parents=True, exist_ok=True)
    m = {f'ctx_{i:05d}': entry(i, js=(i % 5 == 0)) for i in range(n)}
    (cfg / 'contexts.json').write_text(json.dumps(m))
    arc = cfg / 'contexts-archive.jsonl'
    if arc.exists():
        if arc.is_dir():
            shutil.rmtree(arc)
        else:
            arc.unlink()
    return m


def store(home=None):
    return json.loads((pathlib.Path(home or HOME) / 'config' / 'contexts.json').read_text())


def archive(home=None):
    f = pathlib.Path(home or HOME) / 'config' / 'contexts-archive.jsonl'
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.is_file() else []


# 1. under the cap
seed(CAP - 10)
lb.remember_context('ctx_new', 'alpha beta', 3, 'advancing')
show('under the cap nothing moves', len(store()) == CAP - 9, len(store()))
show('  and no archive is written', archive() == [], len(archive()))

# 2. over the cap: the oldest go, whole
m = seed(CAP + 200)
lb.remember_context('ctx_new', 'alpha beta', 3, 'advancing')
s = store()
arc = archive()
show('the store is held at the cap', len(s) == CAP, len(s))
show('  the rest are archived', len(arc) == 201, len(arc))
show('  oldest first', [a['id'] for a in arc] == [f'ctx_{i:05d}' for i in range(201)], [a['id'] for a in arc[:3]])
show('  whole, not trimmed', all(a['context'] == m[a['id']] for a in arc))
show('  the context just written stays', 'ctx_new' in s)
show('  and the newest seeded ones stay', all(f'ctx_{i:05d}' in s for i in range(201, CAP + 200)))

# the one being written was the oldest of all: it is fresh now, so it stays
m = seed(CAP + 5)
lb.remember_context('ctx_00000', 'alpha beta', 3, 'advancing')
s = store()
show('re-seeing the oldest context refreshes it instead of evicting it',
     'ctx_00000' in s and s['ctx_00000']['checks'] == 2 and 'ctx_00001' not in s, len(s))

# 3. one clock: a JS stamp at the same second as a Python one sorts by id, not by format
k1 = lb._seen_key(('a', {'last_seen': '2026-01-01T00:00:00.999Z'}))
k2 = lb._seen_key(('b', {'last_seen': '2026-01-01T00:00:00+00:00'}))
k3 = lb._seen_key(('c', {'last_seen': '2026-01-01T00:00:01+00:00'}))
show('Python and JS timestamps sort as one clock', k1 < k2 < k3, (k1, k2, k3))

# 4. the stdio server keeps the same contexts as Python
if shutil.which('node'):
    py_kept = None
    m = seed(CAP + 50)
    lb.remember_context('ctx_zz_same', 'alpha beta', 3, 'advancing')
    py_kept = set(store()) - {'ctx_zz_same'}
    jhome = tempfile.mkdtemp(prefix='lb-ctxcap-js-')
    seed(CAP + 50, jhome)
    env = dict(os.environ, LASERBRAIN_HOME=jhome, LASERBRAIN_DRIFT_LOG=str(pathlib.Path(jhome) / 'drift.jsonl'),
               LASERBRAIN_HUB='http://127.0.0.1:9', LASERBRAIN_API='http://127.0.0.1:9',
               LASERBRAIN_AGENT='context-cap-test', LASERBRAIN_ARM='open')
    p = subprocess.Popen(['node', str(HERE / 'laserbrain' / 'mcp-server.mjs')], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)

    def rpc(i, method, params):
        p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n')
        p.stdin.flush()
        while True:
            r = json.loads(p.stdout.readline())
            if r.get('id') == i:
                return r

    try:
        rpc(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                              'clientInfo': {'name': 'ctxcap', 'version': '1'}})
        rpc(2, 'tools/call', {'name': 'check_state', 'arguments': {
            'goal': 'write the context cap test', 'progress': 'advancing', 'distance': 3}})
    finally:
        p.terminate()
        p.wait(timeout=5)
    js = store(jhome)
    js_new = set(js) - set(m)
    js_kept = set(js) - js_new
    show('the stdio server holds the store at the cap', len(js) == CAP, len(js))
    show('  and keeps exactly the contexts Python keeps', js_kept == py_kept,
         f'{len(js_kept ^ py_kept)} differ')
    show('  and archives the same ones', sorted(a['id'] for a in archive(jhome)) == sorted(set(m) - py_kept),
         len(archive(jhome)))
    shutil.rmtree(jhome, ignore_errors=True)
else:
    print('  SKIP  node not found: the server half was not run')

# 5. an archive that cannot be written drops nothing
seed(CAP + 20)
(pathlib.Path(HOME) / 'config' / 'contexts-archive.jsonl').mkdir()
lb.remember_context('ctx_new', 'alpha beta', 3, 'advancing')
show('if the archive cannot be written, nothing is dropped', len(store()) == CAP + 21, len(store()))
shutil.rmtree(pathlib.Path(HOME) / 'config' / 'contexts-archive.jsonl')

# 6. bounded under a stream of new contexts, and what a check costs at the cap
seed(CAP)
t = time.perf_counter()
for i in range(50):
    lb.remember_context(f'ctx_stream_{i}', 'alpha beta', 3, 'advancing', score=f's{i}')
per = (time.perf_counter() - t) / 50
show('a full store stays at the cap as new contexts arrive', len(store()) == CAP, len(store()))
print(f'        ({per * 1e3:.1f} ms per write at the cap, synthetic entries)')

shutil.rmtree(HOME, ignore_errors=True)
print()
print('  PASS' if ok else '  FAIL')
sys.exit(0 if ok else 1)
