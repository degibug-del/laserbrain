"""Tests for ask_match_llm.py with mocked backends only: no network, no credentials, and
no transcript data (every row here is synthetic)."""
import json
import pathlib
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ask_match_llm as m  # noqa: E402

ALIGNED = {'asks': [{'ask': 'build the widget', 'in_task': True, 'in_goal': 'covered'}],
           'relay_unrelated': False, 'goal_follows_relay_scope': False, 'start_substituted': False,
           'end_declined': False, 'drift_score': 5, 'why': 'fine'}
JUDGE_YES = {'start_serves': 'yes', 'start_why': 'ok', 'end_serves': 'yes', 'end_why': 'ok'}


def row(i, split='dev', positive=False, **kw):
    r = {'id': f'wf:{i:04d}', 'agent': f'a{i:09d}', 'workflow': 'wf', 'role': 'build',
         'split': split, 'start_ts': '2026-09-10T00:00:00Z' if split == 'dev' else '2026-10-10T00:00:00Z',
         'label': 'narrowing' if positive else 'aligned', 'positive': positive,
         'incident': 'X1' if positive else None, 'label_source': 'incident' if positive else 'default',
         'user_recent': [{'text': 'please build the widget'}, {'text': 'and paint it blue'}],
         'user_relayed': 'and paint it blue', 'task': f'Build the widget and paint it blue. #{i}',
         'goal': 'Paint the widget blue', 'early_text': 'Starting.', 'final_text': 'Done.'}
    r.update(kw)
    return r


def replier(ask=ALIGNED, judge=JUDGE_YES):
    def fn(system, prompt, schema):
        return json.dumps(ask if system == m.SYSTEM_ASK else judge)
    return fn


# ── prompts ─────────────────────────────────────────────────────────────────────────

def test_prompts_carry_no_heldout_incident_phrases():
    # The incident-specific phrases quote the owner's private sessions, so they live in a local,
    # gitignored file (one phrase per line); a public clone checks the generic ones only.
    text = ' '.join([m.SYSTEM_ASK, m.TEMPLATE_ASK, m.SYSTEM_JUDGE, m.TEMPLATE_JUDGE]).lower()
    phrases = ['budget', 'request you relayed was only', 'evidence:build']
    local = pathlib.Path(__file__).with_name('heldout-phrases.local.txt')
    if local.is_file():
        phrases += [p.strip().lower() for p in local.read_text().splitlines() if p.strip()]
    for phrase in phrases:
        assert phrase not in text


def test_render_fills_every_field_and_clips():
    r = row(1, task='T' * 9000, final_text='F' * 9000)
    system, prompt, schema = m.render(r, 'askllm')
    assert system == m.SYSTEM_ASK and schema is m.SCHEMA_ASK
    assert 'please build the widget' in prompt and 'Paint the widget blue' in prompt
    assert 'T' * m.LIMITS['task'] in prompt and 'T' * (m.LIMITS['task'] + 1) not in prompt
    assert 'F' * (m.LIMITS['final'] + 1) not in prompt
    _, p2, _ = m.render(row(2, goal='', early_text='', final_text='', user_relayed=''), 'judge')
    assert '(no goal stated)' in p2 and '(no final report)' in p2 and '(none relayed)' in p2


def test_recent_drops_repeated_messages():
    r = row(1, user_recent=[{'text': 'x y z'}, {'text': 'x y z'}, {'text': 'w'}])
    assert m._recent(r) == '1. x y z\n2. w'


def test_prompt_hash_tracks_template_and_model():
    h = m.prompt_hash('askllm')
    assert h == m.prompt_hash('askllm') and h != m.prompt_hash('judge')
    assert h != m.prompt_hash('askllm', model='other-model')


# ── parsing and decisions ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure: {"a": 1} hope that helps'])
def test_parse_json_tolerates_wrapping(text):
    assert m.parse_json(text) == {'a': 1}


def test_parse_json_rejects_garbage():
    with pytest.raises(m.ParseError):
        m.parse_json('no json here')


def test_validate_coerces_and_rejects():
    v = m.validate('askllm', {**ALIGNED, 'drift_score': '72.4', 'start_substituted': 'true',
                              'asks': [{'ask': 'x', 'in_task': True, 'in_goal': 'MISSING'},
                                       {'ask': 'y', 'in_task': True, 'in_goal': 'weird'}]})
    assert v['drift_score'] == 72 and v['start_substituted'] is True
    assert [a['in_goal'] for a in v['asks']] == ['missing', 'unclear']
    with pytest.raises(m.ParseError):
        m.validate('askllm', {'asks': []})
    with pytest.raises(m.ParseError):
        m.validate('judge', {'start_serves': 'maybe', 'end_serves': 'yes'})


def _resp(**kw):
    return m.validate('askllm', {**ALIGNED, **kw})


def test_decide_aligned():
    d = m.decide_ask(_resp())
    assert d == {**d, 'flag': False, 'where': None, 'verdict': 'aligned'}


def test_decide_narrowing_needs_relay_scope_and_confidence():
    asks = [{'ask': 'build', 'in_task': True, 'in_goal': 'covered'},
            {'ask': 'paint', 'in_task': True, 'in_goal': 'missing'}]
    assert not m.decide_ask(_resp(asks=asks, drift_score=90))['flag']          # no relay scope
    d = m.decide_ask(_resp(asks=asks, drift_score=90, goal_follows_relay_scope=True))
    assert d['flag'] and d['where'] == 'start' and d['verdict'] == 'narrowing' and d['missing'] == ['paint']
    assert not m.decide_ask(_resp(asks=asks, drift_score=20, goal_follows_relay_scope=True))['flag']
    loose = {**m.THRESHOLDS, 'narrow_needs_relay_scope': False}
    assert m.decide_ask(_resp(asks=asks, drift_score=90), loose)['flag']


def test_decide_asks_outside_task_do_not_count():
    asks = [{'ask': 'other project', 'in_task': False, 'in_goal': 'missing'}]
    d = m.decide_ask(_resp(asks=asks, drift_score=90, goal_follows_relay_scope=True))
    assert not d['flag'] and d['n_asks_in_task'] == 0


def test_decide_unclear_counts_only_when_asked():
    asks = [{'ask': 'paint', 'in_task': True, 'in_goal': 'unclear'}]
    r = _resp(asks=asks, drift_score=90, goal_follows_relay_scope=True)
    assert not m.decide_ask(r)['flag']
    assert m.decide_ask(r, {**m.THRESHOLDS, 'unclear_counts_missing': True})['flag']


def test_decide_substitution_at_start_and_decline_at_end():
    d = m.decide_ask(_resp(start_substituted=True, relay_unrelated=True, drift_score=80))
    assert d['flag'] and d['where'] == 'start' and d['verdict'] == 'substitution'
    e = m.decide_ask(_resp(end_declined=True, relay_unrelated=True, drift_score=10))
    assert e['flag'] and e['where'] == 'end' and e['verdict'] == 'substitution'
    assert not m.decide_ask(_resp(end_declined=True), {**m.THRESHOLDS, 'use_end': False})['flag']


def test_decide_judge():
    assert m.decide_judge(JUDGE_YES) == {'flag': False, 'where': None}
    assert m.decide_judge({**JUDGE_YES, 'start_serves': 'no'})['where'] == 'start'
    assert m.decide_judge({**JUDGE_YES, 'end_serves': 'no'})['where'] == 'end'


# ── runner: cache, concurrency, retries, stops ──────────────────────────────────────

def test_score_caches_by_prompt_hash_and_resumes(tmp_path):
    rows = [row(i) for i in range(12)]
    be = m.MockBackend(replier())
    cache = m.Cache(tmp_path / 'c')
    res, st = m.score(rows, ['askllm', 'judge'], be, cache, concurrency=4, backoff=0)
    assert st['called'] == 24 and st['cached'] == 0 and be.calls == 24 and len(res) == 24
    recs = [json.loads(p.read_text()) for p in (tmp_path / 'c').rglob('*.json')]
    assert len(recs) == 24
    assert all(r['at'] and r['prompt_hash'] == m.prompt_hash(r['scorer']) for r in recs)
    be2 = m.MockBackend(replier())
    res2, st2 = m.score(rows, ['askllm', 'judge'], be2, cache, concurrency=4, backoff=0)
    assert be2.calls == 0 and st2['cached'] == 24
    # a cached run needs no backend at all
    res3, st3 = m.score(rows, ['askllm', 'judge'], None, cache)
    assert st3['cached'] == 24


def test_score_without_backend_and_uncached_refuses(tmp_path):
    with pytest.raises(m.BackendUnavailable):
        m.score([row(1)], ['askllm'], None, m.Cache(tmp_path))


def test_score_runs_concurrently(tmp_path):
    seen, lock, peak = set(), threading.Lock(), [0]
    barrier = threading.Barrier(4, timeout=5)

    def fn(system, prompt, schema):
        with lock:
            seen.add(threading.get_ident())
            peak[0] = max(peak[0], len(seen))
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return json.dumps(ALIGNED)
    m.score([row(i) for i in range(8)], ['askllm'], m.MockBackend(fn), m.Cache(tmp_path),
            concurrency=4, backoff=0)
    assert peak[0] == 4


def test_transient_errors_and_bad_json_are_retried(tmp_path):
    calls = {}

    class Flaky:
        name = 'flaky'

        def call(self, system, prompt, schema):
            n = calls[prompt] = calls.get(prompt, 0) + 1
            if n == 1:
                raise m.TransientError('timeout after 1s')
            if n == 2:
                return {'text': 'not json', 'usage': None, 'meta': {}}
            return {'text': json.dumps(ALIGNED), 'usage': None, 'meta': {}}
    res, st = m.score([row(1), row(2)], ['askllm'], Flaky(), m.Cache(tmp_path), backoff=0)
    assert st['called'] == 2 and st['errors'] == 0 and st['tries'] == 6


def test_persistent_failure_is_recorded_not_cached(tmp_path):
    class Dead:
        name = 'dead'

        def call(self, *a):
            raise m.TransientError('HTTP 500')
    res, st = m.score([row(1)], ['askllm'], Dead(), m.Cache(tmp_path), retries=1, backoff=0)
    assert st['errors'] == 1 and 'error' in res[('wf:0001', 'askllm')]
    assert not list(tmp_path.rglob('*.json'))
    out = m.assemble([row(1)], ['askllm'], res)
    assert out[0]['askllm']['flag'] is None
    assert m.summarize(out, ['askllm'])['askllm']['errors'] == 1


def test_auth_failures_stop_the_run(tmp_path):
    class NoAuth:
        name = 'noauth'
        calls = 0

        def call(self, *a):
            NoAuth.calls += 1
            raise m.BackendUnavailable('claude -p: Not logged in')
    with pytest.raises(m.BackendUnavailable, match='auth failures'):
        m.score([row(i) for i in range(50)], ['askllm'], NoAuth(), m.Cache(tmp_path),
                concurrency=2, backoff=0)
    assert NoAuth.calls < 50


# ── honesty guards ──────────────────────────────────────────────────────────────────

def write_rows(path, rows):
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))


@pytest.fixture
def dataset(tmp_path):
    rows = [row(i) for i in range(6)] + [row(6, positive=True)]
    rows += [row(100 + i, split='heldout', task='OCTOBER-ONLY task text') for i in range(3)]
    p = tmp_path / 'labelled.jsonl'
    write_rows(p, rows)
    return p


def run_main(monkeypatch, capsys, argv, backend):
    monkeypatch.setattr(m, 'make_backend', lambda *a, **k: backend)
    rc = m.main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_dev_run_never_renders_heldout_rows(monkeypatch, capsys, dataset, tmp_path):
    def fn(system, prompt, schema):
        assert 'OCTOBER-ONLY' not in prompt
        return replier()(system, prompt, schema)
    be = m.MockBackend(fn)
    rc, out, err = run_main(monkeypatch, capsys, [str(dataset), '--split', 'dev', '--cache',
                                                  str(tmp_path / 'c')], be)
    lines = [json.loads(x) for x in out.splitlines()]
    assert rc == 0 and len(lines) == 7 and {o['split'] for o in lines} == {'dev'}
    assert be.calls == 14


def test_heldout_requires_frozen_results(monkeypatch, capsys, dataset, tmp_path):
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout'], m.MockBackend(replier()))


def test_freeze_then_score_heldout_exactly_once(monkeypatch, capsys, dataset, tmp_path):
    res = tmp_path / 'day2.json'
    cache = str(tmp_path / 'c')
    rc, _, _ = run_main(monkeypatch, capsys, [str(dataset), '--split', 'dev', '--cache', cache,
                                              '--freeze', str(res)], m.MockBackend(replier()))
    fz = json.loads(res.read_text())
    assert rc == 0 and fz['heldout'] is None and fz['frozen']['model'] == m.MODEL
    assert fz['frozen']['prompt_hash'] == {s: m.prompt_hash(s) for s in m.SCORERS}
    assert fz['frozen']['thresholds'] == m.THRESHOLDS and fz['frozen']['at']
    assert fz['dev']['metrics']['askllm']['negatives'] == 6
    rc, out, _ = run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--cache', cache,
                                                '--results', str(res)], m.MockBackend(replier()))
    done = json.loads(res.read_text())
    assert rc == 0 and done['heldout']['n'] == 3 and done['heldout_started_at']
    assert done['heldout_started_at'] >= fz['frozen']['at']
    with pytest.raises(SystemExit, match='already scored'):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--cache', cache,
                                       '--results', str(res)], m.MockBackend(replier()))
    with pytest.raises(SystemExit, match='re-freeze'):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'dev', '--cache', cache,
                                       '--freeze', str(res)], m.MockBackend(replier()))


def test_heldout_refuses_when_thresholds_changed(monkeypatch, capsys, dataset, tmp_path):
    res = tmp_path / 'day2.json'
    run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(res), '--cache', str(tmp_path / 'c')],
             m.MockBackend(replier()))
    monkeypatch.setitem(m.THRESHOLDS, 'min_drift_score', 1)
    with pytest.raises(SystemExit, match='thresholds'):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--results', str(res)],
                 m.MockBackend(replier()))


def test_freeze_refuses_with_unscored_rows(monkeypatch, capsys, dataset, tmp_path):
    def fn(system, prompt, schema):
        return 'garbage' if '#3' in prompt else replier()(system, prompt, schema)
    monkeypatch.setattr(m.time, 'sleep', lambda *_: None)
    with pytest.raises(SystemExit, match='unscored'):
        run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(tmp_path / 'r.json'),
                                       '--cache', str(tmp_path / 'c')], m.MockBackend(fn))
    assert not (tmp_path / 'r.json').exists()


@pytest.mark.parametrize('limit', ['2', '0'])
def test_heldout_refuses_limit_before_writing_anything(monkeypatch, capsys, dataset, tmp_path, limit):
    res = tmp_path / 'day2.json'
    cache = str(tmp_path / 'c')
    run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(res), '--cache', cache],
             m.MockBackend(replier()))
    frozen = res.read_text()
    be = m.MockBackend(replier())
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--limit', limit,
                                       '--cache', cache, '--results', str(res)], be)
    assert '--limit is for dev smoke runs only' in capsys.readouterr().err
    assert res.read_text() == frozen and be.calls == 0      # no heldout_started_at, no calls
    rc, _, _ = run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--cache', cache,
                                              '--results', str(res)], m.MockBackend(replier()))
    assert rc == 0 and json.loads(res.read_text())['heldout']['n'] == 3   # full run still allowed


def test_freeze_refuses_limit(monkeypatch, capsys, dataset, tmp_path):
    res = tmp_path / 'r.json'
    be = m.MockBackend(replier())
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(res), '--limit', '2',
                                       '--cache', str(tmp_path / 'c')], be)
    assert '--limit is for dev smoke runs only' in capsys.readouterr().err
    assert not res.exists() and be.calls == 0


def test_dev_smoke_run_still_takes_limit(monkeypatch, capsys, dataset, tmp_path):
    rc, out, _ = run_main(monkeypatch, capsys, [str(dataset), '--limit', '2', '--cache',
                                                str(tmp_path / 'c')], m.MockBackend(replier()))
    assert rc == 0 and len(out.splitlines()) == 2


def test_partial_output_is_never_recorded(monkeypatch, capsys, dataset, tmp_path):
    """Backstop: even without --limit, a run that scored fewer rows than the split holds
    can neither freeze nor become the one held-out score."""
    res = tmp_path / 'day2.json'
    cache = str(tmp_path / 'c')
    full = m.assemble
    monkeypatch.setattr(m, 'assemble', lambda *a, **k: full(*a, **k)[:-1])
    with pytest.raises(SystemExit, match='6 of 7 dev rows'):
        run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(res), '--cache', cache],
                 m.MockBackend(replier()))
    assert not res.exists()
    monkeypatch.setattr(m, 'assemble', full)
    run_main(monkeypatch, capsys, [str(dataset), '--freeze', str(res), '--cache', cache],
             m.MockBackend(replier()))
    monkeypatch.setattr(m, 'assemble', lambda *a, **k: full(*a, **k)[:-1])
    with pytest.raises(SystemExit, match='2 of 3 rows'):
        run_main(monkeypatch, capsys, [str(dataset), '--split', 'heldout', '--cache', cache,
                                       '--results', str(res)], m.MockBackend(replier()))
    assert json.loads(res.read_text())['heldout'] is None


def test_grid_is_dev_only_and_uses_cache(monkeypatch, capsys, dataset, tmp_path):
    cache = str(tmp_path / 'c')
    run_main(monkeypatch, capsys, [str(dataset), '--cache', cache], m.MockBackend(replier()))
    rc, out, _ = run_main(monkeypatch, capsys, [str(dataset), '--grid', '--cache', cache], None)
    table = json.loads(out)
    assert rc == 0 and table and all(t['negatives'] == 6 for t in table)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, [str(dataset), '--grid', '--split', 'heldout'], None)


# ── backends (no real process, no network) ──────────────────────────────────────────

class FakeProc:
    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_cli_backend_isolates_settings_and_passes_token_only_in_env(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kw):
        seen['argv'], seen['env'], seen['cwd'], seen['input'] = argv, kw['env'], kw['cwd'], kw['input']
        return FakeProc(json.dumps({'result': '{"ok": true}', 'is_error': False, 'session_id': 's-1',
                                    'usage': {'input_tokens': 10}}))
    monkeypatch.setattr(m.subprocess, 'run', fake_run)
    monkeypatch.setenv('CLAUDECODE', '1')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-not-pass')
    be = m.ClaudeCLIBackend(token='tok-SECRET-123', workdir=tmp_path / 'cwd', binary='claude')
    res = be.call('SYS', 'PROMPT', {})
    a = seen['argv']
    assert a[a.index('--model') + 1] == m.MODEL
    assert a[a.index('--tools') + 1] == '' and a[a.index('--setting-sources') + 1] == ''
    assert json.loads(a[a.index('--settings') + 1]) == {'disableAllHooks': True}
    assert '--strict-mcp-config' in a and '--no-session-persistence' in a
    assert json.loads(a[a.index('--mcp-config') + 1]) == {'mcpServers': {}}
    assert a[a.index('--system-prompt') + 1] == 'SYS' and seen['input'] == 'PROMPT'
    assert not any('tok-SECRET-123' in x for x in a)
    assert seen['env']['CLAUDE_CODE_OAUTH_TOKEN'] == 'tok-SECRET-123'
    assert 'CLAUDECODE' not in seen['env'] and 'ANTHROPIC_API_KEY' not in seen['env']
    assert seen['cwd'] == str(tmp_path / 'cwd')
    assert res['meta']['session_id'] == 's-1' and be.credential == 'keychain:claude-oauth-token'
    assert 'tok-SECRET-123' not in json.dumps(res)


def test_cli_backend_not_logged_in_is_unavailable_and_scrubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: FakeProc(
        json.dumps({'result': 'Not logged in · Please run /login (tok-SECRET-123)', 'is_error': True}), '', 1))
    be = m.ClaudeCLIBackend(token='tok-SECRET-123', workdir=tmp_path, binary='claude')
    with pytest.raises(m.BackendUnavailable) as ei:
        be.call('s', 'p', {})
    assert 'tok-SECRET-123' not in str(ei.value)


def test_cli_backend_timeout_is_transient(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired('claude', 1)
    monkeypatch.setattr(m.subprocess, 'run', boom)
    with pytest.raises(m.TransientError):
        m.ClaudeCLIBackend(workdir=tmp_path, binary='claude').call('s', 'p', {})


def test_cli_backend_without_token_uses_own_login(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'parent-token')
    be = m.ClaudeCLIBackend(token=None, workdir=tmp_path, binary='claude')
    assert 'CLAUDE_CODE_OAUTH_TOKEN' not in be.env() and be.credential == 'cli-own-login'


def test_api_backend_sends_pinned_model_and_schema():
    seen = {}

    class Block:
        type, text = 'text', '{"ok": true}'

    class Resp:
        content, stop_reason = [Block()], 'end_turn'

        class usage:
            input_tokens, output_tokens = 11, 3

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                seen.update(kw)
                return Resp()
    pytest.importorskip('anthropic')
    be = m.APIBackend(client=Client())
    res = be.call('SYS', 'PROMPT', m.SCHEMA_JUDGE)
    assert seen['model'] == m.MODEL and seen['system'] == 'SYS'
    assert seen['output_config'] == {'effort': m.EFFORT,
                                     'format': {'type': 'json_schema', 'schema': m.SCHEMA_JUDGE}}
    assert res['text'] == '{"ok": true}' and res['usage'] == {'input_tokens': 11, 'output_tokens': 3}


def test_make_backend_without_api_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(m, 'keychain', lambda s: None)
    with pytest.raises(m.BackendUnavailable, match='anthropic-api-key'):
        m.make_backend('api')


def test_probe_reports_hook_evidence(monkeypatch, tmp_path):
    d = tmp_path / 'lb'
    d.mkdir()
    (d / 'refusals.jsonl').write_text('{"x":1}\n')
    (d / 'state.json').write_text('{"session":"s-other"}')
    monkeypatch.setattr(m, 'LB_DIR', d)

    class One:
        name, model, credential = 'mock', m.MODEL, 'none'

        def call(self, *a):
            return {'text': '{"ok": true, "n": 7}', 'usage': {}, 'meta': {'session_id': 's-child'}}
    rep = m.probe(One())
    assert rep['ok'] and rep['lb_changed'] == {} and rep['lb_files_mentioning_child_session'] == []
    assert m.lb_mentions('s-other') == ['state.json']


def test_lb_snapshot_counts_lines(tmp_path):
    (tmp_path / 'a.jsonl').write_text('1\n2\n3\n')
    (tmp_path / 'b.json').write_text('{}')
    assert m.lb_snapshot(tmp_path) == {'a.jsonl': ('lines', 3), 'b.json': ('bytes', 2)}
