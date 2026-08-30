#!/usr/bin/env python3
"""waves.py — the wave protocol from LINK.md, implemented.

LINK.md specified waves and nothing ran them. This is the running part: open a wave,
claim disjoint scope, check the disjointness BEFORE anyone edits, close.

WHAT A WAVE IS FOR. Continuous concurrent editing has an N² conflict surface — every
agent must hold every other in mind, always, and nobody can see what is in flight. Two
agents nearly got away with it on 2026-07-25 and still produced two collisions: a merged
session file, and a silent edit into /locus while a host was building there. A wave makes it
N: everyone declares up front, overlap is caught before work rather than discovered in a
merge, and the interval has a boundary.

THE BOUNDARY IS A GROUND. This is the part that is not scheduling. A wave declares one
goal, so a wave boundary is a `reset_task` boundary: each agent grounds its harness at
wave_open and holds that ground until wave_close. Then drift is measured against the goal
the wave actually declared — instead of whatever stray prompt happened to land, which is
how one session came to record its ground as 'do all'. Coverage becomes per-wave and
comparable across agents, because every denominator is the same interval.

THE INVARIANT IT OBEYS. Everything here is append-only. A wave is not a lock and a claim
is not a mutex — both are lines in the shared log. Nothing is shared and mutable, which is
the one rule every failure so far has broken.

    python3 waves.py status
    python3 waves.py open  "the wave's one goal" --surf agent-a
    python3 waves.py claim --agent agent-a --paths lasermind/ laserbrain-sdk/
    python3 waves.py close --agent agent-a --summary "what changed"
"""
import sys, json, os, datetime, pathlib, fnmatch


def _link_log_default():
    """~/.config/laserbrain/link.jsonl, falling back to the pre-rename tandem.jsonl.

    Renamed 2026-07-27. FOUR files resolve this path independently — link.py, waves.py,
    lb_gate.py and mcp-server.mjs — and they must land on the same file. If they do not,
    two agents "sharing" a channel each write to a different log and each reads an empty
    one, which presents exactly as the other agent having said nothing. The legacy path is
    honoured when it exists and the new one does not, so an un-migrated machine keeps its
    history instead of silently starting over.
    """
    import sys as _s, pathlib as _p
    _s.path.insert(0, str(_p.Path(__file__).resolve().parent))
    import _root
    base = _root.config_dir()
    new, old = base / 'link.jsonl', base / 'tandem.jsonl'
    return old if (old.exists() and not new.exists()) else new

LOG = pathlib.Path(os.environ.get('LASERBRAIN_LINK_LOG')
                   or os.environ.get('LASERBRAIN_TANDEM_LOG')
                   or _link_log_default())

# A claim this broad is technically a claim and practically a lock on everything under it.
# The protocol can check overlap; it cannot check good faith, so it says so out loud.
TOO_BROAD = ('**', '*', '.', './', '/', 'app/**', 'app/', 'src/**')

# A wave nobody closes blocks every future wave. LINK.md specifies a timeout and the first
# implementation did not have one — which meant the author could deadlock the protocol by
# claiming three paths and walking away, and did. An agent that never closes is a fact
# worth logging, not a lock worth honouring forever.
STALE_AFTER_H = 6


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _append(obj):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a') as f:
        f.write(json.dumps(obj) + '\n')
    return obj


def _read():
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass          # a malformed line is not a reason to lose the rest
    return out


def overlaps(a, b):
    """Do two claimed paths collide?

    Prefix containment in either direction, plus glob matching both ways. 'app/' contains
    'app/locus/page.tsx'; 'app/**' matches it; 'app/locus/' is contained BY it. All three
    are collisions and a naive equality check would miss every one.
    """
    a, b = a.rstrip('/'), b.rstrip('/')
    if a == b:
        return True
    if fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    return (a + '/').startswith(b + '/') or (b + '/').startswith(a + '/')


def _age_hours(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return 0.0


def current_wave(rows=None):
    """The most recent wave_open with no matching close from every claimant, or None."""
    rows = rows if rows is not None else _read()
    opens = [r for r in rows if r.get('kind') == 'wave_open']
    if not opens:
        return None
    w = opens[-1]
    wid = w.get('payload', {}).get('wave')
    claims = [r for r in rows if r.get('kind') == 'claim' and r.get('payload', {}).get('wave') == wid]
    closes = [r for r in rows if r.get('kind') == 'wave_close' and r.get('payload', {}).get('wave') == wid]
    claimed = {c.get('from') for c in claims}
    # A forced close is made BY one agent ON BEHALF OF another, so crediting it to
    # `from` credits the wrong party: on 2026-07-25 `waves.py force-close --for agent-b`
    # printed "✓ force-closed ... recorded, not hidden" and the wave stayed OPEN with agent-b
    # still outstanding, because the close was attributed to agent-a — who had already
    # closed. The record was right and the reader of it was wrong.
    #
    # open_wave's stale path masked this: it force-closes and then never re-checks
    # cur['open'], so it deadlocked no further and the bug had nothing to show for itself.
    # test_waves.py asserted the forced close was RECORDED and never that it was COUNTED.
    closed = {(c.get('payload') or {}).get('on_behalf_of') or c.get('from') for c in closes}
    age = _age_hours(w.get('ts'))
    return {'wave': wid, 'goal': w.get('goal'), 'surf': w.get('payload', {}).get('surf'),
            'opened': w.get('ts'), 'claims': claims, 'claimed': claimed, 'closed': closed,
            'open': bool(claimed - closed) or not claimed,
            'age_h': age, 'stale': age >= STALE_AFTER_H,
            'outstanding': sorted(claimed - closed)}


def open_wave(goal, surf, agent):
    rows = _read()
    cur = current_wave(rows)
    if cur and cur['open']:
        if cur['stale']:
            # Close it on their behalf and RECORD that we did. Surf rides atop the wave;
            # part of that is ending one the fleet has abandoned.
            for who in cur['outstanding']:
                _append({'ts': _now(), 'from': agent, 'kind': 'wave_close',
                         'goal': cur['goal'],
                         'text': f'closed on behalf of {who} — no close after '
                                 f'{cur["age_h"]:.1f}h (stale after {STALE_AFTER_H}h)',
                         'payload': {'wave': cur['wave'], 'on_behalf_of': who,
                                     'forced': True, 'by': agent}})
            cur = current_wave()
        else:
            return None, (f"wave {cur['wave']} is still open — {cur['outstanding']} have not "
                          f"closed (open {cur['age_h']:.1f}h, stale at {STALE_AFTER_H}h). "
                          f"A wave opens only when the previous one has closed.")
    nxt = (cur['wave'] + 1) if cur else 1
    return _append({'ts': _now(), 'from': agent, 'kind': 'wave_open', 'goal': goal,
                    'text': f'wave {nxt} opens: {goal}',
                    'payload': {'wave': nxt, 'surf': surf}}), None


def claim(agent, paths):
    """Claim scope. Refuses on overlap — that is the whole point of claiming before work."""
    rows = _read()
    cur = current_wave(rows)
    if not cur or not cur['open']:
        return None, 'no wave is open — open one first'

    broad = [p for p in paths if p.strip().rstrip('/') in [t.rstrip('/') for t in TOO_BROAD]]
    if broad:
        return None, (f'refusing a claim on {broad}: that is a lock on everything beneath it, '
                      f'not a scope. Name the files you will actually edit.')

    conflicts = []
    for other in cur['claims']:
        if other.get('from') == agent:
            continue
        for mine in paths:
            for theirs in other.get('payload', {}).get('paths', []):
                if overlaps(mine, theirs):
                    conflicts.append((mine, theirs, other.get('from')))
    if conflicts:
        lines = [f'{m} overlaps {t} claimed by {who}' for m, t, who in conflicts]
        return None, 'claim refused, ' + '; '.join(lines)

    return _append({'ts': _now(), 'from': agent, 'kind': 'claim',
                    'goal': cur['goal'], 'text': f'claims {", ".join(paths)}',
                    'payload': {'wave': cur['wave'], 'paths': list(paths)}}), None


def close(agent, summary):
    rows = _read()
    cur = current_wave(rows)
    if not cur:
        return None, 'no wave to close'
    return _append({'ts': _now(), 'from': agent, 'kind': 'wave_close',
                    'goal': cur['goal'], 'text': summary,
                    'payload': {'wave': cur['wave']}}), None


def status():
    cur = current_wave()
    if not cur:
        print('  no wave has been opened'); return 0
    stale = '  STALE' if cur.get('stale') and cur['open'] else ''
    print(f"  wave {cur['wave']} — {'OPEN' if cur['open'] else 'closed'}"
          f"  ({cur['age_h']:.1f}h){stale}")
    print(f"  goal    {cur['goal']}")
    print(f"  surf    {cur['surf']}   opened {cur['opened']}")
    if not cur['claims']:
        print('  claims  none yet — nobody should be editing')
    for c in cur['claims']:
        who = c.get('from')
        mark = 'closed' if who in cur['closed'] else 'working'
        print(f"    {who:<8} {mark:<8} {', '.join(c.get('payload', {}).get('paths', []))}")
    if cur['open']:
        print(f"\n  ground your harness on the wave goal, and reset_task at the boundary —")
        print(f"  that is what makes coverage comparable between agents.")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().split('\n\n')[-1]); return 1
    cmd = argv[1]
    agent = os.environ.get('LASERBRAIN_AGENT', 'unknown')

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default

    if cmd == 'status':
        return status()
    if cmd == 'force-close':
        cur = current_wave()
        if not cur or not cur['open']:
            print('  nothing open to force'); return 1
        who = opt('--for')
        targets = [who] if who else cur['outstanding']
        for t in targets:
            _append({'ts': _now(), 'from': agent, 'kind': 'wave_close', 'goal': cur['goal'],
                     'text': f'force-closed on behalf of {t} by {agent}',
                     'payload': {'wave': cur['wave'], 'on_behalf_of': t,
                                 'forced': True, 'by': agent}})
            print(f'  ✓ force-closed wave {cur["wave"]} on behalf of {t} — recorded, not hidden')
        return 0
    if cmd == 'open':
        row, err = open_wave(argv[2], opt('--surf', agent), opt('--agent', agent))
    elif cmd == 'claim':
        paths = argv[argv.index('--paths') + 1:] if '--paths' in argv else []
        row, err = claim(opt('--agent', agent), paths)
    elif cmd == 'close':
        row, err = close(opt('--agent', agent), opt('--summary', 'closed'))
    else:
        print(f'  unknown command {cmd!r}'); return 1

    if err:
        print(f'  ✗ {err}'); return 1
    print(f"  ✓ {row['kind']} wave {row['payload']['wave']} — {row['text'][:70]}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
