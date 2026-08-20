"""link — many agents, one shared log.

This shipped as `tandem` and was described as a two-agent channel: two named agents, one
JSONL between them. The record format was never two-agent — every line already carries
an `agent` field — so the limit lived in the documentation and the tool names, not in the
data. Renamed and generalised 2026-07-27 on Diego's instruction: link has to be multiple
agents.

    from laserbrain import link_write, link_read, link_agents

    link_write('parser done, handing over the benchmark', kind='handoff')
    link_agents()          # everyone who has spoken on this link
    link_read(agent='builder', limit=5)

The link carries DATA about the work. The field carries the weather. The harness carries
the goal. Three different shared things, and conflating them is the mistake this project
keeps declining to make.

Local by default — a JSONL under ~/.config/laserbrain. Nothing here needs a key or a
network, so a link works between agents on one machine with no account at all.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

def _link_log_default():
    """~/.config/laserbrain/link.jsonl, falling back to the pre-rename tandem.jsonl.

    Renamed 2026-07-27. FOUR files resolve this path independently — this one, waves.py,
    lb_gate.py and mcp-server.mjs — and they must land on the same file. If they do not,
    two agents "sharing" a channel each write to a different log and each reads an empty
    one, which presents exactly as the other agent having said nothing. The legacy path is
    still used when it exists and the new one does not, so an un-migrated machine keeps its
    history instead of silently starting over.
    """
    from . import _paths as _P
    base = _P.config_dir()
    new, old = base / 'link.jsonl', base / 'tandem.jsonl'
    return old if (old.exists() and not new.exists()) else new

LOG = Path(os.environ.get('LASERBRAIN_LINK_LOG')
           or os.environ.get('LASERBRAIN_TANDEM_LOG')
           or _link_log_default())
HUB = os.environ.get('LASERBRAIN_HUB', 'https://phronesis.world/api/laserbrain')


def _agent_name() -> str:
    """Who this process is. Explicit beats guessed, so the env var wins."""
    return os.environ.get('LASERBRAIN_AGENT') or 'unknown'


def link_whoami() -> dict:
    """This agent's identity, the hub it shares, and where the link log lives."""
    return {'agent': _agent_name(), 'hub': HUB, 'log': str(LOG), 'exists': LOG.exists()}


def link_write(text: str, kind: str = 'note', goal: str | None = None,
               payload: dict | None = None, agent: str | None = None) -> dict:
    """Append one record to the shared link. Returns the record written.

    Appends rather than rewrites, so N agents can write concurrently without a lock and
    without any of them being able to erase another's line.
    """
    rec = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
        'agent': agent or _agent_name(),
        'hub': HUB,
        'kind': kind,
        'text': text,
    }
    if goal is not None:
        rec['goal'] = goal
    if payload is not None:
        rec['payload'] = payload
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def _records() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # one malformed line must not blind you to the rest
    return out


def link_read(limit: int = 20, agent: str | None = None, kind: str | None = None) -> list[dict]:
    """Recent records, newest last. Filter by agent or kind to read one voice."""
    recs = _records()
    if agent:
        recs = [r for r in recs if r.get('agent') == agent]
    if kind:
        recs = [r for r in recs if r.get('kind') == kind]
    return recs[-limit:]


def link_agents() -> dict:
    """Everyone on this link and how much each has said.

    The reading that only makes sense once it is N-agent: with two you can see who spoke
    by looking. With five you cannot, and a link where one agent has written everything
    is not a link — it is a log with an audience.
    """
    counts: dict[str, int] = {}
    last: dict[str, str] = {}
    for r in _records():
        a = r.get('agent', 'unknown')
        counts[a] = counts.get(a, 0) + 1
        last[a] = r.get('ts', '')
    return {'agents': sorted(counts), 'count': len(counts),
            'wrote': counts, 'last_seen': last}
