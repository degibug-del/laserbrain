#!/usr/bin/env python3
"""What the shipped text may say (0.58.0): no private text, no refused claims, R7's cadence.

    python3 test_shipped_text.py

WHY. Up to 0.57.0 the package's own comments quoted the owner by name and in his words, named
sessions by id, and the hook refusal named one person; PyPI and the repository published all
of it. The READMEs opened with a claim the measurements do not support ("detects agent
drift"). This pins the cleanup:

  1. python/laserbrain/**/*.py, the two READMEs, the repo skill and SECURITY.md name no person
     (checked against sha256 prefixes, so this file does not spell the names either), carry
     no chat-style quotes and no session ids.
  2. The READMEs and the skill use none of the refused phrases.
  3. Both READMEs open with the agreed sentence and link phronesis.world/laserbrain.
  4. Both READMEs and the skill say to check in "when a task starts and when it changes",
     and none says to call check_state every step.

THIS TEST CAN FAIL: put a name, a quoted chat line or a session id back in a comment, or
restore the old opening line, and it goes red.
"""
import hashlib
import io
import pathlib
import re
import tokenize

HERE = pathlib.Path(__file__).resolve().parent
TOP = HERE.parent
PKG = HERE / 'laserbrain'
DOCS = [TOP / 'README.md', HERE / 'README.md', TOP / 'skills' / 'laserbrain' / 'SKILL.md', TOP / 'SECURITY.md']
READMES = [TOP / 'README.md', HERE / 'README.md']
SKILL = TOP / 'skills' / 'laserbrain' / 'SKILL.md'

NAME_SHA = {'00e48a815525529b', '72b978cf9608f1ed', 'ad50386caa3f6c55'}
CHAT = re.compile(r'"u should|"i want u|\bu should be able\b|"yes, noticeably', re.I)
SESSION_ID = re.compile(r'\b(?:session|run)\s+`?(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,12}\b', re.I)
REFUSED = [
    'hand-labelled', 'hand labelled', 'labelled by hand', 'adaptive stop', 'agentic spiraling',
    'catch spiraling', 'immutable signal', 'no second llm', '0.965', '28 of 28', '36 of 36',
    'real near-miss', 'prevented', 'catches drift', 'stops drift', 'detects drift',
    'detects agent drift', 'protects your', 'rarely misses', 'ai wrote', 'most of the making',
    'read the work', 'next release', 'fleet view', 'shipped today', 'powered by laserbrain',
    'free, forever', 'call check_state every step', '75%', '83%', '0.6%',
]
OPENING = ("laserbrain is a small drift check for AI agents. We measured it over 60 days of real use on "
           "one machine: the old every-step check caught 1 of 16 drifted helpers and cost about a tenth of "
           "the agents' responses. What it is, what it is not, and every number: "
           "[phronesis.world/laserbrain](https://phronesis.world/laserbrain).")
CADENCE = 'when a task starts and when it changes'

ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def names_in(text):
    return sorted({w for w in re.findall(r'[a-z]+', text.lower())
                   if hashlib.sha256(w.encode()).hexdigest()[:16] in NAME_SHA})


def prose_of_py(path):
    """Comments and every string token: the parts of a .py file that are text, not code."""
    src = path.read_text(encoding='utf-8')
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            out.append((tok.start[0], tok.string))
    return out


# ── 1 · private text ──────────────────────────────────────────────────────────────────────
pys = sorted(p for p in PKG.rglob('*.py') if '__pycache__' not in p.parts)
show(f'the package has its .py files ({len(pys)})', len(pys) >= 30)
hits = []
for p in pys:
    for ln, text in prose_of_py(p):
        if names_in(text) or CHAT.search(text) or SESSION_ID.search(text):
            hits.append(f'{p.relative_to(HERE)}:{ln}')
show('no comment or string in python/laserbrain names a person, quotes chat or names a session',
     not hits, ', '.join(hits[:8]))
# Package data ships in the wheel too: the node server copy, grammar.json and the other JSON
# and Markdown files. Their whole text is checked, not only comments.
data = sorted(p for p in PKG.rglob('*') if p.is_file() and p.suffix in ('.mjs', '.js', '.json', '.md')
              and '__pycache__' not in p.parts)
show(f'the package has its data files ({len(data)})', len(data) >= 2)
hits = []
for p in data:
    t = p.read_text(encoding='utf-8', errors='replace')
    if names_in(t) or CHAT.search(t) or SESSION_ID.search(t):
        hits.append(f'{p.relative_to(HERE)} {names_in(t)} {bool(CHAT.search(t))} {bool(SESSION_ID.search(t))}')
show('no shipped .mjs/.js/.json/.md file names a person, quotes chat or names a session',
     not hits, ', '.join(hits[:8]))
for d in DOCS:
    t = d.read_text(encoding='utf-8')
    show(f'{d.relative_to(TOP)}: names no person, quotes no chat, names no session',
         not names_in(t) and not CHAT.search(t) and not SESSION_ID.search(t),
         f'{names_in(t)} {bool(CHAT.search(t))} {bool(SESSION_ID.search(t))}')

# ── 2 · refused phrases ───────────────────────────────────────────────────────────────────
for d in DOCS:
    low = d.read_text(encoding='utf-8').lower()
    found = [r for r in REFUSED if r in low]
    show(f'{d.relative_to(TOP)}: no refused phrase', not found, found)

# ── 3 · the opening ───────────────────────────────────────────────────────────────────────
for r in READMES:
    lines = r.read_text(encoding='utf-8').splitlines()
    first = []
    for ln in lines[1:]:
        if ln.strip():
            first.append(ln.strip())
        elif first:
            break
    para = ' '.join(first)
    show(f'{r.relative_to(TOP)}: opens with the agreed sentence', para == OPENING, para[:160])
    links = re.findall(r'\]\((https?://[^)]+)\)', para)
    show(f'{r.relative_to(TOP)}: the opening links /laserbrain and nothing else',
         links == ['https://phronesis.world/laserbrain'], links)

# ── 4 · R7: when to check in ──────────────────────────────────────────────────────────────
for d in READMES + [SKILL]:
    flat = ' '.join(d.read_text(encoding='utf-8').split())
    show(f'{d.relative_to(TOP)}: says to check in {CADENCE!r}', CADENCE in flat)
    bad = re.findall(r'(?:call|run|check in|check)\w*\s+(?:check_state\s+)?(?:on\s+)?(?:every|each) step', flat, re.I)
    show(f'{d.relative_to(TOP)}: never says to check every step', not bad, bad)

print('\n  all ok' if ok else '\n  FAILURES above')
raise SystemExit(0 if ok else 1)
