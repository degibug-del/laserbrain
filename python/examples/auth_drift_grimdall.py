"""Example: grimdall integration reproducing laserbrain's drift scenario.

Reproduces the published drift scenario: "fix the failing auth test" drifting
to "refactor the session store". Shows the destructive `rm -rf ./src` call
blocked at the drift step with a composed receipt printed.

This example needs `pip install laserbrain[grimdall]` to run.
"""

from laserbrain import Harness, Operator
from laserbrain.integrations.grimdall_guard import GrimdallPEP


def main():
    pep = GrimdallPEP()
    op = Operator(pep=pep)
    harness = Harness()

    print("=== laserbrain drift scenario with grimdall integration ===\n")

    # Step 1: Agent starts grounded - fixing the failing auth test
    print("Step 1: Agent is grounded - fixing the failing auth test")
    harness.check(goal="fix the failing auth test", progress="advancing", distance=0)
    v = harness.last
    pep.sync_from(v)
    print(f"  Verdict: {v.reason} (Φ={v.phi:.2f}), tier={pep.tier}")
    print(f"  Policy: {pep.policy()}\n")

    # Step 2: Agent drifts - refactoring the session store
    print("Step 2: Agent drifts - refactoring the session store")
    harness.check(goal="refactor the session store", progress="advancing", distance=5, reason="goal-drift", phi=0.6)
    v = harness.last
    pep.sync_from(v)
    print(f"  Verdict: {v.reason} (Φ={v.phi:.2f}), tier={pep.tier}")
    print(f"  Policy: {pep.policy()}\n")

    # Step 3: Attempt destructive action (rm -rf ./src) - should be blocked
    print("Step 3: Attempting destructive 'rm -rf ./src' action...")
    try:
        # The wrapped function will be blocked by grimdall's policy
        # Since tier is "review" (goal-drift), the policy calls for human review
        # and the guard will block the call
        result = op.act(
            lambda: None,  # placeholder - actual rm would be blocked
            kind="shell",
            target="rm -rf ./src",
            reversible=False,
        )
        print(f"  Result: {result}  (unexpected - should have been blocked)")
    except Exception as e:
        print(f"  Blocked: {type(e).__name__}: {e}")

    # Step 4: Composed receipt showing both verdict and enforcement
    print("\nStep 4: Composed receipt")
    receipt = pep.compose_receipt(v, {"status": "blocked", "reason": "goal-drift enforces review"})
    print(f"  Alignment: band={receipt['alignment']['band']}, goal_score={receipt['alignment']['goal_score']}")
    print(f"  Enforcement: {receipt['enforcement']}")

    print("\n=== End of scenario ===")
    print("Note: This example needs `pip install laserbrain[grimdall]` to function fully.")


if __name__ == "__main__":
    main()