#!/usr/bin/env python3
"""test_runtime.py — one implementation of the runtime attachment, many event shapes.

A hook-based host had to duplicate the progress rules because it could not import
laserbrain, and that duplication needed its own parity test to stay safe. This module
exists so the next four runtimes do not each add a copy. The tests below check the two
things that makes true: different event SHAPES normalise to the same contract, and the
recorded file is what dogfood.py already scores.
"""
import json, tempfile, pathlib
from laserbrain.runtime import (
    Session, normalise, from_claude_code, from_grok, from_openai_agents, session_id_of,
)

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


# ── normalisation: several runtimes, one contract ────────────────────────────
cc = {'tool_name': 'Bash', 'tool_input': {'command': 'x'}, 'tool_response': {'exit_code': 1}}
oa = {'name': 'Bash', 'arguments': {'command': 'x'}, 'output': {'error': 'boom'}}
gk = {'toolName': 'run_terminal_command', 'toolInput': {'command': 'x'},
      'toolResult': {'exit_code': 1}, 'sessionId': 'g1'}
show('snake_case shape normalises', normalise(cc)[:4] == ('tool', 'Bash', {'command': 'x'}, False))
show('OpenAI-Agents shape normalises to the same thing', normalise(oa)[:4] == ('tool', 'Bash', {'command': 'x'}, False))
show('camelCase shape normalises', normalise(gk)[:4] == ('tool', 'run_terminal_command', {'command': 'x'}, False))
show('a prompt is recognised', normalise({'prompt': 'ship it'})[0] == 'prompt')
show('a check is recognised', normalise({'tool_name': 'mcp__laserbrain__check_state'})[0] == 'check')
show('a wrapped MCP check is recognised', normalise({'toolName': 'laserbrain__check_state',
      'toolInput': {'goal': 'g', 'progress': 'advancing', 'distance': 3}})[0] == 'check')
show('use_tool wrapper unwraps to check', normalise({
    'toolName': 'use_tool',
    'toolInput': {'tool_name': 'laserbrain__check_state',
                  'tool_input': {'goal': 'g', 'progress': 'advancing', 'distance': 1}},
})[0] == 'check')
# Some hosts rewrite toolName to server__tool but leave toolInput nested (empty-goal bug).
_env = normalise({
    'toolName': 'laserbrain__check_state',
    'toolInput': {'tool_name': 'laserbrain__check_state',
                  'tool_input': {'goal': 'ship it', 'progress': 'advancing', 'distance': 2}},
    'sessionId': 'env1',
})
show('a name-unwrapped envelope still peels args',
     _env[0] == 'check' and _env[2].get('goal') == 'ship it', _env[2])
_envc = normalise({
    'toolName': 'laserbrain__check_state',
    'toolInput': {'toolName': 'laserbrain__check_state',
                  'toolInput': {'goal': 'ship it', 'progress': 'stuck', 'distance': 4}},
})
show('a camelCase nested envelope peels',
     _envc[2].get('goal') == 'ship it' and _envc[2].get('progress') == 'stuck', _envc[2])
_str = normalise({
    'toolName': 'laserbrain__check_state',
    'toolInput': '{"goal":"g","progress":"advancing","distance":1}',
})
show('JSON-string toolInput is coerced', _str[2].get('goal') == 'g', _str[2])
show('reset is recognised', normalise({'toolName': 'laserbrain__reset_task'})[0] == 'reset')
show('junk is ignored rather than guessed at', normalise('not a dict')[0] is None)
show('a non-dict argument does not crash normalisation', normalise({'name': 'T', 'arguments': 5})[2] == {'_': 5})
show('session_id_of prefers sessionId', session_id_of({'sessionId': 'abc'}) == 'abc')

with tempfile.TemporaryDirectory() as d:
    # ── the goal is captured once ───────────────────────────────────────────
    s = Session('t1', directory=d)
    s.prompt('ship the sky billboard')
    s.prompt('actually do something else entirely')
    show('a later prompt does not overwrite the ground goal',
         s.d['goal'] == 'ship the sky billboard', s.d['goal'])

    # ── failures become catches, without judgement ──────────────────────────
    s.tool('Bash', {'command': 'npm run build'}, ok=False)
    show('a failed call is recorded as a catch', len(s.d['catches']) == 1, s.d['catches'][0]['what'])
    s.tool('Bash', {'command': 'npm run build'}, ok=True)
    show('a successful call is not', len(s.d['catches']) == 1)

    # ── inference matches observe.py, because it IS observe.py ──────────────
    s2 = Session('t2', goal='g', directory=d)
    for _ in range(3):
        s2.tool('Bash', {'command': 'same'}, ok=True)
    show('three identical calls infer circling', s2.d['inferred'][-1]['progress'] == 'circling',
         s2.d['inferred'][-1]['why'])
    s2.tool('Bash', {'command': 'different'}, ok=True)
    show('and one different call recovers immediately',
         s2.d['inferred'][-1]['progress'] == 'advancing')

    # ── the nudge ───────────────────────────────────────────────────────────
    s3 = Session('t3', goal='g', directory=d)
    fired = [s3.tool('Read', {'p': i}).nudge() for i in range(9)]
    show('no nudge before the threshold', all(f is None for f in fired[:7]))
    show('a nudge at the threshold', fired[7] is not None, (fired[7] or '')[:48])

    # ── spelled checks are recorded WITH their inputs, for replay ───────────
    s3.check('the goal', 'advancing', 5, drifting=False)
    c = s3.d['checks'][-1]
    show('a spelled check records its inputs', c['goal'] == 'the goal' and c['distance'] == 5)
    show('and resets the nudge counter', s3.nudge() is None)

    # ── the file is what dogfood already scores ─────────────────────────────
    raw = json.loads((pathlib.Path(d) / 't3.json').read_text())
    show('the session file has the keys dogfood.py reads',
         all(k in raw for k in ('id', 'steps', 'checks', 'inferred', 'catches')))

    # ── the adapters are thin wrappers over the same path ───────────────────
    from_claude_code({'session_id': 't4', 'prompt': 'ship it'}, directory=d)
    from_claude_code({'session_id': 't4', 'tool_name': 'Bash',
                      'tool_input': {'command': 'q'}, 'tool_response': {'exit_code': 2}}, directory=d)
    t4 = json.loads((pathlib.Path(d) / 't4.json').read_text())
    show('the hook adapter records goal, step and catch',
         t4['goal'] == 'ship it' and t4['steps'] == 1 and len(t4['catches']) == 1)

    from_openai_agents('t5', 'search', {'q': 'x'}, error='rate limited', directory=d)
    t5 = json.loads((pathlib.Path(d) / 't5.json').read_text())
    show('the OpenAI-Agents adapter lands in the same format',
         t5['steps'] == 1 and len(t5['catches']) == 1, t5['catches'][0]['what'])

    from_grok({'sessionId': 't7', 'prompt': 'upgrade agent-b'}, directory=d)
    from_grok({'sessionId': 't7', 'toolName': 'run_terminal_command',
               'toolInput': {'command': 'false'}, 'toolResult': {'exit_code': 1}}, directory=d)
    from_grok({'sessionId': 't7', 'toolName': 'laserbrain__check_state',
               'toolInput': {'goal': 'upgrade agent-b', 'progress': 'advancing', 'distance': 4},
               'toolResult': {'drifting': False}}, directory=d)
    t7 = json.loads((pathlib.Path(d) / 't7.json').read_text())
    show('the a host adapter records goal, catch and spelled check',
         t7['goal'] == 'upgrade agent-b' and len(t7['catches']) == 1 and len(t7['checks']) == 1,
         f"goal={t7.get('goal')} catches={len(t7.get('catches',[]))} checks={len(t7.get('checks',[]))}")
    show('session stamps agent', bool(t7.get('agent')), t7.get('agent'))

    # Empty-goal bug fixture: name unwrapped, input still envelope
    from_grok({
        'sessionId': 't7b',
        'toolName': 'laserbrain__check_state',
        'toolInput': {
            'tool_name': 'laserbrain__check_state',
            'tool_input': {'goal': 'fix empty goals', 'progress': 'advancing', 'distance': 1},
        },
        'toolResult': {'drifting': False},
    }, directory=d)
    t7b = json.loads((pathlib.Path(d) / 't7b.json').read_text())
    c7b = (t7b.get('checks') or [{}])[-1]
    show('envelope check_state records goal/progress/distance',
         c7b.get('goal') == 'fix empty goals' and c7b.get('progress') == 'advancing'
         and c7b.get('distance') == 1 and t7b.get('goal') == 'fix empty goals',
         c7b)

    s6 = Session('t6', goal='g', directory=d)
    s6.tool('Read'); s6.reset()
    show('reset clears the run', s6.d['steps'] == 0 and s6.d['goal'] is None)

    s8 = Session('t8', goal='g', directory=d, nudge_after=3)
    for _ in range(3):
        s8.tool('Read', {'p': 1})
    show('coverage_warning fires after lapse', s8.coverage_warning() is not None)

# ── the link-run fixes (2026-07-25) ────────────────────────────────────────
# Found by running a host and a host at the same time and reading the corpus: 50 steps
# from two agents merged into one `unknown.json`, a ground goal of 'do all', and a
# prompt stored as '<user_query>...</user_query>'.

def _link_tests():
    import os
    from laserbrain.runtime import session_id_of, clean_prompt

    show('an explicit session id always wins', session_id_of({'sessionId': 'abc'}) == 'abc')
    show('no id does NOT fall back to a shared literal',
         session_id_of({}) != 'unknown', session_id_of({}))
    show('the fallback is stable within a process',
         session_id_of({}) == session_id_of({}))
    show('the fallback names the parent, so concurrent agents differ',
         session_id_of({}).endswith(str(os.getppid())))

    show('a wrapped prompt is unwrapped', clean_prompt('<user_query>\nship it\n</user_query>') == 'ship it')
    show('an unwrapped prompt is untouched', clean_prompt('  ship it  ') == 'ship it')
    show('empty stays empty', clean_prompt(None) == '')

    with tempfile.TemporaryDirectory() as d:
        s = Session('link', directory=d)
        s.prompt('<user_query>build the parser</user_query>')
        show('the ground is stored clean, not as markup', s.d['goal'] == 'build the parser', s.d['goal'])

        s.reset()
        s.prompt('do all')
        show('a post-reset prompt does NOT become the ground', s.d.get('goal') is None,
             'this is the "do all" bug')

        s.check('build the parser properly', 'advancing', 5, drifting=False)
        show('the next SPELLED check does become the ground',
             s.d['goal'] == 'build the parser properly', s.d['goal'])

        s2 = Session('link2', directory=d)
        s2.prompt('first task')
        s2.prompt('second thing')
        show('a later prompt still cannot overwrite an existing ground',
             s2.d['goal'] == 'first task')


_link_tests()
print('\n  ' + ('PASS' if ok else 'FAIL'))
raise SystemExit(0 if ok else 1)
