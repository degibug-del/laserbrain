#!/usr/bin/env bash
# Publish laserbrain 0.19.0 to PyPI.
#
# You run this, not me. The token is read with `read -rs` into a variable that lives only
# for the length of this process — never echoed, never written to a file, never in an env
# var another process can read, and never through the assistant's context.
#
# A PyPI release is PERMANENT. A version cannot be reused even after deleting it, so this
# refuses to upload if 0.19.0 already exists.
#
# WHY STEP 5 CHANGED, AND IT MATTERS
#
# 0.10.0 shipped without Nova. The fix was step 5: install the built wheel into a clean
# venv, cd somewhere neutral, and import from site-packages rather than from the tree.
#
# 0.12.0 then shipped without Workflow and Store — with step 5 passing. The check asserted
# a HAND-WRITTEN list of symbols: Nova, Skill, Operator, Refused. Every one was present, so
# it went green while the wheel was three exports short, because a hardcoded list can never
# contain the thing you just added. The check was stale in exactly the situation it exists
# for.
#
# So it no longer names symbols. It reads `__all__` from the SOURCE TREE and from the
# INSTALLED WHEEL and diffs them. Anything exported but not shipped fails the release,
# automatically, forever, with no list for anyone to remember to update.

set -euo pipefail
cd "$(dirname "$0")"

DIST=dist_0190
VERSION=0.19.0

echo "── laserbrain ${VERSION} → PyPI"
echo

# 1 · the artifacts exist
for f in "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" "${DIST}/laserbrain-${VERSION}.tar.gz"; do
  [ -f "$f" ] || { echo "  missing: $f"; echo "  run: python3 -m build --outdir ${DIST}"; exit 1; }
  printf "  ok  %s  (%s bytes)\n" "$(basename "$f")" "$(wc -c < "$f" | tr -d ' ')"
done

# 2 · the declared versions agree
PYPROJ=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
DUNDER=$(grep -m1 '^__version__' laserbrain/__init__.py | sed "s/.*'\(.*\)'.*/\1/")
if [ "$PYPROJ" != "$VERSION" ] || [ "$DUNDER" != "$VERSION" ]; then
  echo "  version mismatch: pyproject=${PYPROJ} __init__=${DUNDER} expected=${VERSION}"
  exit 1
fi
echo "  ok  version ${VERSION} in pyproject.toml and __init__.py"

# 3 · not already on PyPI. Upload is one-way.
if curl -sf "https://pypi.org/pypi/laserbrain/${VERSION}/json" >/dev/null 2>&1; then
  echo; echo "  ${VERSION} is ALREADY on PyPI. Bump the version first."; exit 1
fi
echo "  ok  ${VERSION} is not yet published"

# 4 · twine's own check
python3 -m twine check "${DIST}"/* >/dev/null 2>&1 \
  && echo "  ok  twine check" \
  || { echo "  twine check failed"; python3 -m twine check "${DIST}"/*; exit 1; }

# 5 · THE ARTIFACT CHECK. Diff the tree's exports against the installed wheel's.
TREE_ALL=$(python3 -c "import sys; sys.path.insert(0,'.'); import laserbrain as L; print(' '.join(sorted(L.__all__)))")
VENV=$(mktemp -d)/v
python3 -m venv "$VENV" >/dev/null 2>&1
"$VENV/bin/pip" install -q "${DIST}/laserbrain-${VERSION}-py3-none-any.whl" >/dev/null 2>&1 \
  || { echo "  the built wheel does not install"; exit 1; }

# cd out of the source tree first: from here, `import laserbrain` finds ./laserbrain and
# every assertion below would pass while saying nothing about the wheel.
WHEEL_ALL=$( cd / && "$VENV/bin/python" -c "
import laserbrain as L
assert 'site-packages' in L.__file__, 'not the installed copy: ' + L.__file__
print(' '.join(sorted(L.__all__)))
" ) || { echo "  the wheel does not import"; exit 1; }

MISSING=$(comm -23 <(tr ' ' '\n' <<<"$TREE_ALL" | sort -u) <(tr ' ' '\n' <<<"$WHEEL_ALL" | sort -u) | tr '\n' ' ')
if [ -n "${MISSING// /}" ]; then
  echo
  echo "  ARTIFACT CHECK FAILED — the wheel is short of the tree."
  echo "    exported but not shipped: ${MISSING}"
  echo "    rebuild:  python3 -m build --outdir ${DIST}"
  echo
  echo "  This is what let 0.12.0 go out without Workflow and Store."
  exit 1
fi
TREE_N=$(wc -w <<<"$TREE_ALL" | tr -d ' ')
echo "  ok  wheel exports match the tree exactly (${TREE_N} symbols)"

# ...and that the headline objects actually construct, not merely import.
# The __all__ diff above catches a missing top-level SYMBOL. It cannot catch a missing
# METHOD — `Nova.follow` is not an export — so the headline path is exercised end to end
# here instead: author a method, store it, vend it, bind an agent's own skills to it, run
# it with the operator gating the step that acts.
( cd / && "$VENV/bin/python" - <<'PY'
import tempfile
from laserbrain import Nova, Operator, Refused, Workflow, Store

with tempfile.TemporaryDirectory() as shelf:
    author = Workflow(goal='verify the artifact')
    author.step('probe', lambda c: None, goal='the probe runs')
    author.step('ship', lambda c: None, goal='the artifact ships', irreversible=True)

    store = Store(root=shelf)
    store.put(author, 'verify')
    spec = store.vend('verify')
    assert [s['name'] for s in spec['steps'] if s['irreversible']] == ['ship'], spec

    done = []
    n = Nova(goal='verify the artifact')
    n.learn('probe', lambda c: done.append('probe') or {'progress': 'advancing', 'distance': 1})
    n.learn('ship', lambda c: done.append('ship') or {'progress': 'advancing', 'distance': 0})

    w = store.get('verify')
    assert w.unbound() == ['probe', 'ship'], w.unbound()

    # No operator: the irreversible step must be refused, not run.
    out = n.follow(w, operator=None)
    assert out['refused_at'] == 'ship', out
    assert done == ['probe'], done

    # With one: it completes.
    done.clear()
    w2 = store.get('verify')
    n2 = Nova(goal='verify the artifact')
    n2.learn('probe', lambda c: done.append('probe') or {'progress': 'advancing', 'distance': 1})
    n2.learn('ship', lambda c: done.append('ship') or {'progress': 'advancing', 'distance': 0})
    out2 = n2.follow(w2, operator=Operator(authorize=lambda a: True))
    assert out2['completed'] is True, out2
    assert done == ['probe', 'ship'], done

print('  ok  author → store → vend → nova.follow → operator, end to end')
PY
) || { echo "  the shipped objects do not work"; exit 1; }
rm -rf "$VENV"

echo
echo "  This uploads permanently. ${VERSION} can never be reused."
read -r -p "  Type the version to confirm: " CONFIRM
[ "$CONFIRM" = "$VERSION" ] || { echo "  aborted"; exit 1; }

echo
echo "  Paste your PyPI API token (starts pypi-). Input is hidden."
read -rs -p "  token: " PYPI_TOKEN
echo
[ -n "$PYPI_TOKEN" ] || { echo "  no token, aborted"; exit 1; }

TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
  python3 -m twine upload "${DIST}"/*
unset PYPI_TOKEN

echo
echo "  published. verify from OUTSIDE the source tree:"
echo "    cd /tmp && python3 -m venv c && ./c/bin/pip install -q laserbrain==${VERSION}"
echo "    ./c/bin/python -c 'from laserbrain import Workflow, Store; print(Workflow)'"
