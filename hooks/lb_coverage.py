#!/usr/bin/env python3
"""lb_coverage.py — PostToolUse / UserPromptSubmit / Stop hook for laserbrain coverage.

Makes coverage automatic instead of remembered. Works for Claude Code (snake_case)
and Grok Build (camelCase). Same session directory: ~/.claude/laserbrain.

WHY THIS EXISTS. On 2026-07-24 a long, error-dense session produced ten independently
caught errors and ONE laserbrain check across ~48 steps — 2% coverage. The agent
had a standing order to call check_state each step and did not. That is not a
discipline problem to be solved by more discipline: "remember to call it every step"
is not an interface.

WHAT IT CAN AND CANNOT DO. A hook is a shell command; it cannot spell the agent's
goal, progress or distance, so it cannot call check_state on the agent's behalf.
What it can do is:

  1. COUNT the steps (dogfood denominator).
  2. LOG catches it can see (non-zero shell exits).
  3. INTERRUPT when coverage lapses:
       - Claude: PostToolUse additionalContext
       - Grok: Stop gate with decision=block (PostToolUse stdout is ignored)

SAFETY. Every path is wrapped; exits 0 unconditionally except intentional stop-blocks.
A hook that crashes the tool it observes is worse than no hook.
"""
import json, os, sys, pathlib, datetime

NUDGE_AFTER = 8
WINDOW, REPEAT, FAILS = 6, 3, 2   # must match laserbrain.observe — test_hook_parity.py pins this
STATE_DIR = pathlib.Path.home() / '.claude' / 'laserbrain'
# Written when the user speaks, consumed by mcp-server.mjs on the next check_state. A file
# rather than shared memory because the hook and the MCP server are separate processes with
# no channel between them; this is the whole channel.
USER_TURN = pathlib.Path.home() / '.config' / 'laserbrain' / 'user-turn'


def _mark_user_turn():
    """The user just spoke, so the next check_state is a re-ground rather than a drift.

    Called from BOTH the primary path and the embedded fallback. They are separate routes
    through this hook and only one runs on any given invocation, which is precisely how
    the first attempt at this fix came to be inert: it was written into the fallback only.
    """
    try:
        USER_TURN.parent.mkdir(parents=True, exist_ok=True)
        # UTC, matching the drift log's new Date().toISOString(). They disagreed until
        # 2026-07-26, and the cost was a wrong diagnosis: a goal-drift fire logged at
        # 01:25 UTC was compared against a flag stamped 19:36 local, which made a fire
        # that happened BEFORE the flag look like it happened seven hours after — i.e.
        # like reground was broken when it was working correctly. One clock per system.
        USER_TURN.write_text(
            datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
    except Exception:
        pass          # fail open: a missing flag only restores the old behaviour


def infer_progress(events):
    """advancing | stuck | circling, from the tool trace alone.

    Deliberately DUPLICATED from laserbrain.observe.Observer rather than imported. A hook
    runs against whatever python3 is on PATH, and that interpreter may lag the working
    tree. The copy is small and test_hook_parity.py fails if the two ever disagree.
    """
    w = events[-WINDOW:]
    if not w:
        return 'advancing'
    sigs = [e['sig'] for e in w]
    if sigs.count(sigs[-1]) >= REPEAT:
        return 'circling'
    trailing = 0
    for e in reversed(events):
        if e['ok']:
            break
        trailing += 1
    return 'stuck' if trailing >= FAILS else 'advancing'


def load(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {'id': path.stem, 'started': datetime.datetime.now().isoformat(timespec='seconds'),
                'goal': None, 'steps': 0, 'checks': [], 'inferred': [], 'catches': [], 'events': []}


def _sid(ev):
    return str(
        ev.get('session_id') or ev.get('sessionId')
        or os.environ.get('GROK_SESSION_ID')
        or os.environ.get('CLAUDE_SESSION_ID')
        or 'unknown'
    )


def _tool(ev):
    return str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '')


def _args(ev):
    a = (ev.get('tool_input') if ev.get('tool_input') is not None
         else ev.get('toolInput') if ev.get('toolInput') is not None
         else ev.get('arguments') if ev.get('arguments') is not None
         else {})
    return a if isinstance(a, dict) else {'_': a}


def _verdict(resp):
    """Pull {drifting, reason, phi} out of a check response, whatever shape it arrives in.

    This replaced a substring match on the serialised response:

        '"drifting": true' in text.lower() or '"drifting":true' in text.lower()

    which returned False for EVERY fire and did so silently. The reason is that an MCP
    response arrives wrapped — {"content":[{"type":"text","text":"{...}"}]} — and
    json.dumps escapes the inner quotes, so the serialised text contains \\"drifting\\"
    and neither pattern can match. Verified 2026-07-25: bare dicts and raw JSON strings
    were detected, the wrapped form never was.

    The cost was the whole corpus. 204 checks across 10 sessions recorded zero fires,
    including 104 checks sitting below the 0.30 threshold that DEFINES goal-drift, while
    the agent was being told it had drifted in the same breath. The verdicts had to be
    rebuilt from chat transcripts because the session files never held them.

    So: parse, do not pattern-match. Walk the structure, decode any JSON carried as a
    string, and read the field as the boolean it is. `reason` and `phi` are captured too
    — the old code wrote the literal 'see response', which made it impossible to ask the
    corpus which SIGNAL fired, and that question is the whole point of the corpus.
    """
    def walk(x, depth=0):
        if depth > 6 or isinstance(x, bool):
            return None
        if isinstance(x, dict):
            if isinstance(x.get('drifting'), bool):
                return x
            for val in x.values():
                got = walk(val, depth + 1)
                if got is not None:
                    return got
        elif isinstance(x, list):
            for val in x:
                got = walk(val, depth + 1)
                if got is not None:
                    return got
        elif isinstance(x, str):
            t = x.strip()
            if t[:1] in ('{', '['):
                try:
                    return walk(json.loads(t), depth + 1)
                except Exception:
                    return None
        return None

    found = walk(resp) or {}
    return {'drifting': bool(found.get('drifting')),
            'reason': str(found.get('reason') or 'unparsed'),
            'phi': found.get('phi')}


def _resp(ev):
    r = (ev.get('tool_response') if ev.get('tool_response') is not None
         else ev.get('toolResult') if ev.get('toolResult') is not None
         else ev.get('output') if ev.get('output') is not None
         else {})
    return r


def _unwrap(tool, args):
    """Grok may route MCP as use_tool with nested tool_name."""
    if tool not in ('use_tool', 'CallMcpTool', 'call_mcp_tool', 'mcp_tool'):
        return tool, args
    nested = str(args.get('tool_name') or args.get('toolName') or args.get('name') or '')
    nested_in = (args.get('tool_input') if args.get('tool_input') is not None
                 else args.get('toolInput') if args.get('toolInput') is not None
                 else args.get('arguments') if args.get('arguments') is not None
                 else args)
    if nested:
        return nested, nested_in if isinstance(nested_in, dict) else args
    return tool, args


def _is_check(tool):
    return tool.lower().endswith('check_state')


def _is_reset(tool):
    t = tool.lower()
    return t.endswith('reset_task') or t.endswith('__reset_task')


def _is_shell(tool):
    return tool in ('Bash', 'run_terminal_command', 'Shell', 'bash')


def _event_name(ev):
    return str(ev.get('hookEventName') or ev.get('hook_event_name')
               or os.environ.get('GROK_HOOK_EVENT') or '').lower()


def _emit_claude_nudge(nudge, event='PostToolUse'):
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': event,
            'additionalContext': nudge,
        }
    }))


def _emit_grok_stop_block(nudge):
    # Grok Stop hooks: decision=block feeds reason back and keeps the agent working.
    print(json.dumps({'decision': 'block', 'reason': nudge}))


def main():
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        ev = {}

    # Prefer the shared implementation when the installed package has Grok support.
    try:
        from laserbrain.runtime import from_claude_code, from_grok, Session, session_id_of
        has_runtime = True
    except Exception:
        has_runtime = False
        from_claude_code = from_grok = Session = session_id_of = None

    ename = _event_name(ev)
    is_grok = bool(os.environ.get('GROK_SESSION_ID') or os.environ.get('GROK_HOOK_EVENT')
                   or ev.get('sessionId') is not None or ev.get('toolName') is not None
                   or ev.get('toolInput') is not None)

    # ── Stop gate (Grok primary injection path) ─────────────────────────────
    # Only genuine turn ends. Session-end Stop is observe-only.
    if 'stop' in ename and 'failure' not in ename:
        reason = str(ev.get('reason') or '')
        if reason and reason != 'end_turn':
            return
        try:
            if has_runtime:
                sid = session_id_of(ev)
                s = Session(sid, directory=str(STATE_DIR))
                warn = s.coverage_warning() if hasattr(s, 'coverage_warning') else s.nudge()
            else:
                path = STATE_DIR / f'{_sid(ev)}.json'
                st = load(path)
                steps = int(st.get('steps') or 0)
                checks = st.get('checks') or []
                last = checks[-1]['step'] if checks else 0
                since = steps - last
                warn = None
                if since >= NUDGE_AFTER:
                    cov = len(checks) / steps if steps else 0
                    warn = (f'laserbrain: {since} steps since your last check_state '
                            f'(coverage {cov:.0%} over {steps} steps). dogfood.py withholds any '
                            f'detection result below 50%. Call check_state now with your CURRENT '
                            f'goal, progress (advancing|stuck|circling) and distance 0-10.')
            if warn:
                if is_grok:
                    _emit_grok_stop_block(warn)
                else:
                    _emit_claude_nudge(warn, event='Stop')
        except Exception:
            pass
        return

    # ── Shared Session path when import works ───────────────────────────────
    if has_runtime:
        try:
            if is_grok:
                nudge = from_grok(ev, directory=str(STATE_DIR))
            else:
                nudge = from_claude_code(ev, directory=str(STATE_DIR))
            # Session-start / prompt: remind multi-agent link hygiene + honest progress.
            promptish = (ev.get('prompt') is not None
                         or ev.get('userPrompt') is not None
                         or ev.get('promptText') is not None
                         or 'prompt' in ename or 'userprompt' in ename.replace('_', ''))
            extras = []
            if promptish:
                # Mark that the NEXT check_state is a re-ground, not a drift. See the long
                # note in the embedded fallback below for why this exists.
                #
                # This copy is the one that RUNS. The first version of the fix was written
                # only into the fallback branch, which fires solely when importing
                # laserbrain.runtime fails — so the flag was never written, no reground
                # ever happened, and the whole patch was inert while every test passed.
                # test_reground.py drives the MCP server directly and simulates the flag
                # itself, so it could not have caught this. Only asking the live hook for
                # the file did.
                _mark_user_turn()
                extras.append(
                    'laserbrain link: multi-step work in a shared repo → tandem_read '
                    '(limit≥10) and answer open claims before first write. '
                    'Gate: never batch non-laserbrain tools with the check_state that '
                    'clears the gate — check alone, then reissue. '
                    'Subagents: parent check_state between spawn waves; children do not '
                    'share parent harness Φ.'
                )
            # Subagent spawn: structural reminder (parent must check between waves)
            try:
                tname = str(ev.get('tool_name') or ev.get('toolName') or ev.get('name') or '').lower()
                if any(x in tname for x in (
                    'spawn_subagent', 'task', 'agent', 'subagent',
                )) and 'check_state' not in tname:
                    extras.append(
                        'laserbrain subagent: child sessions have their own Φ. '
                        'check_state on the parent before the next spawn wave; '
                        'do not assume coverage from the child.'
                    )
            except Exception:
                pass
            # Honesty: if last two spelled checks show same distance while not done, nudge.
            try:
                sid = session_id_of(ev)
                s = Session(sid, directory=str(STATE_DIR))
                checks = s.d.get('checks') or []
                if len(checks) >= 2:
                    a, b = checks[-2], checks[-1]
                    da, db = a.get('distance'), b.get('distance')
                    if da is not None and da == db and da not in (0, '0', 0.0):
                        extras.append(
                            'laserbrain honesty: distance has not fallen across the last '
                            'two checks. If you are circling or stuck, say so — false '
                            'advancing wastes the dogfood corpus.'
                        )
            except Exception:
                pass
            if extras and not is_grok:
                _emit_claude_nudge('\n'.join(extras) + (('\n' + nudge) if nudge else ''))
            elif nudge and not is_grok:
                _emit_claude_nudge(nudge)
            elif extras and is_grok and promptish:
                # Grok UserPromptSubmit: try Claude-compatible additionalContext.
                print(json.dumps({
                    'hookSpecificOutput': {
                        'hookEventName': 'UserPromptSubmit',
                        'additionalContext': '\n'.join(extras),
                    }
                }))
            elif nudge and is_grok:
                # PostToolUse stdout ignored on Grok — still record; Stop will gate.
                pass
            return
        except Exception:
            pass  # fall through to embedded copy

    # ── Embedded fallback (older laserbrain or import failure) ──────────────
    try:
        sid = _sid(ev)
        tool = _tool(ev)
        args = _args(ev)
        tool, args = _unwrap(tool, args)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = STATE_DIR / f'{sid}.json'
        s = load(path)
        s.setdefault('inferred', []); s.setdefault('events', []); s.setdefault('goal', None)

        prompt = ev.get('prompt')
        if prompt is None:
            prompt = ev.get('userPrompt') if ev.get('userPrompt') is not None else ev.get('promptText')
        if prompt is not None and not tool:
            if not s.get('goal'):
                s['goal'] = str(prompt)[:400]
            # Mark that the NEXT check_state is a re-ground, not a drift.
            #
            # check_state receives only (goal, progress, distance), and none of those says
            # whether the goal changed because the user changed it. That missing bit made
            # goal-drift 24 of 35 fires in the whole recovered corpus with ZERO coinciding
            # real errors — 22 of the 24 on the first check after Diego spoke. The rule was
            # faithfully reporting that the subject had changed. It had. He changed it.
            #
            # Thresholding on goal overlap cannot substitute: the anchor values at those 24
            # fires run continuously from 0.00 to 0.29 with no gap, so any cut just weakens
            # the rule for everyone. The discriminator genuinely lives out here.
            _mark_user_turn()
            path.write_text(json.dumps(s, indent=2))
            return

        if _is_reset(tool):
            # Archive, then clear — mirroring Session.reset in laserbrain.runtime. This
            # branch only runs when importing the SDK failed, but it must not behave
            # differently when it does: a fallback that silently loses data is worse than
            # one that fails outright, because nothing reports it.
            if int(s.get('steps', 0)) > 0:
                s.setdefault('segments', []).append({
                    'goal': s.get('goal'),
                    'steps': int(s.get('steps', 0)),
                    'checks': s.get('checks', []),
                    'inferred': s.get('inferred', []),
                    'catches': s.get('catches', []),
                    'ended': datetime.datetime.now().isoformat(timespec='seconds'),
                })
            s.update(steps=0, checks=[], inferred=[], catches=[], events=[], goal=None)
            path.write_text(json.dumps(s, indent=2))
            return

        if not tool:
            return

        s['steps'] = int(s.get('steps', 0)) + 1
        step = s['steps']

        if _is_check(tool):
            resp = _resp(ev)
            ti = args
            v = _verdict(resp)
            s['checks'].append({'step': step,
                                'drifting': v['drifting'],
                                'goal': str(ti.get('goal', ''))[:400],
                                'progress': str(ti.get('progress', '')),
                                'distance': ti.get('distance'),
                                'reason': v['reason'],
                                'phi': v['phi']})
            path.write_text(json.dumps(s, indent=2))
            return

        ok_flag = True
        if 'failure' in ename:
            ok_flag = False
        resp0 = _resp(ev)
        if isinstance(resp0, dict):
            code = resp0.get('exit_code')
            if code is None:
                code = resp0.get('exitCode')
            if isinstance(code, int):
                ok_flag = code == 0
            elif resp0.get('error') or resp0.get('is_error') or resp0.get('isError'):
                ok_flag = False

        if _is_shell(tool) and not ok_flag:
            cmd = str(args.get('command', ''))[:120]
            s['catches'].append({'step': step, 'by': 'build', 'what': f'non-zero exit: {cmd}'})

        try:
            args_s = json.dumps(args, sort_keys=True, default=str)[:400]
        except Exception:
            args_s = ''
        s['events'].append({'sig': f'{tool}|{args_s}', 'ok': ok_flag})
        s['events'] = s['events'][-40:]
        s['inferred'].append({'step': step, 'progress': infer_progress(s['events'])})
        s['inferred'] = s['inferred'][-200:]

        last = s['checks'][-1]['step'] if s['checks'] else 0
        since = step - last
        path.write_text(json.dumps(s, indent=2))

        if since >= NUDGE_AFTER and since % NUDGE_AFTER == 0 and not is_grok:
            cov = len(s['checks']) / step if step else 0
            _emit_claude_nudge(
                f'laserbrain: {since} steps since your last check_state '
                f'(coverage {cov:.0%} over {step} steps). dogfood.py withholds any '
                f'detection result below 50%. Call check_state now with your CURRENT '
                f'goal, progress (advancing|stuck|circling) and distance 0-10.'
            )
    except Exception:
        pass


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
