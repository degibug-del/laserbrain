#!/usr/bin/env python3
"""test_gate_hosts.py — per-host claim/coverage gate behaviours.

Pins the 2026-07-25 improvement list:
  - search_replace is a write tool (the claim gate sees edits made with it)
  - search_tool is always allowed (no schema-discovery deadlock)
  - agent identity: env → session → unknown
  - link rows: from= and agent= both count
  - the deny howto is per-host: a configured host gets its own text, others the default

Agent names here are FIXTURES. The assertions prove which key is read and which branch
runs, never which vendor sent the payload, so 'agent-a' and 'agent-b' say what they are.
The one place a name is load-bearing — the howto lookup — installs its own fixture config
rather than depending on whichever host the deployment happens to configure.
"""
import json, os, pathlib, subprocess, sys, tempfile, importlib.util

# LASERGEAR IS A SEPARATE REPO and this suite reaches into it. That was invisible until CI
# ran for the first time on 2026-08-17 and three suites failed on a clean runner, looking
# for /home/runner/Library/Mobile Documents/… — a path that exists on exactly one laptop.
# They had always passed locally, which is precisely why nobody knew: a machine-dependent
# test is indistinguishable from a passing one until the machine changes.
#
# LASERGEAR_DIR points at a checkout, and CI clones the now-public lasergear repo to supply
# it. Absent, this exits 77 and the runner reports SKIPPED rather than passed — a check that
# could not run has not passed, and the two must never print the same.
_GEAR = pathlib.Path(os.environ.get('LASERGEAR_DIR') or (
    pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/lasergear'))
HOOK = _GEAR / 'lb_gate.py'
if not HOOK.exists():
    print(f'  SKIP  lb_gate.py not found at {HOOK} — set LASERGEAR_DIR to a lasergear checkout')
    raise SystemExit(77)
ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


def load_hook():
    spec = importlib.util.spec_from_file_location('lb_gate_test', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_gate(ev, env=None, link=None, session=None, sid='test-gate-sid'):
    """Run lb_gate as a subprocess with temp link/session; return (exit, stderr, stdout)."""
    env = dict(os.environ, **(env or {}))
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        tlog = td / 'link.jsonl'
        if link is not None:
            tlog.write_text('\n'.join(json.dumps(r) for r in link) + ('\n' if link else ''))
        else:
            tlog.write_text('')
        env['LASERBRAIN_LINK_LOG'] = str(tlog)
        sdir = td / 'sessions'
        sdir.mkdir()
        # Patch STATE_DIR by writing where the hook looks — we can't easily; instead
        # inject session via monkey through import path for unit checks, and subprocess
        # only for integration of main() with env.
        # For subprocess: point HOME so STATE_DIR = home/.claude/laserbrain
        fake_home = td / 'home'
        (fake_home / '.claude' / 'laserbrain').mkdir(parents=True)
        if session is not None:
            (fake_home / '.claude' / 'laserbrain' / f'{sid}.json').write_text(
                json.dumps(session))
        env['HOME'] = str(fake_home)
        # AND CLEAR THE ROOT OVERRIDES, because this suite isolates via HOME and lb_paths
        # deliberately ranks LASERBRAIN_HOME above the HOME-derived default. run-tests.sh
        # exports LASERBRAIN_HOME for every suite, so without this the hook resolves to the
        # runner's temp root and never sees the session file written into fake_home — the
        # precedence working exactly as documented, against a test that predates it.
        for _v in ('LASERBRAIN_HOME', 'LASERBRAIN_STATE_DIR'):
            env.pop(_v, None)
        # also clear agent unless set
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({**ev, 'session_id': sid, 'sessionId': sid}),
            text=True, capture_output=True, env=env,
        )
        return proc.returncode, proc.stderr, proc.stdout


def main():
    if not HOOK.exists():
        show('lb_gate exists', False, str(HOOK))
        return 1
    g = load_hook()

    # ── constants ──────────────────────────────────────────────────────────
    show('search_replace in WRITE_TOOLS',
         any('search_replace' == w for w in g.WRITE_TOOLS)
         or any('search_replace' in w for w in g.WRITE_TOOLS))
    show('search_tool in ALWAYS_ALLOW',
         any('search_tool' in a for a in g.ALWAYS_ALLOW))

    # ── edit_target sees search_replace ────────────────────────────────────
    ev = {
        'tool_name': 'search_replace',
        'tool_input': {'file_path': '/repo/app/locus/page.tsx', 'old_string': 'a', 'new_string': 'b'},
    }
    tgt = g.edit_target(ev, 'search_replace')
    show('edit_target(search_replace) returns path',
         tgt == '/repo/app/locus/page.tsx', repr(tgt))

    ev_write = {
        'tool_name': 'write',
        'tool_input': {'file_path': '/repo/x.py', 'content': '1'},
    }
    show('edit_target(write) still works',
         g.edit_target(ev_write, 'write') == '/repo/x.py')

    # ── entry_agent ────────────────────────────────────────────────────────
    show('entry_agent from=', g.entry_agent({'from': 'agent-a'}) == 'agent-a')
    show('entry_agent agent=', g.entry_agent({'agent': 'agent-b'}) == 'agent-b')
    show('entry_agent payload.from',
         g.entry_agent({'payload': {'from': 'agent-b'}}) == 'agent-b')

    # ── resolve_me priority ────────────────────────────────────────────────
    old = os.environ.get('LASERBRAIN_AGENT')
    try:
        os.environ['LASERBRAIN_AGENT'] = 'agent-b'
        show('resolve_me prefers env', g.resolve_me({}, {'agent': 'agent-a'}) == 'agent-b')
        del os.environ['LASERBRAIN_AGENT']
        show('resolve_me falls back to session',
             g.resolve_me({}, {'agent': 'agent-b'}) == 'agent-b')
        show('resolve_me unknown default', g.resolve_me({}, None) == 'unknown')
    finally:
        if old is not None:
            os.environ['LASERBRAIN_AGENT'] = old
        else:
            os.environ.pop('LASERBRAIN_AGENT', None)

    # ── check_howto agent-aware ────────────────────────────────────────────
    # Fixture config on the freshly-loaded module. Asserting against the real hosts.json
    # would tie this test to whichever host the deployment configures — it would pass for
    # the wrong reason today and break when the config changes, without the behaviour
    # having moved. What is under test is the LOOKUP: a configured host gets its own text,
    # anything else gets the default.
    _saved_hosts, _saved_default = g._HOSTS, g.CHECK_HOWTO_DEFAULT
    try:
        g._HOSTS = {'by_agent': {'agent-b': 'CALL-IT-THE-AGENT-B-WAY'}}
        g.CHECK_HOWTO_DEFAULT = 'CALL-IT-THE-GENERIC-WAY'
        show('a configured host gets its own howto',
             g.check_howto('agent-b') == 'CALL-IT-THE-AGENT-B-WAY')
        show('an unconfigured host gets the default',
             g.check_howto('agent-z') == 'CALL-IT-THE-GENERIC-WAY')
        show('a missing agent gets the default',
             g.check_howto(None) == 'CALL-IT-THE-GENERIC-WAY')
    finally:
        g._HOSTS, g.CHECK_HOWTO_DEFAULT = _saved_hosts, _saved_default

    # ── claimed_by_others: agent= claims + closed waves ────────────────────
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tlog = pathlib.Path(td) / 't.jsonl'
        rows = [
            {'kind': 'wave_open', 'from': 'agent-a', 'payload': {'wave': 9}},
            {'kind': 'claim', 'agent': 'agent-b', 'payload': {'wave': 9, 'paths': ['app/locus/']}},
            {'kind': 'claim', 'from': 'agent-a', 'payload': {'wave': 9, 'paths': ['lasermind/']}},
        ]
        tlog.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        g.LINK_LOG = tlog
        by = g.claimed_by_others('agent-b')
        show('an agent does not see its own claim as other',
             'app/locus/' not in by, repr(by))
        show("an agent sees another agent's claim",
             by.get('lasermind/') == 'agent-a', repr(by))
        by_c = g.claimed_by_others('agent-a')
        show('a claim written with agent= is seen too',
             by_c.get('app/locus/') == 'agent-b', repr(by_c))
        # close the wave
        rows.append({'kind': 'wave_close', 'from': 'agent-a', 'payload': {'wave': 9}})
        tlog.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        by_after = g.claimed_by_others('agent-b')
        show('closed agent claims drop',
             'lasermind/' not in by_after, repr(by_after))
        # free-form standing (no open wave at all)
        tlog.write_text('\n'.join(json.dumps(r) for r in [
            {'kind': 'claim', 'agent': 'agent-a',
             'payload': {'paths': ['phronesis/lasermind/hooks/']}},
        ]) + '\n')
        by_ff = g.claimed_by_others('agent-b')
        show('free-form claim locks without wave',
             by_ff.get('phronesis/lasermind/hooks/') == 'agent-a', repr(by_ff))
        tlog.write_text('\n'.join(json.dumps(r) for r in [
            {'kind': 'claim', 'agent': 'agent-a',
             'payload': {'paths': ['phronesis/lasermind/hooks/']}},
            {'kind': 'done', 'agent': 'agent-a',
             'payload': {'release_claims': True}},
        ]) + '\n')
        by_rel = g.claimed_by_others('agent-b')
        show('free-form claim released by done(release_claims)',
             'phronesis/lasermind/hooks/' not in by_rel, repr(by_rel))

    # ── integration: search_tool always allowed even past BLOCK_AFTER ──────
    code, err, out = run_gate(
        {'tool_name': 'search_tool', 'tool_input': {'query': 'laserbrain'}},
        env={'LASERBRAIN_AGENT': 'agent-b'},
        session={'steps': 20, 'checks': [{'step': 1}], 'agent': 'agent-b'},
    )
    show('search_tool allowed under gate pressure', code == 0, f'exit={code} err={err[:120]!r}')

    # ── integration: search_replace blocked on foreign claim ───────────────
    code, err, out = run_gate(
        {
            'tool_name': 'search_replace',
            'tool_input': {
                'file_path': '/Users/x/phronesis-world/app/locus/page.tsx',
                'old_string': 'a', 'new_string': 'b',
            },
        },
        env={'LASERBRAIN_AGENT': 'agent-a'},
        link=[
            {'kind': 'wave_open', 'from': 'agent-a', 'payload': {'wave': 42}},
            {'kind': 'claim', 'agent': 'agent-b', 'payload': {'wave': 42, 'paths': ['app/locus/']}},
        ],
        session={'steps': 1, 'checks': [{'step': 1}], 'agent': 'agent-a'},
    )
    show('search_replace claim-blocked for foreign path',
         code == 2 and 'claim gate' in err, f'exit={code} err={err[:200]!r}')

    # ── integration: own claim not blocked when the claimer is this agent ──
    code, err, out = run_gate(
        {
            'tool_name': 'search_replace',
            'tool_input': {
                'file_path': '/Users/x/phronesis-world/app/locus/page.tsx',
                'old_string': 'a', 'new_string': 'b',
            },
        },
        env={'LASERBRAIN_AGENT': 'agent-b'},
        link=[
            {'kind': 'wave_open', 'from': 'agent-a', 'payload': {'wave': 42}},
            {'kind': 'claim', 'agent': 'agent-b', 'payload': {'wave': 42, 'paths': ['app/locus/']}},
        ],
        session={'steps': 1, 'checks': [{'step': 1}], 'agent': 'agent-b'},
    )
    show('search_replace allowed on own claim',
         code == 0, f'exit={code} err={err[:200]!r}')

    # ── integration: the coverage deny carries a howto ─────────────────────
    code, err, out = run_gate(
        {'tool_name': 'run_terminal_command', 'tool_input': {'command': 'echo hi'}},
        env={'LASERBRAIN_AGENT': 'agent-b'},
        session={'steps': 20, 'checks': [{'step': 1}], 'agent': 'agent-b'},
    )
    # This subprocess runs as an UNCONFIGURED agent, so the deny must carry the default
    # howto. Asserting a configured host's wording here would have tested the deployment's
    # hosts.json rather than the gate, and would break whenever that config changed
    # without the gate having moved. The per-host branch is covered above, in isolation.
    show('the coverage deny carries the default howto',
         code == 2 and 'mcp__laserbrain__check_state' in err,
         f'exit={code} err={err[:220]!r}')

    print('\n  ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
