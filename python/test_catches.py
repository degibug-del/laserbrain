"""Each detector must fire on the real incident, and stay silent on the healthy case.

Rule 1 applied to the detectors themselves: a detector that has only ever been green
is not evidence. Every test below has a negative half.
"""
from laserbrain.catches import (Event, catches, unfalsified, instrument_blind, unrun,
                               residue, contaminated, stale_gate)

sigs = lambda evs: sorted(c.signature for c in catches(evs))


def test_unfalsified_fires_on_the_grain_guard():
    # the real one: a guard that passed on a page with no grain, four times
    evs = [Event('check', 'sheet-grain present', ok=True) for _ in range(4)]
    assert sigs(evs) == ['unfalsified']


def test_unfalsified_silent_once_the_check_has_been_red():
    evs = [Event('check', 'sheet-grain present', ok=True),
           Event('check', 'sheet-grain present', ok=False),   # proven falsifiable
           Event('check', 'sheet-grain present', ok=True)]
    assert unfalsified(evs) == []


def test_instrument_blind_fires_on_the_blank_screenshots():
    evs = [Event('tool', 'screenshot', result='blank') for _ in range(3)]
    assert sigs(evs) == ['instrument-blind']


def test_instrument_blind_fires_on_a_zeroed_viewport():
    evs = [Event('tool', 'viewport', result={'y': 0, 'vh': 0}) for _ in range(3)]
    assert [c.signature for c in instrument_blind(evs)] == ['instrument-blind']


def test_instrument_blind_silent_when_the_run_is_broken():
    evs = [Event('tool', 'screenshot', result='blank'),
           Event('tool', 'screenshot', result='blank'),
           Event('tool', 'screenshot', result='<png 40kb>'),   # instrument recovered
           Event('tool', 'screenshot', result='blank')]
    assert instrument_blind(evs) == []


def test_instrument_blind_ignores_a_legitimate_false():
    # False is a real answer, not an empty one
    evs = [Event('tool', 'is_dark', result=False) for _ in range(4)]
    assert instrument_blind(evs) == []


def test_unrun_fires_on_a_claim_read_not_executed():
    evs = [Event('claim', 'Harness.check', text='four verdicts hold, four interrupt')]
    assert sigs(evs) == ['unrun']


def test_unrun_silent_when_the_code_was_executed():
    evs = [Event('tool', 'Harness.check', result='self-report:stuck drifting=False'),
           Event('claim', 'Harness.check', text='two of the eight are two-strike')]
    assert unrun(evs) == []


def test_healthy_log_is_silent():
    evs = [Event('check', 'contrast', ok=False),
           Event('check', 'contrast', ok=True),
           Event('tool', 'Harness.check', result='advancing'),
           Event('claim', 'Harness.check', text='advancing is the ordinary verdict')]
    assert catches(evs) == []


def test_a_bad_day_reports_all_three():
    evs = [Event('check', 'grain', ok=True),
           Event('tool', 'screenshot', result='blank'),
           Event('tool', 'screenshot', result='blank'),
           Event('tool', 'screenshot', result='blank'),
           Event('claim', 'verdict split', text='four hold, four interrupt')]
    assert sigs(evs) == ['instrument-blind', 'unfalsified', 'unrun']



# ── the three that needed an input the event log does not carry ───────────────

def test_residue_fires_on_the_colour_sweep():
    before = "['#3a93c9'] color:'#3a93c9' fill:'#3a93c9' link:'#3a93c9'"
    after = "['#3a93c9'] color:'#276990' fill:'#276990' link:'#276990'"
    c = residue(before, after, r'#3a93c9')
    assert [x.signature for x in c] == ['residue']
    assert 'left 1' in c[0].detail


def test_residue_silent_when_the_sweep_was_total():
    before = "a #3a93c9 b #3a93c9"
    assert residue(before, before.replace('#3a93c9', '#276990'), r'#3a93c9') == []


def test_contaminated_fires_on_a_leaked_comment():
    assert [c.signature for c in contaminated('text /* my commentary */ text')] == ['contaminated']


def test_contaminated_fires_on_a_todo():
    assert contaminated('TODO: fix before ship') != []


def test_contaminated_silent_on_clean_prose():
    assert contaminated('an ordinary paragraph, nothing left in it') == []


def test_stale_gate_silent_when_the_gate_catches_its_mutant():
    gate = lambda s: '#0E7154' in s
    mutate = lambda s: s.replace('#0E7154', '#0F7A5A')
    assert stale_gate(gate, mutate, "color:'#0E7154'") == []


def test_stale_gate_fires_when_the_gate_survives_the_mutation():
    weak = lambda s: 'color' in s
    mutate = lambda s: s.replace('#0E7154', '#0F7A5A')
    assert [c.signature for c in stale_gate(weak, mutate, "color:'#0E7154'")] == ['stale-gate']


def test_stale_gate_tells_broken_from_stale():
    c = stale_gate(lambda s: False, lambda s: s, 'x')
    assert 'broken, not stale' in c[0].detail

# Every other suite here is a standalone script that exits its own status — running the
# directory under pytest aborts on their SystemExit. Match that, so this file runs the
# same way as its neighbours instead of being the one nobody executes.
if __name__ == '__main__':
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    bad = 0
    for t in tests:
        try:
            t()
            print(f'  ok    {t.__name__}')
        except AssertionError as e:
            bad += 1
            print(f'  FAIL  {t.__name__}  {e}')
    print(f'\n  catch signatures: {len(tests) - bad}/{len(tests)}')
    sys.exit(1 if bad else 0)
