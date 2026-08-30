"""A private state root for a suite, so no test can poison another.

WHY — the two-day flake, and the reason lb_paths.py exists at all

`user-turn` is one file at one path shared by every suite and both agents. Setting it is
how the harness says "the user just spoke", and a set flag turns `excursion` into
`reground` — so a suite that sets it and a suite that reads it are testing each other.
test_parent_overlap failed intermittently for two days and then passed nine times in a
row when run alone, which is the signature of exactly this and nothing else.

It was worse than a flake: test_parent_overlap ALSO deleted the real `user-turn` from the
running agent's own state, on every run.

    import _testhome; _testhome.isolate()

sets LASERBRAIN_HOME in os.environ before anything reads it, and returns the private
root. Both halves of a suite pick it up: Python via lb_paths / laserbrain._paths, and a
spawned `node mcp-server.mjs` via inherited environment — the suites already pass
`{**os.environ, ...}`, so the server lands in the same private tree without another edit.

Call it FIRST, above any laserbrain import, since the resolvers read the variable at
import time.
"""
import atexit
import os
import pathlib
import shutil
import tempfile


def isolate(keep=False):
    """Point LASERBRAIN_HOME at a fresh temp root and return it. Idempotent."""
    have = os.environ.get('LASERBRAIN_HOME')
    if have:
        return pathlib.Path(have)
    root = pathlib.Path(tempfile.mkdtemp(prefix='lb-test-'))
    (root / 'config').mkdir()
    (root / 'sessions').mkdir()
    os.environ['LASERBRAIN_HOME'] = str(root)
    if not keep:
        atexit.register(shutil.rmtree, root, True)
    return root


def config(*parts):
    """A file under the isolated config root — config('user-turn')."""
    return isolate().joinpath('config', *parts)
