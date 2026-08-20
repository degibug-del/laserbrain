#!/usr/bin/env python3
"""`laserbrain coverage` must count archived segments, not just the live task.

WHY. reset_task archives the finished run into segments[] and clears steps/checks/inferred/
catches. A reader that sums only the top level sees the CURRENT task and reports it as the
whole session. On 2026-08-07 that made a session with 2,396 checks across 248 segments print
as 3 steps and 1 check — 0.1% of the work, shown as all of it.

The failure direction is what makes it dangerous: it fails toward ZERO. The harness looks
unattached when it was attached all day, and `coverage` exists precisely to answer "is my
monitoring attached?". A tool that answers that wrongly, in the reassuring-to-ignore
direction, is worse than no tool.

And the drift fires are the worst-hit: the harness ADVISES a reset when goal-drift fires, so
a fire is followed by exactly the operation that archives it out of the naive view.
"""
import json
import os
import subprocess
import sys
import tempfile

d = tempfile.mkdtemp()
# One session: 2 live steps, plus two archived segments carrying 100 more.
session = {
    'id': 'seg-test', 'started': '2026-08-07T00:00:00', 'goal': 'now',
    'steps': 2, 'checks': [{'step': 1}], 'inferred': [], 'catches': [], 'events': [],
    'segments': [
        {'goal': 'a', 'steps': 60, 'checks': [{'step': i} for i in range(30)],
         'inferred': [{}] * 5, 'catches': [{}] * 3},
        {'goal': 'b', 'steps': 40, 'checks': [{'step': i} for i in range(20)],
         'inferred': [{}] * 2, 'catches': [{}] * 1},
    ],
}
json.dump(session, open(os.path.join(d, 'seg-test.json'), 'w'))

out = subprocess.run([sys.executable, '-m', 'laserbrain.cli', 'coverage', '--dir', d],
                     capture_output=True, text=True, env={**os.environ, 'LASERBRAIN_HOME': tempfile.mkdtemp()}).stdout

fails = []
def ok(label, cond, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + (f'   {detail}' if detail else ''))
    if not cond:
        fails.append(label)

# 2 + 60 + 40 = 102 steps, 1 + 30 + 20 = 51 checks, 0+5+2 = 7 inferred, 0+3+1 = 4 catches.
ok('steps include archived segments', ' 102' in out, 'expected 102; naive read gives 2')
ok('checks include archived segments', ' 51' in out, 'expected 51; naive read gives 1')
ok('inferred include archived segments', ' 7' in out)
ok('catches include archived segments', ' 4' in out)
# 51/102 = 50%. The naive read would be 1/2 = 50% too — same ratio, wrong scale — which is
# exactly why a coverage PERCENTAGE alone cannot reveal this bug. The totals are the tell.
ok('and the ratio is still right', '50%' in out)

print()
if fails:
    print(f'  FAIL — {len(fails)}\n')
    print(out)
    sys.exit(1)
print('  PASS — coverage counts the whole session, not only the live task.\n')
