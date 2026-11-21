#!/usr/bin/env python3
"""R3 (0.58.0): lb_safety's one Worker allowance lives in user config, and nothing else moved.

    python3 test_safety_config.py
    python3 test_safety_config.py --write-golden OLD_LB_SAFETY.py     # maintainers only

WHY. Until 0.58.0 lb_safety.py carried one standing permission in its code (a deploy of one
named Worker, authorized on the machine the hook was written on), and its refusal told every
user's agent that one named person had to approve and run the command. The allowance now
comes from <config dir>/safety.json, and the refusal names nobody. Everything else the guard
decides must be exactly what it decided before, because it is the only guard for agents
running with permission prompts off.

WHAT THIS PINS.
  1. Equivalence. A fixed synthetic command list (tests/safety-decisions-5d5b02b.json, written
     from lb_safety.py at commit 5d5b02b, sha256 below) is replayed through this copy:
       - with safety.json naming the Worker the old code named: every decision identical to
         the old file as it was;
       - with no safety.json: every decision identical to the old file with its built-in
         allowance removed.
     When git can show the old file (a checkout with history), the same list also runs
     through the old file itself, and a few commands run end to end through both hooks,
     where the refusal text may differ only in the two lines R3 rewrote.
  2. The config allowance: absent, unreadable, malformed, oversized and ill-shaped files
     allow nothing; bad names are skipped; LASERBRAIN_HOME moves the file; both orders,
     --config and case behave as the built-in entry did.
  3. The refusal: "needs the explicit OK of the person running this session", no name, and no
     mention of the allowance file (a refused agent should ask, not grant itself the right).
  4. The source names no Worker and no person.

THIS TEST CAN FAIL: hardcode the Worker again and (4) and the no-file replay go red; let a
malformed file allow anything and (2) goes red; change any pattern, label, the B9 scanner or
the order of checks and (1) goes red.

LB_SAFETY points at another copy of the hook; LB_SAFETY_OLD at another copy of the old file.
"""
import builtins
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
HOOK = pathlib.Path(os.environ.get('LB_SAFETY') or HERE / 'laserbrain' / 'hooks' / 'lb_safety.py')
GOLDEN = HERE / 'tests' / 'safety-decisions-5d5b02b.json'
OLD_COMMIT = '5d5b02b'
OLD_SHA = '65e25636e410982256ce115558ed349a6b55c09d06e888321996bee9efa165f1'
# The Worker the old code allowed. It is a public name (the hosted laserbrain Worker); it is
# here only so the replay can put it in safety.json and compare with the old file.
OLD_WORKER = 'laserbrain-mcp-remote'

ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the fixed synthetic list (used only by --write-golden; the test replays the file) ─────
RF, FP, NP = 'rm -rf', 'git push --force', 'npm publish'
GUARDED = [
    RF + ' /tmp/x', 'rm -fr build', 'rm -Rf out', 'rm -rfv dist', FP + ' origin main',
    'git push -f origin head', 'git push origin main --force-with-lease', 'git reset --hard HEAD~1',
    'wrangler deploy', 'npx wrangler deploy', 'npx wrangler deploy --env production',
    'npx wrangler deploy --dry-run', 'npx wrangler deploy --dry-run | tail -3',
    'npx wrangler deploy; echo --dry-run', 'wrangler pages deploy dist', NP, NP + ' --access public',
    'twine upload dist/*', 'python3 -m twine upload dist/*', 'python -m twine upload dist/*',
    'flit publish', 'poetry publish --build', 'uv publish',
]
BENIGN = [
    'ls -la', 'git status', 'git push origin main', 'git push', 'pytest -q', 'npm test',
    'echo hi', 'cat README.md', 'grep -n foo bar.py', 'git log --oneline | head',
    'python3 -c "print(1)"', 'rm notes.txt', 'rm -r dir', 'rm -f one.txt', 'git reset HEAD~1',
    'git reset --soft HEAD~1', 'wrangler dev', 'wrangler tail', 'npm pack', 'pip install .',
    'uv pip install -e .', 'git commit -m "fix"', 'echo the pypi package', '',
]
WRAPS = [
    '{}', 'cd /tmp && {}', '{} && echo done', 'echo start; {}', 'grep -n "{}" notes.md',
    "grep -rn '{}' . | head -20", 'git commit -m "mention {}"', 'echo "{}" > notes.md',
    'echo "{}" > notes.sh', 'echo "{}" | sh', 'bash -c "{}"', "cat <<'EOF' > notes.md\n{}\nEOF",
    "cat <<'EOF' | sh\n{}\nEOF", 'sudo {}', 'X=1 {}', '# {}', 'ls  # {}', '(cd sub && {})',
    '{} 2>&1 | tail -5', 'echo `{}`', 'echo "$({})"', 'git commit -m "$(cat <<\'EOF\'\n{}\nEOF\n)"',
    'if true; then {}; fi', 'echo "{}" >> ~/.zshrc',
]


def worker_cases(w):
    return [
        f'cd workers/{w} && npx wrangler deploy',
        f'cd workers/{w} && npx wrangler deploy --env production',
        f'npx wrangler deploy --config workers/{w}/wrangler.toml',
        f'wrangler deploy workers/{w}',
        f'cd ~/site/workers/{w}\nnpx wrangler deploy',
        f'cd workers/{w} && npx WRANGLER DEPLOY',
        f'cd workers/{w.upper()} && npx wrangler deploy',
        f'cd workers/{w}-staging && npx wrangler deploy',
        f'echo {w}; npx wrangler deploy',
        f'cd workers/{w} && npx wrangler deploy --dry-run',
        f'cd workers/{w} && npx wrangler pages deploy dist',
        f'cd workers/{w} && npx wrangler deploy && {RF} /tmp/x',
        f'{RF} /tmp/x && cd workers/{w} && npx wrangler deploy',
        f'cd workers/{w} && {FP}',
        f'cd workers/{w} && {NP}',
        f'cd workers/{w} && git status',
        f'git commit -m "deploy {w} with wrangler deploy"',
        f'grep -n "wrangler deploy" workers/{w}/README.md',
        f'echo "wrangler deploy" | sh # {w}',
        w,
    ]


def synthetic_commands():
    out = []
    for wrap in WRAPS:
        for c in GUARDED + BENIGN:
            out.append(wrap.replace('{}', c))
    for w in (OLD_WORKER, 'demo-worker', 'laserbrain-mcp', 'other'):
        out.extend(worker_cases(w))
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def old_decisions(old, cmds):
    keep = list(old.ALLOW_PATTERNS)
    try:
        builtin = [old.blocked_reason(c) for c in cmds]
        old.ALLOW_PATTERNS = []
        bare = [old.blocked_reason(c) for c in cmds]
    finally:
        old.ALLOW_PATTERNS = keep
    return builtin, bare


def write_golden(old_path):
    src = pathlib.Path(old_path).read_bytes()
    sha = hashlib.sha256(src).hexdigest()
    if sha != OLD_SHA:
        sys.exit(f'refusing: {old_path} is not lb_safety.py at {OLD_COMMIT} (sha256 {sha})')
    old = load(old_path, 'lb_safety_old')
    cmds = synthetic_commands()
    builtin, bare = old_decisions(old, cmds)
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps({
        'what': 'lb_safety.blocked_reason() at commit 5d5b02b over a fixed synthetic command list. '
                'old_builtin: the file as it was. old_no_allow: the same file with its one '
                'built-in allowance removed. Written by test_safety_config.py --write-golden.',
        'old_commit': OLD_COMMIT, 'old_sha256': OLD_SHA, 'old_worker': OLD_WORKER,
        'commands': cmds, 'old_builtin': builtin, 'old_no_allow': bare,
    }, indent=1, ensure_ascii=False) + '\n')
    print(f'  wrote {GOLDEN}: {len(cmds)} commands, {sum(x is not None for x in builtin)} '
          f'blocked as built, {sum(x is not None for x in bare)} with no allowance')


if len(sys.argv) == 3 and sys.argv[1] == '--write-golden':
    write_golden(sys.argv[2])
    raise SystemExit(0)

S = load(HOOK, 'lb_safety_under_test')
G = json.loads(GOLDEN.read_text())
CMDS = G['commands']
TMP = pathlib.Path(tempfile.mkdtemp(prefix='lb-safety-config-'))


def lb_home(name, content=None, raw=None):
    """A fresh LASERBRAIN_HOME; content is JSON-dumped into config/safety.json, raw written as is."""
    h = TMP / name
    (h / 'config').mkdir(parents=True, exist_ok=True)
    f = h / 'config' / 'safety.json'
    if content is not None:
        f.write_text(json.dumps(content))
    elif raw is not None:
        f.write_bytes(raw)
    return h


def decide(home, cmds):
    keep = os.environ.get('LASERBRAIN_HOME')
    os.environ['LASERBRAIN_HOME'] = str(home)
    try:
        return [S.blocked_reason(c) for c in cmds]
    finally:
        if keep is None:
            os.environ.pop('LASERBRAIN_HOME', None)
        else:
            os.environ['LASERBRAIN_HOME'] = keep


# Words that must not appear, kept as sha256 prefixes so this file does not spell them either.
NAME_SHA = {'00e48a815525529b', '72b978cf9608f1ed', 'ad50386caa3f6c55'}


def names_a_person(text):
    return any(hashlib.sha256(w.encode()).hexdigest()[:16] in NAME_SHA
               for w in re.findall(r'[a-z]+', text.lower()))


def first_diff(a, b):
    for c, x, y in zip(CMDS, a, b):
        if x != y:
            return f'{c[:80]!r}: old {x!r} new {y!r}'
    return ''


# ── 1 · equivalence on the fixed list ─────────────────────────────────────────────────────
show('the golden file was written from the old lb_safety.py',
     G.get('old_sha256') == OLD_SHA and G.get('old_worker') == OLD_WORKER and len(CMDS) >= 500,
     f"{G.get('old_sha256')} {len(CMDS)}")
H_ALLOW = lb_home('allow', {'allow_worker_deploys': [OLD_WORKER]})
H_NONE = lb_home('none')
new_allow = decide(H_ALLOW, CMDS)
new_none = decide(H_NONE, CMDS)
same_allow = sum(x == y for x, y in zip(G['old_builtin'], new_allow))
same_none = sum(x == y for x, y in zip(G['old_no_allow'], new_none))
show(f'with safety.json naming the old Worker: {same_allow}/{len(CMDS)} decisions identical to the old file',
     same_allow == len(CMDS), first_diff(G['old_builtin'], new_allow))
show(f'with no safety.json: {same_none}/{len(CMDS)} identical to the old file without its allowance',
     same_none == len(CMDS), first_diff(G['old_no_allow'], new_none))
moved = [c for c, x, y in zip(CMDS, G['old_builtin'], G['old_no_allow']) if x != y]
show(f'the list exercises the allowance ({len(moved)} commands differ between the two old variants)',
     len(moved) >= 8 and all(OLD_WORKER.lower() in c.lower() for c in moved), moved[:3])
show('the list holds blocked, allowed and text-only cases',
     sum(x is not None for x in G['old_no_allow']) >= 200 and sum(x is None for x in G['old_no_allow']) >= 200)


def old_from_git():
    p = os.environ.get('LB_SAFETY_OLD')
    if p:
        return pathlib.Path(p)
    try:
        r = subprocess.run(['git', '-C', str(HERE), 'show', f'{OLD_COMMIT}:python/laserbrain/hooks/lb_safety.py'],
                           capture_output=True, timeout=30)
    except Exception:
        return None
    if r.returncode != 0 or hashlib.sha256(r.stdout).hexdigest() != OLD_SHA:
        return None
    f = TMP / 'lb_safety_old.py'
    f.write_bytes(r.stdout)
    return f


OLD_PATH = old_from_git()
if OLD_PATH is None:
    print(f'  note: git cannot show lb_safety.py at {OLD_COMMIT} here; the live replay against the old '
          'file is skipped and the golden file stands in for it')
else:
    O = load(OLD_PATH, 'lb_safety_old')
    live_builtin, live_bare = old_decisions(O, CMDS)
    show('the old file itself still produces the golden decisions',
         live_builtin == G['old_builtin'] and live_bare == G['old_no_allow'])
    show('with safety.json, new == old file on the whole list', new_allow == live_builtin,
         first_diff(live_builtin, new_allow))

    def hook(path, command, home):
        env = {k: v for k, v in os.environ.items() if k != 'LASERBRAIN_SAFETY_OFF'}
        env['LASERBRAIN_HOME'] = str(home)
        p = subprocess.run([sys.executable, '-P', str(path)], text=True, capture_output=True, env=env,
                           input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}),
                           timeout=60)
        return p.returncode, p.stdout

    # The two rewritten lines sit between these markers in both versions; everything before
    # and after them must be byte-identical.
    NEW_LINES = ("permission_mode may be always-approve, but this command is irreversible or destructive, "
                 "so it needs the explicit OK of the person running this session.\nAsk them, then have "
                 "them run it themselves — reissuing will be blocked again, and that is intended.\n")

    def parts(r):
        head, rest = r.split('THIS CALL DID NOT RUN.\n', 1)
        mid, tail = rest.split('If you are a helper agent', 1)
        return head, mid, tail
    E2E = [RF + ' /tmp/never-created', 'echo "' + RF + ' x" | sh', FP + ' origin main', NP,
           'cd workers/' + OLD_WORKER + ' && npx wrangler deploy', 'npx wrangler deploy',
           'grep -n "' + RF + '" notes.md', 'ls -la', 'git reset --hard', 'twine upload dist/*']
    agree, text_ok = 0, 0
    for c in E2E:
        rc_o, out_o = hook(OLD_PATH, c, H_ALLOW)
        rc_n, out_n = hook(HOOK, c, H_ALLOW)
        agree += (rc_o, '"deny"' in out_o) == (rc_n, '"deny"' in out_n)
        if out_o.strip():
            r_o = json.loads(out_o)['hookSpecificOutput']['permissionDecisionReason']
            r_n = json.loads(out_n)['hookSpecificOutput']['permissionDecisionReason'] if out_n.strip() else ''
            try:
                (h_o, m_o, t_o), (h_n, m_n, t_n) = parts(r_o), parts(r_n)
                text_ok += h_o == h_n and t_o == t_n and m_n == NEW_LINES and names_a_person(m_o)
            except ValueError:
                pass
        else:
            text_ok += out_n == ''
    show(f'end to end, old and new hooks agree on {agree}/{len(E2E)} commands', agree == len(E2E))
    show(f'and the refusal differs only in the two R3 lines ({text_ok}/{len(E2E)})', text_ok == len(E2E))

# ── 2 · the allowance file ────────────────────────────────────────────────────────────────
DEPLOY = 'cd workers/demo-worker && npx wrangler deploy'
LABEL = 'wrangler deploy (production Workers deploy)'


def one(home, cmd=DEPLOY):
    return decide(home, [cmd])[0]


show('no config dir at all: the deploy is blocked', one(TMP / 'nothing-here') == LABEL)
show('no file: blocked', one(lb_home('absent')) == LABEL)
show('a file naming it: allowed', one(lb_home('named', {'allow_worker_deploys': ['demo-worker']})) is None)
h = lb_home('named2', {'allow_worker_deploys': ['demo-worker']})
show('  the name after the verb (--config): allowed',
     one(h, 'npx wrangler deploy --config workers/demo-worker/wrangler.toml') is None)
show('  case does not matter, as before', one(h, 'cd workers/DEMO-WORKER && npx Wrangler Deploy') is None)
show('  another Worker is still blocked', one(h, 'cd workers/other && npx wrangler deploy') == LABEL)
show('  a bare deploy is still blocked', one(h, 'npx wrangler deploy') == LABEL)
show('  every other rule is untouched', one(h, RF + ' /tmp/x') == 'rm -rf (recursive force delete)'
     and one(h, NP) == 'npm publish (public package publish)')
show('  --dry-run runs with or without the file',
     one(h, 'npx wrangler deploy --dry-run') is None and one(H_NONE, 'npx wrangler deploy --dry-run') is None)
show('malformed JSON: blocked', one(lb_home('bad', raw=b'{"allow_worker_deploys": ["demo-worker"')) == LABEL)
show('not UTF-8: blocked', one(lb_home('bin', raw=b'\xff\xfe\x00{')) == LABEL)
show('a top-level list: blocked', one(lb_home('list', ['demo-worker'])) == LABEL)
show('a string, not a list (would otherwise iterate characters): blocked',
     one(lb_home('str', {'allow_worker_deploys': 'demo-worker'})) == LABEL
     and one(lb_home('str1', {'allow_worker_deploys': 'd'}), 'cd d && npx wrangler deploy') == LABEL)
show('the wrong key: blocked', one(lb_home('key', {'allow_deploys': ['demo-worker']})) == LABEL)
bad_names = ['', ' ', '.*', '.', '-demo', '/', 'demo worker', 'a|b', '(?i)x', 'x' * 201, None, 3, ['demo-worker']]
hb = lb_home('badnames', {'allow_worker_deploys': bad_names})
show('names that are not plain path fragments allow nothing',
     all(one(hb, c) == LABEL for c in (DEPLOY, 'npx wrangler deploy', 'npx wrangler deploy .*', 'cd a|b && npx wrangler deploy')),
     str(decide(hb, [DEPLOY, 'npx wrangler deploy'])))
hm = lb_home('mixed', {'allow_worker_deploys': ['', '.*', 'demo-worker', 7]})
show('a good name beside bad ones still works, and only it',
     one(hm, DEPLOY) is None and one(hm, 'cd workers/other && npx wrangler deploy') == LABEL)
show('a UTF-8 BOM is accepted', one(lb_home('bom', raw=b'\xef\xbb\xbf{"allow_worker_deploys": ["demo-worker"]}')) is None)
big = b'{"allow_worker_deploys": ["demo-worker"], "pad": "' + b'x' * 70000 + b'"}'
show('a file over 64 KiB: blocked', one(lb_home('big', raw=big)) == LABEL)
hd = lb_home('dir')
(hd / 'config' / 'safety.json').mkdir()
show('a directory where the file should be: blocked', one(hd) == LABEL)
if hasattr(os, 'geteuid') and os.geteuid() != 0:
    hu = lb_home('unreadable', {'allow_worker_deploys': ['demo-worker']})
    f = hu / 'config' / 'safety.json'
    f.chmod(0)
    show('an unreadable file: blocked', one(hu) == LABEL)
    f.chmod(0o600)
hf = lb_home('fake-home')
(hf / '.config' / 'laserbrain').mkdir(parents=True)
(hf / '.config' / 'laserbrain' / 'safety.json').write_text(json.dumps({'allow_worker_deploys': ['demo-worker']}))
keep_home, keep_lb = os.environ.get('HOME'), os.environ.pop('LASERBRAIN_HOME', None)
try:
    os.environ['HOME'] = str(hf)
    show('without LASERBRAIN_HOME the file is ~/.config/laserbrain/safety.json',
         S.allowance_path() == str(hf / '.config' / 'laserbrain' / 'safety.json') and S.blocked_reason(DEPLOY) is None)
    os.environ['LASERBRAIN_HOME'] = str(H_NONE)
    show('with LASERBRAIN_HOME set, the file under ~/.config is not read',
         S.allowance_path() == str(H_NONE / 'config' / 'safety.json') and S.blocked_reason(DEPLOY) == LABEL)
finally:
    os.environ.pop('LASERBRAIN_HOME', None)
    if keep_lb is not None:
        os.environ['LASERBRAIN_HOME'] = keep_lb
    if keep_home is None:
        os.environ.pop('HOME', None)
    else:
        os.environ['HOME'] = keep_home
calls = []
real_path = S.allowance_path
S.allowance_path = lambda: calls.append(1) or real_path()
try:
    decide(H_ALLOW, ['ls -la && git status', 'pytest -q', 'grep -n foo bar.py'])
    show('a call that names nothing guarded never opens the allowance file', calls == [], calls)
    decide(H_ALLOW, [DEPLOY])
    show('  and a guarded one does', len(calls) == 1, calls)
finally:
    S.allowance_path = real_path

# A FIFO at the path must not hang the hook: Claude Code kills a hook at its timeout and lets
# the call through, so a read that blocks would fail OPEN. It is opened non-blocking and
# checked with fstat first (0.58.0 review). Run in a child with a deadline, so a regression
# shows as a FAIL rather than a hung suite.
if hasattr(os, 'mkfifo'):
    hq = lb_home('fifo')
    os.mkfifo(hq / 'config' / 'safety.json')
    fifo_ok = False
    try:
        rc_f, out_f, _ = (lambda p: (p.returncode, p.stdout, p.stderr))(subprocess.run(
            [sys.executable, '-P', str(HOOK)], text=True, capture_output=True, timeout=20,
            env={**{k: v for k, v in os.environ.items() if k != 'LASERBRAIN_SAFETY_OFF'},
                 'LASERBRAIN_HOME': str(hq)},
            input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': DEPLOY}})))
        fifo_ok = rc_f == 2 and '"deny"' in out_f
        show('a FIFO where the file should be: blocked at once, no hang', fifo_ok, (rc_f, out_f[:120]))
    except subprocess.TimeoutExpired:
        show('a FIFO where the file should be: blocked at once, no hang', False, 'the hook hung for 20 s')
    if fifo_ok:                     # in process only once it is known not to hang
        show('  and in process too', one(hq) == LABEL)

# The name is matched as plain text: re.escape keeps a dot a dot.
hdot = lb_home('dot', {'allow_worker_deploys': ['my.worker']})
show("a '.' in a name is a dot, not any character",
     one(hdot, 'cd workers/my.worker && npx wrangler deploy') is None
     and one(hdot, 'cd workers/myXworker && npx wrangler deploy') == LABEL)
# DOCUMENTED, NOT FIXED (a decision for the owner, since it changes the golden decisions): a
# name is a substring anywhere in the command, so a longer name and a short one match too, and
# an allowance covers the whole command. These pin that the docs describe what the code does.
hsub = lb_home('substr', {'allow_worker_deploys': ['demo-worker']})
show('as documented: a name inside a longer one allows that one too',
     one(hsub, 'cd workers/demo-worker-2 && npx wrangler deploy') is None)
hshort = lb_home('short', {'allow_worker_deploys': ['x']})
show('as documented: a one-letter name matches nearly every deploy',
     one(hshort, 'npx wrangler deploy --config wrangler.toml --env x') is None)
show('as documented: an allowance covers the whole command, other rules included',
     one(hsub, FP + ' origin main # demo-worker wrangler deploy') is None
     and one(H_NONE, FP + ' origin main # demo-worker wrangler deploy') is not None)


# ── 3 · the refusal, end to end ───────────────────────────────────────────────────────────
def run_hook(command, home):
    env = {k: v for k, v in os.environ.items() if k != 'LASERBRAIN_SAFETY_OFF'}
    env['LASERBRAIN_HOME'] = str(home)
    p = subprocess.run([sys.executable, '-P', str(HOOK)], text=True, capture_output=True, env=env,
                       input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}), timeout=60)
    return p.returncode, p.stdout, p.stderr


rc, out, err = run_hook(DEPLOY, H_NONE)
reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] if out.strip() else ''
show('hook: an unallowed Worker deploy is denied (exit 2, deny)', rc == 2 and '"deny"' in out, (rc, out[:160]))
show('the refusal says it needs the explicit OK of the person running this session',
     'needs the explicit OK of the person running this session' in reason, reason[:300])
show('the refusal names nobody', not names_a_person(reason) and not any(w in reason.lower() for w in ('owner', ' his ', ' her ')), reason[:300])
show('the refusal does not mention the allowance file', 'safety.json' not in reason and 'allow_worker' not in reason)
show('the refusal keeps its head and helper line',
     reason.startswith('laserbrain safety: blocked wrangler deploy') and 'THIS CALL DID NOT RUN.' in reason
     and 'helper agent with no one to ask' in reason)
rc, out, err = run_hook(DEPLOY, lb_home('hook-allow', {'allow_worker_deploys': ['demo-worker']}))
show('hook: with the file naming it, the same deploy passes silently', rc == 0 and out == '', (rc, out[:160]))

# ── 4 · the source ────────────────────────────────────────────────────────────────────────
src = HOOK.read_text()
show('lb_safety.py names no Worker', OLD_WORKER not in src and 'mcp-remote' not in src)
show('lb_safety.py names no person', not names_a_person(src))
show('lb_safety.py has no ALLOW_PATTERNS list left to hardcode into', 'ALLOW_PATTERNS' not in src)

print('\n  all ok' if ok else '\n  FAILURES above')
raise SystemExit(0 if ok else 1)
