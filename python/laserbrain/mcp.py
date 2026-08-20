"""laserbrain as an MCP server — offline, stdlib only, no account.

    laserbrain mcp          # speaks JSON-RPC on stdin/stdout

Point any MCP client at that command and the agent gets the harness. No key, no network,
no telemetry, nothing to sign up for.

WHY THIS SHIPS IN THE PACKAGE

Until 0.25.0 `pip install laserbrain` gave you a library and a CLI, and the only way to
reach the instrument over MCP was the hosted Worker. The stdio server that Diego actually
uses is a Node file living on one machine, distributed to nobody. So the way the author
uses his own product was the one way a user could not.

That is backwards for a tool whose headline claim is that the check is local, free, and
needs no server. Most agents cannot `import laserbrain` — they speak MCP. Making the local
path reachable over MCP is what makes "free and offline" true for agents rather than only
for Python programs.

WHY THERE IS NO DEPENDENCY

MCP over stdio is JSON-RPC in newline-delimited JSON. That is `json` and `sys.stdin`. An
SDK would add a dependency to a package that has none, for a protocol that fits in this
file. Keeping it stdlib means the offline path has nothing to install, nothing to break at
version boundaries, and nothing to audit.

WHAT IT DELIBERATELY DOES NOT EXPOSE

Only tools that work with the network unplugged. The field, Alice, the spectral grammar
and the persisted self are real capabilities, and every one of them is a call to a server —
offering them here would produce an MCP server that silently fails the moment it is used
the way it advertises. They live on the hosted Worker, which is honest about being a
server. `capabilities` says so, in as many words, rather than leaving a user to discover
it by failure.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import PRESETS, Harness, Store, Verdict, __version__, ground_score, laserscore, norm
from . import _G

PROTOCOL = '2024-11-05'

# One process is one agent's session. The ground lives here, in memory, for exactly as
# long as the client holds the pipe open — which is the correct lifetime: a ground that
# outlived the conversation would be measuring a task nobody is doing any more.
#
# THAT PREMISE IS FALSE WHEN AN AGENT SPAWNS SUBAGENTS, and it cost a whole session on
# 2026-08-16. In-process subagents share this server, so they share this dict — one
# `harness`, one ground, between a parent and every child it spawns. Every agent is also
# told, by its own instructions, to call reset_task when it starts a genuinely new task,
# and a subagent's task is always new. So a child's reset destroyed the PARENT's ground,
# the child's goal became the reference, and the parent's next check — with a byte-identical
# goal string — came back `goal-drift` at 0.02, then escalated to `wrong-problem` and told
# a correctly-working agent to abandon correct work.
#
# Reproduced deterministically before it was fixed:
#
#     parent grounds                       grounded    1.00
#     child resets, then checks            grounded    1.00      <- parent's ground gone
#     parent checks, IDENTICAL goal        goal-drift  0.32
#
# That is a frozen-reference violation in the instrument whose whole thesis is that the
# reference cannot move. PROOF's three adjectives are fixed, findable, UNCHANGEABLE, and
# reset_task was an unauthenticated delete of somebody else's ground.
#
# THE FIX, and why it needs no agent id. The server cannot tell which agent is calling —
# MCP hands it a tool call and nothing else, and guessing from pids or env vars was already
# tried and rejected elsewhere in this codebase for good reasons. So identity is not used.
# Instead a reset SUSPENDS the current ground rather than deleting it, and a later check
# whose goal matches a suspended ground better than the live one RESUMES it. The ground is
# found by what it is about, which is what "findable" means.
#
# There is no threshold here, deliberately. Resume happens on a COMPARISON — does this goal
# look more like a ground we already hold than the one currently live — so there is no
# number to tune and none to justify. And a reset always yields a fresh ground to the very
# next check, because a reset is a declaration that new work is starting; without that rule
# a child could never open a ground of its own.
_state: dict[str, Any] = {'harness': None, 'checks': [], 'suspended': []}

# Bounded so a long session cannot grow this without limit. Oldest goes first: the ground
# most likely to be resumed is the one most recently suspended.
MAX_SUSPENDED = 8


def _ground_goal(h) -> str:
    """The goal a harness is grounded on, or '' if it has never been checked."""
    return str(getattr(getattr(h, '_run', None), 'first_goal_text', '') or '')


def _overlap(a: str, b: str) -> float:
    """The instrument's own grammar, not a new one — the same Jaccard over norm() token
       sets that _Run.step uses to compute `anchor`. Using anything else here would mean
       the server resumed grounds by one definition of "the same goal" while the detector
       scored them by another."""
    A, B = norm(a), norm(b)
    return (len(A & B) / len(A | B)) if (A or B) else 0.0


def _verdict_dict(v: Verdict) -> dict[str, Any]:
    return {
        'drifting': v.drifting,
        'reason': v.reason,
        'phi': round(v.phi, 4),
        'anchored': round(v.anchored, 4) if v.anchored is not None else None,
        'laserscore': v.laserscore,
        'advice': v.advice,
        'ground_score': round(ground_score(v.phi), 4),
    }


# ── the tools ────────────────────────────────────────────────────────────────────────
def _maybe_resume(goal: str) -> str | None:
    """Swap a suspended ground back in when THIS goal is more that ground's than the live
       one's. Returns the resumed goal, or None if nothing changed.

       Only runs when a ground is already live. Straight after a reset there is none, and
       the next check must be allowed to open a fresh one — otherwise a subagent that just
       declared new work would be handed its parent's reference instead of its own.
    """
    live = _state['harness']
    if live is None or not _state['suspended']:
        return None
    live_sim = _overlap(goal, _ground_goal(live))
    best_i, best_sim = -1, live_sim
    for i, s in enumerate(_state['suspended']):
        sim = _overlap(goal, s['goal'])
        if sim > best_sim:                      # strictly better, so ties keep the live one
            best_i, best_sim = i, sim
    if best_i < 0:
        return None
    # The live ground is not discarded — it is suspended in turn, so the agent that owns it
    # reclaims it the same way on its next check. This is what makes a parent and a child
    # able to alternate indefinitely without either losing its reference.
    resumed = _state['suspended'].pop(best_i)
    _state['suspended'].append({'goal': _ground_goal(live), 'harness': live,
                                'checks': _state['checks']})
    del _state['suspended'][:-MAX_SUSPENDED]
    _state['harness'], _state['checks'] = resumed['harness'], resumed['checks']
    return resumed['goal']


def _check_state(args: dict) -> dict:
    goal = str(args.get('goal', '')).strip()
    if not goal:
        return {'error': 'check_state needs a goal — the ground is set from it and frozen'}
    resumed = _maybe_resume(goal)
    if _state['harness'] is None:
        _state['harness'] = Harness()
    v = _state['harness'].check(goal, str(args.get('progress', 'advancing')),
                                args.get('distance'))
    out = _verdict_dict(v)
    if resumed is not None:
        # Said out loud. A ground silently swapping underneath a caller would be the same
        # class of problem as the one this fixes — the reference has to be findable, and a
        # reference that moves without saying so is not.
        out['resumed_ground'] = resumed
    _state['checks'].append({'goal': goal, **out})
    return out


def _reset_task(args: dict) -> dict:
    """Start a new task. SUSPENDS the current ground rather than deleting it.

       It used to delete. That made it an unauthenticated destroy of whatever ground was
       live, which in a session with subagents is usually not the caller's — see the note
       on _state. Suspending keeps reset_task's meaning for the caller (the next check sets
       a fresh ground) while making it non-destructive for everyone else.
    """
    live = _state['harness']
    if live is not None and _ground_goal(live):
        _state['suspended'].append({'goal': _ground_goal(live), 'harness': live,
                                    'checks': _state['checks']})
        del _state['suspended'][:-MAX_SUSPENDED]
    _state['harness'] = None
    _state['checks'] = []
    return {'ok': True,
            'note': 'ground and history cleared — your next check_state sets a new ground',
            'suspended': len(_state['suspended'])}


def _get_history(args: dict) -> dict:
    ch = _state['checks']
    spelled = len(ch)
    drifts = sum(1 for c in ch if c['drifting'])
    return {'checks': ch[-int(args.get('limit', 20)):], 'total': spelled, 'drifting': drifts}


def _similarity(args: dict) -> dict:
    a, b = str(args.get('a', '')), str(args.get('b', ''))
    na, nb = norm(a), norm(b)
    inter = na & nb
    union = na | nb
    return {'a_tokens': sorted(na), 'b_tokens': sorted(nb),
            'overlap': round(len(inter) / len(union), 4) if union else 0.0,
            'shared': sorted(inter)}


def _laserscore(args: dict) -> dict:
    return {'laserscore': laserscore(str(args.get('goal', '')),
                                     str(args.get('progress', 'advancing')),
                                     args.get('distance'))}


# The policy table, from the grammar — the same one teams.ts reads. Kept out of this file
# on purpose: it lived only in the Worker's TypeScript until 2026-07-29, which is exactly
# why modulate could not be offered locally. Copying it here would have made a fourth copy
# of a list this project has already watched drift twice.
_MOD = (_G.get('modulation') or {})
_MODES = _MOD.get('modes') or []
_DEPTHS = _MOD.get('depths') or {}


def _modulate(args: dict) -> dict:
    """The verdict, and what the agent's ROLE should do about it.

    Detection is the theorem and is computed by the same Harness as check_state. Policy is
    which drifts a given role acts on, and it is negotiable — which is why it comes from
    grammar.modulation rather than from the instrument.
    """
    goal = str(args.get('goal', '')).strip()
    if not goal:
        return {'error': 'modulate needs a goal — the ground is set from it and frozen'}
    if _state['harness'] is None:
        _state['harness'] = Harness()
    v = _state['harness'].check(goal, str(args.get('progress', 'advancing')), args.get('distance'))
    out = _verdict_dict(v)
    _state['checks'].append({'goal': goal, **out})

    team_name, role_name = args.get('team'), args.get('role')
    # An unknown team is an ERROR, not a quiet fall back to unstyled — that would answer
    # "return" on everything and let a caller believe a policy they misspelled was applied.
    if team_name and team_name not in PRESETS:
        return {'error': f'no preset named {team_name!r}',
                'presets': sorted(PRESETS)}
    roles = PRESETS.get(team_name) if team_name else None
    role = next((r for r in (roles or []) if r.get('role') == role_name), None)
    if roles and role_name and role is None:
        return {'error': f'{team_name} has no role {role_name!r}',
                'roles': [r.get('role') for r in roles]}

    if v.reason not in _MODES:
        mod = {'return': False, 'advice': v.advice, 'basis': f'{v.reason} is not a drift mode'}
    elif role is None:
        mod = {'return': True, 'advice': v.advice, 'basis': 'unstyled — every drift returns'}
    else:
        acts = role.get('modes') or _DEPTHS.get(role.get('recurse', 'balanced'), [])
        ret = v.reason in acts
        mod = {
            'return': ret,
            'advice': (role.get('return') or v.advice) if ret
                      else f"{role['role']} (recurse: {role.get('recurse')}) tolerates {v.reason} — recursing on.",
            'basis': f"{role['role']} recurses {role.get('recurse')}",
        }
    mod['team'] = team_name if roles else None
    mod['role'] = role['role'] if role else None
    return {**out, 'modulation': mod}


# The store is 100% local — shipped task-workflows plus whatever ~/.laserbrain/workflows/
# holds, and the recursion-team presets — so it belongs here on the same principle as
# check_state: it works with the network unplugged. It shipped in 0.29.0 (Store) and today
# (team vending) with no MCP surface at all, which meant the most common way an agent
# reaches this package could not discover it — the exact gap `mcp.py`'s own docstring
# names as the reason this file exists in the first place, reproduced one layer up.
_STORE = Store()


def _store_list(args: dict) -> dict:
    kind = str(args.get('kind', 'workflow'))
    if kind == 'team':
        return {'kind': 'team', 'names': _STORE.list_teams()}
    return {'kind': 'workflow', 'names': _STORE.list()}


def _store_find(args: dict) -> dict:
    task = str(args.get('task', '')).strip()
    if not task:
        return {'error': 'store_find needs a task, in words, to match against'}
    kind = str(args.get('kind', 'workflow'))
    top = int(args.get('top', 3))
    if kind == 'team':
        return {'kind': 'team', 'matches': _STORE.find_team(task, top=top)}
    return {'kind': 'workflow', 'matches': _STORE.find(task, top=top)}


def _store_vend(args: dict) -> dict:
    name = str(args.get('name', '')).strip()
    if not name:
        return {'error': 'store_vend needs a name — see store_list or store_find'}
    kind = str(args.get('kind', 'workflow'))
    try:
        if kind == 'team':
            return {'kind': 'team', 'spec': _STORE.vend_team(name)}
        return {'kind': 'workflow', 'spec': _STORE.vend(name)}
    except KeyError as e:
        return {'error': str(e)}


def _capabilities(args: dict) -> dict:
    return {
        'version': __version__,
        'transport': 'stdio (JSON-RPC, newline-delimited)',
        'offline': True,
        'account_required': False,
        'local_tools': sorted(TOOLS),
        'not_here': {
            'why': 'these are calls to a server, and this server is your own machine',
            'tools': ['read_field', 'speak_to_field', 'ask_alice', 'analyze_language',
                      'compare_phrasings', 'remember_self', 'resume_self', 'forget_self'],
            'where': 'https://laserbrain-mcp.degibug.workers.dev/mcp',
        },
        'note': 'The check is a pure local function. It runs with the network unplugged '
                'and keeps working if the hosted service disappears.',
    }


def _read_text(args: dict) -> dict:
    """Read the shape of a text: circling, connected, loose, or too short to say.

    The companion to write_grounded. That one holds GENERATION to a ground; this one asks
    what shape a piece of writing is already in — and the term that answers it, variety,
    needs no model, no network and no key.

    `connectivity` is optional because it is the one term this cannot compute: it is a
    spectral quantity over a discourse graph and belongs to the analyzer. A reading without
    it is honest and useful, which is why it defaults to 0 rather than being required.
    """
    from .reading import read as _r
    text = args.get('text') or ''
    try:
        conn = float(args.get('connectivity') or 0.0)
    except (TypeError, ValueError):
        conn = 0.0
    return _r(text, connectivity=conn)


TOOLS: dict[str, dict[str, Any]] = {
    'check_state': {
        'fn': _check_state,
        'description': (
            'Spell where you are. The FIRST call freezes the ground — every later reading is '
            'measured against it, which is what makes this different from asking yourself. '
            'Call it each step. Returns one of nine verdicts, Φ, and what to do.'),
        'schema': {
            'type': 'object',
            'properties': {
                'goal': {'type': 'string', 'description': 'What you are working on, in your own words.'},
                'progress': {'type': 'string', 'enum': ['advancing', 'stuck', 'circling'],
                             'description': 'Honestly. A false "advancing" wastes the reading.'},
                'distance': {'type': 'number',
                             'description': 'How far from done, 0-10. 0 means finished.'},
            },
            'required': ['goal'],
        },
    },
    'modulate': {
        'fn': _modulate,
        'description': (
            'Check your state AND get the intervention your role should take. Same verdict as '
            'check_state, plus a policy decision: whether THIS role returns on THIS drift, and '
            'the wording to return with. Pass team + role for a recursion-team preset; without '
            'them every drift returns, unstyled. Offline, like everything else here.'),
        'schema': {
            'type': 'object',
            'properties': {
                'goal': {'type': 'string'},
                'progress': {'type': 'string', 'enum': ['advancing', 'stuck', 'circling']},
                'distance': {'type': 'number'},
                'team': {'type': 'string', 'description': 'A recursion-team preset name.'},
                'role': {'type': 'string', 'description': 'Which role this agent is playing.'},
            },
            'required': ['goal'],
        },
    },
    'reset_task': {
        'fn': _reset_task,
        'description': ('Start a genuinely new task. Clears the ground so the next check_state '
                        'sets a fresh one. Use when the user redirects you — NOT to escape a '
                        'drift verdict, which is the one thing that makes the reading useless.'),
        'schema': {'type': 'object', 'properties': {}},
    },
    'get_history': {
        'fn': _get_history,
        'description': 'The checks spelled so far this session, and how many were drifting.',
        'schema': {'type': 'object',
                   'properties': {'limit': {'type': 'number', 'description': 'Default 20.'}}},
    },
    'similarity': {
        'fn': _similarity,
        'description': ('Token overlap between two statements under the same normaliser the '
                        'harness uses. Useful for asking whether two goals are the same goal.'),
        'schema': {'type': 'object',
                   'properties': {'a': {'type': 'string'}, 'b': {'type': 'string'}},
                   'required': ['a', 'b']},
    },
    'laserscore': {
        'fn': _laserscore,
        'description': 'The compact one-line reading of a state, without setting or touching a ground.',
        'schema': {'type': 'object',
                   'properties': {'goal': {'type': 'string'},
                                  'progress': {'type': 'string'},
                                  'distance': {'type': 'number'}},
                   'required': ['goal']},
    },
    'capabilities': {
        'fn': _capabilities,
        'description': 'What this server can do offline, and what needs the hosted one.',
        'schema': {'type': 'object', 'properties': {}},
    },
    'store_list': {
        'fn': _store_list,
        'description': (
            'Every prefabricated method on the shelf: 10 task workflows shipped with the '
            'package plus anything saved locally, or the 3 recursion-team presets. Names '
            'only — pass one to store_vend to see what it actually does.'),
        'schema': {'type': 'object',
                   'properties': {'kind': {'type': 'string', 'enum': ['workflow', 'team'],
                                            'description': 'Default workflow.'}}},
    },
    'store_find': {
        'fn': _store_find,
        'description': (
            'Which stored method is FOR a task, in your own words — ranked by what it does, '
            'not by name, so you do not need to already know it exists.'),
        'schema': {'type': 'object',
                   'properties': {
                       'task': {'type': 'string', 'description': 'What you need done, in words.'},
                       'kind': {'type': 'string', 'enum': ['workflow', 'team']},
                       'top': {'type': 'number', 'description': 'Default 3.'},
                   },
                   'required': ['task']},
    },
    'store_vend': {
        'fn': _store_vend,
        'description': (
            "The raw spec for one stored method — its goal or task, and its steps or roles. "
            "Data only; nothing here can execute. A workflow comes back with unbound steps "
            "(bind them in Python to run it); a team preset comes back with each role's "
            "recurse depth and return policy."),
        'schema': {'type': 'object',
                   'properties': {
                       'name': {'type': 'string'},
                       'kind': {'type': 'string', 'enum': ['workflow', 'team']},
                   },
                   'required': ['name']},
    },
    'read_text': {
        'fn': _read_text,
        'description': (
            'Read the shape of a text — circling, connected, loose, or too short to say. The '
            'companion to write_grounded: that one holds generation to a ground, this one asks '
            'what shape writing is already in. Offline, no model, no key. Repetition RAISES the '
            'spectral score, so variety is the term that catches someone circling one thought.'),
        'schema': {
            'type': 'object',
            'properties': {
                'text': {'type': 'string', 'description': 'The text to read.'},
                'connectivity': {'type': 'number',
                                 'description': 'Spectral connectivity 0-1 from the analyzer, '
                                                'if you have it. Optional — variety alone '
                                                'catches circling.'},
            },
            'required': ['text'],
        },
    },
}


# ── JSON-RPC, on a pipe ──────────────────────────────────────────────────────────────
def _tool_list() -> list[dict]:
    return [{'name': n, 'description': t['description'], 'inputSchema': t['schema']}
            for n, t in TOOLS.items()]


def handle(msg: dict) -> dict | None:
    """One request in, one response out. None means notification — say nothing back."""
    method, mid = msg.get('method'), msg.get('id')

    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': PROTOCOL,
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'laserbrain', 'version': __version__},
        }}
    if method in ('notifications/initialized', 'initialized'):
        return None
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': _tool_list()}}
    if method == 'tools/call':
        params = msg.get('params') or {}
        name = params.get('name')
        tool = TOOLS.get(name)
        if tool is None:
            return {'jsonrpc': '2.0', 'id': mid,
                    'error': {'code': -32602, 'message': f'no such tool: {name}'}}
        try:
            out = tool['fn'](params.get('arguments') or {})
        except Exception as e:      # a tool that throws must not take the server with it
            return {'jsonrpc': '2.0', 'id': mid, 'result': {
                'content': [{'type': 'text', 'text': f'{type(e).__name__}: {e}'}],
                'isError': True}}
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'content': [{'type': 'text', 'text': json.dumps(out, indent=2)}]}}

    if mid is None:
        return None                 # an unknown notification is not an error
    return {'jsonrpc': '2.0', 'id': mid,
            'error': {'code': -32601, 'message': f'no such method: {method}'}}


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC until the pipe closes.

    stderr is left alone: an MCP client parses stdout, so anything printed there that is
    not a response corrupts the stream. Diagnostics belong on stderr and nowhere else.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            # Malformed input is the client's bug, not a reason to die mid-session.
            print(json.dumps({'jsonrpc': '2.0', 'id': None,
                              'error': {'code': -32700, 'message': 'parse error'}}),
                  file=stdout, flush=True)
            continue
        res = handle(msg)
        if res is not None:
            print(json.dumps(res), file=stdout, flush=True)
    return 0
