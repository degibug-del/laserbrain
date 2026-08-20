#!/usr/bin/env python3
"""lb_secrets.py — scan a tree, or a git history, before it leaves this machine.

    python3 lb_secrets.py ~/some/repo            # working tree
    python3 lb_secrets.py ~/some/repo --history  # every blob in every commit
    python3 lb_secrets.py --self-test            # prove it can fail

WHY THIS EXISTS

On 2026-07-29 a Telegram bot token was pushed to a new repo. The pre-push check that
cleared it grepped for four patterns — sk-, pypi-, ghp_, AKIA — and reported "0 hits".
A Telegram token is `digits:AA…` and matches none of them.

The failure was not the missing pattern. It was reporting a FOUR-PATTERN grep as a secret
scan: "0 hits" meant "none of these four shapes", and it was read as "no secrets". A check
whose coverage is invisible produces a green light that means nothing, which is the same
shape as every other failure recorded in PROTOCOL.md.

So this file does three things that grep did not:

  1. Names every pattern it knows, and PRINTS the count. A scan that cannot say what it
     looked for cannot be trusted when it finds nothing.
  2. Scans git HISTORY, not just the working tree. The token that leaked was absent from
     the tip and present in one commit from May. Scanning the checkout would still have
     said clean.
  3. Ships a self-test that FAILS if the scanner stops catching the exact token shape that
     got through. Every other assertion here would pass against a function returning [],
     so without a case that legitimately fires, green proves nothing.

WHAT IT DOES NOT DO

It is a pattern scanner, not a secret oracle. It cannot find a credential with no
recognisable shape — a bare password, a base64 blob, a key in a format nobody has written
a rule for. `--self-test` tells you what it covers; the honest reading of a clean result is
"none of these N shapes", never "no secrets".
"""

import argparse
import os
import re
import subprocess
import sys

# name -> (regex, why it matters). Ordered roughly by how often each actually shows up.
PATTERNS = {
    'telegram-bot-token':  (r'\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}\b',
                            'the one that got through on 2026-07-29'),
    'openai':              (r'\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b', 'OpenAI API key'),
    'anthropic':           (r'\bsk-ant-[A-Za-z0-9_\-]{20,}\b', 'Anthropic API key'),
    'github-token':        (r'\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}\b', 'GitHub token'),
    'github-pat':          (r'\bgithub_pat_[A-Za-z0-9_]{30,}\b', 'GitHub fine-grained PAT'),
    'aws-access-key':      (r'\bAKIA[0-9A-Z]{16}\b', 'AWS access key id'),
    'pypi-token':          (r'\bpypi-[A-Za-z0-9_\-]{20,}\b', 'PyPI upload token'),
    'slack-token':         (r'\bxox[baprs]-[A-Za-z0-9\-]{10,}\b', 'Slack token'),
    'stripe-live':         (r'\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b', 'Stripe LIVE key'),
    'google-api-key':      (r'\bAIza[0-9A-Za-z_\-]{35}\b', 'Google API key'),
    'private-key-block':   (r'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----',  # lb-secrets: allow
                            'a private key, inline'),
    'jwt':                 (r'\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.',
                            'a JSON web token'),
    'zenodo-ish':          (r'\b[A-Za-z0-9]{50,64}\b(?=.{0,40}(?i:zenodo))',
                            'a long opaque string next to the word zenodo'),
    'assigned-secret':     (r'(?i)\b(?:api[_-]?key|secret|passwd|password|token|bearer)\b'
                            r'\s*[:=]\s*[\'"][^\'"\s]{16,}[\'"]',
                            'something named like a credential with a long literal'),
}
COMPILED = {k: (re.compile(v[0]), v[1]) for k, v in PATTERNS.items()}

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build',
             '.next', 'out', '.mypy_cache', '.pytest_cache'}
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.gz', '.whl', '.mp4',
            '.woff', '.woff2', '.ico', '.eeg', '.fdt', '.set'}


# A LINE MAY DECLARE ITSELF A PATTERN RATHER THAN A SECRET.
#
# This scanner flagged ITSELF: its own pattern table and self-test fixtures contain the
# strings it hunts for, so every clean repository reported exactly one finding. A check
# that always fires is one people learn to wave through — which is how a real leak
# eventually passes. Found 2026-08-20, making this repository public.
#
# The pragma is deliberately narrow. It exempts the LINE, not the file: a real credential
# pasted three lines below is still caught, and marking a line is a visible choice in a
# diff rather than a silent skip.
ALLOW = re.compile(r'#\s*lb-secrets:\s*allow\b')


def hits_in(text, where):
    """Every match, with the VALUE redacted — a scanner that prints secrets is a leak."""
    out = []
    lines = text.splitlines()
    # offset -> line index, so a match can be mapped back to the line that produced it
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos); pos += len(ln) + 1
    def line_of(off):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= off: lo = mid
            else: hi = mid - 1
        return lo
    for name, (rx, why) in COMPILED.items():
        for m in rx.finditer(text):
            if lines and ALLOW.search(lines[line_of(m.start())]):
                continue
            raw = m.group(0)
            out.append({'pattern': name, 'why': why, 'where': where,
                        'shown': raw[:4] + '…' + str(len(raw)) + ' chars'})
    return out


def scan_tree(root):
    found = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            p = os.path.join(dirpath, f)
            try:
                with open(p, encoding='utf-8', errors='ignore') as fh:
                    found += hits_in(fh.read(), os.path.relpath(p, root))
            except Exception:
                continue
    return found


def scan_history(root):
    """Every blob in every commit. The 2026-07-29 leak was absent from the tip."""
    def git(*a):
        return subprocess.run(('git',) + a, cwd=root, capture_output=True,
                              text=True, errors='ignore').stdout
    found, seen = [], set()
    for line in git('rev-list', '--objects', '--all').splitlines():
        parts = line.split(' ', 1)
        if len(parts) != 2:
            continue
        sha, path = parts
        if sha in seen or os.path.splitext(path)[1].lower() in SKIP_EXT:
            continue
        seen.add(sha)
        if git('cat-file', '-t', sha).strip() != 'blob':
            continue
        found += hits_in(git('cat-file', '-p', sha), f'{path} (history)')
    return found


def self_test():
    """Prove it fires. Rule 1: break the thing it watches, confirm red."""
    cases = [
        ('telegram-bot-token', '123456789:AA' + 'x' * 33),
        ('openai', 'sk-' + 'a' * 32),
        ('github-token', 'ghp_' + 'b' * 36),
        ('aws-access-key', 'AKIA' + 'C' * 16),
        ('private-key-block', '-----BEGIN RSA PRIVATE KEY-----'),  # lb-secrets: allow
        ('assigned-secret', 'api_key = "' + 'z' * 24 + '"'),
    ]
    ok = True
    print(f'  {len(COMPILED)} patterns loaded\n')
    for want, sample in cases:
        got = {h['pattern'] for h in hits_in(sample, 'self-test')}
        hit = want in got
        ok = ok and hit
        print(f"  {'ok  ' if hit else 'FAIL'}  {want}")
    clean = hits_in('this file contains nothing secret at all, only prose.', 'self-test')
    print(f"  {'ok  ' if not clean else 'FAIL'}  clean text produces no finding")
    ok = ok and not clean
    print(f"\n  {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='Scan for credentials before pushing.')
    ap.add_argument('path', nargs='?', help='directory to scan')
    ap.add_argument('--history', action='store_true', help='scan every blob in every commit')
    ap.add_argument('--self-test', action='store_true', help='prove the scanner can fire')
    a = ap.parse_args()

    if a.self_test:
        sys.exit(self_test())
    if not a.path:
        ap.error('give a path, or --self-test')

    root = os.path.abspath(os.path.expanduser(a.path))
    found = scan_history(root) if a.history else scan_tree(root)

    scope = 'git history' if a.history else 'working tree'
    print(f'\n  scanned {scope} of {root}')
    print(f'  patterns checked: {len(COMPILED)}  ({", ".join(sorted(COMPILED))})')
    if not found:
        print(f'\n  no match for any of {len(COMPILED)} patterns.')
        print('  That is NOT "no secrets" — it is "none of these shapes". A credential '
              'with no recognisable form will not appear here.\n')
        sys.exit(0)
    print(f'\n  {len(found)} FINDING(S):\n')
    for h in found:
        print(f"    {h['pattern']:<20} {h['where']}")
        print(f"      {h['why']}  [{h['shown']}]")
    print('\n  Revoke first. Removing it from history does not un-leak it.\n')
    sys.exit(1)


if __name__ == '__main__':
    main()
