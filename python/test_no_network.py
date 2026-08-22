#!/usr/bin/env python3
"""SECURITY.md claims the package makes no network calls. This is what checks it.

The claim was previously supported by "scanning every shipped file for URLs", which is
not a method that can establish it: a host assembled at runtime, read from an environment
variable, or reached through a dependency all pass a URL scan and all make the claim
false. The claim happened to be true. The check could not have told anyone.

So block the socket instead and exercise the package against it. This cannot be satisfied
by a file that merely contains no literal URL, and it fails if a dependency added later
phones home on import.
"""
import os
import socket
import sys
import tempfile

os.environ['LASERBRAIN_HOME'] = tempfile.mkdtemp(prefix='lb-nonet-')

ok = True
attempts = []


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


class Blocked(Exception):
    pass


def _guard_method(self, addr, *a, **k):
    attempts.append(addr)
    raise Blocked(f'connect {addr}')


def _guard_fn(addr, *a, **k):
    attempts.append(addr)
    raise Blocked(f'create_connection {addr}')


# Installed BEFORE laserbrain is imported, so import-time traffic is caught too — that is
# the moment a phone-home would most plausibly sit.
socket.socket.connect = _guard_method
socket.socket.connect_ex = _guard_method
socket.create_connection = _guard_fn

import asyncio          # noqa: E402  — after the guard, deliberately
import importlib        # noqa: E402
import pathlib          # noqa: E402

import laserbrain as lb  # noqa: E402

show('importing the package opens no connection', not attempts, str(attempts))

# The full path a real run takes.
hz = lb.Harness()
for _d in (7, 6, 5, 4):
    hz.check(goal='reconcile the March statement against the ledger',
             progress='advancing', distance=_d)
hz.check(goal='pull the bank feed for March', progress='advancing', distance=3,
         user_turn=True)
hz.phronesis()
hz.report()
chain = hz.audit()
hz.export_audit(os.path.join(os.environ['LASERBRAIN_HOME'], 'run.json'))
asyncio.run(hz.acheck(goal='check the unmatched lines', progress='advancing', distance=2))
show('a full run opens no connection', not attempts, str(attempts))

# Every shipped module, not only the ones __init__ happens to pull in.
pkg = pathlib.Path(lb.__file__).parent
# rglob, NOT glob. The non-recursive version skipped laserbrain/hooks/ entirely — the very
# modules SECURITY.md's sentence named, and the ones that run on every tool call. Caught by
# a review on 2026-08-21: the wheel holds 32 .py files and this reported 25.
shipped = sorted(str(p.relative_to(pkg).with_suffix('')).replace('/', '.')
                 for p in pkg.rglob('*.py') if p.stem != '__init__')
blocked_on_import = []
for _m in shipped:
    try:
        importlib.import_module(f'laserbrain.{_m}')
    except Blocked:
        blocked_on_import.append(_m)
    except Exception:
        # An optional dependency missing is not a network call. Only Blocked is a failure.
        pass
show(f'all {len(shipped)} shipped modules import without connecting',
     not blocked_on_import, str(blocked_on_import))
show('no module was silently skipped', len(shipped) >= 30, f'{len(shipped)} modules')

# Importing the package must not even pull in a TLS or HTTP client. asyncio drags in ssl,
# which is why this is measured in a clean subprocess rather than in this one.
import subprocess       # noqa: E402
probe = subprocess.run(
    [sys.executable, '-c',
     'import laserbrain, sys; '
     "print([m for m in ('ssl','http.client','urllib.request','requests','httpx') "
     'if m in sys.modules])'],
    capture_output=True, text=True, timeout=60)
show('importing it pulls in no TLS or HTTP client', probe.stdout.strip() == '[]',
     probe.stdout.strip() or probe.stderr.strip()[:80])

# The guard itself must work, or every check above is vacuous — the failure this whole
# file exists to prevent.
try:
    socket.create_connection(('127.0.0.1', 9))
    show('the guard actually blocks', False, 'a connection went through')
except Blocked:
    show('the guard actually blocks', True)
except Exception as e:
    show('the guard actually blocks', False, f'wrong error: {type(e).__name__}')

print('\n' + ('NO NETWORK CALLS ✓' if ok else 'SOME FAILED ✗'))
raise SystemExit(0 if ok else 1)
