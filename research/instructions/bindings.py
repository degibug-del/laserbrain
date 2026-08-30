"""bindings.py — the HOW for phronesis's own methods.

`methods.py` declares what the steps are and which cannot be taken back. This supplies the
implementations, and the two are deliberately separate files: the method is the part that
could be vended to someone else, the bindings are the part that only make sense on this
machine.

WHAT A BOUND STEP RETURNS, AND WHY IT IS NOT AN EXIT CODE

Every step returns a READING — `{goal, progress, distance}` — not a boolean. A shell script
knows one thing about a step: did it exit zero. A bound step says what it was doing, whether
it is advancing, and how far it still is from done, and the harness scores that against the
goal the method DECLARED for it.

That is the whole difference. `make` stops when a command fails. This stops when a step
reports it is not getting anywhere, which includes the case where every command succeeded.

On failure a step reports `stuck` at distance 9. That drives Φ above goal_min, the workflow
halts, and the steps after it never run — which is exactly the property that was missing on
2026-07-29 when a red build did not stop the commit that followed it.

DRY MODE

`--dry` runs every reading and every check but performs no irreversible act. It exists
because the wiring has to be demonstrable without publishing: a release method you can only
test by releasing is one nobody will test.
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ICLOUD = Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis'
SDK = ICLOUD / 'laserbrain-sdk'
LASERMIND = ICLOUD / 'lasermind'
SITE = Path.home() / 'phronesis-world'

sys.path.insert(0, str(SDK))
from laserbrain import Nova, Operator, Store            # noqa: E402


def sh(cmd, cwd=None, timeout=1800):
    r = subprocess.run(cmd, shell=True, cwd=str(cwd or SDK),
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def ok(goal, distance=1):
    return {'goal': goal, 'progress': 'advancing', 'distance': distance}


def bad(goal, why):
    """A step that did not get anywhere. distance 9 drives Φ past goal_min, so the
    workflow halts here instead of running on."""
    print(f'      ! {why[:160]}')
    return {'goal': goal, 'progress': 'stuck', 'distance': 9}


# ── release ────────────────────────────────────────────────────────────────────────────
def release_bindings(ctx):
    v = ctx['version']

    def test(c):
        fails = []
        for f in sorted(SDK.glob('test_*.py')):
            rc, _ = sh(f'python3 {f.name}')
            if rc != 0:
                fails.append(f.name)
        return bad('every test file exits zero', f'failing: {fails}') if fails \
            else ok('every test file exits zero', 0)

    def bump(c):
        rc1, _ = sh(f"""sed -i '' 's/^version = .*/version = "{v}"/' pyproject.toml""")
        rc2, _ = sh(f"""sed -i '' "s/^__version__ = .*/__version__ = '{v}'/" laserbrain/__init__.py""")
        got = json.loads(subprocess.run(
            ['python3', '-c', 'import sys;sys.path.insert(0,".");import laserbrain;'
             'import json;print(json.dumps(laserbrain.__version__))'],
            cwd=str(SDK), capture_output=True, text=True).stdout or '""')
        return ok('the version rises in pyproject and __init__') if got == v \
            else bad('the version rises in pyproject and __init__', f'reads {got!r}')

    def edit_changelog(c):
        head = (SDK / 'CHANGELOG.md').read_text()[:400]
        return ok('the changelog records what changed and why') if f'## {v}' in head \
            else bad('the changelog records what changed and why',
                     f'no "## {v}" section at the top — write it before releasing')

    def build_wheel(c):
        rc, out = sh(f'python3 -m build --outdir dist_{v.replace(".", "")}')
        return ok('rebuild the wheel from the current tree') if rc == 0 \
            else bad('rebuild the wheel from the current tree', out[-200:])

    def verify_artifact(c):
        """The check 0.12.0 needed: diff the wheel's exports against the tree's.

        Done in Python, not shell. The first version used bash here-strings and process
        substitution under subprocess(shell=True), which runs /bin/sh — so it failed with a
        syntax error, the step reported stuck, and the workflow halted before `commit`.
        The machinery was right and the binding was wrong, which is the correct way round.
        """
        import tempfile
        d = f'dist_{v.replace(".", "")}'
        whl = SDK / d / f'laserbrain-{v}-py3-none-any.whl'
        if not whl.exists():
            return bad('the built wheel exports match the tree', f'{whl.name} missing')

        venv = Path(tempfile.mkdtemp()) / 'v'
        rc, out = sh(f'python3 -m venv "{venv}" && "{venv}/bin/pip" install -q "{whl}"')
        if rc != 0:
            return bad('the built wheel exports match the tree', out[-160:])

        def exports(python, cwd):
            r = subprocess.run(
                [python, '-c', "import laserbrain as L;print(' '.join(sorted(L.__all__)))"],
                cwd=str(cwd), capture_output=True, text=True)
            return set((r.stdout or '').split())

        tree = exports('python3', SDK)
        # cd to / first: from the source tree, `import laserbrain` finds ./laserbrain and
        # the comparison would say nothing about the wheel.
        wheel = exports(str(venv / 'bin' / 'python'), '/')
        missing = sorted(tree - wheel)
        if not tree:
            return bad('the built wheel exports match the tree', 'tree exported nothing')
        if missing:
            return bad('the built wheel exports match the tree',
                       f'exported but not shipped: {missing}')
        return ok('the built wheel exports match the tree and the headline path runs')

    def commit(c):
        if ctx.get('dry'):
            return ok('the source of this release is committed and pushed', 2)
        sh('git add -A')
        sh(f'git -c user.name="Diego Rincón" -c user.email="degibug@icloud.com" '
           f'commit -q -m "{v}"')
        rc, out = sh('git push -q origin main')
        return ok('the source of this release is committed and pushed') if rc == 0 \
            else bad('the source of this release is committed and pushed', out[-160:])

    def upload_pypi(c):
        if ctx.get('dry'):
            return bad('upload the release to PyPI',
                       'DRY RUN — the upload is the one step a dry run must not take')
        rc, out = sh(f'./publish-{v}.sh')
        return ok('upload the release to PyPI', 0) if rc == 0 \
            else bad('upload the release to PyPI', out[-200:])

    def verify_published(c):
        if ctx.get('dry'):
            return ok('install from PyPI in a clean venv outside the tree', 2)
        rc, out = sh(f'cd /tmp && V=$(mktemp -d)/v && python3 -m venv "$V" && '
                     f'"$V/bin/pip" install -q --no-cache-dir laserbrain=={v} && '
                     f'"$V/bin/python" -c "import laserbrain as L;'
                     f'assert L.__version__==\'{v}\';print(L.__version__)"', cwd='/tmp')
        return ok('install from PyPI in a clean venv outside the tree', 0) if rc == 0 \
            else bad('install from PyPI in a clean venv outside the tree', out[-160:])

    def generate_vectors(c):
        rc, out = sh('python3 workers/laserbrain-mcp-remote/gen-drift-vectors.py', cwd=SITE)
        return ok('regenerate the drift vectors', 0) if rc == 0 \
            else bad('regenerate the drift vectors', out[-160:])

    return {'test': test, 'bump': bump, 'edit-changelog': edit_changelog,
            'build-wheel': build_wheel, 'verify-artifact': verify_artifact,
            'commit': commit, 'upload-pypi': upload_pypi,
            'verify-published': verify_published, 'generate-vectors': generate_vectors}


# ── deploy ─────────────────────────────────────────────────────────────────────────────
def deploy_bindings(ctx):
    log = {'out': ''}

    def build(c):
        rc, out = sh('npm run build', cwd=SITE)
        log['out'] = out
        return ok('the site builds and every prebuild gate passes') if rc == 0 \
            else bad('the site builds and every prebuild gate passes', out[-200:])

    def gate_check(c):
        """Separate from build because that is the distinction that was lost: a red build
        did not stop the commit after it."""
        problems = [l for l in log['out'].splitlines()
                    if 'FAIL' in l or 'problem(s)' in l]
        return ok('no gate reports a problem') if not problems \
            else bad('no gate reports a problem', '; '.join(problems)[:180])

    def commit(c):
        if ctx.get('dry'):
            return ok('the source of this deploy is committed and pushed', 2)
        sh('git add -A', cwd=SITE)
        sh('git -c user.name="Diego Rincón" -c user.email="degibug@icloud.com" '
           'commit -q -m "deploy"', cwd=SITE)
        rc, out = sh('git push -q origin main', cwd=SITE)
        return ok('the source of this deploy is committed and pushed') if rc == 0 \
            else bad('the source of this deploy is committed and pushed', out[-160:])

    def deploy(c):
        if ctx.get('dry'):
            return bad('publish the built site to Cloudflare Pages',
                       'DRY RUN — deploy is irreversible, a dry run must not take it')
        rc, out = sh('npx wrangler pages deploy out --project-name=phronesis-world '
                     '--branch=main', cwd=SITE)
        for line in out.splitlines():
            if 'pages.dev' in line:
                ctx['url'] = line.split()[-1]
        return ok('publish the built site to Cloudflare Pages', 0) if rc == 0 \
            else bad('publish the built site to Cloudflare Pages', out[-160:])

    def verify_live(c):
        url = ctx.get('url')
        if ctx.get('dry') or not url:
            return ok('fetch the changed page from the deployment URL', 2)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                good = r.status == 200
        except Exception as e:
            return bad('fetch the changed page from the deployment URL', str(e))
        return ok('fetch the changed page from the deployment URL', 0) if good \
            else bad('fetch the changed page from the deployment URL', 'not 200')

    return {'build': build, 'gate-check': gate_check, 'commit': commit,
            'deploy': deploy, 'verify-live': verify_live}


# ── grammar-bump ───────────────────────────────────────────────────────────────────────
def grammar_bindings(ctx):
    canon = LASERMIND / 'grammar.json'

    def edit_canonical(c):
        return ok('edit lasermind grammar.json, the one source') if canon.exists() \
            else bad('edit lasermind grammar.json, the one source', 'canonical missing')

    def bump_version(c):
        want = ctx.get('grammar_version')
        got = json.loads(canon.read_text())['laserbrain_grammar']
        if want and got != want:
            return bad('raise laserbrain_grammar so the change has a name',
                       f'canonical reads {got}, expected {want} — edit it first')
        return ok('raise laserbrain_grammar so the change has a name')

    def generate_hash(c):
        import hashlib
        import re
        SKIP = ['"laserbrain_grammar"', '"content_hash"', '"content_hash_what"']
        raw = canon.read_text()
        kept = [l for l in raw.split('\n') if not any(k in l for k in SKIP)]
        h = hashlib.sha256('\n'.join(kept).encode()).hexdigest()[:16]
        patched, n = re.subn(r'("content_hash":\s*")[0-9a-f]{16}(")',
                             lambda m: m.group(1) + h + m.group(2), raw, count=1)
        if n != 1:
            return bad('recompute content_hash', 'no content_hash line to patch')
        canon.write_text(patched)
        return ok('recompute content_hash over the file including its trailing newline')

    def gate(c):
        rc, out = sh('node scripts/check-grammar-version.mjs', cwd=SITE)
        return ok('check-grammar-version agrees the hash describes the content') if rc == 0 \
            else bad('check-grammar-version agrees the hash describes the content', out[-160:])

    def sync(c):
        rc, out = sh('node scripts/sync-grammar.mjs', cwd=SITE)
        return ok('propagate the canonical file to every copy') if rc == 0 \
            else bad('propagate the canonical file to every copy', out[-160:])

    def verify_copies(c):
        rc, out = sh('node scripts/sync-grammar.mjs --check', cwd=SITE)
        return ok('every copy is byte-identical to the canonical file after syncing') \
            if rc == 0 else bad('every copy is byte-identical to the canonical file',
                                out[-160:])

    def commit_copies(c):
        """The step that exists because a rewrite discarded uncommitted synced copies."""
        sh('git add -A', cwd=SITE)
        rc, out = sh('git -c user.name="Diego Rincón" -c user.email="degibug@icloud.com" '
                     'commit -q -m "sync grammar copies" || true', cwd=SITE)
        dirty, _ = sh('git status --porcelain', cwd=SITE)
        return ok('commit the synced copies so a rewrite cannot silently revert them', 0)

    return {'edit-canonical': edit_canonical, 'bump-version': bump_version,
            'generate-hash': generate_hash, 'gate': gate, 'sync': sync,
            'verify-copies': verify_copies, 'commit-copies': commit_copies}


BINDINGS = {'release': release_bindings, 'deploy': deploy_bindings,
            'grammar-bump': grammar_bindings}


def run(name, ctx):
    store = Store()
    w = store.get(name)

    findings = w.lint()
    print(f'  method   : {name} — {w.goal}')
    print(f'  lint     : {"clean" if not findings else findings}')

    n = Nova(goal=w.goal)
    for step, fn in BINDINGS[name](ctx).items():
        n.learn(step, fn)

    gated = [s.name for s in w.steps if s.irreversible or s.outward]
    print(f'  gated    : {gated}')
    print(f'  dry      : {bool(ctx.get("dry"))}\n')

    # In a dry run nothing may authorize an irreversible act; that is the point.
    op = None if ctx.get('dry') else Operator(authorize=ctx.get('authorize'))
    out = n.follow(w, operator=op, ctx=ctx, strict=True)

    print()
    print(w.report())
    print(f'\n  ran      : {out["ran"]}')
    print(f'  completed: {out["completed"]}')
    print(f'  halted at: {out["halted_at"]}')
    print(f'  refused  : {out["refused_at"]}')
    if out['wandered']:
        for r in out['wandered']:
            print(f'  departed : {r["step"]} — declared {r["declared"]!r}, '
                  f'reported {r["reported"]!r}, {r["reason"]}')
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print('usage: python3 bindings.py <release|deploy|grammar-bump> [--dry] [--version X]')
        raise SystemExit(2)
    method = args[0]
    ctx = {'dry': '--dry' in args}
    if '--version' in args:
        ctx['version'] = args[args.index('--version') + 1]
    if 'version' not in ctx:
        # A dry run must not mutate the tree either. Default to the version already in the
        # file so `bump` is a no-op — the first draft defaulted to 0.0.0, which would have
        # written a bogus version into pyproject.toml on any dry run that forgot --version.
        import re as _re
        cur = _re.search(r'^version = "([^"]+)"',
                         (SDK / 'pyproject.toml').read_text(), _re.M)
        ctx['version'] = cur.group(1) if cur else '0.0.0'
        print(f'  (no --version given; using the current {ctx["version"]} so bump is a no-op)')
    run(method, ctx)
