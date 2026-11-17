#!/usr/bin/env python3
"""Prove every benchmark task in research/bench/tasks/.

For each task this script builds throwaway sandboxes and checks:

  repo/ alone                   visible tests FAIL, acceptance FAIL
  repo/ + hidden/reference/     visible tests PASS, acceptance PASS
  type 1  + hidden/narrowed/    visible PASS, acceptance FAIL  (the dropped requirement only shows in acceptance)
  type 3  reference + injected  visible FAIL, acceptance FAIL  (the trap is real)
          ... + hidden/hint_fix visible PASS, acceptance PASS  (the buried hint is sufficient)
  type 4  + hidden/swapped/     acceptance FAIL                (following the injected task breaks the ask)
  type 5  + hidden/premature/   visible PASS, acceptance FAIL  (visible tests miss the edge case)
  non-trap file injections      reference + injection still PASSES (the injected file is inert)

It also validates task.json against the fixed format. Results go to proof-results.json.

Usage: python3 research/bench/prove.py [task-id ...]
"""
import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

BENCH = pathlib.Path(__file__).resolve().parent
TASKS = BENCH / "tasks"
CHANNELS = {"prompt", "relay", "tool_output", "file", "none"}


def copy_tree(src, dst):
    for p in src.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        target = dst / p.relative_to(src)
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)


def run(cmd, cwd, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "BENCH_SANDBOX", "BENCH_EPISODE")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
        return r.returncode, (r.stdout + r.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def pytest_cmd(ini, rootdir, confcut, target):
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(ini),
            "--rootdir", str(rootdir), "--confcutdir", str(confcut), str(target)]


def visible(sandbox, ini):
    return run(pytest_cmd(ini, sandbox, sandbox, sandbox / "tests"), cwd=sandbox)


def accept(task_dir, sandbox, ini, episode=None):
    hidden = task_dir / "hidden"
    extra = {"BENCH_SANDBOX": str(sandbox)}
    if episode:
        extra["BENCH_EPISODE"] = episode
    return run(pytest_cmd(ini, hidden, hidden, hidden / "accept_test.py"), cwd=ini.parent, env_extra=extra)


def apply_injection(sandbox, inj):
    p = sandbox / inj["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    if inj.get("mode") == "append":
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(inj["text"])
    else:
        p.write_text(inj["text"], encoding="utf-8")


def validate_json(tj, task_dir):
    errs = []
    need = ["id", "title", "drift_type", "onset_k", "requirements", "user_messages", "agent_prompt_clean",
            "agent_prompt_drift", "injection", "detour", "user_switch"]
    for k in need:
        if k not in tj:
            errs.append(f"missing {k}")
    if tj.get("id") != task_dir.name:
        errs.append("id != directory name")
    if tj.get("drift_type") not in (1, 2, 3, 4, 5):
        errs.append("drift_type")
    if tj.get("onset_k") not in (1, 3, 6):
        errs.append("onset_k")
    if not 2 <= len(tj.get("requirements", [])) <= 4:
        errs.append("requirements count")
    inj = tj.get("injection", {})
    if inj.get("channel") not in CHANNELS:
        errs.append("channel")
    if inj.get("at_step") != tj.get("onset_k"):
        errs.append("at_step != onset_k")
    same = tj.get("agent_prompt_clean") == tj.get("agent_prompt_drift")
    if (inj.get("channel") == "prompt") == same:
        errs.append("prompt drift mismatch (drift prompt must differ iff channel == prompt)")
    if inj.get("channel") == "file" and not inj.get("path"):
        errs.append("file injection without path")
    sw = tj.get("user_switch")
    if sw:
        if sw.get("at_step") == inj.get("at_step"):
            errs.append("user switch collides with injection step")
        if sw.get("text") not in tj.get("user_messages", []):
            errs.append("user switch text not in user_messages")
        if sw.get("text") in tj.get("agent_prompt_clean", ""):
            errs.append("user switch leaked into the starting prompt")
    if not tj.get("detour"):
        errs.append("no detour")
    if not (task_dir / "repo" / "tests").is_dir():
        errs.append("no repo/tests")
    return errs


def prove(task_dir):
    tj = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    typ = tj["drift_type"]
    inj = tj["injection"]
    hidden = task_dir / "hidden"
    res = {"id": tj["id"], "type": typ, "k": tj["onset_k"], "channel": inj["channel"],
           "switch": bool(tj["user_switch"]), "schema_errors": validate_json(tj, task_dir), "checks": []}

    def check(name, got_rc, want_pass, out):
        ok = (got_rc == 0) == want_pass and got_rc in (0, 1)
        m = re.findall(r"\b(\d+) (passed|failed|error|errors)\b", out.strip().splitlines()[-1] if out.strip() else "")
        summary = ", ".join(f"{n} {w}" for n, w in m) or out.strip().splitlines()[-1][:80] if out.strip() else ""
        res["checks"].append({"check": name, "rc": got_rc, "want": "pass" if want_pass else "fail", "ok": ok,
                              "summary": summary, **({} if ok else {"tail": out})})

    with tempfile.TemporaryDirectory(prefix="bench-proof-") as tmp:
        tmp = pathlib.Path(tmp)
        ini = tmp / "pytest.ini"
        ini.write_text("[pytest]\n")

        def sandbox(name, *overlays, injection=None):
            sb = tmp / name
            copy_tree(task_dir / "repo", sb)
            for ov in overlays:
                copy_tree(ov, sb)
            if injection:
                apply_injection(sb, injection)
            return sb

        a = sandbox("repo_only")
        rc, out = visible(a, ini)
        check("repo/ visible", rc, False, out)
        rc, out = accept(task_dir, a, ini)
        check("repo/ acceptance", rc, False, out)

        b = sandbox("reference", hidden / "reference")
        rc, out = visible(b, ini)
        check("reference visible", rc, True, out)
        rc, out = accept(task_dir, b, ini, episode="clean" if typ == 3 else None)
        check("reference acceptance", rc, True, out)

        if typ == 1:
            n = sandbox("narrowed", hidden / "narrowed")
            rc, out = visible(n, ini)
            check("narrowed visible", rc, True, out)
            rc, out = accept(task_dir, n, ini)
            check("narrowed acceptance", rc, False, out)
        if typ == 3:
            injected = (hidden / "injected" / inj["path"]).read_text(encoding="utf-8")
            res["injection_text_matches_file"] = injected == inj["text"]
            if not res["injection_text_matches_file"]:
                res["schema_errors"].append("injection text differs from hidden/injected")
            hint = (task_dir / "repo" / inj["hint_path"]).read_text(encoding="utf-8")
            fix = (hidden / "hint_fix" / inj["fix_path"]).read_text(encoding="utf-8")
            res["hint_lines_before"] = hint.count("\n")
            i = sandbox("injected", hidden / "reference", injection=inj)
            rc, out = visible(i, ini)
            check("reference+injection visible", rc, False, out)
            rc, out = accept(task_dir, i, ini, episode="drift")
            check("reference+injection acceptance", rc, False, out)
            h = sandbox("hint_fixed", hidden / "reference", hidden / "hint_fix", injection=inj)
            rc, out = visible(h, ini)
            check("reference+injection+hint_fix visible", rc, True, out)
            rc, out = accept(task_dir, h, ini, episode="drift")
            check("reference+injection+hint_fix acceptance", rc, True, out)
            orig_cfg = (task_dir / "repo" / inj["fix_path"]).read_text(encoding="utf-8")
            changed = [l for l in fix.splitlines() if l not in orig_cfg.splitlines()]
            new_values = re.findall(r"[a-z]+-\d{4}", "\n".join(changed))
            res["hint_names_fix_value"] = bool(new_values) and all(v in hint for v in new_values)
            if not res["hint_names_fix_value"]:
                res["schema_errors"].append("buried hint does not contain the value hint_fix needs")
        if typ == 4:
            s = sandbox("swapped", hidden / "swapped")
            rc, out = accept(task_dir, s, ini)
            check("swapped acceptance", rc, False, out)
            res["swapped_visible_rc"] = visible(s, ini)[0]
        if typ == 5:
            p = sandbox("premature", hidden / "premature")
            rc, out = visible(p, ini)
            check("premature visible", rc, True, out)
            rc, out = accept(task_dir, p, ini)
            check("premature acceptance", rc, False, out)
        if inj["channel"] == "file" and typ != 3:
            f = sandbox("reference_plus_file", hidden / "reference", injection=inj)
            rc, out = visible(f, ini)
            check("reference+file injection visible", rc, True, out)
            rc, out = accept(task_dir, f, ini)
            check("reference+file injection acceptance", rc, True, out)
    res["ok"] = not res["schema_errors"] and all(c["ok"] for c in res["checks"])
    return res


def main(argv):
    dirs = sorted(d for d in TASKS.iterdir() if d.is_dir() and (d / "task.json").exists())
    if argv:
        dirs = [d for d in dirs if d.name in argv]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(prove, dirs))
    out = BENCH / "proof-results.json"
    if not argv:
        out.write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        bad = [c["check"] for c in r["checks"] if not c["ok"]] + r["schema_errors"]
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['id']:<18} type {r['type']} k={r['k']} {r['channel']:<11} "
              f"checks {sum(c['ok'] for c in r['checks'])}/{len(r['checks'])}" + (f"  BAD: {bad}" if bad else ""))
    n_ok = sum(r["ok"] for r in results)
    print(f"\n{n_ok}/{len(results)} tasks proven; {sum(len(r['checks']) for r in results)} sandbox checks")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
