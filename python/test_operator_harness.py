"""The sixth join — the hands consult the instrument before doing something final.

Until 0.26.0 the harness could say "return to your goal" and the agent was free to deploy
anyway, because advice is advice. Operator(harness=…) makes the return enforceable for the
one class of action where it matters: the kind that cannot be taken back.

WHAT EACH CASE GUARDS

  grounded acts       the join must not break the normal path. An operator that refuses
                      everything is not safe, it is broken, and it would look identical
                      from inside a test that only checked refusals.
  drifting refused    the point of the feature.
  no reading refused  NO READING IS NOT A GOOD READING. An operator wired to a harness
                      nobody has checked knows nothing about the agent asking it to act.
                      Spending "nothing" as "fine" is the failure this instrument is named
                      after.
  reversible allowed  a drifting agent may still read a file. If drift blocked everything,
                      the first thing every user would do is unwire the harness.
  before the human    the consult happens BEFORE the authorizer, and the ordering is the
                      substance. Asking a person to approve an irreversible act by an
                      off-goal agent is exactly when a person rubber-stamps: the request
                      looks reasonable in isolation, because every drifting step does.
  opt-in              an Operator with no harness behaves exactly as it did before.
  return clears it    after the agent returns to ground the hands work again, otherwise
                      one drift would end the run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laserbrain import Harness, Operator, Refused  # noqa: E402

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


def refused(op, **kw):
    """Did this act get refused? Returns (was_refused, message)."""
    try:
        op.act(lambda: 'done', kind=kw.pop('kind', 'deploy'), target=kw.pop('target', 'prod'), **kw)
        return False, ''
    except Refused as e:
        return True, str(e)


# ── no reading at all ────────────────────────────────────────────────────────────────
h = Harness('build the parser')
op = Operator(authorize=lambda a: True, harness=h)
was, msg = refused(op)
check('an unchecked harness refuses an irreversible act', was, msg[:60])
check('and says WHY, so it is fixable', 'no reading' in msg, msg[:60])

# ── grounded: the normal path must still work ────────────────────────────────────────
h.check('build the parser', 'advancing', 5)
try:
    out = op.act(lambda: 'deployed', kind='deploy', target='prod')
    check('a grounded agent may act', out == 'deployed', str(out))
except Refused as e:
    check('a grounded agent may act', False, str(e)[:60])

# ── drifting: the whole point ────────────────────────────────────────────────────────
h.check('write documentation instead', 'advancing', 4)
check('the harness sees the drift', h.last.drifting, h.last.reason)
was, msg = refused(op)
check('a drifting agent is refused', was, msg[:56])
check('the refusal names the verdict', h.last.reason in msg, msg[:70])
check('the refusal carries the return advice', len(msg) > 60, f'{len(msg)} chars')

# ── but only for what cannot be taken back ───────────────────────────────────────────
try:
    out = op.act(lambda: 'contents', kind='read', target='f.txt', reversible=True)
    check('a drifting agent may still do reversible things', out == 'contents', str(out))
except Refused as e:
    check('a drifting agent may still do reversible things', False, str(e)[:60])

# ── ordering: the human is never asked about a drifting agent ────────────────────────
asked = []
op2 = Operator(authorize=lambda a: (asked.append(a), True)[1], harness=h)
refused(op2)
check('the authorizer is NOT consulted while drifting', asked == [],
      f'{len(asked)} call(s) — a human was asked to rubber-stamp')

# ── returning to ground restores the hands ───────────────────────────────────────────
h.check('build the parser', 'advancing', 2)
try:
    out = op.act(lambda: 'deployed', kind='deploy', target='prod')
    check('returning to ground restores the hands', out == 'deployed', h.last.reason)
except Refused as e:
    check('returning to ground restores the hands', False, str(e)[:60])

# ── opt-in: no harness, no change ────────────────────────────────────────────────────
plain = Operator(authorize=lambda a: True)
try:
    check('an operator with no harness is unchanged',
          plain.act(lambda: 'ok', kind='deploy', target='prod') == 'ok')
except Refused as e:
    check('an operator with no harness is unchanged', False, str(e)[:60])

# ── and the counter is real, not decorative ──────────────────────────────────────────
check('blocked_by_drift counts the stops', op.blocked_by_drift == 2, str(op.blocked_by_drift))

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    sys.exit(1)
print('  PASS — a drifting agent cannot do what it cannot undo, and everything else works.')
