"""The ICM Reading contract, agent side.

WHAT THIS IS FOR. "Integrated Coherence Machine" has been describing something true and
unenforced: laserbrain reads agents, the phronesis surfaces read people, both implement
displacement from a reference that cannot be revised, and they share no code. Two
implementations of one idea that have never been made to agree is the condition that let
`coherence` mean three different numbers on the site, and that nearly let read() diverge
between the site and the Worker before check-reading-parity caught it.

So the shape is declared once — phronesis-world/lib/icm-reading.ts — and both sides are
gated against it by scripts/check-reading-contract.mjs.

WHAT IS NOT SHARED, deliberately: the computation. Phi is
0.5*jaccard(goal) + 0.3*|delta d|/10 + 0.2*(progress changed); the human side is 100 minus
a keyword tally. Those SHOULD differ. An agent spells its state against a goal it declared;
a person writes prose about how they are. Forcing one formula onto both would be the same
error as averaging Dialogue's four facts into a single coupling score.

WHY DISPLACEMENT IS PHI * 100 AND NOT SOMETHING TIDIER: phi is already the displacement
this instrument measures, on 0..1, and rescaling is the only honest conversion. Deriving a
different number here would create a third quantity nobody calibrated — which is exactly
how `coherence` came to mean three things.
"""


def reading(harness, verdict):
    """One Verdict as a Reading. Returns the plain dict the contract describes.

    `harness` is the Harness that produced `verdict` — the ground lives on the run, not on
    the verdict, because the whole point is that it was frozen before this reading existed.
    """
    run = harness._run
    ground = ''
    if isinstance(run.ground, dict):
        ground = run.ground.get('goal') or ''
    ground = ground or run.first_goal_text or ''

    # WHAT BACKED THIS, and the honest answer is usually "only the agent". `anchored` is
    # 0.5 when the reading rests on self-report and 1.0 when observed work corroborated it;
    # the published calibration puts half of phi on the agent's own account. Reporting
    # `backed` as anything but a direct read of that would be inventing corroboration.
    anchored = getattr(verdict, 'anchored', None)
    backed = bool(anchored is not None and anchored > run.cal.w_goal)

    reads = ['goal overlap against the frozen ground', 'distance as spelled', 'progress as spelled']
    if run.saw_any:
        reads.append(f'{run.corroborated} of {run.checks} checks corroborated by observed work')
    else:
        # Said out loud rather than omitted: uninstrumented is not the same as unbacked,
        # and a reading that quietly drops the distinction is the failure test_unbacked
        # exists to prevent.
        reads.append('no observed channel — nothing recorded through saw()')

    return {
        'instrument': 'laserbrain',
        'subject': 'agent',
        'ground': {'text': ground, 'frozen': True},
        # phi is already the displacement, on 0..1. Rescale, do not re-derive.
        'displacement': round(min(100.0, max(0.0, float(verdict.phi) * 100)), 2),
        'return': verdict.advice or '',
        'evidence': {'backed': backed, 'reads': reads},
    }


def violations(r):
    """The same checks the TypeScript side runs, so a divergence is a gate failure."""
    out = []
    if not r.get('instrument'):
        out.append('instrument is unnamed')
    if r.get('subject') not in ('agent', 'human'):
        out.append(f"subject is {r.get('subject')}")
    g = r.get('ground') or {}
    if not isinstance(g.get('text'), str) or not g.get('text'):
        out.append('ground has no text')
    if g.get('frozen') is not True:
        out.append('ground is not declared frozen')
    d = r.get('displacement')
    if not isinstance(d, (int, float)):
        out.append('displacement is not a number')
    elif d < 0 or d > 100:
        out.append(f'displacement {d} out of 0..100')
    if isinstance(d, (int, float)) and d > 0 and not r.get('return'):
        out.append('displaced with no return path')
    e = r.get('evidence') or {}
    if not isinstance(e.get('backed'), bool):
        out.append('evidence.backed is not a boolean')
    if not isinstance(e.get('reads'), list) or not e.get('reads'):
        out.append('evidence.reads is empty — a reading that cannot say what it consulted')
    return out
