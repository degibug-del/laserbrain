#!/usr/bin/env python3
"""Differential probe: does the shell RUN a spot that the B9 scanner treats as text?

For each template with one slot {P}:
  - the SHELL sees P = `printf %s%s PRO BE`: harmless, and the output contains "PROBE" only
    if it actually executed (printed as text it reads "printf %s%s PRO BE");
  - the SCANNER sees P = a recursive force delete of a path that does not exist. That string
    is only passed to blocked_reason(); it is never given to a shell.
A bypass = the shell executed P, and blocked_reason() returned None for the delete version.
Runs in a throwaway directory with HOME pointed into it.
"""
import importlib.util, itertools, os, random, subprocess, sys, tempfile

HOOK = sys.argv[1] if len(sys.argv) > 1 else str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'python/laserbrain/hooks/lb_safety.py')
spec = importlib.util.spec_from_file_location('cand', HOOK)
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)

SHELL_P = 'printf %s%s PRO BE'
SCAN_P = 'rm ' + '-rf /tmp/lb-probe-does-not-exist'

CTX = [
    '{P}', "'{P}'", '"{P}"', '$"{P}"', "$'{P}'", '\\\n{P}', '# x\n{P}', '#{P}', ' #{P}', 'a#{P}',
    'echo a#b; {P}', 'echo ${x#a}; {P}', "echo 'a'{P}", 'echo "a"{P}', "echo 'a''{P}'",
    'echo "a\\"{P}"', "echo 'a\\'{P}'", 'echo "a"\'"\'{P}', 'echo "\'"{P}"\'"', "echo \\'{P}\\'",
    'echo "a\\\\"{P}', "echo 'it''s'; {P}", 'echo "x" # it\'s\n{P}', "echo x # \"\n{P}",
    "cat <<'EOF'\n{P}\nEOF", 'cat <<EOF\n{P}\nEOF', "cat <<'EOF'\nEOF \n{P}\nEOF", "cat <<'E'OF\n{P}\nEOF",
    'cat <<"EOF"\n{P}\nEOF', "cat <<'EOF'; {P}\nx\nEOF", "cat <<'EOF' && {P}\nx\nEOF",
    "cat <<A <<B\nx\nA\n{P}\nB", "cat <<-'EOF'\n\t{P}\n\tEOF", "cat <<- 'EOF'\n  EOF\n{P}\nEOF",
    "cat <<'EOF' |\n{P}\nEOF", "cat <<'EOF'\nx\nEOF\n{P}", "cat <<'EOF' > o.md\n{P}\nEOF",
    "cat <<'EOF'\n{P}", "cat <<'EOF' #\n{P}\nEOF", "cat <<'EOF'\\\n{P}\nEOF", "cat << 'EOF'\n{P}\n EOF\nEOF",
    "cat <<'EO F'\n{P}\nEO F", "cat <<EOF\n\\$({P})\nEOF", "cat <<'EOF'\n{P}\nEOF\n", "cat <<''\n{P}\n\n",
    'echo "$(cat <<\'EOF\'\nx\nEOF\n)" ; {P}', 'echo "$(cat <<\'EOF\'\n{P}\nEOF\n)"',
    'echo "$(cat <<\'EOF\'\nx\nEOF\n{P})"', 'echo "$(cat <<\'EOF\'\nx\n EOF\n)"\n{P}\nEOF\n)"',
    'grep -q "x" /dev/null || {P}', 'grep -e "{P}" /dev/null', "grep '{P}' /dev/null; true",
    'echo "{P}" | cat', "echo '{P}' > o.md", "echo '{P}' >> o.txt", 'echo x > o.md; {P}',
    'echo "a" >o.md {P}', 'echo a >| o.md; {P}', 'echo a 2>&1 >o.md; {P}', 'echo a &>o.md; {P}',
    '{ echo a; {P}; }', '( echo a; {P} )', 'if true; then {P}; fi', 'while false; do :; done; {P}',
    'echo a |& cat; {P}', 'echo a & {P}', 'echo a;{P}', 'echo a&&{P}', 'echo a||{P}', 'echo a\n{P}',
    'echo a\r\n{P}', 'echo a\t;{P}', '! {P}', 'cd . && {P}', 'test -n "{P}"', '[ "{P}" ]',
    'echo "${HOME}{P}"', "echo ${x:-'{P}'}", 'echo ${x:-"{P}"}', 'echo ${x:-{P}}', "echo ${x/a/'{P}'}",
    'echo {a,"{P}"}', "echo {a,'{P}'}", 'echo a{,{P}}', 'echo ~{P}', 'echo "a"#"{P}"',
    'echo \'a\'"b"\'{P}\'', "echo 'a'\"\n\"'{P}'", 'echo "a\n{P}"', "echo 'a\n{P}'",
    'printf "%s" "{P}"', "jq -n '\"{P}\"'", "sed -n 1p o.md; {P}", 'sed -n 1p "{P}"',
    'git log -1 --format="{P}"', "echo a <<< '{P}'", 'cat <<< "{P}"', 'cat <<<{P}',
]
PREFIX = ['', 'echo a; ', 'cd . && ', 'grep -q x /dev/null; ', 'echo "q" ']

def run(shell, cmd, cwd):
    env = {'HOME': cwd, 'PATH': os.environ['PATH'], 'LANG': 'C'}
    try:
        p = subprocess.run([shell, '-c', cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=3)
        return 'PROBE' in p.stdout
    except Exception:
        return False

def check(tmpl, shells, cwd, found):
    shell_cmd = tmpl.replace('{P}', SHELL_P)
    scan_cmd = tmpl.replace('{P}', SCAN_P)
    if S.blocked_reason(scan_cmd) is not None:
        return 0
    for sh in shells:
        if run(sh, shell_cmd, cwd):
            found.append((sh, tmpl))
    return 1

def main():
    shells = [s for s in ('/bin/zsh', '/bin/bash', '/opt/homebrew/bin/bash') if os.path.exists(s)]
    found, passed, total = [], 0, 0
    with tempfile.TemporaryDirectory() as d:
        for pre, ctx in itertools.product(PREFIX, CTX):
            total += 1
            passed += check(pre + ctx, shells, d, found)
        rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
        TOK = ["'", '"', '\\', '#', ' ', '\n', ';', '<<', "<<'EOF'", '<<EOF', 'EOF', '$', '{', '}',
               '(', ')', 'cat ', 'echo ', '|', '&&', '>', ' o.md', '`', '\t', '<<-', '${', 'x', '!', '=',
               '~', '[', ']', '*', '?', '&', '}#', '{#', ')#', 'a#', '#!', '2>', '>>', '<<<', '$(cat <<\'EOF\'',
               '\\\n', '"$', "'$", '%', '^', ',', '-', 'grep ', 'git commit -m ', 'sed -n 1p ', ':', '@']
        for _ in range(int(sys.argv[3]) if len(sys.argv) > 3 else 3000):
            k = rnd.randint(2, 9)
            parts = [rnd.choice(TOK) for _ in range(k)]
            parts.insert(rnd.randint(0, k), '{P}')
            tmpl = rnd.choice(['', 'echo a; ', 'cat ']) + ''.join(parts)
            total += 1
            passed += check(tmpl, shells, d, found)
    print(f'shells: {shells}')
    print(f'templates: {total}; delete-version let through by the scanner: {passed}')
    print(f'BYPASSES (shell ran the slot, scanner let the delete through): {len(found)}')
    for sh, t in found[:40]:
        print(f'  {sh}: {t!r}')

main()
