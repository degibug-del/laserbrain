#!/usr/bin/env python3
"""Does the package describe the offer that actually exists?

WHY, 2026-08-07

laserbrain does ~6,300 downloads a month. The module docstring is the first thing every
one of those installs shows a reader, and `laserbrain tiers` is the only place the CLI
mentions money. On 2026-08-07 both were selling something that had been withdrawn:

  "the fleet view"          renamed to `pro` on 2026-07-29, nine days earlier
  "retained drift history"  the retention offer, which tiers.ts had already retired as
                            not honest — "charging for retention was charging for
                            something the client already had"
  "the field"               the laserfield hub was DESTROYED on 2026-08-03. The CLI was
                            telling prospective customers a key buys a thing that no
                            longer exists.

Nothing failed. No gate fired. The package kept installing and the sentence kept being
read, because a product's own description is not the kind of thing anything checks.

WHAT THIS PINS

  the tier names are the current ones      ground / group / pro, not the two retired sets
  the retired offer does not reappear      retention, "pay to see", the fleet view
  nothing sells the destroyed field        the hub is gone; a key cannot buy it
  there is a way to find out more          a package with no path to its own paid tier is
                                           not a free tier, it is a leak

DELIBERATELY NOT PINNED: prices. A price on a page is an offer, and scripts/check-meta-prices.mjs
already owns the question of whether a stated price survives contact with the page. Two gates
asserting one number is how they come to disagree, and the loser is whichever one nobody runs.

  (The first draft of this line said prices were "frozen until 2026-08-20". skeleton.json
  was unfrozen on 2026-07-24 and check-skeleton.mjs left the build chain with it, so that
  sentence was fourteen days stale on the day it was written — in the file whose entire job
  is catching copy that outlived what it describes. Left visible rather than quietly edited,
  because a gate that has made the mistake it guards against is the only kind worth trusting.)
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SDK = HERE.parent / 'laserbrain-sdk' / 'laserbrain'

fails = []


def check(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)


init = (SDK / '__init__.py').read_text()
cli = (SDK / 'cli.py').read_text()
# What a user actually reads: the module docstring and the CLI's tier output.
doc = init.split('"""')[1] if '"""' in init else ''
seen = doc + '\n' + cli

print('\n  the retired offers stay retired\n')

# THE THIRD NAMING. free/maker/studio -> ground/watch/fleet -> ground/group/pro. Each
# rename happened because what is sold changed, so an old name in the shop window is not a
# typo — it is a different product.
for old, new in (('fleet view', 'pro'), ('watch tier', 'group')):
    check(f'"{old}" does not appear (renamed to {new})', old not in seen.lower())

for phrase, why in (
    ('retained drift history', 'the retention offer tiers.ts calls not honest'),
    ('pay to see', 'the same offer in its slogan form'),
    ('pay to *see*', 'and in its emphasised form'),
):
    check(f'"{phrase}" does not appear', phrase not in seen.lower(), why)

print()
print('  nothing sells the field, which was destroyed 2026-08-03')
# Narrow on purpose: "the field" as something a KEY ADDS. laserbrain may still discuss
# fields elsewhere; what it may not do is offer one for money.
sells_field = re.search(r'(adds|buys|includes|get)[^.\n]{0,60}\bthe field\b', seen, re.I)
check('a key is not sold as buying "the field"', not sells_field,
      sells_field.group(0)[:60] if sells_field else '')

print()
print('  the current offer is stated, and reachable')
check('the tier names appear', all(t in seen for t in ('ground', 'group', 'pro')))
check('  the offer is a place to meet, not retention',
      'meet' in seen.lower(), 'what requires a server is somewhere machines can meet')
check('  and there is somewhere to go',
      'phronesis.world/laserbrain' in seen,
      'a package with no path to its paid tier is a leak, not a free tier')

print()
print('  and the tier TABLE does not advertise it either')
# My first version of this gate checked the prose and not the numbers, and passed while the
# CLI printed "field history  24h" three lines above the sentence it had just cleared. A
# shop window is the whole window.
#
# Comments are stripped first, because the second version then failed on the comment that
# explains the removal. What a customer reads is the OUTPUT, so that is what gets checked;
# a gate that cannot tell code from a note about code will be silenced by deleting the note.
code = '\n'.join(l for l in cli.splitlines() if not l.lstrip().startswith('#'))
check('the tier list does not print field history',
      'field history' not in code,
      'the hub is gone; the API still returns historyHours, so the CLI must not show it')

print()
if fails:
    print(f'  FAIL — {len(fails)}: ' + '; '.join(fails))
    print('\n  The shop window is laserbrain/__init__.py and laserbrain/cli.py.')
    print('  If the tiers changed, they changed here too.\n')
    sys.exit(1)
print('  PASS — the package sells the thing that exists.\n')
