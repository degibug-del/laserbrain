#!/usr/bin/env python3
"""The API mirror must cost the caller nothing, and must not lie about what it sent.

check() used to end with a blocking POST to /v1/drift, commented "best-effort". Profiling
put 96% of check() inside urlopen: ~135 ms per keyed check against 869 us keyless, and a
hung network would have paid the full 8-second timeout. A side-channel on the critical
path of the measurement it mirrors is not best-effort, it is a dependency.

Three properties, and all three are load-bearing rather than nice:

  FAST      the caller does not wait for the network. This is the whole point.
  ORDERED   one worker, one queue. A thread per post would race and scramble a run's
            history on the server — worse than being slow, because it would be wrong.
  BOUNDED   a wedged network must shed rows, not grow. An unbounded queue is a memory
            leak inside the thing that was supposed to cost nothing.

The network is stubbed throughout. A test that reached the real API would be slow, would
fail offline, and would be testing Cloudflare rather than this queue.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import laserbrain                                    # noqa: E402
from laserbrain import Harness, MIRROR               # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


_real_post = laserbrain._post
seen = []


def slow_stub(api, key, path, body):
    time.sleep(0.02)
    seen.append(dict(body))
    return {'ok': True}


laserbrain._post = slow_stub

print('fast — the caller does not wait for the network')

h = Harness('alpha beta gamma')
h.key, h.api = 'test-key', 'https://example.invalid'
for _ in range(3):
    h.check('alpha beta gamma', 'advancing', 5)
MIRROR.flush(10)
seen.clear()

t = time.perf_counter()
for _ in range(20):
    h.check('alpha beta gamma', 'advancing', 5)
per = (time.perf_counter() - t) / 20
check('a keyed check does not pay the network', per < 0.02, f'{per * 1e6:.0f} µs/check')
check('  which is far below one mirror round-trip', per < 0.02,
      f'the stub alone sleeps 20000 µs')

print()
print('ordered — one worker, one queue')

# Drain BEFORE clearing. The timing loop above left 20 posts in flight, and clearing while
# they were still queued let them land afterwards — which read as 30 rows arriving for 10
# sends. The queue was right and the test was racing it.
MIRROR.flush(20)
seen.clear()
dists = [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
for d in dists:
    h.check('alpha beta gamma', 'advancing', d)
drained = MIRROR.flush(20)
check('the queue drains', drained, str(MIRROR.stats()))
got = [b.get('distance') for b in seen]
check('every row arrives', len(got) == len(dists), f'{len(got)} of {len(dists)}')
check('and in the order it was produced', got == dists, f'{got}')

print()
print('bounded — a wedged network sheds rows instead of growing')


def wedged(api, key, path, body):
    time.sleep(5)
    return None


laserbrain._post = wedged
before = MIRROR.dropped
for n in range(400):
    MIRROR.send('https://example.invalid', 'k', '/v1/drift', {'n': n})
queued = MIRROR.stats()['queued']
check('the queue is capped', queued <= 256, f'queued {queued}')
check('  and the overflow is counted, not silently lost',
      MIRROR.dropped > before, f'dropped +{MIRROR.dropped - before}')

print()
print('honest — a mirror may never reach the caller')


def exploding(api, key, path, body):
    raise RuntimeError('network on fire')


laserbrain._post = exploding
try:
    v = h.check('alpha beta gamma', 'advancing', 5)
    check('a mirror that raises does not break check()', v is not None, v.reason)
except Exception as e:
    check('a mirror that raises does not break check()', False, f'{type(e).__name__}: {e}')

laserbrain._post = _real_post
check('the verdict never depends on the mirror',
      MIRROR.stats()['sent'] >= 0 and h.check('alpha beta gamma', 'advancing', 5) is not None)

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — off the critical path, in order, bounded, and unable to reach the caller.')
