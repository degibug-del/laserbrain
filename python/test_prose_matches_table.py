#!/usr/bin/env python3
"""Numbers in prose must not drift from the data that produced them.

attention.json is rewritten by every recalibration. Any figure typed into a docstring
beside it is therefore guaranteed to rot, and did — quietly, across every release from
0.44.0 onward:

    the module header    "rate': 0.387"          shipped 0.2714
    the caveat at :33    "92% a single agent"    shipped 100%
    agent_risk's reasoning  "0.3% of the sample"  shipped 7.68%   (wrong by 25x)

None of those broke anything that could fail. A reader is simply told a number the wheel
does not contain, in the same file that contains it. Correcting the digits has been tried
and has not held, because the next regeneration desynchronises them again — so this asserts
the invariant instead: a percentage or rate in attention.py's prose must either be absent,
or agree with the table shipped beside it.

This is the repo's own `assert-the-prose` discipline applied to the module that needs it
most: the one whose entire subject is a regenerated measurement.
"""
import os
import re
import tempfile

os.environ.setdefault('LASERBRAIN_HOME', tempfile.mkdtemp(prefix='lb-prose-'))

from laserbrain import attention as A                              # noqa: E402

ok = True


def show(name, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'✓' if passed else '✗'} {name}" + (f"  — {detail}" if detail else ''))


TABLE = A.table()
PROV = TABLE.get('provenance', {})
AC = TABLE.get('agent_clock', {})

# ── the module header quotes no rate it cannot keep ───────────────────────────
_head = A.__doc__ or ''
_rates = re.findall(r"'rate':\s*([0-9]*\.[0-9]+)", _head)
show('the header example quotes no literal rate', not _rates,
     f'found {_rates} — these rot on every recalibration')

# ── no percentage in the docstring contradicts the table ──────────────────────
# SCOPED TO CLAIMS ABOUT THIS TABLE. A percentage in the docstring is only checkable if it
# purports to describe attention.json's own corpus — so only lines that say so are read. The
# three this deliberately does not flag are all legitimate and none of them can rot:
#   "drift exceeds 25%"        echoes the 0.25 argument in the example above it
#   "precision ... is 14.6%"   a figure from the drift DETECTOR, not from this table
#   "\"92% ...\" against a shipped 100%"   a note recording what the stale value used to be
# A line that describes the corpus and quotes a number is the shape that has rotted three
# times, and it is the shape this catches.
_CLAIMS = ('corpus', 'sample', 'every gap', 'lands in')
_pcts = [float(m) for line in _head.splitlines()
         if any(w in line.lower() for w in _CLAIMS) and 'against a shipped' not in line
         for m in re.findall(r'(\d+(?:\.\d+)?)%', line)]
_share = round((PROV.get('dominant_agent_share') or 0) * 100, 1)


def _agent_clock_share(lo, hi=None):
    tot = sum(b.get('n') or 0 for b in AC.get('bands', []))
    if not tot:
        return None
    sel = sum(b.get('n') or 0 for b in AC.get('bands', [])
              if b.get('from_steps', 0) >= lo and (hi is None or (b.get('to_steps') or 10**9) <= hi))
    return round(100 * sel / tot, 1)


_legit = {v for v in (_share, _agent_clock_share(4, 7), _agent_clock_share(8)) if v is not None}
_legit |= {round(v) for v in _legit}                      # 77.8 quoted as 78 is honest
_bad = [p for p in _pcts if p not in _legit and round(p) not in _legit]
show('every percentage in the docstring matches the shipped table',
     not _bad, f'unmatched: {_bad} — table offers {sorted(_legit)}')

# ── provenance is internally ordered ──────────────────────────────────────────
# A table cannot cover data that postdates its own write; describe() prints both, so an
# inconsistency here is user-visible. 0.54.1 shipped written=2026-08-21 with
# corpus_to=2026-08-22.
_cf, _ct, _w = PROV.get('corpus_from'), PROV.get('corpus_to'), PROV.get('written')
show('provenance dates are ordered', bool(_cf and _ct and _w) and _cf <= _ct <= _w,
     f'corpus_from={_cf} corpus_to={_ct} written={_w}')

# ── a band that says "+" covers everything above its floor ────────────────────
_last = (AC.get('bands') or [{}])[-1]
show('the open-ended step band is actually open-ended',
     not (str(_last.get('label', '')).endswith('+ steps') and _last.get('to_steps') is not None),
     f"{_last.get('label')} to_steps={_last.get('to_steps')}")
show('and agent_risk answers in it well past the old cap',
     A.agent_risk(1000).get('band') == _last.get('label'),
     f"agent_risk(1000) -> {A.agent_risk(1000).get('band')}")

# ── describe() renders without quoting anything absent ────────────────────────
_desc = A.describe() or ''
show('describe() renders', bool(_desc.strip()), f'{len(_desc)} chars')

# ── a carried block declares its own vintage ──────────────────────────────────
# agent_clock is built from the session store, which records a verdict only when the agent
# was told one. Under a blind arm the calibrator carries the last readable block forward
# rather than overwrite a real measurement with "unknown" — so those rows can be much older
# than the table around them. describe() prints the TABLE's dates, so a block that does not
# share them has to say so, in both the machine-readable and the human-readable path.
_carried = AC.get('carried_written')
if _carried:
    show('a carried block carries a date, not prose', bool(_carried), _carried)
    show('  agent_risk exposes it', A.agent_risk(4).get('carried_from') == _carried,
         repr(A.agent_risk(4).get('carried_from')))
    show('  and describe() says so', 'carried from the calibration' in (A.describe() or ''),
         'the corpus line above it would otherwise imply these rows share its dates')
    show('  the vintage predates the table it sits in',
         _carried <= (PROV.get('written') or ''), f"{_carried} vs {PROV.get('written')}")
else:
    print('  skip  carried-block vintage   this agent_clock is the table\'s own measurement')

print('\n' + ('PROSE AGREES WITH THE TABLE ✓' if ok else 'SOME FAILED ✗'))
raise SystemExit(0 if ok else 1)
