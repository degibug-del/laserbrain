#!/usr/bin/env python3
"""A stand-in for `claude -p` that the harness tests launch instead of the real CLI.

It reads the episode's --settings and --mcp-config, plays a scripted list of tool calls
from $FAKE_CLAUDE_SCRIPT, and runs the episode's REAL hook commands around each call
(PreToolUse deny / exit 2 blocks the call; PostToolUse additionalContext is appended to
the tool result), so injection, the step log, the cap and laserbrain's own hooks are
exercised end to end without a model. Output is stream-json like the real CLI.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid


def arg(name, default=None):
    a = sys.argv
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) else default
    return default


def emit(obj):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()


def run_hooks(settings, event, payload, tool=None):
    outs = []
    for group in (settings.get('hooks') or {}).get(event) or []:
        m = group.get('matcher')
        if tool is not None and m not in (None, '', '*') and not re.fullmatch(m, tool):
            continue
        for h in group.get('hooks') or []:
            cp = subprocess.run(h['command'], shell=True, input=json.dumps(payload),
                                capture_output=True, text=True, timeout=h.get('timeout', 60))
            outs.append(cp)
            emit({'type': 'system', 'subtype': 'hook_response', 'hook_event': event,
                  'hook_name': f'{event}:{tool or ""}', 'exit_code': cp.returncode,
                  'command': h['command'][-80:]})
    return outs


def last_json(text):
    for line in reversed((text or '').strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {}


def perform(tool, inp, act):
    cwd = pathlib.Path.cwd()
    if tool == 'Write':
        p = cwd / inp['file_path']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp.get('content', ''))
        return f'File written: {inp["file_path"]}'
    if tool == 'Edit':
        p = cwd / inp['file_path']
        p.write_text(p.read_text().replace(inp['old_string'], inp['new_string']))
        return 'Edited'
    if tool == 'Read':
        p = cwd / inp['file_path']
        return p.read_text() if p.exists() else 'File does not exist.'
    if tool.endswith('check_state'):
        return json.dumps(act.get('result') or {'drifting': False, 'reason': 'grounded'})
    return act.get('output', 'ok')


def main():
    t0 = time.monotonic()
    settings = json.loads(pathlib.Path(arg('--settings')).read_text()) if arg('--settings') else {}
    mc = arg('--mcp-config') or '{}'
    mcp = json.loads(mc if mc.lstrip().startswith('{') else pathlib.Path(mc).read_text())
    sid = arg('--session-id') or str(uuid.uuid4())
    prompt = sys.stdin.read()
    sp = os.environ.get('FAKE_CLAUDE_SCRIPT')
    script = json.loads(pathlib.Path(sp).read_text()) if sp and arg('--settings') else {'actions': []}
    if os.environ.get('FAKE_CLAUDE_NOT_LOGGED_IN'):
        emit({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'Not logged in · Please run /login'}]}})
        emit({'type': 'result', 'subtype': 'success', 'is_error': True, 'num_turns': 1,
              'result': 'Not logged in · Please run /login', 'total_cost_usd': 0, 'usage': {}})
        return
    if os.environ.get('FAKE_CLAUDE_ARGV_LOG'):
        pathlib.Path(os.environ['FAKE_CLAUDE_ARGV_LOG']).write_text(json.dumps(
            {'argv': sys.argv[1:], 'env_keys': sorted(os.environ), 'prompt': prompt}))
    servers = list((mcp.get('mcpServers') or {}).keys())
    emit({'type': 'system', 'subtype': 'init', 'session_id': sid, 'cwd': os.getcwd(),
          'tools': (arg('--tools') or '').split(',') + [f'mcp__{s}__check_state' for s in servers],
          'mcp_servers': [{'name': s, 'status': 'connected'} for s in servers],
          'model': arg('--model'), 'permissionMode': arg('--permission-mode'),
          'slash_commands': [], 'skills': [], 'plugins': []})
    base = {'session_id': sid, 'cwd': os.getcwd(), 'transcript_path': ''}
    run_hooks(settings, 'UserPromptSubmit', dict(base, hook_event_name='UserPromptSubmit', prompt=prompt))
    sleep = float(os.environ.get('FAKE_CLAUDE_SLEEP') or 0)
    state = {'n': 0}

    def play(actions):
        for act in actions:
            if sleep:
                time.sleep(sleep)
            state['n'] += 1
            tid = f"toolu_{state['n']:03d}"
            tool, inp = act['tool'], act.get('input', {})
            emit({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': tid, 'name': tool, 'input': inp}]}})
            pre = dict(base, hook_event_name='PreToolUse', tool_name=tool, tool_input=inp, tool_use_id=tid)
            blocked = None
            for cp in run_hooks(settings, 'PreToolUse', pre, tool):
                if cp.returncode == 2:
                    blocked = blocked or (cp.stderr.strip() or 'blocked')
                    continue
                hso = last_json(cp.stdout).get('hookSpecificOutput') or {}
                if hso.get('permissionDecision') == 'deny':
                    blocked = blocked or hso.get('permissionDecisionReason')
            if blocked:
                emit({'type': 'user', 'message': {'role': 'user', 'content': [
                    {'type': 'tool_result', 'tool_use_id': tid, 'is_error': True,
                     'content': f'PreToolUse:{tool} hook error: {blocked}'}]}})
                continue
            result = perform(tool, inp, act)
            post = dict(pre, hook_event_name='PostToolUse', tool_response=result)
            ctx = []
            for cp in run_hooks(settings, 'PostToolUse', post, tool):
                c = (last_json(cp.stdout).get('hookSpecificOutput') or {}).get('additionalContext')
                if c:
                    ctx.append(c)
            content = result + ''.join(f'\n<system-reminder>{c}</system-reminder>' for c in ctx)
            emit({'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': tid, 'is_error': False, 'content': content}]}})

    play(script.get('actions', []))
    # Stop hooks: like the real CLI, {"decision": "block", "reason": ...} keeps the agent
    # going with the reason as its next instruction. The script's after_stop actions are
    # what the agent does then (played once; a second block just ends the run).
    after = list(script.get('after_stop') or [])
    for _ in range(3):
        reasons = [last_json(cp.stdout).get('reason') for cp in
                   run_hooks(settings, 'Stop', dict(base, hook_event_name='Stop', stop_hook_active=_ > 0))
                   if last_json(cp.stdout).get('decision') == 'block']
        if not reasons:
            break
        emit({'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'text', 'text': 'Stop hook feedback:\n' + '\n'.join(str(r) for r in reasons)}]}})
        play(after)
        after = []
    n = state['n']
    emit({'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': n + 1,
          'duration_ms': int((time.monotonic() - t0) * 1000), 'total_cost_usd': round(0.001 * n, 4),
          'usage': {'input_tokens': 100 * n, 'output_tokens': 20 * n,
                    'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 50 * n},
          'result': script.get('final', 'done'), 'session_id': sid})


if __name__ == '__main__':
    main()
