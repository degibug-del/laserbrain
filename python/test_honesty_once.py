"""The honesty note ("distance has not fallen across the last two checks") goes out once per spelled
check in nudge mode, on the check's own call, and not after the agent already said stuck or circling.
Replays a short session through lb_coverage as a subprocess, the way the harness runs it.
Before 2026-11-04 it repeated on every tool call until the next check (239 times for 39 checks in one
session). usage: python3 test_honesty_once.py [dir holding the laserbrain package]"""
import json
import os
import subprocess
import sys
import tempfile

PY = sys.executable
NOTE = "distance has not fallen across the last two checks"


def run(pkg_dir, events):
    state = tempfile.mkdtemp(prefix="lbstate-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("LASERBRAIN_")}
    env['LASERBRAIN_STUDY'] = '1'  # the pre-2026-11-19 text; the quiet default is test_quiet_default.py
    env.update(PYTHONPATH=pkg_dir, LASERBRAIN_STATE_DIR=state, LASERBRAIN_AGENT="claude", HOME=state)
    hits = []
    for i, ev in enumerate(events):
        r = subprocess.run([PY, "-P", "-m", "laserbrain.hooks.lb_coverage"], input=json.dumps(ev), text=True,
                           capture_output=True, env=env, timeout=60)
        if NOTE in (r.stdout + r.stderr):
            hits.append(i)
    return hits


def check(d, prog, agent=None):
    ev = {"hook_event_name": "PostToolUse", "session_id": "honesty-test", "tool_name": "mcp__laserbrain__check_state",
          "tool_input": {"goal": "replay the honesty note", "progress": prog, "distance": d},
          "tool_response": json.dumps({"arm": "sighted", "drifting": False})}
    if agent:
        ev["agent_id"] = agent
    return ev


def bash(agent=None):
    ev = {"hook_event_name": "PostToolUse", "session_id": "honesty-test", "tool_name": "Bash",
          "tool_input": {"command": "true"}, "tool_response": {"stdout": "", "exit_code": 0}}
    if agent:
        ev["agent_id"] = agent
    return ev


SEQ = ([check(3, "advancing")] + [bash()] * 3 +      # 0..3
       [check(3, "advancing")] + [bash()] * 3 +      # 4: equal pair -> one note here, none on 5..7
       [check(3, "stuck")] + [bash()] * 2 +          # 8: equal pair but said stuck -> no note
       [check(3, "advancing")] + [bash()] * 2 +      # 11: equal again, advancing -> one note
       [check(2, "advancing")] + [bash()] * 2)       # 14: distance fell -> nothing

if __name__ == "__main__":
    pkg = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    hits = run(pkg, SEQ)
    sub = run(pkg, [check(4, "advancing", "a1"), bash("a1"), check(4, "advancing", "a1"), bash("a1"), bash("a1")])
    ok = hits == [4, 11] and sub == [2]      # a subagent gets it once too, on its own check
    print("  note on events", hits, "(want [4, 11]); subagent", sub, "(want [2])")
    print("  PASS" if ok else "  FAIL")
    raise SystemExit(0 if ok else 1)
