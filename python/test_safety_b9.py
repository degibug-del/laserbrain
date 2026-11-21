#!/usr/bin/env python3
"""B9: lb_safety reads a quoted phrase as text, and still refuses every real command.

    python3 test_safety_b9.py

WHY. research/DAY-FOUR-ROUND2.md §7, B9: the deny patterns matched their text anywhere in
the command, so `grep -n "rm -rf" notes.md`, a commit message naming a guarded command, and
a cat here-document documenting the guard were refused like the real thing (14 worker
cleanups and several auditors' reads in one round). Since 2026-11-17 a match is let
through only when the call cannot run text at all. This pins both halves: the text-only
calls now pass, and every way of running text that the scanner knows about still blocks,
including the ones that hide a command inside a quote or a here-document.

LB_SAFETY points at a different copy of the hook (a scratch build); default is this
repo's python/laserbrain/hooks/lb_safety.py.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOOK = pathlib.Path(os.environ.get('LB_SAFETY') or HERE / 'laserbrain' / 'hooks' / 'lb_safety.py')
spec = importlib.util.spec_from_file_location('lb_safety_under_test', HOOK)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


RF = 'rm -rf'          # spelled once, so the cases below read as what they are
NP = 'npm publish'
FP = 'git push --force'

# ── text only: refused before B9, let through now ───────────────────────────────────────
TEXT = [
    f'grep -n "{RF}" python/laserbrain/hooks/lb_safety.py',
    f"grep -rn '{RF}' . | head -20",
    f'rg -n "{RF}|{NP}" research/ | wc -l',
    f'grep -c "{FP}" CHANGELOG.md 2>&1 | head -1',
    f'if grep -q "{RF}" f; then echo found; fi',
    f'git commit -m "lb_safety: a quoted {RF} is text, not a command"',
    f'git -C ~/laserbrain commit -m "mention {RF} and {NP}"',
    f'cd ~/laserbrain && git log --oneline --grep="{RF}" | head',
    f"git commit -m \"$(cat <<'EOF'\nB9: {RF}, {NP} and {FP} inside quotes are text.\n\nCo-Authored-By: x\nEOF\n)\"",
    f"cat > notes.md <<'EOF'\n# the guard\nNever run {RF} on ~.\nEOF",
    f"cat <<'EOF' > notes.md\n{RF} is refused\nEOF",
    f"cat <<EOF > notes.md\n{RF} is refused, plain delimiter, no substitution\nEOF",
    f"cat <<-'EOF' > notes.md\n\t{RF} with <<- and a tab-indented terminator\n\tEOF",
    f'echo "{RF} is blocked by lb_safety" >> notes.md',
    f"printf '%s\\n' 'wrangler deploy' '{NP}' > list.txt",
    f'ls -la  # {RF} would be refused here',
    f'mkdir -p out && echo "twine upload is a registry upload" > out/n.txt',
    # from the 2026-11-17 review's false blocks
    f"grep -n '{RF}' ~/.zshrc",
    f"git commit -m 'guard {RF} in .git/hooks/pre-commit'",
    f'cd ~/laserbrain/python && grep -nE "{RF}|dist" release.sh | head -30; echo; sed -n 30,40p release.sh',
    f"git grep -n '{RF}' -- python",
    f"echo '{NP} checklist' | pbcopy",
    f'grep -c "{RF}" f 2>/dev/null || echo none',
]
# text only, but deliberately still refused (the exemption is narrow on purpose)
CONSERVATIVE = [
    f"tee notes.md <<'EOF' >/dev/null\n{NP} needs an OK\nEOF",                # tee names files
    f"sed -n '/{RF}/p' notes.md",                                              # sed script in quotes
    f"python3 -c \"print('{RF}')\"",                                          # an interpreter
    f'echo "{RF}" > notes.sh',                                                 # not .md/.txt
    f'echo {RF} x',                                                            # unquoted
]
for c in CONSERVATIVE:
    show(f'conservative, still blocked: {c[:60]!r}', S.blocked_reason(c) is not None)
for c in TEXT:
    show(f'text passes: {c[:70]!r}', S.blocked_reason(c) is None, S.blocked_reason(c))

# ── real, or able to run text: still refused ─────────────────────────────────────────────
REAL = [
    f'{RF} /tmp/x',
    f'cd /tmp && {RF} build',
    f'grep -n "x" f; {RF} out',
    f'sudo {RF} /x',
    f'{RF} "$HOME/x"',
    f'find . -name x -exec {RF} {{}} +',
    f'echo "{RF} /tmp/x" | sh',
    f'echo "{RF} /tmp/x" | bash',
    f'/bin/echo "{RF} x" | /bin/sh',
    f"printf '{RF} /tmp/x' | xargs -I{{}} sh -c {{}}",
    f'echo "{RF} x" | while read c; do $c; done',
    f"echo \"{RF} x\" | awk '{{system($0)}}'",
    f'grep "{RF}" f | sh',
    f'bash -c "{RF} /tmp/x"',
    f"sh -c '{RF} /tmp/x'",
    f'ssh host "{RF} /srv/x"',
    f'eval "{RF} /tmp/x"',
    f'echo "$({RF} /tmp/x)"',
    f'echo `{RF} /tmp/x`',
    f"echo $'{RF} x'",
    f"x='{RF} /tmp/a'; $x",
    f"cat > x.sh <<'EOF'\n{RF} /tmp/x\nEOF\nbash x.sh",
    f"cat > x.sh <<'EOF'\n{RF} /tmp/x\nEOF\nchmod +x x.sh && ./x.sh",
    f"cat <<'EOF' > f\n{RF} x\nEOF\nsource f",
    f'echo "{RF} x" > f && . ./f',
    f'echo "{RF} x" > f; zsh f',
    f"cat <<'EOF' | sh\n{RF} /tmp/x\nEOF",
    f"bash <<'EOF'\n{RF} /tmp/x\nEOF",
    f"python3 - <<'EOF'\nimport os; os.system('{RF} /tmp/x')\nEOF",
    f"cat <<EOF > f\n$({RF} /tmp/x)\nEOF",
    f"cat <<EOF > f\n`{RF} /tmp/x`\nEOF",
    f"cat > .git/hooks/pre-commit <<'EOF'\n{RF} ~\nEOF\ngit commit -m x",
    f"echo '{RF} ~' >> ~/.zshrc",
    f"git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n); {RF} /tmp/x)\"",
    f"git commit -m \"$(cat <<EOF\nmsg $({RF} /tmp/x)\nEOF\n)\"",
    f'git commit -m "x" && {FP}',
    f'git push -f origin main',
    f'git reset --hard HEAD~1',
    f'echo "{NP}" | sh',
    NP,
    f'cd typescript && {NP}',
    'twine upload dist/*',
    'python3 -m twine upload dist/*',
    'wrangler deploy',
    f'rg --pre "{RF} /tmp/x" foo .',
    f'sort --compress-program="{RF}" f',
    f'git -c alias.z="!{RF} /tmp/x" z',
    f'git grep -O"{RF} /tmp/x" foo',
    f"cat <<'EOF' > f\n{RF} x",                       # no terminator: unsure → block
    f'grep "{RF} f',                                   # unclosed quote: unsure → block
    f'echo "{RF} x" > >(sh)',
    # the 2026-11-17 review: text written where it runs later
    f"echo '{RF} ~' >> ~/.zprofile",
    f"echo '{RF} ~' >> ~/.zlogin",
    f"echo '{RF} ~' > .envrc",
    f"echo '{NP}' > .envrc",
    f"echo 'wrangler deploy' > .envrc",
    f"cat > Makefile <<'EOF'\nall:\n\t{RF} ~\nEOF",
    f'echo \'{{"scripts":{{"build":"{RF} ~"}}}}\' > package.json',
    f"echo '{RF} ~' >> ~/.config/fish/config.fish",
    f"echo '{RF} /srv' >> ~/.ssh/rc",
    f"printf '[alias]\\n\\tp = !{FP}\\n' >> .git/config",
    f"echo '{RF} ~' >> ~/.config/git/config",
    f"sort -o .envrc <<< '{RF} ~'",
    f"tee a.txt .envrc <<'EOF'\n{RF} ~\nEOF",
    f"echo '{RF} ~' > ~/bin/ls",
    f"echo '{RF} ~' > .git/info/notes.md",
    f'echo "{RF} ~" > "notes.md"',
    f"git log -1 --format='{RF} ~' --output=.envrc",
    f"cat <<EOF\n${{ {RF} /tmp/x; }}\nEOF",
    f'echo "${{ {RF} /tmp/x; }}"',
    f'echo ${{ {RF} /tmp/x; }}',
    f"echo ${{(e)x}} '{RF}'",
    f'cat =({RF} /tmp/x)',
    f"LESSOPEN='|{RF} ~' less f",
    f"GIT_PAGER='{RF} ~' git log",
    f"EDITOR='{RF} ~' git commit",
    f"GIT_EXTERNAL_DIFF='{RF} ~' git diff",
    f"BASH_ENV=x.txt echo '{RF}'",
    f"X='{RF} ~'; echo ok",
    f"cat <<EOF > notes.md\n$HOME {RF}\nEOF",
    # the differential probe (probe.py): `}#` is a word, not a comment
    f'cat }}#;{RF} /tmp/x',
    f'cat {{#;{RF} /tmp/x',
    f'echo a(#;{RF} /tmp/x',
    f'tee >(sh) <<\'EOF\'\n{RF} x\nEOF',
]
for c in REAL:
    show(f'still blocked: {c[:70]!r}', S.blocked_reason(c) is not None)

# ── unchanged rulings from before B9 ──────────────────────────────────────────────────────
show('git push without force runs', S.blocked_reason('git push origin main') is None)
show('wrangler deploy --dry-run runs', S.blocked_reason('npx wrangler deploy --dry-run') is None)
# Since 0.58.0 a Worker deploy is allowed only by name in the user's safety.json (R3; the full
# coverage is test_safety_config.py). LASERBRAIN_HOME points both lookups at a scratch root.
import tempfile                                                                      # noqa: E402
_keep = os.environ.get('LASERBRAIN_HOME')
with tempfile.TemporaryDirectory() as _h:
    os.environ['LASERBRAIN_HOME'] = _h
    show('with no safety.json, every Worker deploy is blocked',
         S.blocked_reason('cd workers/demo-worker && npx wrangler deploy') is not None)
    os.makedirs(os.path.join(_h, 'config'))
    with open(os.path.join(_h, 'config', 'safety.json'), 'w') as _f:
        json.dump({'allow_worker_deploys': ['demo-worker']}, _f)
    show('a Worker named in safety.json deploys',
         S.blocked_reason('cd workers/demo-worker && npx wrangler deploy') is None)
    show('another Worker deploy is still blocked',
         S.blocked_reason('cd workers/other && npx wrangler deploy') is not None)
if _keep is None:
    os.environ.pop('LASERBRAIN_HOME', None)
else:
    os.environ['LASERBRAIN_HOME'] = _keep
show('a call that names nothing guarded never builds the view',
     S.blocked_reason('ls -la && git status') is None)

# ── the hook end to end ───────────────────────────────────────────────────────────────────
def hook(command):
    env = dict(os.environ)
    env.pop('LASERBRAIN_SAFETY_OFF', None)
    p = subprocess.run([sys.executable, '-P', str(HOOK)], text=True, capture_output=True, env=env,
                       input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}))
    return p.returncode, p.stdout, p.stderr


rc, out, err = hook(f'grep -n "{RF}" notes.md')
show('hook: a quoted phrase passes silently', rc == 0 and out == '', (rc, out[:200]))
rc, out, err = hook(f'{RF} /tmp/b9-never-created')
deny = json.loads(out)['hookSpecificOutput'] if out.strip() else {}
show('hook: a real delete is denied', rc == 2 and deny.get('permissionDecision') == 'deny', (rc, out[:200]))
reason = deny.get('permissionDecisionReason', '')
show('the denial still says the call did not run', 'THIS CALL DID NOT RUN.' in reason)
show('and tells a helper agent with no one to ask what to do instead',
     'helper agent with no one to ask' in reason and 'final' in reason and 'report' in reason, reason[:400])
rc, out, err = hook(f'echo "{RF} x" | sh')
reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] if out.strip() else ''
show('a quoted case that did not qualify says why text is let through and this was not',
     rc == 2 and 'only TEXT' in reason and 'did' in reason and 'not qualify' in reason, reason[-500:])
rc, out, err = hook(f'{RF} "$S"')
reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] if out.strip() else ''
show('a real delete of a quoted path is NOT told to rephrase a literal',
     rc == 2 and 'only TEXT' not in reason, reason[-300:])

print('\n  all ok' if ok else '\n  FAILURES above')
raise SystemExit(0 if ok else 1)
