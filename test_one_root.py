#!/usr/bin/env python3
"""There is one state root, three resolvers agree on it, and nothing bypasses them.

WHY THIS EXISTS

State lived at two hardcoded roots — ~/.config/laserbrain and ~/.claude/laserbrain —
written by eleven files, two of which honoured an override. `user-turn` is one file at one
of those paths, shared by every suite and both agents, and a set flag turns `excursion`
into `reground`. test_parent_overlap failed intermittently for two days and passed nine
times in a row when run alone. It was also DELETING the running agent's own flag on every
run. Nothing could be tested hermetically because nothing could be moved.

lb_paths.py fixed that. This file is what keeps it fixed, because the failure mode is not
a bug — it is one more `Path.home() / '.config' / 'laserbrain'` typed into a new file by
someone who has never read lb_paths.py, and that is invisible until two hosts disagree
about where the corpus is.

THREE COPIES, CHECKED AGAINST EACH OTHER

lasergear, laserbrain-sdk and mcp-server.mjs each resolve the paths themselves, because
the hooks cannot import the SDK (an ImportError there fails the gate, which it must never
do) and the published wheel cannot import lasergear (not shipped). Three deployment units
that genuinely cannot reach each other — so the compiler cannot check they agree, and this
does: same default with the environment clear, same destination with LASERBRAIN_HOME set.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
HOME = pathlib.Path.home()
fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


# ── 1. nothing bypasses a resolver ────────────────────────────────────────────────────
# Only executable lines count: the docstrings deliberately SPELL the historical paths,
# because a reader needs to know what the defaults are.
print('no live code hardcodes a state root')
# The resolvers themselves, and this file. A resolver must spell the default — that is
# what a resolver IS — and this file spells it twice more: once as the expected value it
# asserts against, once as a MIRROR of the JS resolver, which is the whole comparison. A
# gate that flagged them would only teach people to add markers.
RESOLVERS = {'lb_paths.py', 'lb_paths.mjs', '_paths.py', '_testhome.py', '_root.py',
             'test_one_root.py'}
# Only laserbrain's OWN roots. ~/.claude/projects is Claude's transcript directory — a
# different product's path that this file has no business relocating.
# BOTH separators. Python joins with `/` — `Path.home() / '.config' / 'laserbrain'` — and
# JS joins with `,` — `join(homedir(), '.config', 'laserbrain')`. A first draft matched
# only the comma, passed green, and then passed AGAIN with a hardcoded Python path
# deliberately injected into waves.py. A gate that cannot fail is not a gate; the injection
# at the bottom of this file is what caught that, and it is why it is permanent.
PAT = re.compile(r"""['"]\.config['"]\s*[,/]\s*['"]laserbrain|
                     ['"]\.claude['"]\s*[,/]\s*['"]laserbrain|
                     ['"]\.config/laserbrain|
                     ['"]\.claude/laserbrain""", re.X)
# The one exemption, and it must be WRITTEN IN THE SOURCE to count: the hooks carry an
# inline fallback for a missing lb_paths.py, because an ImportError at module scope lands
# above the handler that fails the gate open. That fallback has to spell the defaults.
ALLOW = 'one-root: fallback'
# A SECOND sanctioned marker, and it means something different. `fallback` is "this code
# must spell the default because it runs when the resolver is missing". `live` is "this
# code must reach the REAL corpus, and relocating it would make it vacuous" — which is
# exactly one file: test_corpus_clean, whose subject is what has accumulated in $HOME. Under
# run-tests.sh every suite gets a private root, so a corpus gate that honoured it would find
# an empty directory, report PASS and mean nothing.
ALLOW_LIVE = 'one-root: live'
offenders = []
for d in ('lasergear', 'lasermind', 'laserbrain-sdk/laserbrain'):
    for f in sorted((ROOT / d).rglob('*.py')) + sorted((ROOT / d).rglob('*.mjs')):
        if f.name in RESOLVERS:
            continue
        try:
            src = f.read_text()
        except Exception:
            continue
        # strip comments and docstrings — prose about the path is not a use of the path
        body = re.sub(r'""".*?"""', '', src, flags=re.S)
        body = re.sub(r"'''.*?'''", '', body, flags=re.S)
        body = '\n'.join(l for l in body.split('\n')
                         if not l.lstrip().startswith(('#', '*', '/*', '//')))
        for i, line in enumerate(body.split('\n'), 1):
            if PAT.search(line) and ALLOW not in line and ALLOW_LIVE not in line:
                offenders.append(f'{f.relative_to(ROOT)}: {line.strip()[:70]}')
check('every path goes through a resolver', not offenders,
      f'{len(offenders)} bypass(es)' if offenders else 'lasergear, lasermind, the SDK')
for o in offenders[:8]:
    print(f'        {o}')


# ── 2. the three copies agree, clear and relocated ────────────────────────────────────
def py_lasergear(env):
    return json.loads(subprocess.run(
        [sys.executable, '-c',
         "import importlib.util as u,json;"
         f"sp=u.spec_from_file_location('p',r'{ROOT}/lasergear/lb_paths.py');"
         "m=u.module_from_spec(sp);sp.loader.exec_module(m);"
         "print(json.dumps([str(m.config_dir()),str(m.sessions_dir())]))"],
        capture_output=True, text=True, env=env).stdout)


def py_sdk(env):
    return json.loads(subprocess.run(
        [sys.executable, '-c',
         "import sys,json;sys.path.insert(0,r'" + str(ROOT / 'laserbrain-sdk') + "');"
         "from laserbrain import _paths as p;"
         "print(json.dumps([str(p.config_dir()),str(p.sessions_dir())]))"],
        capture_output=True, text=True, env=env).stdout)


def js_server(env):
    """The server exposes only the config root, which is the one it uses."""
    return [subprocess.run(
        ['node', '-e',
         "const{join}=require('path'),{homedir}=require('os');"
         "const h=process.env.LASERBRAIN_HOME||null;"
          "console.log(h?join(h,'config'):join(homedir(),'.config','laserbrain'))"],
        capture_output=True, text=True, env=env).stdout.strip()]


clear = {k: v for k, v in os.environ.items()
         if k not in ('LASERBRAIN_HOME', 'LASERBRAIN_STATE_DIR')}

print()
print('with the environment clear, all three land on the historical defaults')
g, k, j = py_lasergear(clear), py_sdk(clear), js_server(clear)
want_c, want_s = str(HOME / '.config/laserbrain'), str(HOME / '.claude/laserbrain')
check('lasergear', g == [want_c, want_s], ' | '.join(g))
check('the SDK', k == [want_c, want_s], ' | '.join(k))
check('mcp-server.mjs', j[0] == want_c, j[0])
check('  and that is what shipped before any of this', g == k,
      'an unset environment must behave exactly as it always did')

print()
print('LASERBRAIN_HOME moves all three to the same private tree')
with tempfile.TemporaryDirectory() as d:
    env = {**clear, 'LASERBRAIN_HOME': d}
    g2, k2, j2 = py_lasergear(env), py_sdk(env), js_server(env)
    check('lasergear follows', g2 == [f'{d}/config', f'{d}/sessions'], ' | '.join(g2))
    check('the SDK follows', k2 == [f'{d}/config', f'{d}/sessions'], ' | '.join(k2))
    check('the server follows', j2[0] == f'{d}/config', j2[0])
    check('  and they agree with each other', g2 == k2 and j2[0] == g2[0],
          'three copies, one destination')

print()
print('a specific override still wins over LASERBRAIN_HOME — it predates it')
with tempfile.TemporaryDirectory() as d:
    env = {**clear, 'LASERBRAIN_HOME': d, 'LASERBRAIN_STATE_DIR': '/tmp/explicit'}
    g3, k3 = py_lasergear(env), py_sdk(env)
    check('lasergear honours LASERBRAIN_STATE_DIR', g3[1] == '/tmp/explicit', g3[1])
    check('the SDK honours it too', k3[1] == '/tmp/explicit', k3[1])
    check('  while config still moves with HOME', g3[0] == f'{d}/config', g3[0])

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails[:3]))
    sys.exit(1)
print('  PASS — one root, three resolvers that agree, and no way back to a hardcoded path')
print('  without this saying so.')
