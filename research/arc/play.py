#!/usr/bin/env python3
"""Play an ARC-AGI-3 game one step at a time, with a real agent in the loop.

    python3 play.py --new                                    # start, show the frame
    python3 play.py --action ACTION3 --progress advancing --distance 8 --why "..."
    python3 play.py --summary                                # the trace and the verdicts

WHY THIS EXISTS SEPARATELY FROM bench.py

bench.py runs a RANDOM agent. It measured 0 of 1,070 "you are going nowhere" verdicts
correct — but a random walker is not the subject laserbrain was built for. It has no
hypothesis to abandon, nothing to be wrong about, and its self-report is a mechanical
readout of whether the frame changed. The negative result is a floor, not a verdict.

This puts a reasoning agent in the same seat, on the same games, with the same observe-only
rule: laserbrain watches, records, and never stops the run. The difference is that
`progress` and `distance` are now a JUDGEMENT — the agent says how it thinks the run is
going, which is what the instrument is designed to read and what it can be wrong about.

WHAT IS DELIBERATELY NOT AUTOMATED

The agent does not read the verdicts. They are written to the trace and shown only by
--summary, after the fact. If the agent saw them it would be steering by them, and the
counterfactual — would this run have got somewhere if left alone — becomes unobservable,
which is exactly what makes bench.py's numbers meaningful.

STATE lives in ./runs/session.json between invocations, so each call is one step and the
run survives across them. Isolated under ./.state like everything else here.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / 'runs'
def session_path(tag):
    return RUNS / (f'session-{tag}.json' if tag else 'session.json')


SESSION = RUNS / 'session.json'

BENCH_HOME = HERE / '.state'
(BENCH_HOME / 'config').mkdir(parents=True, exist_ok=True)
(BENCH_HOME / 'sessions').mkdir(parents=True, exist_ok=True)
os.environ['LASERBRAIN_HOME'] = str(BENCH_HOME)
sys.path.insert(0, str(HERE.parent.parent / 'laserbrain-sdk'))

GLYPH = ' .:+*#%@ABCDEFGH'          # 16 values, so nothing renders as '?'


def key_of(arr):
    return hashlib.md5(arr.tobytes()).hexdigest()[:12]


def render(arr, width=64, height=40):
    out = []
    for row in arr[:height]:
        out.append(''.join(GLYPH[v] if v < len(GLYPH) else '?' for v in row[:width]))
    return '\n'.join('  ' + r for r in out)


def arcade():
    import logging
    import warnings
    logging.disable(logging.INFO)
    warnings.filterwarnings('ignore')
    import arc_agi
    p = pathlib.Path.home() / '.config' / 'laserbrain' / 'arc-api-key'   # one-root: live
    k = p.read_text().strip() if p.exists() else ''
    return arc_agi.Arcade(arc_api_key=k) if k else arc_agi.Arcade()


def measured_distance(a):
    """Distance from the board, not from the agent's imagination.

    THE CORRECTION THAT MATTERS. laserbrain reads goal, progress and distance. Two were
    honest and the third was invented — 9, 8, 7, 6, counted down because the run FELT like
    it was going somewhere. `stalled` fires when distance stops falling, so it was firing on
    a number that had never touched the game, and every verdict about it was empty.

    On r11l a census gives a real metric: `%` (value 6) is exactly ONE cell — the player —
    and the `H` cluster above row 30 is the target. Manhattan between them falls when the
    player closes and rises when it wanders, which is what distance is supposed to mean.

    Returns None when the board has no such pair, so a game this does not fit says so
    instead of quietly handing back a made-up number, which is the failure being fixed.
    """
    import numpy as np
    py, px = np.where(a == 6)
    if len(py) != 1:
        return None
    hy, hx = np.where(a == 15)
    top = [(y, x) for y, x in zip(hy, hx) if y <= 30]
    if not top:
        return None
    best = min(abs(py[0] - y) + abs(px[0] - x) for y, x in top)
    return min(10, round(best / 6)), int(best)


def frame_of(obs):
    import numpy as np
    f = obs.frame
    return np.array(f[-1] if isinstance(f, list) and len(f) else f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--new', action='store_true', help='start a fresh run')
    ap.add_argument('--game', default=None, help='game id; default is the first available')
    ap.add_argument('--action', default=None, help='ACTION1..ACTION6, or RESET')
    ap.add_argument('--progress', choices=['advancing', 'stuck', 'circling'], default=None)
    ap.add_argument('--distance', type=int, default=None, help='0-10, your honest estimate')
    ap.add_argument('--reground', action='store_true',
                    help="make the current goal the new ground — the analogue of reset_task. "
                         "Needed because `narrow` tells you to shrink the goal and the "
                         "reading layer then scores the smaller goal against the original "
                         "forever, so goal-drift drowns the distance signal you narrowed in "
                         "order to see.")
    ap.add_argument('--auto-distance', action='store_true',
                    help='measure distance from the board instead of estimating it')
    ap.add_argument('--why', default='', help='one line: what you are trying and why')
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--coach', action='store_true',
                    help='SHOW the verdict after the step. This is the treatment arm — the '
                         'agent is meant to act on what it says. Off by default because the '
                         'observe-only run is what makes precision measurable.')
    ap.add_argument('--tag', default='', help='label this run, e.g. coached / control')
    ap.add_argument('--goal', default=None,
                    help="narrow the goal, when the instrument says to. Recorded per step, "
                         "so the trace shows WHEN the agent narrowed and what it narrowed to "
                         "— which is the thing `narrow` is asking for and the thing that "
                         "would otherwise be invisible afterwards.")
    ap.add_argument('--x', type=int, default=None, help='column, for complex (click) actions')
    ap.add_argument('--y', type=int, default=None, help='row, for complex (click) actions')
    ap.add_argument('--diff', action='store_true',
                    help='show only the rows that changed — a player sees the whole screen '
                         'at once; reading 64 lines through a pipe every step does not')
    args = ap.parse_args()

    RUNS.mkdir(exist_ok=True)
    global SESSION
    if args.tag:
        SESSION = session_path(args.tag)

    if args.summary:
        if not SESSION.exists():
            print('no session'); return 2
        d = json.loads(SESSION.read_text())
        print(f"  game {d['game']}   {len(d['trace'])} steps   "
              f"{len(set(d['states']))} distinct states   levels {d['levels']}")
        print()
        print('  step  action    progress    dist  novel  reason            judgment')
        for s in d['trace']:
            print(f"  {s['step']:4}  {s['action']:9} {s['progress']:10}  {s['distance']:4}  "
                  f"{'yes' if s['novel'] else '  .':5}  {str(s['reason']):17} {s['judgment'] or ''}")
        print()
        for s in d['trace']:
            if s['why']:
                print(f"    {s['step']:3}: {s['why']}")
        return 0

    from arcengine import GameAction
    from laserbrain import Harness

    arc = arcade()

    if args.new or not SESSION.exists():
        gid = args.game or [e.game_id for e in arc.get_environments()][0]
        env = arc.make(gid)
        obs = env.reset()
        a = frame_of(obs)
        d = {'game': gid, 'trace': [], 'states': [key_of(a)], 'last_frame': a.tolist(),
             'levels': obs.levels_completed, 'tag': args.tag or ('coached' if args.coach else 'control'),
             'goal': f'complete a level of {gid}'}
        SESSION.write_text(json.dumps(d))
        print(f"  game {gid}   win_levels {obs.win_levels}   actions {obs.available_actions}")
        print(f"  state {obs.state}   levels {obs.levels_completed}\n")
        print(render(a))
        print('\n  choose: --action ACTIONn --progress ... --distance N --why "..."')
        return 0

    d = json.loads(SESSION.read_text())
    if not (args.action and args.progress and (args.distance is not None or args.auto_distance)):
        print('need --action, --progress and --distance'); return 2

    # Replay the run so the environment is at the right point — the API is stateful per
    # env instance and this script is one process per step.
    env = arc.make(d['game'])
    obs = env.reset()
    def do(name, x=None, y=None):
        # ACTION6 and ACTION7 are COMPLEX actions — clicks, carrying x/y. The data goes as a
        # SEPARATE ARGUMENT to step(), not onto the action object: `set_data` populates
        # action.action_data and the wrapper never reads it, building its ActionInput from
        # `data` instead. Setting it the wrong way raises KeyError('x') inside the compiled
        # game and returns None, which surfaced here as an AttributeError two frames later
        # and looked like the game rejecting the move.
        a = getattr(GameAction, name)
        if a.is_complex():
            return env.step(a, data={'x': 32 if x is None else x, 'y': 32 if y is None else y})
        return env.step(a)

    for s in d['trace']:
        obs = do(s['action'], s.get('x'), s.get('y'))
    obs = do(args.action, args.x, args.y)

    a = frame_of(obs)
    k = key_of(a)
    novel = k not in d['states']

    # The harness sees only what the agent says, replayed in order — the verdicts are a
    # function of the reported run, not of the frames.
    m = measured_distance(a) if args.auto_distance else None
    distance = m[0] if m else args.distance
    if args.auto_distance and m is None:
        print('  no measurable distance on this board — falling back to the estimate')
        distance = args.distance if args.distance is not None else 10
    goal = args.goal or d.get('current_goal') or d['goal']
    if args.reground:
        d['ground_at'] = len(d['trace'])
    since = d.get('ground_at', 0)
    h = Harness()
    for s in d['trace'][since:]:
        h.check(s.get('goal') or d['goal'], s['progress'], s['distance'])
    v = h.check(goal, args.progress, distance)
    j = h.phronesis()

    d['trace'].append({
        'step': len(d['trace']) + 1, 'action': args.action, 'progress': args.progress,
        'x': args.x, 'y': args.y, 'goal': goal,
        'distance': distance, 'measured': m[1] if m else None, 'why': args.why, 'novel': novel,
        'levels': obs.levels_completed, 'state': str(obs.state),
        'reason': v.reason, 'phi': round(float(v.phi), 3), 'judgment': j.get('verdict'),
    })
    d['states'].append(k)
    d['levels'] = obs.levels_completed
    d['current_goal'] = goal
    prev_frame = d.get('last_frame')
    d['last_frame'] = a.tolist()
    SESSION.write_text(json.dumps(d))

    print(f"  step {len(d['trace'])}  {args.action}   "
          f"{'NEW STATE' if novel else 'seen before'}   "
          f"levels {obs.levels_completed}/{obs.win_levels}   {obs.state}")
    print(f"  distinct states so far: {len(set(d['states']))}"
          + (f"   MEASURED distance {m[1]} cells -> {distance}/10" if m else "") + "\n")
    if args.diff and prev_frame:
        import numpy as np
        prev = np.array(prev_frame)
        rows = [i for i in range(min(len(prev), len(a))) if not np.array_equal(prev[i], a[i])]
        if rows:
            print(f'  rows changed: {rows[0]}-{rows[-1]} ({len(rows)} of {len(a)})\n')
            for i in rows[:24]:
                before = ''.join(GLYPH[v] if v < len(GLYPH) else '?' for v in prev[i][:64])
                after = ''.join(GLYPH[v] if v < len(GLYPH) else '?' for v in a[i][:64])
                print(f'  {i:3} -  {before}')
                print(f'      +  {after}')
        else:
            print('  no row changed')
    else:
        print(render(a))
    # COACHED ARM. Off by default: an agent that sees the verdict is steering by it, and
    # the counterfactual — would this run have got somewhere on its own — stops being
    # observable, which is what made the observe-only numbers mean anything.
    #
    # It is on here because the question changed. Observe-only asked "is the verdict true".
    # Coached asks "does acting on it save moves", and moves are what ARC-AGI-3 actually
    # scores (RHAE, relative human action efficiency). A verdict can be false by the
    # new-states criterion and still be worth obeying: on the uncoached run `stalled` fired
    # at step 11, one step before the agent independently gave up on the same line, and the
    # mechanic turned up two steps later. Obeying it would have bought one move.
    if args.coach:
        print()
        print(f"  laserbrain: {v.reason}   phi {round(float(v.phi), 2)}   "
              f"judgment {j.get('verdict')}")
        if j.get('counsel'):
            print(f"  counsel: {j['counsel']}")
        if v.reason in ('stalled', 'oscillating') or j.get('verdict') in (
                'repeating', 'wrong-problem', 'abandon', 'narrow'):
            print('  ^ this is the instrument telling you to change something. Do that, or '
                  'record why not.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
