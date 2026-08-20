"""The operator layer, tested by trying to get an irreversible action past it.

Every assertion here is about a REFUSAL actually preventing something, not about an
exception being raised. Those are different claims: a guard that raises after the deletion
has happened still raises. So each blocking test carries a side effect and checks the side
effect did not occur — rule 1 of the protocol, prove the check can fail.
"""
import sys

sys.path.insert(0, '.')

from laserbrain import Operator, Act, Refused, Nova, Supercode   # noqa: E402

ok = True


def check(label, cond):
    global ok
    print(f'  {"ok  " if cond else "FAIL"}  {label}')
    ok = ok and bool(cond)


print('operator')

# ── 1 · a reversible, inward action needs nobody ───────────────────────────────────────
op = Operator()                                   # no authorizer at all
ran = []
out = op.act(lambda: ran.append('x') or 'done', kind='file', target='/tmp/scratch',
             reversible=True)
check('reversible + inward runs with no authorizer', out == 'done' and ran == ['x'])

# ── 2 · default is DENY, and the callable never runs ───────────────────────────────────
op = Operator()
fired = []
try:
    op.act(lambda: fired.append('BOOM'), kind='file', target='/etc/passwd')
    check('irreversible with no authorizer is refused', False)
except Refused:
    check('irreversible with no authorizer is refused', True)
check('  and the action never ran', fired == [])

# ── 3 · a refusing authorizer refuses, and the callable never runs ─────────────────────
op = Operator(authorize=lambda a: False)
fired = []
try:
    op.act(lambda: fired.append('BOOM'), kind='deploy', target='production')
    check('authorizer saying no refuses', False)
except Refused:
    check('authorizer saying no refuses', True)
check('  and the action never ran', fired == [])

# ── 4 · an approving authorizer lets it through ────────────────────────────────────────
op = Operator(authorize=lambda a: True)
out = op.act(lambda: 'shipped', kind='deploy', target='production')
check('authorizer saying yes allows it', out == 'shipped')

# ── 5 · APPROVAL DOES NOT CACHE — the one that matters most ────────────────────────────
# A loop deleting a thousand files must ask a thousand times. Caching by fingerprint would
# let one approval cover every repeat the person never saw.
asked = []
op = Operator(authorize=lambda a: (asked.append(str(a)), True)[1])
for _ in range(3):
    op.act(lambda: None, kind='file', target='/tmp/same-exact-target')
check('identical repeats each ask again (no caching)', len(asked) == 3)

# ── 6 · outward alone triggers, even when reversible ───────────────────────────────────
op = Operator()
fired = []
try:
    op.act(lambda: fired.append('sent'), kind='send', target='degibug@icloud.com',
           reversible=True, outward=True)
    check('outward asks even when reversible', False)
except Refused:
    check('outward asks even when reversible', True)
check('  and nothing was sent', fired == [])

# ── 7 · an authorizer that BREAKS is not an authorizer that consented ──────────────────
def explodes(a):
    raise RuntimeError('auth backend down')


op = Operator(authorize=explodes)
fired = []
try:
    op.act(lambda: fired.append('BOOM'), kind='file', target='/x')
    check('a raising authorizer is treated as refusal', False)
except Refused:
    check('a raising authorizer is treated as refusal', True)
check('  and the action never ran', fired == [])

# ── 8 · refusals are recorded, not silent ──────────────────────────────────────────────
op = Operator()
try:
    op.act(lambda: None, kind='file', target='/gone')
except Refused:
    pass
check('the refusal is in the log', len(op.log) == 1 and op.log[0].ok is False)
check('the refusal counts', op.refused == 1 and op.taken == 0 and op.asked == 1)

# ── 9 · undeclared means irreversible ──────────────────────────────────────────────────
op = Operator()
a = Act(kind='shell', target='rm')
check('an undeclared action needs authorization', a.needs_authorization is True)

# ── 10 · it attaches to nova as an ordinary skill ──────────────────────────────────────
n = Nova(goal='drive the machine')
op = Operator(authorize=lambda a: True)
op.attach(n)
check('operator registers on nova', 'operator' in n.skills)
got = n.use('operator', lambda: 'ran', kind='shell', target='ls', reversible=True)
check('nova can drive it', got == 'ran')

# ── 11 · supercode may NOT route operator work ─────────────────────────────────────────
sc = Supercode(goal='keep every agent on its own ground')
op = Operator(authorize=lambda a: True)
try:
    sc.manage({'worker': op.act})
    check('supercode refuses to route an operator', False)
except Refused:
    check('supercode refuses to route an operator', True)

# ── 12 · and the bar does not block ordinary agents ────────────────────────────────────
def plain(ctx):
    return {'goal': 'keep every agent on its own ground', 'progress': 'advancing',
            'distance': 2, 'done': True}


try:
    sc2 = Supercode(goal='keep every agent on its own ground')
    sc2.manage({'a': plain}, max_steps=2)
    check('a normal fleet still runs', True)
except Refused:
    check('a normal fleet still runs', False)

# ── 13 · the patterns actually loaded ──────────────────────────────────────────────────
from laserbrain.operator import classify, _patterns   # noqa: E402

pats = _patterns()
check('patterns loaded from grammar.json', len(pats['deny']) >= 8)

# ── 14 · classify ESCALATES — the caller cannot talk the guard down ────────────────────
DANGER = 'git ' + 'reset --hard origin/main'
rev, outw, why = classify(DANGER, reversible=True)     # caller lies
check('a dangerous command declared reversible comes back irreversible', rev is False)
check('  and says why', 'reset' in why)

WIPE = 'rm ' + '-rf /tmp/build'
rev, _, why = classify(WIPE, reversible=True)
check('recursive delete cannot be declared reversible', rev is False)

# ── 15 · outward is escalated too ──────────────────────────────────────────────────────
rev, outw, why = classify('npm publish', reversible=True, outward=False)
check('publish is escalated to outward', outw is True and rev is False)

# ── 16 · a benign command is left exactly as declared ──────────────────────────────────
rev, outw, why = classify('ls -la', reversible=True, outward=False)
check('a benign command keeps the declaration', rev is True and outw is False and why == '')

# ── 17 · THE BYPASS ATTEMPT: reversible=True on a dangerous shell command ──────────────
op = Operator()                                        # no authorizer → default deny
fired = []
try:
    op.shell(DANGER, reversible=True, run=lambda c: fired.append(c))
    check('shell() refuses a dangerous command declared reversible', False)
except Refused:
    check('shell() refuses a dangerous command declared reversible', True)
check('  and the command never ran', fired == [])

# ── 18 · a benign command runs through the injected runner ─────────────────────────────
op = Operator()
seen = []
out = op.shell('ls -la', reversible=True, run=lambda c: seen.append(c) or 'listing')
check('shell() runs a benign command with no authorizer', out == 'listing' and seen == ['ls -la'])

# ── 19 · the carve-out does not downgrade ──────────────────────────────────────────────
CARVE = 'wrangler deploy workers/laserbrain-mcp-remote'
rev, outw, why = classify(CARVE, reversible=True)
check('an authorized carve-out still asks', rev is False and 'carve-out' in why)

# ── 20 · write: reversibility is read off the disk, not declared ───────────────────────
import os          # noqa: E402
import tempfile    # noqa: E402

with tempfile.TemporaryDirectory() as d:
    fresh = os.path.join(d, 'new.txt')
    op = Operator()                                   # no authorizer at all
    op.write(fresh, 'hello')
    check('creating a new file needs no authorizer', open(fresh).read() == 'hello')

    # Same call, same arguments, same operator — different answer, because the disk changed.
    try:
        op.write(fresh, 'clobbered')
        check('overwriting an existing file is refused', False)
    except Refused:
        check('overwriting an existing file is refused', True)
    check('  and the original content survives', open(fresh).read() == 'hello')

    op2 = Operator(authorize=lambda a: True)
    op2.write(fresh, 'approved')
    check('an approved overwrite goes through', open(fresh).read() == 'approved')

# ── 21 · delete: never reversible, and not recursive ───────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, 'x.txt')
    open(f, 'w').write('data')
    op = Operator()
    try:
        op.delete(f)
        check('deleting a file is refused with no authorizer', False)
    except Refused:
        check('deleting a file is refused with no authorizer', True)
    check('  and the file is still there', os.path.exists(f))

    sub = os.path.join(d, 'tree')
    os.mkdir(sub)
    try:
        Operator(authorize=lambda a: True).delete(sub)
        check('a directory is refused outright, even when authorized', False)
    except IsADirectoryError:
        check('a directory is refused outright, even when authorized', True)
    check('  and the directory survives', os.path.isdir(sub))

    Operator(authorize=lambda a: True).delete(f)
    check('an authorized file delete goes through', not os.path.exists(f))

# ── 22 · http: reads pass, writes ask ──────────────────────────────────────────────────
op = Operator()                                        # no authorizer
seen = []
got = op.http('GET', 'https://example.invalid/x', run=lambda: seen.append('GET') or 'body')
check('a GET needs no authorizer', got == 'body' and seen == ['GET'])

for verb in ('POST', 'PUT', 'PATCH', 'DELETE'):
    fired = []
    try:
        op.http(verb, 'https://example.invalid/x', run=lambda: fired.append(verb))
        check(f'{verb} is refused with no authorizer', False)
    except Refused:
        check(f'{verb} is refused with no authorizer', True)
    if fired:
        check(f'  {verb} never left the machine', False)

# ── 23 · every one of those is in the log ──────────────────────────────────────────────
check('refusals and actions all land in the log', len(op.log) == 5 and op.taken == 1)

print()
raise SystemExit(0 if ok else 1)
