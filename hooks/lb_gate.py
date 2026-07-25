#!/usr/bin/env python3
"""lb_gate.py — a PreToolUse gate that makes coverage structural instead of optional.

WHY THIS EXISTS. Nudging does not work, and there is now two days of evidence. The
PostToolUse hook counts steps, captures the ground goal, logs failed commands and prints
a reminder every eight steps. Coverage on 2026-07-24 was 10%. On 2026-07-25, with the
nudge firing and a whole protocol written about it, coverage was 6% — it went DOWN.

An advisory that is ignored is not a control. dogfood.py withholds any detection result
below 50%, calibrate.py refuses to derive a profile, and precision has never once been
computed. All of it waits on a number that discipline has failed to move twice.

So this blocks. After BLOCK_AFTER steps without a spelled check, no tool runs until
check_state is called. Coverage stops being a virtue and becomes a precondition.

TWO THINGS IT MUST NEVER DO:

  deadlock — the laserbrain tools are ALWAYS allowed. Blocking check_state while
             demanding check_state is a trap, and it would be the only bug here that
             could not be worked around.

  break    — any exception, any malformed input, any missing session: allow. A gate that
             fails closed takes the session down with it. Every path exits 0 and the
             default is to permit.

Grok notes (2026-07-25):
  - WRITE_TOOLS must include search_replace (Grok's primary edit tool).
  - LASERBRAIN_AGENT is often missing on the hook process (MCP sets it, hooks do not);
    fall back to session file agent so Grok does not self-block on its own claims.
  - tandem entries use agent= or from= — accept both.
  - search_tool is always allowed so a blocked Grok can re-discover laserbrain schemas
    without burning the gate (discovery is read-only).
  - Deny text is agent-aware (Claude MCP name vs Grok use_tool).
"""
import sys, json, os, pathlib, fnmatch

TANDEM_LOG = pathlib.Path(os.environ.get('LASERBRAIN_TANDEM_LOG',
                                         pathlib.Path.home() / '.config/laserbrain/tandem.jsonl'))
# Tools that change files. Reads are never gated on claims — orienting in someone else's
# area is fine; editing it is not.
# Claude: Edit / Write / NotebookEdit / StrReplace
# Grok:   search_replace / write  (search_replace was missing until 2026-07-25 — claim gate blind)
WRITE_TOOLS = (
    'edit', 'write', 'notebookedit', 'str_replace',
    'search_replace',  # Grok Build primary edit tool
)

# Steps without a spelled check before the gate closes. The number is not a taste
# judgement — it fixes the floor, because an agent doing the minimum checks only when
# blocked. Simulated over 400 steps:
#
#     12 -> 8%     6 -> 14%     4 -> 20%     3 -> 25%     2 -> 33%     1 -> 50%
#
# Set to 4 by Diego, 2026-07-25: a 20% floor. That is more than three times the 6% that
# discipline produced, and it does NOT clear the 50% dogfood.py needs — only 1 does, and
# a check between every single tool call is a tax nobody would keep paying. 20% is the
# honest trade: the corpus stays attributable and dense enough to be worth reading, and
# the gate stays closed until someone decides the detection result is worth 1.
BLOCK_AFTER = 4
STATE_DIR = pathlib.Path.home() / '.claude' / 'laserbrain'
# Shared corpus lives under ~/.claude/laserbrain for historical reasons (both agents).
# Alias doc: ~/.config/laserbrain/sessions → same path (see sync / rules).

# Never gated. check_state is how you get out; reset_task starts a new ground; the read
# tools are how an agent orients before spelling its state.
# search_tool: Grok MCP discovery — read-only; blocking it deadlocks a Grok that needs
# the schema before it can call check_state through use_tool.
ALWAYS_ALLOW = (
    'check_state', 'reset_task', 'get_history', 'read_field', 'field_vocabulary',
    'speak_to_field', 'tandem_read', 'tandem_whoami', 'tandem_write', 'drift_grammar',
    'search_tool',  # MCP schema discovery (Grok); not a side-effect tool
)


def entry_agent(r):
    """Who authored a tandem row? Claude uses from=; Grok MCP uses agent=; payload.from too."""
    if not isinstance(r, dict):
        return 'unknown'
    who = r.get('from') or r.get('agent') or (r.get('payload') or {}).get('from')
    return str(who or 'unknown').lower()


def claim_paths(r):
    """Paths locked by a claim row. payload.paths preferred; path-like payload.claims ok."""
    p = r.get('payload') or {}
    paths = list(p.get('paths') or [])
    if not paths:
        for c in p.get('claims') or []:
            if not isinstance(c, str):
                continue
            s = c.strip()
            # path-like only (skip prose claim descriptions)
            if '/' in s or s.endswith(('.py', '.ts', '.tsx', '.js', '.mjs', '.md', '.json')):
                paths.append(s)
    return [x for x in paths if isinstance(x, str) and x.strip()]


def _releases_claims(r):
    """Does this row release the author's standing claims?"""
    k = r.get('kind')
    if k == 'wave_close':
        return True
    if k == 'done':
        p = r.get('payload') or {}
        if p.get('release_claims') or p.get('release') or p.get('event') == 'wave_close':
            return True
        if 'paths' in p and p.get('paths') == []:
            return True
    if k == 'claim':
        p = r.get('payload') or {}
        if p.get('release_claims') or p.get('release'):
            return True
    return False


def claimed_by_others(me):
    """{path: agent} for paths claimed by someone who is not me.

    Two modes:
      1) Open wave — claims with matching payload.wave (or no wave, attached to open
         wave if logged after that wave_open). Closed agents drop out.
      2) Free-form / standing — when no open wave, claims with paths stay active until
         the author wave_close / done(release) / claim(release).

    waves.py refuses overlapping CLAIM at write time; this refuses the EDIT.
    """
    me = (me or 'unknown').lower()
    try:
        rows = [json.loads(l) for l in TANDEM_LOG.read_text().splitlines() if l.strip()]
    except Exception:
        return {}

    opens = [r for r in rows if r.get('kind') == 'wave_open']
    out = {}

    if opens:
        wid = opens[-1].get('payload', {}).get('wave')
        open_idx = max(i for i, r in enumerate(rows) if r.get('kind') == 'wave_open'
                       and (r.get('payload') or {}).get('wave') == wid)
        wave_claims = [r for r in rows if r.get('kind') == 'claim'
                       and (r.get('payload') or {}).get('wave') == wid]
        claimed_agents = {entry_agent(r) for r in wave_claims} - {'unknown'}
        # on_behalf_of first — a forced close is made BY one agent FOR another, so crediting
        # it to the author credits the wrong party. Identical defect to the one fixed in
        # waves.current_wave() on 2026-07-25, and here it deadlocked the protocol outright:
        # grok retired, `force-close --for grok` was recorded and printed success, and the
        # gate still counted grok outstanding. So the wave never closed, the free-form
        # release path below was never reached, and the gate went on holding files for an
        # agent that had gone — including refusing every edit to lb_gate.py itself.
        #
        # A guard with no timeout and no correct release is not strict, it is stuck.
        closed = {(r.get('payload') or {}).get('on_behalf_of') or entry_agent(r) for r in rows
                  if r.get('kind') == 'wave_close'
                  and r.get('payload', {}).get('wave') == wid}
        # Match waves.current_wave: open if outstanding claimants OR no claims yet
        wave_still_open = bool(claimed_agents - closed) or not claimed_agents
        if wave_still_open:
            for i, r in enumerate(rows):
                if r.get('kind') != 'claim':
                    continue
                cw = (r.get('payload') or {}).get('wave')
                if cw is not None and cw != wid:
                    continue
                if cw is None and i < open_idx:
                    continue
                who = entry_agent(r)
                if who == me or who in closed or who == 'unknown':
                    continue
                for path in claim_paths(r):
                    out[path] = who
            return out
        # last wave fully closed → fall through to free-form standing claims

    # free-form standing claims (no open wave, or last wave fully closed)
    active = {}
    for r in rows:
        who = entry_agent(r)
        if who == 'unknown':
            continue
        if _releases_claims(r):
            active.pop(who, None)
            continue
        if r.get('kind') != 'claim':
            continue
        paths = claim_paths(r)
        if not paths:
            continue
        active[who] = {p: True for p in paths}

    for who, paths in active.items():
        if who == me:
            continue
        for path in paths:
            out[path] = who
    return out


def touches(target, claim):
    """Does an edit at `target` fall inside `claim`? Same rule waves.overlaps uses."""
    t, c = str(target).rstrip('/'), str(claim).rstrip('/')
    if not t or not c:
        return False
    if t == c or fnmatch.fnmatch(t, c) or fnmatch.fnmatch(c, t):
        return True
    return (t + '/').startswith(c + '/') or (c + '/').startswith(t + '/')


def edit_target(ev, tool):
    if not any(w in tool for w in WRITE_TOOLS):
        return None
    ti = ev.get('tool_input') or ev.get('toolInput') or {}
    if not isinstance(ti, dict):
        return None
    return ti.get('file_path') or ti.get('path') or ti.get('notebook_path') or ti.get('filePath')


def steps_since_check(sess):
    checks = sess.get('checks') or []
    last = checks[-1].get('step', 0) if checks else 0
    return int(sess.get('steps', 0) or 0) - last


def deny(reason):
    """Emit a block in both shapes and exit. Shared by the coverage and claim gates."""
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
    }}))
    sys.stderr.write(reason + '\n')
    sys.exit(2)


def _tool_of(ev):
    """Match coverage/runtime: peel use_tool envelopes so ALWAYS_ALLOW sees real names."""
    tool = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')
    args = (ev.get('tool_input') if ev.get('tool_input') is not None
            else ev.get('toolInput') if ev.get('toolInput') is not None
            else ev.get('arguments') if ev.get('arguments') is not None
            else {})
    try:
        from laserbrain.runtime import unwrap_tool_args
        tool, _ = unwrap_tool_args(tool, args)
        return tool
    except Exception:
        pass
    # Embedded peel (fail-open if package missing)
    if not isinstance(args, dict):
        try:
            args = json.loads(args) if isinstance(args, str) else {}
        except Exception:
            args = {}
    for _ in range(3):
        nested = str(args.get('tool_name') or args.get('toolName') or args.get('name') or '')
        nested_in = (args.get('tool_input') if args.get('tool_input') is not None
                     else args.get('toolInput') if args.get('toolInput') is not None
                     else None)
        if not nested_in and not nested:
            break
        if nested:
            tool = nested
        if isinstance(nested_in, dict):
            args = nested_in
        elif isinstance(nested_in, str) and nested_in.strip().startswith('{'):
            try:
                args = json.loads(nested_in)
            except Exception:
                break
        else:
            break
        if tool and tool not in ('use_tool', 'CallMcpTool', 'call_mcp_tool', 'mcp_tool'):
            if 'goal' in args or 'progress' in args or not (
                'tool_input' in args or 'toolInput' in args
            ):
                break
    return tool


def resolve_me(ev, sess=None):
    """Who am I for the claim gate?

    Priority: LASERBRAIN_AGENT env (MCP or hook wrapper) → session.agent stamp →
    event agent fields → unknown.
    Unknown is dangerous: own claims look foreign and can self-block.
    """
    env = (os.environ.get('LASERBRAIN_AGENT') or '').strip().lower()
    if env and env != 'unknown':
        return env
    if sess:
        a = str(sess.get('agent') or '').strip().lower()
        if a and a != 'unknown':
            return a
    for k in ('agent', 'agent_name', 'agentName'):
        v = ev.get(k)
        if v and str(v).strip().lower() != 'unknown':
            return str(v).strip().lower()
    return 'unknown'


def check_howto(me):
    """Agent-aware escape hatch text for the coverage deny message."""
    if me == 'grok':
        return (
            'Call laserbrain__check_state via use_tool (tool_name="laserbrain__check_state") '
            'ALONE — do not batch with other tools — with your CURRENT goal, progress '
            '(advancing|stuck|circling) and distance 0-10, then reissue the blocked call. '
            'If you need the schema first, search_tool is always allowed.'
        )
    return (
        'Call mcp__laserbrain__check_state now with your CURRENT goal, progress '
        '(advancing|stuck|circling) and distance 0-10, then reissue the blocked call. '
        'Do not batch check_state with other tools (gate race).'
    )


def load_session(ev):
    sid = (ev.get('session_id') or ev.get('sessionId')
           or os.environ.get('GROK_SESSION_ID') or os.environ.get('CLAUDE_SESSION_ID'))
    if not sid:
        return None, None
    path = STATE_DIR / f'{sid}.json'
    try:
        return sid, json.loads(path.read_text())
    except Exception:
        return sid, None


def main():
    # The gate demands a check_state that only the MCP server can answer. If that server
    # is down — crashed, restarting, misconfigured — the demand is unsatisfiable and the
    # gate blocks every tool call for the rest of the session with no way out. An env var
    # cannot rescue it either: the hook reads its OWN environment, not the environment of
    # the command it is inspecting, so a bypass has to be something a blocked agent can
    # still create. A file is that.
    #
    # Added 2026-07-25 before deliberately restarting the MCP server, but the hazard is
    # general: a guard whose precondition can become impossible needs a door.
    #
    #   touch ~/.config/laserbrain/gate-off     disable
    #   rm    ~/.config/laserbrain/gate-off     re-enable
    if (pathlib.Path.home() / '.config' / 'laserbrain' / 'gate-off').exists():
        return
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return                                   # unparseable → allow

    tool = _tool_of(ev)
    low = tool.lower()
    if any(a in low for a in ALWAYS_ALLOW):
        return                                   # never gate the way out

    sid, sess = load_session(ev)
    me = resolve_me(ev, sess)

    # ── claim gate: never edit into another agent's declared scope ──────────
    target = edit_target(ev, low)
    if target:
        for path, who in claimed_by_others(me).items():
            # match on the tail, since claims are repo-relative and tools pass absolute
            if touches(target, path) or path.rstrip('/') in str(target):
                deny(f'laserbrain claim gate: {path} is claimed by {who} in the open wave.\n'
                     f'THIS CALL DID NOT RUN — nothing was written.\n'
                     f'Editing another agent\'s scope is the collision waves exist to prevent '
                     f'(2026-07-25: app/locus edited while grok was building there).\n'
                     f'Either wait for {who} to close, or say so on the link and agree a '
                     f'handoff before touching it.\n'
                     f'(me={me}; set LASERBRAIN_AGENT on the hook env if this is wrong.)')

    if not sid or not sess:
        return                                   # cannot attribute / no session → do not gate

    since = steps_since_check(sess)
    if since < BLOCK_AFTER:
        return

    steps = int(sess.get('steps', 0) or 0)
    cov = (len(sess.get('checks') or []) / steps) if steps else 0.0
    reason = (
        f'laserbrain gate: {since} steps since your last check_state '
        f'(coverage {cov:.0%} over {steps} steps).\n'
        f'Blocked because nudging did not work — coverage was 10% one day and 6% the '
        f'next while this same reminder printed every 8 steps.\n'
        f'THIS CALL DID NOT RUN. Nothing was written, executed or sent — you must '
        f'reissue it after checking. (A draft composed inside a blocked call is gone: '
        f'on 2026-07-25 a 100-line heredoc was denied here and the file simply did not '
        f'exist, which only surfaced when the next command failed.)\n'
        f'{check_howto(me)}'
    )
    deny(reason)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass                                     # fail OPEN, always
    sys.exit(0)
