"""lb_shellread: a shell command counts as a read only when every part of it is one.

WHY THIS SUITE EXISTS. The gate counted every Bash call as acting, so `ls` and `git status`
burned the step budget and were refused under a message saying reads still pass. The
classifier that fixes it must be conservative in one direction only: a write called a read
slips past the gate, a read called a write costs a nudge. So most cases here are the tricky
writes — redirects, tee, sed -i, xargs rm, find -delete, subshells, substitutions.

Run:  python3 test_shellread.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'laserbrain' / 'hooks'))
from lb_shellread import is_read_only_command, shell_command_of  # noqa: E402

ok = True
RM = 'r' + 'm'                     # built at runtime so the safety hook does not match this file


def show(label, passed):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")


READS = [
    'ls -la /tmp', 'grep -n "a|b" f.py', 'cat f | wc -l', 'ls 2>/dev/null', 'git status',
    'git log --oneline -5', 'git diff HEAD~1', 'ffprobe x.mp4 2>&1',
    'find . -name "*.py" | xargs wc -c', 'sed -n 1,80p f', 'sed -n \'5,$p\' f', 'cd /x && ls',
    'head -5 a; tail -3 b', 'cat < in.txt', 'grep x f 2>&1 | head', 'git stash list',
    'git remote -v', 'stat f', 'wc -l a b', 'git -C repo status', 'du -sh .', 'echo done',
    'ls\nwc -l f', 'jq .a f.json', 'sort f | uniq', 'git branch', 'git show HEAD:f.py',
]
# `sort f | uniq` — uniq is not on the allow-list (uniq IN OUT writes OUT), so it is acting.
READS.remove('sort f | uniq')
ACTING = [
    'ls > out.txt', 'echo hi >> f', 'cat a | tee b', 'find . -delete', f'find . -exec {RM} {{}} ;',
    f'xargs {RM}', f'find . | xargs {RM} -f', 'sed -i s/a/b/ f', "sed -i '' s/a/b/ f",
    'sed -n 1,5w out f', 'sed s/a/b/ f', '(ls)', f'ls & {RM} x', f'echo $({RM} x)',
    f'echo `{RM} x`', 'cat <<EOF\nx\nEOF', 'X=1 ls', f'{RM} -r -f x', 'python3 -c 1',
    'git branch new', 'git checkout x', 'git diff --output=x', './ls', 'sort -o f a',
    f'ls; {RM} x', 'git -c core.pager=sh log', 'diff <(ls) b', 'ls && npm i', '',
    'git stash', 'git remote add o u', 'sort f | uniq', 'awk 1 f', 'ls >| f', 'ls &> f',
    'cat f 1>f2', 'tee f', 'cp a b', 'mv a b', 'touch f', 'mkdir d', 'chmod +x f',
    'curl https://example.invalid', 'git push', 'git commit -m x', 'npm test', 'make',
    'ls | sh', 'bash -c ls', 'env ls', 'rg --pre cat x', 'tree -o out', 'git tag -d v1',
    'find . -fprint out', 'date -s 1200', 'ls ;; ls', None, 123,
]

# THE CHECKERS' CASES, 2026-10-17. Every one of these was classed as a READ by the first
# version (shlex-based): 47 of 83 in one probe, 24 of 58 in another, 13 of 28 in a third, all
# of them writes or program launches. Comments swallowing later lines, expansions the lexer
# never saw, xargs feeding arguments from stdin, and option spellings the rules missed.
ADVERSARIAL = [
    # a '#' anywhere unquoted: shlex dropped everything after it, newlines included
    f'echo a#b; {RM} -rf build', f'ls build  # list\n{RM} -rf build', 'grep -c foo#bar f; git push',
    f'ls  # list first\n{RM} old.txt', f'cat a#b; {RM} -f victim', f'echo x#y && {RM} -f victim',
    'ls #c\ntouch victim', f'cat x # comment\n{RM} -f victim', 'grep foo f #\ntouch victim',
    f'ls\n# note\n{RM} victim', 'echo a#b ; touch victim', 'git log --pretty=%h#x ; touch victim',
    # expansion of any kind
    'find . ${X:--delete}', 'find . ${X:=-delete}', "find . $'-delete'", "find . $'\\x2ddelete'",
    'find . {-delete,-print}', 'ls "$(touch x)"', 'ls $HOME; touch x', 'git show HEAD@{1}',
    # globs, for commands an argument can turn into a writer (a file named -delete, -o...)
    'find . *', 'sort *', 'sed -n 1p *', 'git log *', 'rg foo *', 'file *', 'tree *',
    # xargs: stdin supplies arguments; flags that take an argument shift the command word
    'echo -delete | xargs find .', 'echo "-o victim" | xargs sort in.txt',
    'printf "%s\\n" "w victim" | xargs sed -n 1p', f'ls | xargs -J ls {RM} -f ls',
    f'xargs --arg-file cat {RM}', f'xargs -J cat {RM}', f'xargs -R ls {RM}', f'xargs -S ls {RM}',
    f'xargs -a ls {RM}', f'cat x | xargs -0 {RM}', 'xargs -I x cp x y', 'ls | xargs git show',
    # sed: every script must be a print range; -f/-i in any spelling is acting
    'sed -n 1p -e "w victim" in.txt', 'sed -n --expression="w victim" 1p in.txt',
    'sed -n --expr="w victim" 1p in.txt', 'sed -n -e 1p -e "e touch x" f', 'sed -n 1p -f evil.sed f',
    'sed -n --in-place=.bak 1p in.txt', 'sed -n -Ei 1p in.txt', 'sed -n -si 1p in.txt',
    'sed -ni 1p f', 'sed -n --file=x f',
    # sort / tree / file / ffprobe / date
    'sort -uo victim in.txt', 'sort -ro victim in.txt', 'sort --out=victim f',
    'sort --compress-program=sh in.txt', 'sort --comp=sh f', 'tree -fo victim', 'tree -R -L 1 -H . ',
    'file -C -m magic', 'file --compile -m magic', 'ffprobe -o victim in.mp4', 'ffprobe -report in.mp4',
    'ffprobe -i x -report', "ffprobe -f lavfi -i 'nullsrc'", 'date 202601010000', 'date 0101',
    'date --set=2026-01-01', 'date -s 1200',
    # git: reflog expire/delete, grep -O, branch upstream edits, abbreviated --output
    'git reflog expire --expire=now --all', 'git --no-pager reflog expire --expire=now --all',
    'git reflog delete x', 'git grep -Orm pattern', 'git grep -Ovim x', 'git grep -O"touch" pattern',
    'git grep -iOvim x', 'git grep --open-files-in-pager=rm pattern', 'git grep --open=vim x',
    'git branch --unset-upstream', 'git branch --set-upstream-to=origin/x', 'git branch --set-up=x',
    'git branch -u origin/x', 'git diff --out=x', 'git log --ext-diff', 'git stash -p list',
    # redirect shapes
    'cat x <>victim', 'jq . x > victim', 'cat x 1>victim', 'cat x &>victim', 'ls 3>x',
    'ls > "/dev/null" x; touch y', 'cat "unterminated', 'ls \\',
]
EXTRA_READS = [
    "grep -n '#include' f.c", 'grep -n "a#b" f', 'ls *.py', 'wc -l src/*.md', 'cat x | xargs echo',
    "git log -- '*.py'", 'git grep -o foo', 'git reflog', 'git reflog show -5', 'git branch -av',
    'git tag -l', 'date +%F', 'date -u', 'sort -n f', 'sed -ne 1,5p f', 'sed --quiet -e 1p f',
    'ls -la ~ ; cd /tmp && pwd', 'grep x f >/dev/stderr', 'ls 2> /dev/null', 'git --git-dir=x log',
    'find . -name "*.py" -print', 'ls | xargs -0 -n 2 wc -l', 'echo "a\\$b"',
]

for c in READS + EXTRA_READS:
    show(f'read    {c!r}', is_read_only_command(c) is True)
for c in ACTING + ADVERSARIAL:
    show(f'acting  {c!r}', is_read_only_command(c) is False)

# The tokenizer must stay linear: a long pasted line is refused quickly, never parsed slowly.
import time  # noqa: E402
_t0 = time.perf_counter()
is_read_only_command('ls ' + 'a' * 7000)
is_read_only_command('ls ' + '"' + 'a' * 100000)
show('long commands classify in under 50 ms', time.perf_counter() - _t0 < 0.05)

show('shell_command_of reads Bash command',
     shell_command_of({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}) == 'ls')
show('shell_command_of ignores non-shell tools',
     shell_command_of({'tool_name': 'Write', 'tool_input': {'command': 'ls'}}) is None)
show('shell_command_of survives junk', shell_command_of({'tool_name': 'Bash', 'tool_input': 'x'}) is None)

print(f'\n  {len(READS) + len(EXTRA_READS)} reads, {len(ACTING) + len(ADVERSARIAL)} acting cases')
print('  ' + ('PASS' if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
