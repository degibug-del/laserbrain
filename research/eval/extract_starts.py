#!/usr/bin/env python3
"""extract_starts.py — one row per subagent START, for EVAL-PLAN step 8.

For each subagent transcript under a Claude Code session directory it records:

  user_relayed   the "user request" the workflow harness relayed into the prompt (often
                 only Diego's LATEST message — the D1-D3 failure)
  user_recent    Diego's own messages in the main session before the agent started
                 (prompts and mid-turn queued messages), newest last
  task           the task text handed to the agent (the computed workflow prompt)
  goal           the agent's first check_state goal, and `plan`, its first stated text
  early_text     the agent's text before its first acting call (where a refusal shows)
  final_text     the agent's last text or StructuredOutput (where a refusal is reported)

Read-only on transcripts. Every text field passes through lb_secrets redaction; a field
that cannot be redacted is written as null.

Usage:
  extract_starts.py SESSION.jsonl [SESSION.jsonl ...] > starts.jsonl
  extract_starts.py --all [--projects ~/.claude/projects/-] > starts.jsonl
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import redact, split_of, write_jsonl  # noqa: E402

RECENT_N = 6                     # how many main-session user messages to keep per start
RECENT_WINDOW_H = 12             # ...within this many hours before the start
TEXT_CAP = 6000

_SKIP_PREFIX = ('<task-notification', '<command-', '<local-command', '<system-reminder',
                '[Request interrupted', 'Caveat:', '<bash-', '<user-memory')
READ_TOOLS = ('read', 'grep', 'glob', 'ls', 'toolsearch', 'search', 'find', 'get_', 'list_',
              'check_state', 'reset_task', 'webfetch', 'websearch')


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
            return None
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return None


def _ts_key(ts):
    return str(ts or '')


def main_user_messages(session_jsonl):
    """[(ts, kind, text)] for Diego's own messages in the main session."""
    out = []
    try:
        fh = open(session_jsonl, encoding='utf-8')
    except OSError:
        return out
    with fh:
        for line in fh:
            if '"user"' not in line and 'queue-operation' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get('type')
            if t == 'user' and not r.get('isMeta') and not r.get('toolUseResult') \
                    and not r.get('isSidechain'):
                txt = _text_of((r.get('message') or {}).get('content'))
                kind = 'prompt'
            elif t == 'queue-operation' and r.get('operation') == 'enqueue':
                txt = r.get('content') if isinstance(r.get('content'), str) else None
                kind = 'queued'
            else:
                continue
            if not txt or not txt.strip() or txt.lstrip().startswith(_SKIP_PREFIX):
                continue
            out.append((r.get('timestamp'), kind, txt.strip()))
    out.sort(key=lambda x: _ts_key(x[0]))
    return out


_HARNESS = re.compile(r'^\[Workflow harness[^\]]*\][^\n]*\n?', re.S)


def _strip_harness(text):
    """Drop a '[Workflow harness — ...]' header line and dedent the indented body."""
    if not text:
        return text
    body = _HARNESS.sub('', text, count=1)
    lines = body.split('\n')
    if lines and all(l.startswith('  ') or not l.strip() for l in lines):
        lines = [l[2:] for l in lines]
    return '\n'.join(lines).strip()


def _hours_between(a, b):
    from datetime import datetime
    try:
        fa = datetime.fromisoformat(str(a).replace('Z', '+00:00'))
        fb = datetime.fromisoformat(str(b).replace('Z', '+00:00'))
        return (fb - fa).total_seconds() / 3600
    except Exception:
        return None


def parse_agent(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return None
    start_ts = next((r.get('timestamp') for r in rows if r.get('timestamp')), None)
    agent_id = next((r.get('agentId') for r in rows if r.get('agentId')), path.stem.replace('agent-', ''))

    # The opening user turns, before the first assistant turn.
    opening = []
    for r in rows:
        if r.get('type') == 'assistant':
            break
        if r.get('type') == 'user':
            txt = _text_of((r.get('message') or {}).get('content'))
            if txt and txt.strip():
                opening.append(txt)
    relayed, task = None, None
    for txt in opening:
        head = txt.lstrip()[:80].lower()
        if head.startswith('[workflow harness') and 'user request' in head:
            relayed = _strip_harness(txt)
        elif head.startswith('[workflow harness') and 'computed task' in head:
            task = _strip_harness(txt)
        elif task is None:
            task = txt.strip()
        else:
            task = task + '\n\n' + txt.strip()

    # What check_state SAID (the current product's verdicts), keyed by tool_use id.
    results = {}
    for r in rows:
        if r.get('type') != 'user':
            continue
        c = (r.get('message') or {}).get('content')
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get('type') == 'tool_result':
                body = b.get('content')
                if isinstance(body, list):
                    body = ''.join(x.get('text', '') for x in body if isinstance(x, dict))
                results[b.get('tool_use_id')] = body if isinstance(body, str) else ''
    checks = []

    goal = goal_idx = plan = None
    early, final_text, n_tools, acted = [], None, 0, False
    for r in rows:
        if r.get('type') != 'assistant':
            continue
        for b in (r.get('message') or {}).get('content') or []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' \
                    and str(b.get('name') or '').endswith('check_state'):
                v = {}
                try:
                    v = json.loads(results.get(b.get('id')) or '{}')
                except Exception:
                    v = {}
                checks.append({'drifting': v.get('drifting'), 'reason': v.get('reason'),
                               'phi': v.get('phi'), 'goal_score': v.get('goal_score')})
        for b in (r.get('message') or {}).get('content') or []:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'text' and b.get('text', '').strip():
                t = b['text'].strip()
                if plan is None:
                    plan = t
                if not acted:
                    early.append(t)
                final_text = t
            elif b.get('type') == 'tool_use':
                n_tools += 1
                name = str(b.get('name') or '')
                inp = b.get('input') or {}
                if goal is None and name.endswith('check_state') and isinstance(inp, dict):
                    goal, goal_idx = inp.get('goal'), n_tools
                if name == 'StructuredOutput':
                    final_text = json.dumps(inp, ensure_ascii=False)
                if not any(k in name.lower() for k in READ_TOOLS):
                    acted = True
    return {
        'agent_id': agent_id, 'agent': str(agent_id)[:10], 'start_ts': start_ts,
        'user_relayed': relayed, 'task': task, 'goal': goal, 'goal_tool_index': goal_idx,
        'plan': plan, 'early_text': '\n'.join(early)[:3000] if early else None,
        'final_text': final_text, 'n_tool_calls': n_tools,
        'checks': checks,
    }


def starts_for_session(session_jsonl):
    session_jsonl = pathlib.Path(session_jsonl)
    sdir = session_jsonl.with_suffix('')
    users = main_user_messages(session_jsonl)
    journals = {}
    for j in sorted((sdir / 'workflows').glob('wf_*.json')):
        try:
            d = json.loads(j.read_text())
            journals[j.stem] = {'name': d.get('workflowName'), 'status': d.get('status')}
        except Exception:
            journals[j.stem] = {}
    paths = sorted((sdir / 'subagents' / 'workflows').glob('wf_*/agent-*.jsonl')) + \
        sorted((sdir / 'subagents').glob('agent-*.jsonl'))
    for p in paths:
        try:
            a = parse_agent(p)
        except Exception as e:                                  # one bad file must not stop the run
            print(f'skip {p.name}: {type(e).__name__}', file=sys.stderr)
            continue
        if not a:
            continue
        wf = p.parent.name if p.parent.name.startswith('wf_') else None
        meta = {}
        mp = p.with_suffix('.meta.json')
        if mp.exists():
            try:
                meta = json.loads(mp.read_text())
            except Exception:
                meta = {}
        before = [u for u in users if _ts_key(u[0]) <= _ts_key(a['start_ts'])]
        recent = [u for u in before[-RECENT_N:]
                  if (_hours_between(u[0], a['start_ts']) or 0) <= RECENT_WINDOW_H]
        row = {
            'id': f"{session_jsonl.stem[:8]}:{wf or '-'}:{a['agent']}",
            'session': session_jsonl.stem, 'workflow': wf,
            'workflow_name': (journals.get(wf) or {}).get('name') if wf else None,
            'role': meta.get('description'), 'phase': meta.get('workflowPhase'),
            'split': split_of(a['start_ts']),
            'user_latest': redact(before[-1][2], 2000) if before else None,
            'user_recent': [{'ts': u[0], 'kind': u[1], 'text': redact(u[2], 2000)} for u in recent],
            **a,
        }
        for k in ('user_relayed', 'task', 'goal', 'plan', 'early_text', 'final_text'):
            row[k] = redact(row[k], TEXT_CAP) if row[k] is not None else None
        yield row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('sessions', nargs='*', help='main-session .jsonl files')
    ap.add_argument('--all', action='store_true', help='every session under --projects')
    ap.add_argument('--projects', default=str(pathlib.Path.home() / '.claude' / 'projects' / '-'))
    ap.add_argument('-o', '--out', help='write here instead of stdout')
    a = ap.parse_args(argv)
    sessions = list(a.sessions)
    if a.all:
        sessions += [str(p) for p in sorted(pathlib.Path(a.projects).glob('*.jsonl'))]
    # Accept the plan's form too: "SESSION.jsonl SESSION/workflows" — the dir is implied.
    sessions = [s for s in sessions if s.endswith('.jsonl')]
    if not sessions:
        ap.error('give at least one SESSION.jsonl, or --all')
    out = open(a.out, 'w', encoding='utf-8') if a.out else sys.stdout
    n = 0
    for s in sessions:
        rows = list(starts_for_session(s))
        write_jsonl(rows, out)
        n += len(rows)
    if a.out:
        out.close()
    print(f'{n} starts from {len(sessions)} session(s)', file=sys.stderr)


if __name__ == '__main__':
    main()
