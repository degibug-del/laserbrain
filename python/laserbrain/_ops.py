"""The operations both front doors call, so there is only one of each.

WHY THIS FILE EXISTS. These lived in javascript/sdk_bridge.py, reachable only by the stdio
server shelling out to Python — so `laserbrain mcp`, the offline server in this same
package, could not serve them and shipped 11 tools where the JS one served 28. The
capability was here the whole time; only the door was missing.

Moving them into the package rather than copying them is the argument this codebase makes
everywhere else: two copies of a thing that must agree, with nothing making them agree, is
the bug. sdk_bridge.py imports from here now, so the JS server and the Python server run the
identical function and cannot drift.

EVERY OP IN HERE IS LOCAL. No network, no key, no model — that is the property that lets the
offline server carry them at all, and test_no_network.py checks it by importing this module
with the rest of the package. The tools that DO reach a hosted service (ask_alice,
analyze_language, compare_phrasings, remember_self, resume_self, forget_self) are
deliberately absent and are named in mcp.py's `not_here` block.

Each op takes one dict and returns one dict, because that is what a JSON-RPC tool call and a
stdin/stdout bridge both hand it.
"""
from __future__ import annotations

import importlib
import os

from pathlib import Path

import laserbrain as lb

# WHERE THIS SDK ACTUALLY CAME FROM. sdk_bridge.py computed these at module level and
# op_capabilities read them as globals, so moving the op here left it referencing names that
# no longer existed — caught immediately because the bridge answered
# `NameError: name '_origin' is not defined` on the first call after the move.
#
# Computed here instead, from the package that is actually imported. Reporting the path
# rather than a label is deliberate and predates this file: an editable install makes
# "installed" and "source" the same files, so a label implied a difference that had stopped
# existing. A path cannot be wrong in that way.
_RESOLVED = Path(lb.__file__).resolve().parent.parent
_ORIGIN = str(_RESOLVED)
_EDITABLE = (_RESOLVED / 'pyproject.toml').exists()

_catches = importlib.import_module('laserbrain.catches')


def _events(raw):
    """JSON dicts -> Event. Unknown keys are dropped rather than raising: an agent
    sending an extra field should not get a stack trace for being generous."""
    fields = {f for f in _catches.Event.__dataclass_fields__}
    return [_catches.Event(**{k: v for k, v in e.items() if k in fields}) for e in (raw or [])]


def _catch_json(cs):
    return [{'signature': c.signature, 'detail': c.detail, 'evidence': list(c.evidence)} for c in cs]


def op_capabilities(_):
    return {
        'sdk': getattr(lb, '__version__', '?'),
        'origin': _ORIGIN,
        'is_working_tree': _EDITABLE,
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


# ── the four the JS server lacked ────────────────────────────────────────────
#
# laserscore and the store trio were served by `laserbrain mcp` and not by mcp-server.mjs,
# the mirror of the gap the rest of this file closes. Written as ops rather than ported into
# JS for the same reason as everything above: a second implementation is a second thing to
# keep in step, and nothing would have kept it.
#
# They delegate to mcp.py's handlers, which are the definitions. This module is the registry
# both doors read, not a third copy.

def op_laserscore(a):
    from .mcp import _laserscore
    return _laserscore(a or {})


def op_store_list(a):
    from .mcp import _store_list
    return _store_list(a or {})


def op_store_find(a):
    from .mcp import _store_find
    return _store_find(a or {})


def op_store_vend(a):
    from .mcp import _store_vend
    return _store_vend(a or {})


# THE REGISTRY LIVES WITH THE OPS, because op_capabilities reports it — it was reading an
# OPS defined below it in sdk_bridge.py, so the move left it naming something that was no
# longer in scope. Both front doors import this rather than each keeping a list that has to
# be remembered when an op is added.
OPS = {
    'capabilities': op_capabilities,
    'find_bugs': op_find_bugs,
    'explore': op_explore,
    'trailscore': op_trailscore,
    'supercode': op_supercode,
    'write_grounded': op_write_grounded,
    'read_text': op_read_text,
    'similarity': op_similarity,
    'laserscore': op_laserscore,
    'store_list': op_store_list,
    'store_find': op_store_find,
    'store_vend': op_store_vend,
}
