#!/usr/bin/env python3
"""
team_runtime.py — run a styled RECURSION TEAM, and close the loop.

The detector reports drift; a recursion team says which drifts return which role.
This is the missing ACT layer: an orchestrator that actually runs the team, checks
each turn against the shared goal (the fixed reference, via multiagent.Dialogue),
and — when a role's policy fires — INJECTS a return-to-ground so the team recovers
instead of spinning. Detection → return → recover, in one loop.

Offline (no key) it proves the loop deterministically: a team left alone echo-
spirals (distance to the goal never falls); with the runtime, the tight role's
return fires, the correction is injected, and the team advances to a resolution.
`--live` swaps the mock agents for two real LLMs (needs the funded key):
    read -rs K && ANTHROPIC_API_KEY="$K" python3 team_runtime.py --live
"""
import sys, re, json
from multiagent import Dialogue, norm

# ── recursion-team presets + styling (mirror of the worker's teams.ts; same
#    policy — the detector is the theorem, this is the per-role return policy) ──
ALL_MODES = ['ungrammatical', 'topic-drift', 'echo-spiral', 'deliberation-stall', 'goal-drift', 'stalled', 'self-report:stuck', 'self-report:circling']
DEPTH = {
    'deep': {'ungrammatical', 'topic-drift', 'goal-drift'},
    'balanced': {'ungrammatical', 'topic-drift', 'goal-drift', 'echo-spiral', 'self-report:stuck', 'self-report:circling'},
    'tight': set(ALL_MODES),
}
PRESETS = {
    'deep-search': [
        {'role': 'explorer', 'recurse': 'deep'},
        {'role': 'checker', 'recurse': 'tight', 'return': 'Restate the goal and verify the last step against it.'},
    ],
    'iterative-refinement': [
        {'role': 'drafter', 'recurse': 'balanced'},
        {'role': 'critic', 'recurse': 'balanced', 'modes': ['echo-spiral', 'topic-drift', 'ungrammatical'], 'return': 'You are agreeing, not improving. Name one concrete flaw and change it.'},
    ],
    'adversarial-deliberation': [
        {'role': 'advocate-a', 'recurse': 'deep'},
        {'role': 'advocate-b', 'recurse': 'deep'},
        {'role': 'synthesizer', 'recurse': 'tight', 'return': 'The debate is looping. State the single decision that resolves the shared goal.'},
    ],
}

def style_return(reason, role):
    if reason in ('advancing', 'grounded'):
        return False
    acts = set(role['modes']) if role.get('modes') else DEPTH.get(role['recurse'], DEPTH['balanced'])
    return reason in acts

# ── mock agents (offline): a team echo-spirals until a return is injected, then
#    it advances toward the goal, distance falling to resolution ────────────────
def mock_turn(role, turn, corrective):
    if corrective is None:
        return (f"{role['role']}: I agree — a fair structure is what we need.", 7)          # spiral: flat distance, high agreement
    steps = ['authority splits into a science council and an elected steward',
             'the steward is recalled by council supermajority, one-year terms',
             'disputes go to a three-member panel drawn by lot',
             'ratified: council, steward, lot-drawn panel — decided']
    i = min(corrective, len(steps) - 1)
    return (f"{role['role']}: {steps[i]}", max(0, 5 - corrective * 2))                       # corrective: distance falls

# ── live agents (needs the funded key) ───────────────────────────────────────
def live_turn(role, goal, convo, injected):
    import mcp_harness as mh
    sysmsg = (f"You are the {role['role']} (recursion style: {role['recurse']}) in a team resolving a shared goal. "
              "Add ONE substantive turn, then a state line: STATE then JSON "
              "{\"goal\":\"<the ORIGINAL shared goal>\",\"position\":\"<your stance>\",\"distance\":<0-10 to resolved>}. "
              "Hold the goal fixed; advance it, do not merely agree.")
    if injected:
        convo = convo + [{'role': 'user', 'content': f"[return to ground] {injected}"}]
    txt = mh.call(mh.MODEL, sysmsg, convo, 400)
    convo.append({'role': 'assistant', 'content': txt})
    i = txt.find('STATE'); m = re.search(r"\{.*?\}", txt[i:] if i >= 0 else txt, re.S)
    try:
        o = json.loads(m.group(0)) if m else {}
    except Exception:
        o = {}
    return o.get('position', ''), o.get('distance', 5)

def run_team(preset, goal, live=False):
    roles = PRESETS[preset]
    print(f"\n  team: {preset}  ·  goal: {goal}")
    print(f"  roles: " + ", ".join(f"{r['role']}({r['recurse']})" for r in roles))
    dlg = Dialogue(goal)
    convo = [{'role': 'user', 'content': goal}]
    corrective = None        # None = not yet returned; else the corrective-step counter
    injected = None
    for turn in range(12):
        role = roles[turn % len(roles)]
        if live:
            pos, dist = live_turn(role, goal, convo, injected)
        else:
            pos, dist = mock_turn(role, turn, corrective)
        injected = None
        reason, drifting, m = dlg.step(role['role'], pos, dist, restated_goal=goal if live else None)
        act = style_return(reason, role)
        mark = '  ⚑ RETURN' if act else ''
        print(f"    {role['role']:12}({role['recurse']:8}): {reason:18} echo={m['echo']:<4} dist={m['dist']}{mark}")
        if act and corrective is None:
            injected = role.get('return', 'Return to the shared goal and take the step that most directly resolves it.')
            print(f"      ↩ runtime injects: \"{injected}\"")
            corrective = 0
        elif corrective is not None:
            corrective += 1
        if dist == 0:
            print("      ✓ resolved — the team reached the shared goal.")
            break
    print("  (no return / no resolution)" if corrective is None else "")

if __name__ == '__main__':
    GOAL = "decide the governance structure for a lunar research colony"
    live = '--live' in sys.argv
    team = next((a for a in sys.argv[1:] if a in PRESETS), 'adversarial-deliberation')
    if live:
        import mcp_harness as mh
        mh.KEY = mh.api_key()
    print("team_runtime.py — run a styled recursion team and close the detect→return→recover loop")
    run_team(team, GOAL, live=live)
    if not live:
        print("\n  READ: left alone the team echo-spirals (flat distance). The runtime catches it via")
        print("  the tight role's policy, injects the return, and the team advances to a resolution —")
        print("  the ACT layer: detection is only useful if something returns the team to ground.")
        print("  (offline mock demo. For two real LLM agents: python3 team_runtime.py --live)")
