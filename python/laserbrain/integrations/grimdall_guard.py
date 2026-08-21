"""Grimdall payload-level enforcement bridge for laserbrain.

This module completes laserbrain's existing ``Operator`` ("a drifting agent can't do
what it can't undo") by adding payload-level enforcement every tool call — at the
ast-parsed shell, secret-path read, and egress allowlist level — and the OS boundary
(networkless sandbox).  Even an act that ``Operator`` would let through gets contained.

Without ``grimdall`` installed, ``GrimdallPEP`` is a pure no-op: ``wrap()`` returns
the original function unchanged, and ``Operator`` behaves identically with or without
``pep`` set.  This ensures zero behaviour change when the dependency is absent.
"""

from __future__ import annotations

try:
    from grimdall import guard, Policy  # type: ignore
    HAS_GRIMDALL = True
except ImportError:  # pragma: no cover
    HAS_GRIMDALL = False

# Map the nine laserbrain verdict bands to grimdall policy tiers.
# grounded/advancing/reground/excursion -> normal (writes allowed)
# stalled/self-report:stuck/self-report:circling -> warn (caution)
# goal-drift/oscillating -> review (human in the loop)
# ungrammatical -> strict (deny writes)
TIER_FOR_BAND = {
    "grounded": "normal",
    "advancing": "normal",
    "reground": "normal",
    "excursion": "normal",
    "stalled": "warn",
    "self-report:stuck": "warn",
    "self-report:circling": "warn",
    "goal-drift": "review",
    "oscillating": "review",
    "ungrammatical": "strict",
}


class GrimdallPEP:
    """Bridge that maps laserbrain verdict bands to grimdall policy tiers.

    ``sync_from`` reads the current band from the harness verdict and sets ``self.tier``.
    ``policy`` returns a ``grimdall.Policy`` instance appropriate for that tier.
    ``wrap`` instrumentates a tool function so every call passes through grimdall
    evaluation.  When grimdall is not installed everything is a no-op.
    """

    def __init__(self) -> None:
        self.tier: str = "normal"

    # ── sync ────────────────────────────────────────────────────────────────

    def sync_from(self, verdict) -> None:
        """Set ``self.tier`` from a harness verdict.

        Reads the band from ``getattr(verdict, "reason", None)`` or
        ``getattr(verdict, "band", "normal")``.
        """
        band = getattr(verdict, "reason", None) or getattr(verdict, "band", "normal")
        self.tier = TIER_FOR_BAND.get(band, "normal")

    # ── policy ─────────────────────────────────────────────────────────────

    def policy(self):
        """Return a ``grimdall.Policy`` instance for the current tier.

        Returns ``None`` when grimdall is not installed.
        """
        if not HAS_GRIMDALL:
            return None

        if self.tier == "strict":
            # Deny all writes — the most restrictive mode.
            return Policy(deny=["*"])
        # review, normal, and warn all use the default policy;
        # the tier distinction is honoured by the caller (Operator).
        return Policy()

    # ── wrap ───────────────────────────────────────────────────────────────

    def wrap(self, tool_fn):
        """Instrument ``tool_fn`` so every call passes through grimdall evaluation.

        Returns the original function unchanged when grimdall is not installed.
        """
        if not HAS_GRIMDALL:
            return tool_fn

        # Build a guard with the policy for this tier, then wrap.
        from grimdall import Guard  # local import to avoid hard fail at module load

        g = Guard()
        g.add_policy(self.policy())
        return g.wrap(tool_fn)

    # ── compose_receipt ────────────────────────────────────────────────────

    def compose_receipt(self, verdict, enforcement) -> dict:
        """Return a dict carrying both the laserbrain verdict and the enforcement decision.

        ``enforcement`` is the decision dict returned by ``guard.check()`` or
        ``guard.wrap()``.
        """
        return {
            "alignment": {
                "band": getattr(verdict, "reason", None) or getattr(verdict, "band", "normal"),
                "goal_score": getattr(verdict, "goal_score", None),
            },
            "enforcement": enforcement,
        }