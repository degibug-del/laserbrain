#!/usr/bin/env python3
"""laserbrain's check_state without the MCP server: the same verdicts, from the laserbrain package.

    python3 check_state.py --goal "fix the login bug" --progress advancing --distance 6 [--doing "..."]
    python3 check_state.py --session kid-1 --parent-goal "ship v2" --goal "..." ...   # one lane per agent
    python3 check_state.py --reset [--session NAME]     # a new task: clear the lane's ground and history
    python3 check_state.py --history [--session NAME]

Each lane's checks are kept in a small JSON file and replayed into laserbrain.Harness on every call, so the
ground (the goal first stated in the lane) and the distance history carry over between calls the way the MCP
server keeps them. The package is pure Python with no dependencies: `pip install laserbrain` where it is missing.
Prints one JSON object; exit 0 on a reading, 2 on a usage or install problem.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time

STATE = pathlib.Path(os.environ.get("LASERBRAIN_SKILL_STATE")
                     or pathlib.Path.home() / ".cache" / "laserbrain-skill")
PROGRESS = ("advancing", "stuck", "circling")


def lane_file(session):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", session or "default").strip("-.") or "default"
    return STATE / f"{name}.json"


def load(path):
    try:
        rows = json.loads(path.read_text())
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def save(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows[-500:]))
    os.replace(tmp, path)


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--goal")
    ap.add_argument("--progress", default="advancing", help="ONE word: advancing, stuck or circling")
    ap.add_argument("--distance", type=float, help="0-10, how far from done (0 = done)")
    ap.add_argument("--doing")
    ap.add_argument("--next")
    ap.add_argument("--blocked")
    ap.add_argument("--parent-goal")
    ap.add_argument("--session", help="a stable id for THIS agent's lane (subagents: their own)")
    ap.add_argument("--reset", action="store_true", help="clear this lane: the next check sets a new ground")
    ap.add_argument("--history", action="store_true", help="print this lane's checks")
    a = ap.parse_args(argv)
    path = lane_file(a.session)

    if a.reset:
        if path.exists():
            os.replace(path, path.with_suffix(f".reset-{int(time.time())}.json"))   # kept, not deleted
        return out({"reset": True, "lane": path.stem, "advice": "Lane cleared. Your next check sets a new ground."})
    if a.history:
        return out({"lane": path.stem, "checks": load(path)})

    if not a.goal or a.distance is None:
        return out({"error": "--goal and --distance are required (or --reset / --history)"}, 2)
    progress = a.progress.strip().rstrip(".").lower()
    if progress not in PROGRESS:
        return out({"error": f"--progress is ONE word: {', '.join(PROGRESS)}. Put a note in --doing.",
                    "got": a.progress}, 2)
    try:
        import laserbrain
    except ImportError:
        return out({"error": "laserbrain is not installed here. Run: pip install laserbrain "
                             "(PyPI, pure Python, no dependencies)"}, 2)

    rows = load(path)
    new = {"goal": a.goal, "progress": progress, "distance": max(0.0, min(10.0, a.distance)),
           "parent_goal": a.parent_goal, "doing": a.doing, "next": a.next, "blocked": a.blocked,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    h = laserbrain.Harness(run_id=path.stem)
    v = None
    for r in rows + [new]:                  # replay the lane, then read the new step
        v = h.check(r["goal"], r["progress"], r["distance"], parent_goal=r.get("parent_goal"),
                    doing=r.get("doing"), next=r.get("next"), blocked=r.get("blocked"))
    save(path, rows + [new])
    return out({"lane": path.stem, "step": len(rows) + 1, "drifting": v.drifting, "reason": v.reason,
                "phi": v.phi, "ground": getattr(v, "ground", None), "advice": v.advice,
                "laserscore": getattr(v, "laserscore", None)})


if __name__ == "__main__":
    raise SystemExit(main())
