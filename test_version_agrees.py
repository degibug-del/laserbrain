#!/usr/bin/env python3
"""The version is written twice. It must say the same thing both times.

WHY, 2026-08-06

`pyproject.toml` decides what the built artifact is called; `laserbrain.__version__` is what
anything importing the package reads. 0.44.0 was released with only the first bumped, so the
wheel on PyPI is 0.44.0 and reports itself as 0.43.0 from inside.

publish.sh caught it — it installs the released package and compares — but that is AFTER the
upload, and PyPI versions cannot be replaced. The whole cost of the mistake is that it was
detected one step too late.

It is the same shape as the bugs 0.44.0 itself fixed: one fact stored twice, one copy
updated, nothing checking they agree. This is the check that belongs before the upload rather
than after it.
"""
import pathlib
import re
import sys

SDK = pathlib.Path(__file__).resolve().parent.parent / 'laserbrain-sdk'

toml = (SDK / 'pyproject.toml').read_text()
init = (SDK / 'laserbrain' / '__init__.py').read_text()

m_toml = re.search(r'^version = "([^"]+)"', toml, re.M)
m_init = re.search(r"^__version__ = '([^']+)'", init, re.M)

print('the two places the version is written must agree\n')
ok = True
for label, m in (('pyproject.toml', m_toml), ('__init__.py', m_init)):
    if not m:
        print(f'  FAIL  {label} has no version to read')
        ok = False
    else:
        print(f'  ok    {label:16} {m.group(1)}')

if ok and m_toml.group(1) != m_init.group(1):
    print(f'\n  FAIL  they disagree: {m_toml.group(1)} vs {m_init.group(1)}')
    print('        the wheel would ship one number and report the other')
    ok = False

print()
if not ok:
    sys.exit(1)
print('  PASS — the artifact and the package agree on what they are.')
