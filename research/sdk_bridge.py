#!/usr/bin/env python3
"""The MCP server's door into the Python SDK.

Reads one JSON object on stdin, writes one JSON object on stdout. Nothing else — no
banner, no logging to stdout, because the caller parses the whole stream.

WHY A BRIDGE AND NOT A REIMPLEMENTATION
---------------------------------------
Supercode, Search, Writer and the six catches are Python. The MCP server is JavaScript.
The tempting move is to port them, and this session is a catalogue of what that costs:
three hand-kept copies of the logo that had already drifted, a verdict set that shipped
nine in the SDK and eight on the site, four separate resolvers for one log path. Every one
of those was two copies of a thing that had to agree and no mechanism making them.

So: one implementation, reached over a pipe. A port would be a seventh copy.

WHICH SDK
---------
`import laserbrain` resolves to site-packages, which is the PUBLISHED build and lags the
working tree — on 2026-07-27 the installed 0.7.0 was missing three catches from __all__
and the whole tandem->link rename. A bridge that silently called the stale copy would be
the same drift wearing a different hat, so the source tree wins when it is present and the
answer says which one it used. Override with LASERBRAIN_SDK.

WHAT CANNOT COME THROUGH
------------------------
`stale_gate(gate, mutate, sample)` takes two callables — a gate to run and a mutation to
apply. Those are code, not data, and there is no honest way to send them through a JSON
tool boundary. It stays a Python-only function and `capabilities` reports it as such
rather than pretending.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

# ── resolve the SDK before importing it ──────────────────────────────────────────
_SRC = os.environ.get('LASERBRAIN_SDK') or str(
    Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/phronesis/laserbrain-sdk'
)
if (Path(_SRC) / 'laserbrain' / '__init__.py').exists():
    sys.path.insert(0, _SRC)

import laserbrain as lb                                            # noqa: E402

# Report the file that actually got imported, not the mechanism that found it. The first
# version said 'installed' or 'source:<path>' based on which branch ran — which went wrong
# the moment the package was installed editable, because then 'installed' AND 'source' are
# the same files and the label implied a difference that no longer existed. A path cannot
# be wrong in that way.
_resolved = Path(lb.__file__).resolve().parent.parent
_origin = str(_resolved)
_editable = str(_resolved) == str(Path(_SRC).resolve())
# `laserbrain.catches` the FUNCTION shadows `laserbrain.catches` the MODULE, so the six
# catch helpers are unreachable as attributes of the package. importlib gets the module.
_catches = importlib.import_module('laserbrain.catches')


def _events(raw):
    """JSON dicts -> Event. Unknown keys are dropped rather than raising: an agent
    sending an extra field should not get a stack trace for being generous."""
    fields = {f for f in _catches.Event.__dataclass_fields__}
    return [_catches.Event(**{k: v for k, v in e.items() if k in fields}) for e in (raw or [])]


def _catch_json(cs):
    return [{'signature': c.signature, 'detail': c.detail, 'evidence': list(c.evidence)} for c in cs]


# ── the operations ───────────────────────────────────────────────────────────────
def op_capabilities(_):
    return {
        'sdk': getattr(lb, '__version__', '?'),
        'origin': _origin,
        'is_working_tree': _editable,
        'exports': len(getattr(lb, '__all__', [])),
        'tools': sorted(OPS),
        'python_only': {
            'stale_gate': 'takes a gate callable and a mutate callable — code, not data, '
                          'so it cannot cross a JSON tool boundary. Use it from Python.',
        },
    }


def op_find_bugs(a):
    """Every catch that the given evidence can actually support.

    Deliberately one tool rather than five: the caller has some evidence and wants to know
    what is wrong with it, and should not have to know which of five functions applies.
    Catches whose inputs are absent are reported as skipped, so an empty result is
    distinguishable from a result that never ran — which is the `unrun` failure this very
    module exists to detect.
    """
    found, ran, skipped = [], [], []
    evs = _events(a.get('events'))
    if evs:
        for name, fn, kw in (('unfalsified', _catches.unfalsified, {}),
                             ('instrument_blind', _catches.instrument_blind,
                              {'repeats': a.get('repeats', 3)}),
                             ('unrun', _catches.unrun, {})):
            found += _catch_json(fn(evs, **kw)); ran.append(name)
    else:
        skipped += ['unfalsified', 'instrument_blind', 'unrun']

    if a.get('before') is not None and a.get('after') is not None and a.get('pattern'):
        found += _catch_json(_catches.residue(a['before'], a['after'], a['pattern'],
                                              a.get('flags', 0)))
        ran.append('residue')
    else:
        skipped.append('residue')

    if a.get('text'):
        found += _catch_json(_catches.contaminated(a['text'])); ran.append('contaminated')
    else:
        skipped.append('contaminated')

    return {'catches': found, 'count': len(found), 'ran': ran, 'skipped': skipped,
            'note': 'stale_gate needs callables and cannot run over MCP'}


def op_explore(a):
    """Replay a trail through Search and report where the exploration stands.

    The trail is passed whole on every call and the Search is rebuilt from it, so this
    holds no state between calls. That is on purpose: state that lives in a long-running
    subprocess is state that disagrees with the caller's after a restart.
    """
    s = lb.Search()
    trail = a.get('trail') or []
    if not trail:
        return {'error': 'trail is empty — pass the goals you have explored, oldest first'}
    r = None
    for g in trail:
        r = s.ground(g)
    out = {'reason': r.reason, 'novelty': round(r.novelty, 3),
           'commitment': round(r.commitment, 3), 'revisit': round(r.revisit, 3),
           'grounds': r.grounds, 'advice': r.advice, 'steps': len(trail)}
    if r.trail:
        out['trail'] = r.trail
    try:
        out['territory'] = s.territory()
    except Exception:
        pass
    return out


def op_trailscore(a):
    goals = a.get('goals') or []
    return {'trailscore': lb.trailscore(goals), 'goals': len(goals)}


def op_supercode(a):
    """Supervise a set of agents. Advisory — it reports, it does not interrupt."""
    sc = lb.Supercode(a['goal']) if a.get('goal') else lb.Supercode()
    for o in a.get('observations') or []:
        sc.observe(agent=o.get('agent', 'agent'), goal=o.get('goal', ''),
                   progress=o.get('progress', 'advancing'), distance=o.get('distance'),
                   parent_goal=o.get('parent_goal'), user_turn=bool(o.get('user_turn')))
    # collisions() is reported separately from findings() because it answers a different
    # question. findings() is "which agent has left its ground"; collisions() is "which
    # two are on the SAME one" — and a run can have none of the first and still be wasting
    # half its agents.
    # laserbrain is the reference; supercode is the manager. So this returns three
    # different kinds of thing and does not blur them:
    #   findings   — what the REFERENCE said about each agent, unmodified
    #   collisions — a relation only the manager can see
    #   route      — what the manager RECOMMENDS, with `keep: null` where it has no
    #                honest basis and will not manufacture one
    # manage() itself cannot come through here: it takes step callables, which are code
    # rather than data. This is its decision surface, which is the part an agent can use.
    return {'report': sc.report(), 'findings': sc.findings(),
            'collisions': sc.collisions(), 'route': sc.route(),
            # Only what a per-agent Bugfinder cannot reach — including where fleet
            # evidence CLEARS a per-agent catch rather than adding one.
            'fleet_catches': sc.fleet_catches(),
            'self_check': {'reason': sc.self_check().reason,
                           'phi': sc.self_check().phi},
            'observed': len(a.get('observations') or [])}


def op_write_grounded(a):
    """Generate text steered toward a ground, and score how close it landed."""
    corpus = a.get('corpus')
    if isinstance(corpus, str):
        corpus = [corpus]
    if not corpus:
        return {'error': 'corpus is empty — pass the text to learn from'}
    w = lb.Writer(order=a.get('order', 3), seed=a.get('seed'))
    w.train(corpus)
    ground = a.get('ground') or ''
    text = w.write(ground, words=a.get('words', 60), pull=a.get('pull', 1.0),
                   top_k=a.get('top_k', 24))
    return {'text': text, 'ground': ground, 'grounding': round(w.grounding(text, ground), 3)}


def op_read_text(a):
    """Read the shape of a text — the companion to op_write_grounded.

    write_grounded holds GENERATION to a ground; this asks what shape writing is already
    in. Both go through the package rather than being reimplemented here, which is the
    whole reason this bridge exists.
    """
    try:
        conn = float(a.get('connectivity') or 0.0)
    except (TypeError, ValueError):
        conn = 0.0
    return lb.read_text(a.get('text') or '', connectivity=conn)


def op_similarity(a):
    sim = lb.embedding_similarity(a['model']) if a.get('model') else lb.embedding_similarity()
    return {'similarity': round(float(sim(a.get('a', ''), a.get('b', ''))), 4)}


OPS = {
    'capabilities': op_capabilities,
    'find_bugs': op_find_bugs,
    'explore': op_explore,
    'trailscore': op_trailscore,
    'supercode': op_supercode,
    'write_grounded': op_write_grounded,
    'read_text': op_read_text,
    'similarity': op_similarity,
}


def main():
    try:
        req = json.loads(sys.stdin.read() or '{}')
        fn = OPS.get(req.get('op'))
        if fn is None:
            out = {'error': f"unknown op {req.get('op')!r}", 'known': sorted(OPS)}
        else:
            out = fn(req)
    except Exception as e:                       # the caller gets a reason, never a hang
        out = {'error': f'{type(e).__name__}: {e}'}
    json.dump(out, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
