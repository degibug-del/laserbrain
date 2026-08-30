#!/usr/bin/env python3
"""
codebench — a light, ground-truthed H1 harness for the smart recursion harness.

Runs a coding agent on debug/loop-prone tasks that HAVE hidden unit tests (objective
Pass@1), control vs harness. Control runs to a step cap; the harness runs the same
drift check each step and, on drift, injects a return-to-ground instruction — the
intervention whose value H1 asks about. Scores Pass@1 + tokens + steps.

Runs on the Mac: the agent reaches the model API directly (no egress machinery, no
Linux box) and never sees the hidden tests, so a pass is real. It executes the
model's generated Python in a subprocess with a timeout; tasks are pure-computation
(stdlib only). Honest caveat: N is tiny; if the model one-shots, recursion didn't
happen and it nulls — a real result, per STUDY.md.

Run (Diego's funded key): read -rs K && ANTHROPIC_API_KEY="$K" python3 codebench.py
"""
import json, os, re, subprocess, sys, tempfile
import mcp_harness as mh
from mcp_harness import displacement, grammatical, words, as_dist

MAX_STEPS = 12

TASKS = [
    {
        "id": "balanced-brackets",
        "goal": "Fix is_balanced(s): return True iff the brackets ()[]{} are balanced AND correctly nested by type. It currently only counts depth and ignores type.",
        "start": (
            "def is_balanced(s):\n"
            "    depth = 0\n"
            "    for c in s:\n"
            "        if c in '([{': depth += 1\n"
            "        elif c in ')]}': depth -= 1\n"
            "        if depth < 0: return False\n"
            "    return depth == 0\n"
        ),
        "test": (
            "for a,b in [('()',True),('()[]{}',True),('(]',False),('([)]',False),"
            "('{[]}',True),('(',False),('',True),('([{}])',True),(']',False)]:\n"
            "    assert is_balanced(a)==b, (a, is_balanced(a))\n"
            "print('OK')\n"
        ),
    },
    {
        "id": "roman-numerals",
        "goal": "Implement roman(n) converting an integer 1..3999 to a Roman numeral string. Handle the subtractive forms (4=IV, 9=IX, 40=XL, 90=XC, 400=CD, 900=CM).",
        "start": "",
        "test": (
            "cases={1:'I',4:'IV',9:'IX',14:'XIV',40:'XL',58:'LVIII',90:'XC',400:'CD',"
            "944:'CMXLIV',1994:'MCMXCIV',3999:'MMMCMXCIX'}\n"
            "for n,r in cases.items():\n    assert roman(n)==r, (n, roman(n), r)\n"
            "print('OK')\n"
        ),
    },
    {
        "id": "merge-intervals",
        "goal": "Fix merge(intervals): merge all overlapping OR touching intervals and return them sorted. It currently assumes the input is sorted and treats touching intervals ([1,3],[3,5]) as non-overlapping.",
        "start": (
            "def merge(intervals):\n"
            "    out = []\n"
            "    for start, end in intervals:\n"
            "        if out and start < out[-1][1]:\n"
            "            out[-1][1] = max(out[-1][1], end)\n"
            "        else:\n"
            "            out.append([start, end])\n"
            "    return out\n"
        ),
        "test": (
            "assert merge([[1,3],[2,6],[8,10],[15,18]])==[[1,6],[8,10],[15,18]]\n"
            "assert merge([[1,4],[4,5]])==[[1,5]]\n"
            "assert merge([[1,4],[2,3]])==[[1,4]]\n"
            "assert merge([[2,3],[1,4]])==[[1,4]]\n"
            "assert merge([[1,4],[0,4]])==[[0,4]]\n"
            "assert merge([[1,2],[3,4]])==[[1,2],[3,4]]\n"
            "print('OK')\n"
        ),
    },
]

def run_tests(code, test):
    src = code + "\n\n" + test
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src); path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=15)
        return (r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr).strip()[-1200:])
    except subprocess.TimeoutExpired:
        return (False, "timeout (15s) — likely an infinite loop")
    finally:
        try: os.unlink(path)
        except OSError: pass

def extract_code(txt):
    m = re.findall(r"```(?:python)?\s*(.*?)```", txt, re.S)
    return m[-1].strip() if m else None

def parse_state(txt):
    i = txt.find("STATE"); tail = txt[i:] if i >= 0 else txt
    m = re.search(r"\{.*?\}", tail, re.S)
    try: return json.loads(m.group(0)) if m else None
    except Exception: return None

SYSTEM = (
    "You are fixing or implementing a Python function (stdlib only, pure computation — no file, "
    "network, or system access). Each turn: reason briefly, output the FULL current solution in ONE "
    "```python``` block, then a state block — a line reading STATE, then a JSON object "
    '{"goal": "...", "progress": "advancing|stuck|circling", "distance": <0-10>}. '
    "Hold 'goal' fixed. You will see the test result after each turn. Stop when the tests pass."
)

def run(task, harness):
    start = f"\n\nStarting code:\n```python\n{task['start']}```" if task["start"] else ""
    convo = [{"role": "user", "content": task["goal"] + start}]
    ground = None; distHist = []; steps = 0; last_code = task["start"]; fired = False
    for _ in range(MAX_STEPS):
        txt = mh.call(mh.MODEL, SYSTEM, convo, 1600); steps += 1
        convo.append({"role": "assistant", "content": txt})
        code = extract_code(txt) or last_code; last_code = code
        passed, out = run_tests(code, task["test"]) if code else (False, "no code block found")
        if passed:
            return dict(passed=True, steps=steps, ret="solved", fired=fired)
        intervention = ""
        if harness:
            obj = parse_state(txt)
            if obj and grammatical(obj):
                if ground is None:
                    ground = obj; distHist = [as_dist(obj)]
                else:
                    phi = displacement(obj, ground)
                    distHist.append(as_dist(obj)); dh = distHist
                    drift = None
                    if obj["progress"] in ("stuck", "circling") and phi > 0:
                        drift = f"you report {obj['progress']}"
                    elif len(dh) > 3 and min(dh[-3:]) >= dh[-4]:
                        drift = "your distance-to-done has stopped falling"
                    if drift:
                        fired = True
                        intervention = (
                            f"\n\n[smart recursion harness] You have drifted — {drift}. Stop. Restate the "
                            "goal in one line, and make the SINGLE smallest change that moves the failing "
                            "test toward passing. Return to the goal; do not press on down this path."
                        )
        convo.append({"role": "user", "content": f"Test result:\n{out}\n\nContinue with the full solution.{intervention}"})
    passed, _ = run_tests(last_code, task["test"]) if last_code else (False, "")
    return dict(passed=passed, steps=steps, ret="ceiling", fired=fired)

def main():
    mh.KEY = mh.api_key()
    SEEDS = int(os.environ.get("SEEDS", "3"))
    print(f"  codebench: {len(TASKS)} tasks × control vs harness × {SEEDS} seeds · model {mh.MODEL}\n")
    rows = []  # (task, cond, passed, steps, ret, tok, fired)
    for task in TASKS:
        for cond in ("control", "harness"):
            for s in range(SEEDS):
                before = dict(mh.USAGE)
                r = run(task, harness=(cond == "harness"))
                tok = mh.USAGE["in"] + mh.USAGE["out"] - before["in"] - before["out"]
                rows.append((task["id"], cond, r["passed"], r["steps"], r["ret"], tok, r.get("fired", False)))
                fmark = " ⚑fired" if r.get("fired") else ""
                print(f"    {task['id']:<20} {cond:<8} s{s} pass={str(r['passed']):<5} steps={r['steps']:>2} [{r['ret']:<8}] tok={tok}{fmark}")
    print("\n  ---- summary (rate over tasks×seeds) ----")
    for cond in ("control", "harness"):
        rs = [x for x in rows if x[1] == cond]
        p = sum(1 for x in rs if x[2]); st = sum(x[3] for x in rs); tk = sum(x[5] for x in rs)
        print(f"  {cond:<8} Pass@1 {p}/{len(rs)}   steps {st}   tokens {tk}")
    # The mechanism only acts when it fires. Isolate those runs.
    h = [x for x in rows if x[1] == "harness"]
    fired = [x for x in h if x[6]]
    fired_pass = sum(1 for x in fired if x[2])
    print("\n  ---- the mechanism, isolated ----")
    print(f"  harness runs where the intervention FIRED: {len(fired)}/{len(h)}")
    print(f"    of those, recovered (passed): {fired_pass}/{len(fired)}" if fired else "    (it never fired — no run drifted; nothing to test)")
    # Per-task control spiral rate = the ceiling the harness would have to rescue.
    print("\n  ---- where control spirals (the target) ----")
    for task in TASKS:
        c = [x for x in rows if x[0] == task["id"] and x[1] == "control"]
        cf = sum(1 for x in c if not x[2])
        print(f"    {task['id']:<20} control failed {cf}/{len(c)}")
    print("\n  READ: a step-1 pass is NOT the mechanism — the intervention needs ≥2 steps to fire.")
    print("  The real H1 signal is the 'mechanism, isolated' block: when a harness run drifted")
    print("  and the intervention fired, did it recover? Compare that to control's spiral rate on")
    print("  the same task. Overall Pass@1 is confounded by first-draft luck; weight the isolated block.")

if __name__ == "__main__":
    main()
