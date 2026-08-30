"""methods.py — phronesis's own workflows, as stored methods.

lasergear is the instructions layer, so this is where the methods live. Running it writes
them into the store (laserstore), where anything — nova, a future session, Diego — can vend
them.

WHY THESE THREE

Not invented. Each is a method that was performed BY HAND on 2026-07-28/29 and got wrong,
in a way a declared workflow would have caught:

  release   0.12.0 went to PyPI with 53 exports instead of 56. The wheel was built before
            workflow.py existed and never rebuilt. PyPI versions cannot be reused.
  deploy    a commit and a push went out on a RED build, because the steps were written as
            separate shell lines instead of chained — so a failure did not stop what
            followed.
  grammar   the 1.8.0/1.9.0 sync into phronesis-world was uncommitted when git filter-repo
            hard-reset the working tree, and two copies silently reverted to 1.7.0.

Every one of those is an ordering failure, which is the failure a workflow exists to make
impossible: a step that must precede another, and did not.

WHAT A STORED METHOD IS AND IS NOT

It carries the steps, the goal each step is for, and which of them cannot be taken back. It
carries NO code. The point is not automation — these are not scripts. The point is that the
shape is written down and measurable, so a run can be checked against the method rather
than against someone's memory of it.

`irreversible` and `outward` are not decoration. A step marked either way is refused by the
Operator unless a person authorized it, per action and per session, so `pypi-upload` cannot
be reached by an agent working unattended.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/'
                       'phronesis/laserbrain-sdk'))

from laserbrain import Store, Workflow          # noqa: E402


def release() -> Workflow:
    """Publish a laserbrain version to PyPI.

    The rebuild step is FIRST and separate from the build check on purpose. 0.12.0's whole
    failure was a stale artifact passing a check that only ever looked at symbols someone
    had listed by hand.
    """
    w = Workflow(goal='publish a verified laserbrain release to PyPI')
    w.step('test', goal='every test file exits zero')
    w.step('bump', goal='the version rises in pyproject and __init__')
    w.step('edit-changelog', goal='the changelog records what changed and why')
    w.step('build-wheel', goal='rebuild the wheel from the current tree')
    w.step('verify-artifact',
           goal='the built wheel exports match the tree and the headline path runs')
    w.step('commit', goal='the source of this release is committed and pushed')
    w.step('upload-pypi', goal='upload the release to PyPI',
           irreversible=True, outward=True)
    w.step('verify-published',
           goal='install from PyPI in a clean venv outside the tree and import')
    # Added 2026-07-29 after this method was USED. Bumping the SDK invalidates the drift
    # vectors in phronesis-world, which are generated from it — so the site's laserstore
    # gate fails on the next build, in a different repo, with nothing linking the two.
    # A release is not finished when PyPI has the wheel; it is finished when everything
    # generated FROM the wheel agrees with it again.
    w.step('generate-vectors',
           goal='regenerate the drift vectors so the site gate compares against this version')
    return w


def deploy() -> Workflow:
    """Ship phronesis.world.

    `gate-check` is its own step rather than part of the build because that is precisely
    the distinction that was lost: a red build did not stop the commit that followed it.

    `deploy` is irreversible. It was written reversible=False here first, and the dictionary
    linter caught it on its first run against a real method — putting a build in front of
    users cannot be un-shown, and a later deploy replaces it rather than undoing it.
    """
    w = Workflow(goal='ship phronesis.world with every gate green')
    w.step('build', goal='the site builds and every prebuild gate passes')
    w.step('gate-check', goal='no gate reports a problem')
    w.step('commit', goal='the source of this deploy is committed and pushed')
    w.step('deploy', goal='publish the built site to Cloudflare Pages',
           irreversible=True, outward=True)
    w.step('verify-live',
           goal='fetch the changed page from the deployment URL, not the cached domain')
    return w


def grammar_bump() -> Workflow:
    """Change the canonical grammar.

    `commit-copies` exists because of the specific way this failed: the synced copies were
    left uncommitted and a history rewrite discarded them. A generated file that is not
    committed is not synced, it is only currently correct.
    """
    w = Workflow(goal='change the canonical grammar and keep every copy honest')
    w.step('edit-canonical', goal='edit lasermind grammar.json, the one source')
    w.step('bump-version', goal='raise laserbrain_grammar so the change has a name')
    w.step('generate-hash',
           goal='recompute content_hash over the file including its trailing newline')
    w.step('gate', goal='check-grammar-version agrees the hash describes the content')
    w.step('sync', goal='propagate the canonical file to every copy')
    # Added 2026-07-29 by the stale-verify rule, which this method's own failure produced.
    # sync is a CHANGE after the verify: without this step the propagated copies get
    # committed with nothing having checked them, which is exactly how two of them were
    # recorded sitting at 1.7.0 while canonical was 1.9.0.
    w.step('verify-copies',
           goal='every copy is byte-identical to the canonical file after syncing')
    w.step('commit-copies',
           goal='commit the synced copies so a rewrite cannot silently revert them')
    return w


def research_note() -> Workflow:
    """Publish a research note to phronesis.world.

    Performed by hand 2026-07-29 for the harness detection study and got wrong: written
    only to public/research/, and check-research-served caught it as an orphan. The
    convention is a WORKING copy in research/ and a SERVED copy in public/research/.

    `measure` is first because a note whose numbers cannot be reproduced is not a note.
    """
    w = Workflow(goal='publish a research note with reproducible numbers')
    w.step('measure', goal='the analysis runs and produces the numbers the note will quote')
    w.step('edit-note',
           goal='write the note in both research/ and public/research/, byte-identical')
    w.step('build', goal='the site builds and check-research-served finds no orphan')
    w.step('verify-served',
           goal='the note is in the build output and the working copy matches the served one')
    w.step('commit', goal='the note and the script that reproduces it are recorded')
    w.step('deploy', goal='publish the built site', irreversible=True, outward=True)
    w.step('verify-live',
           goal='fetch the note from the deployment URL and find the result in it')
    return w


def repo_surgery() -> Workflow:
    """Rewrite git history to remove something that should never have been committed.

    Performed 2026-07-29 to strip a 14GB dataset that made phronesis-world unpushable for
    51 commits. One thing went wrong: git filter-repo HARD-RESETS the working tree, so
    uncommitted changes are discarded — the grammar sync was uncommitted and two copies
    silently reverted.

    Hence `commit` BEFORE `generate-backup`, not after. `verify-fastforward` decides whether
    this is safe at all: if the data is already on the remote, the rewrite means force-
    pushing over published history, which is a different and much worse operation.
    """
    w = Workflow(goal='remove something from git history without losing anything else')
    w.step('inspect-history', goal='find what is oversized and when it entered')
    # Added 2026-07-29 after a token leaked through a rewrite-and-push done by hand. A
    # history rewrite is the moment to scan, because it is the last point at which the
    # history can still be changed cheaply.
    w.step('inspect-secrets',
           goal='lb_secrets finds nothing in any commit before the history is republished')
    w.step('verify-fastforward',
           goal='the offending commits are unpushed, so nothing published is rewritten')
    w.step('commit', goal='record every uncommitted change, because the rewrite eats them')
    w.step('generate-backup', goal='clone .git so the rewrite is recoverable')
    w.step('rewrite-history', goal='strip the paths from every commit that carries them',
           irreversible=True)
    w.step('verify-history',
           goal='no oversized blobs remain, commits survived, the old tip kept its sha')
    w.step('push', goal='send the rewritten history to the remote',
           irreversible=True, outward=True)
    w.step('verify-remote', goal='the remote matches local and the work is there')
    return w


def new_repo() -> Workflow:
    """Put a directory under git and push it to a new remote.

    Performed FIVE times by hand on 2026-07-29 — papers, book, spectral-backend, lasergear,
    laserfield-private — and got wrong once: a Telegram bot token went to GitHub inside
    laserfield's history and GitGuardian caught it about an hour later.

    The check that cleared it grepped four patterns (sk-, pypi-, ghp_, AKIA) and reported
    "0 hits". A Telegram token matches none of them. The failure was not the missing
    pattern, it was reading a four-pattern grep as a secret scan.

    So `inspect-secrets` is its own declared step, run against HISTORY rather than the
    working tree — the leaked token was absent from the tip and present in one commit from
    May, so scanning the checkout would still have said clean. `push` is irreversible and
    outward because a secret that reaches a remote is leaked whatever happens next; the
    history can be rewritten and the credential still has to be revoked.
    """
    w = Workflow(goal='put a directory under git and push it somewhere safe')
    w.step('inspect-size',
           goal='no file is large enough to make the repo unpushable')
    w.step('inspect-secrets',
           goal='lb_secrets finds nothing in the working tree OR the history')
    w.step('edit-gitignore',
           goal='build output, virtualenvs and caches are excluded before the first commit')
    w.step('verify-staged',
           goal='what is about to be committed is what was actually checked')
    w.step('commit', goal='the initial history exists locally')
    w.step('push', goal='send it to a new private remote',
           irreversible=True, outward=True)
    w.step('verify-remote',
           goal='clone it back and confirm the remote holds what the local does, and no secret')
    return w


METHODS = {'release': release, 'deploy': deploy, 'grammar-bump': grammar_bump,
           'research-note': research_note, 'repo-surgery': repo_surgery,
           'new-repo': new_repo}


def main():
    store = Store()
    for name, build in METHODS.items():
        w = build()
        path = store.put(w, name)
        acts = [s.name for s in w.steps if s.irreversible or s.outward]
        print(f'  stored {name:<13} {len(w.steps)} steps, gated: {acts or "none"}')
        print(f'         {path}')
    print()
    print('  catalogue:')
    for row in store.catalogue():
        print(f'    {row["name"]:<13} {row["goal"]}')


if __name__ == '__main__':
    main()
