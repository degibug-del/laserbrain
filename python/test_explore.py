"""The second instrument: every reading fires, and the healthy search stays quiet.

The failure that mattered while writing this: `revisiting` masked both `thrashing` and
`settled`, because holding one ground read as returning to it. Staying is not revisiting.
"""
from laserbrain import Search, trailscore


def run(grounds, work=3):
    s = Search()
    out = []
    for g in grounds:
        for _ in range(work):
            s.step()
        out.append(s.ground(g).reason)
    return out, s


def test_opens_on_the_first_ground():
    out, _ = run(['design the page'])
    assert out == ['opened']


def test_healthy_search_never_flags():
    out, _ = run(['design the page', 'measure the contrast', 'build the gate',
                  'write the protocol', 'graph the gaps'])
    assert set(out) <= {'opened', 'searching', 'narrowing'}


def test_revisiting_fires_on_returning_to_abandoned_ground():
    out, _ = run(['build the parser', 'benchmark the cache', 'tune the renderer',
                  'build the parser'])
    assert out[-1] == 'revisiting'


def test_staying_is_not_revisiting():
    # holding one ground must not read as returning to it
    out, _ = run(['ship the JSON parser'] * 5)
    assert 'revisiting' not in out


def test_settled_fires_when_novelty_is_gone():
    out, _ = run(['ship the JSON parser'] * 5)
    assert out[-1] == 'settled'


def test_thrashing_fires_when_nothing_is_worked():
    out, _ = run(['parser design', 'cache eviction', 'render pipeline',
                  'colour contrast', 'deploy script', 'font loading'], work=0)
    assert 'thrashing' in out


def test_thrashing_silent_when_ground_is_worked():
    out, _ = run(['parser design', 'cache eviction', 'render pipeline',
                  'colour contrast', 'deploy script', 'font loading'], work=3)
    assert 'thrashing' not in out


def test_trailscore_is_null_before_any_ground():
    assert trailscore([]) is None


def test_trailscore_accumulates_the_path():
    t = trailscore(['build the parser', 'benchmark the cache'])
    assert t.startswith('⟨') and t.endswith('×2')
    assert 'pars' in t and 'cache' in t


def test_territory_reports_what_was_covered():
    _, s = run(['design the page', 'measure the contrast'])
    t = s.territory()
    assert t['grounds'] == 2 and t['tokens'] > 0 and len(t['novelty']) == 2


if __name__ == '__main__':
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    bad = 0
    for t in tests:
        try:
            t(); print(f'  ok    {t.__name__}')
        except AssertionError as e:
            bad += 1; print(f'  FAIL  {t.__name__}  {e}')
    print(f'\n  explore: {len(tests) - bad}/{len(tests)}')
    sys.exit(1 if bad else 0)
