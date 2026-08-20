"""`laserbrain key` — the command that closes the gap between the README and the CLI.

The README has always said "add a key and it also mirrors to the API". Until 0.24.0 the
package offered no way to get one, and on 2026-07-29 that gap measured 6,000 downloads
against twelve keys ever issued.

Nothing here touches the network. The one call that would — new_key — is replaced, so
these tests say what the command does with an answer, not whether the API is up.

WHAT EACH CASE IS FOR

Two of these guard a security property and two guard a silent-failure mode:

  0600            a credential the rest of the machine can read is a defect, and the
                  failure is invisible — the key works perfectly either way.
  env beats file  a CI job that sets LASERBRAIN_KEY must not be overridden by whatever
                  is on the disk of the machine that built the image.
  round trip      save_key writing somewhere stored_key does not read would leave the
                  key in a file nothing loads, and every hosted call would go on
                  quietly unauthenticated. Both sides must name the same path.
  idempotence     a key IS the identity. Minting a second one on a second run would
                  silently strand the first key's history, and the output would look
                  like success.
"""
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain import cli, services  # noqa: E402

fails = []


def check(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
    if not cond:
        fails.append(label)


def with_key_path(tmp):
    """Point the module at a throwaway path. Tests must never touch a real key."""
    services.KEY_PATH = pathlib.Path(tmp) / 'key'
    return services.KEY_PATH


with tempfile.TemporaryDirectory() as tmp:
    path = with_key_path(tmp)
    os.environ.pop('LASERBRAIN_KEY', None)

    # ── the file is written private ────────────────────────────────────────────────
    services.save_key('lb_live_testkey123')
    mode = oct(path.stat().st_mode)[-3:]
    check(f"save_key writes 0600 (got {mode})", mode == '600')

    # Written twice: O_CREAT does not set the mode on a file that already exists, so a
    # key re-fetched onto a world-readable file would stay world-readable.
    os.chmod(path, 0o644)
    services.save_key('lb_live_testkey456')
    check("re-saving over a loose file tightens it back to 0600",
          oct(path.stat().st_mode)[-3:] == '600')

    # ── the two halves agree on where the key lives ────────────────────────────────
    check("save_key -> stored_key round trip", services.stored_key() == 'lb_live_testkey456')

    # ── explicit beats stored ──────────────────────────────────────────────────────
    os.environ['LASERBRAIN_KEY'] = 'lb_from_env'
    check("environment wins over the file", services.stored_key() == 'lb_from_env')
    os.environ['LASERBRAIN_KEY'] = '   '
    check("a blank environment value falls through to the file",
          services.stored_key() == 'lb_live_testkey456')
    os.environ.pop('LASERBRAIN_KEY', None)

    # ── no key at all ──────────────────────────────────────────────────────────────
    path.unlink()
    check("no env and no file -> None", services.stored_key() is None)

    # ── the command itself, with the network replaced ──────────────────────────────
    calls = {'n': 0}

    def fake_new_key(timeout=30.0):
        calls['n'] += 1
        return {'key': 'lb_live_fetched789',
                'tier': {'name': 'ground', 'reads': 1000, 'writes': 10,
                         'historyHours': 24, 'driftDays': 1}}

    real = services.new_key
    services.new_key = fake_new_key
    try:
        class A:
            new = False

        rc = cli._key(A())
        check("fetches and saves when there is no key", rc == 0 and calls['n'] == 1)
        check("the fetched key is what stored_key returns",
              services.stored_key() == 'lb_live_fetched789')

        rc2 = cli._key(A())
        check("a second run does NOT mint a second identity",
              rc2 == 0 and calls['n'] == 1)

        class B:
            new = True

        cli._key(B())
        check("--new does fetch again", calls['n'] == 2)

        # ── the endpoint answering without a key must not be reported as success ───
        services.new_key = lambda timeout=30.0: {'detail': 'rate limited'}
        check("an answer with no key returns nonzero", cli._key(B()) != 0)

        # ── unreachable API: report it, and do not destroy the key already held ────
        def boom(timeout=30.0):
            raise services.ServiceUnavailable('connection refused')

        services.new_key = boom
        check("unreachable API returns 2", cli._key(B()) == 2)
        check("a failed fetch leaves the existing key intact",
              services.stored_key() == 'lb_live_fetched789')
    finally:
        services.new_key = real

print()
if fails:
    print(f"  FAIL — {len(fails)}: " + "; ".join(fails))
    sys.exit(1)
print("  PASS — the key is private, found where it is written, and a second run")
print("  keeps the identity it already had.")
