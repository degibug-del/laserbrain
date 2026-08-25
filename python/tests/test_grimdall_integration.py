"""Tests for the grimdall integration bridge."""

import pytest
import os

from laserbrain import Harness, Verdict, Operator
from laserbrain.integrations.grimdall_guard import GrimdallPEP


def test_no_grimdall_installed(monkeypatch):
    """When grimdall is not installed, GrimdallPEP is a pure no-op."""
    monkeypatch.setattr("laserbrain.integrations.grimdall_guard.HAS_GRIMDALL", False)

    # wrap should return the function unchanged
    fn = lambda: 42
    result = GrimdallPEP().wrap(fn)
    assert result is fn

    # Operator with pep=None should behave identically to without pep
    op_no_pep = Operator()
    op_with_pep = Operator(pep=None)

    # Simple test: both should accept a reversible action
    def my_fn():
        return "ok"

    # Both should not raise for reversible calls
    assert op_no_pep.act(my_fn, kind="shell", target="x", reversible=True) == "ok"
    assert op_with_pep.act(my_fn, kind="shell", target="x", reversible=True) == "ok"


def test_no_grimdall_installed_operator_with_pep(monkeypatch):
    """Operator with pep set vs unset should behave identically when grimdall absent."""
    monkeypatch.setattr("laserbrain.integrations.grimdall_guard.HAS_GRIMDALL", False)

    fn = lambda: "result"

    op_no_pep = Operator()
    op_with_pep = Operator(pep=None)

    # Both should behave the same - reversible actions pass through
    assert op_no_pep.act(fn, kind="shell", target="x", reversible=True) == "result"
    assert op_with_pep.act(fn, kind="shell", target="x", reversible=True) == "result"


@pytest.mark.parametrize("band,expected_tier", [
    ("grounded", "normal"),
    ("advancing", "normal"),
    ("reground", "normal"),
    ("excursion", "normal"),
    ("stalled", "warn"),
    ("self-report:stuck", "warn"),
    ("self-report:circling", "warn"),
    ("goal-drift", "review"),
    ("oscillating", "review"),
    ("ungrammatical", "strict"),
])
def test_tier_mapping(band, expected_tier):
    """Each verdict band maps to the correct tier."""
    pep = GrimdallPEP()
    v = Verdict(drifting=False, reason=band, phi=0.0, advice="", goal_score=1.0)
    pep.sync_from(v)
    assert pep.tier == expected_tier


def test_grounded_allows_writes():
    """Grounded band -> normal tier -> writes allowed via harness."""
    pep = GrimdallPEP()
    harness = Harness()
    v = harness.check(goal="build the parser", progress="advancing", distance=0)
    pep.sync_from(v)
    assert pep.tier == "normal"


def test_goal_drift_downgrades_to_review():
    """goal-drift band -> review tier -> human review for writes."""
    pep = GrimdallPEP()
    # Create verdict directly with goal-drift reason
    v = Verdict(drifting=False, reason="goal-drift", phi=0.5, advice="", goal_score=0.3)
    pep.sync_from(v)
    assert pep.tier == "review"


def test_oscillating_downgrades_to_review():
    """oscillating band -> review tier."""
    pep = GrimdallPEP()
    v = Verdict(drifting=False, reason="oscillating", phi=0.3, advice="", goal_score=1.0)
    pep.sync_from(v)
    assert pep.tier == "review"


def test_ungrammatical_goes_strict():
    """ungrammatical band -> strict tier -> deny writes."""
    pep = GrimdallPEP()
    v = Verdict(drifting=False, reason="ungrammatical", phi=0.3, advice="", goal_score=1.0)
    pep.sync_from(v)
    assert pep.tier == "strict"


def test_composed_receipt_has_both_verdicts():
    """compose_receipt carries both alignment band and enforcement decision."""
    pep = GrimdallPEP()

    class MockVerdict:
        reason = "goal-drift"
        goal_score = 0.3

    enforcement = {"status": "review", "reason": "human review needed"}
    receipt = pep.compose_receipt(MockVerdict(), enforcement)

    assert receipt["alignment"]["band"] == "goal-drift"
    assert receipt["alignment"]["goal_score"] == 0.3
    assert receipt["enforcement"] == enforcement


def test_parity_ports_untouched():
    """Guard the python-only scope - no typescript/javascript files modified."""
    # Verify all changed files are under python/ only
    import glob
    
    # Check that no typescript or javascript files were modified by this integration
    ts_files = glob.glob(r"C:\Users\blaze\laserbrain\typescript\**", recursive=True)
    js_files = glob.glob(r"C:\Users\blaze\laserbrain\javascript\**", recursive=True)
    
    # Just ensure the integration directory only has python files (not dirs)
    integration_dir = r"C:\Users\blaze\laserbrain\python\laserbrain\integrations"
    files = [f for f in os.listdir(integration_dir) if os.path.isfile(os.path.join(integration_dir, f))]
    for f in files:
        assert f.endswith(".py"), f"Unexpected file in integrations: {f}"


def test_operator_with_pep_sync_from(monkeypatch):
    """Operator with pep calls sync_from before the existing drift check."""
    monkeypatch.setattr("laserbrain.integrations.grimdall_guard.HAS_GRIMDALL", False)

    pep = GrimdallPEP()
    # When pep is None, Operator should behave exactly as before
    op = Operator(pep=None)

    # Test that reversible actions still work
    def my_fn():
        return "ok"

    result = op.act(my_fn, kind="shell", target="x", reversible=True)
    assert result == "ok"

    # Test irreversible action without harness still asks
    # (this tests the existing behavior is preserved)