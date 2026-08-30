#!/usr/bin/env bash
# Store your ARC Prize API key, without it ever passing through a transcript.
#
#     ./set-arc-key.sh
#
# YOU run this and paste the key at the prompt. It is read with terminal echo off, so it
# does not appear on screen; it is never passed as an argument, so it does not reach the
# process table or your shell history; and it is never printed back — this script reports
# what the key can DO, never what it is.
#
# WHERE IT GOES
#
#   ~/.config/laserbrain/arc-api-key        mode 600, one line
#
# under the same root everything else laserbrain owns lives under, so LASERBRAIN_HOME
# relocates it with the rest and a test run cannot read your real key.
#
# WHY A FILE AND NOT A SHELL EXPORT: an export in .zshrc is inherited by every process you
# start and shows up in `env` output, which is a thing people paste into bug reports. A
# mode-600 file is read by the one thing that needs it, when it needs it.
#
# WHY THE CHECK IS SHAPED THE WAY IT IS — measured 2026-08-05, and it is not what you would
# write first. A bad key does NOT raise. The toolkit logs a 401 internally and RETURNS
# NORMALLY with a degraded list of one environment. So `try: ... except:` accepts a typo,
# stores it, and every later run quietly falls back to fewer environments while looking
# authenticated. The check therefore watches three things: that nothing logged an error,
# that the list is not the degraded one, and that it is at least as large as the anonymous
# key already sees for free — because a key that buys you less than no key is a key that
# did not work.
set -uo pipefail

python3 - <<'PY'
import getpass
import io
import logging
import os
import pathlib

HOME = os.environ.get('LASERBRAIN_HOME')
CONFIG = (pathlib.Path(HOME).expanduser() / 'config') if HOME else (
    pathlib.Path.home() / '.config' / 'laserbrain')
DEST = CONFIG / 'arc-api-key'

print('  Paste your ARC Prize API key. It will not be shown.')
print('  Get one at https://arcprize.org  (blank to cancel)\n')
try:
    key = getpass.getpass('  key: ').strip()
except (EOFError, KeyboardInterrupt):
    print('\n  cancelled')
    raise SystemExit(1)

if not key:
    print('  cancelled — nothing written')
    raise SystemExit(1)

print('\n  checking it against the ARC API...')
try:
    import arc_agi
except ImportError:
    print('  the arc-agi toolkit is not installed here:')
    print('      python3 -m pip install arc-agi')
    raise SystemExit(2)

# Catch the 401 the library swallows. Without this the only symptom is a short list.
trap = io.StringIO()
handler = logging.StreamHandler(trap)
handler.setLevel(logging.ERROR)
root = logging.getLogger()
root.addHandler(handler)
prev = root.level
root.setLevel(logging.ERROR)
try:
    envs = arc_agi.Arcade(arc_api_key=key).get_environments()
    anon = arc_agi.Arcade().get_environments()
except Exception as e:
    print(f'  the API rejected it: {type(e).__name__}: {str(e)[:140]}')
    print('  NOTHING was written.')
    raise SystemExit(1)
finally:
    root.removeHandler(handler)
    root.setLevel(prev)

logged = trap.getvalue()
if '401' in logged or 'Unauthorized' in logged:
    print('  the API returned 401 Unauthorized for that key.')
    print('  NOTHING was written. Check it and run this again.')
    raise SystemExit(1)
if len(envs) <= 1 or len(envs) < len(anon):
    print(f'  that key sees {len(envs)} environment(s); the anonymous key already sees '
          f'{len(anon)}.')
    print('  That is what a rejected key looks like here — it does not raise, it degrades.')
    print('  NOTHING was written.')
    raise SystemExit(1)

CONFIG.mkdir(parents=True, exist_ok=True)
DEST.write_text(key + '\n')
DEST.chmod(0o600)

print(f'  accepted — {len(envs)} environments available ({len(anon)} anonymously)')
print(f'  stored at {DEST}  (mode 600)')
print()
print('  bench.py reads it from there. Nothing needs to go in your shell profile.')
PY
