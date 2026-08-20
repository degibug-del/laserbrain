"""
laserbrain command line — the smart recursion harness, in your terminal.

    laserbrain demo                      watch an agent wander off-goal and get returned
    laserbrain check --goal "…" [--progress advancing] [--distance 6] [--against "…"]
    laserbrain verify run.json           verify an exported audit chain (tamper-evident)
    laserbrain store [list|find|vend] [--kind workflow|team]   prefabricated methods
    laserbrain key                       get a free key for the hosted half
    laserbrain mcp                       run as an MCP server — offline, no key
    laserbrain version

Dep-free (stdlib only), like the rest of the package.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Sequence

from . import Harness, Verdict, verify_audit, ground_score, __version__

DIM, BOLD, GOLD, RED, GREEN, RESET = '\033[2m', '\033[1m', '\033[33m', '\033[31m', '\033[32m', '\033[0m'


def _c(s: str, code: str) -> str:
    """Colour only when stdout is a TTY — pipes and logs stay clean."""
    return f"{code}{s}{RESET}" if sys.stdout.isatty() else s


def _demo() -> int:
    hz = Harness()
    print()
    print("  " + _c("laserbrain", BOLD) + " — the agent wanders off its goal; the harness catches it and returns it.")
    print()
    print(f"    {'the agent is working on…':38} {'dist':>4} {'Φ':>6}  verdict")
    print("    " + _c("─" * 70, DIM))
    script = [
        ("build the JSON parser", 6),
        ("build the JSON parser", 4),
        ("also add a caching layer and logging", 4),   # ← drifts to a different goal
        ("build the JSON parser", 2),                   # ← returned to ground
        ("build the JSON parser", 0),
    ]
    for goal, dist in script:
        v = hz.check(goal, "advancing", dist)
        if dist == 0:
            tag = _c("✓ done", GREEN)
        elif v.drifting:
            tag = _c("⚑ DRIFT → return", RED)
        elif v.reason == "grounded":
            tag = _c("· grounded", DIM)
        else:
            tag = _c("· on track", DIM)
        print(f"    {goal[:38]:38} {dist:>4} {v.phi:>6.2f}  {v.reason:12} {tag}")
        if v.drifting:
            print(f"    {'':38} {'':>4} {'':>6}  {_c('↩ ' + v.advice, GOLD)}")
    print()
    print("  It left its goal for a single step. Watching only itself, it wouldn't have noticed —")
    print("  laserbrain saw it against the fixed reference and returned it, so it " + _c("finished", GREEN) + ".")
    print()
    print("  " + _c("from laserbrain import Harness", GOLD) + "   →   Harness().check(goal=…, progress=…, distance=…)")
    print()
    return 0


def _check(args: argparse.Namespace) -> int:
    hz = Harness()
    if args.against:
        hz.check(args.against, "advancing", 5)          # set ground to a prior goal, to reveal drift
    v = hz.check(args.goal, args.progress, args.distance)
    print(_verdict_line(v))
    return 1 if v.drifting else 0                        # scriptable: nonzero exit on drift


def _verdict_line(v: Verdict) -> str:
    if v.drifting:
        head = _c("⚑ drifting", RED)
    elif v.reason == "grounded":
        head = _c("✓ grounded", GREEN)
    else:
        head = _c("· on track", DIM)
    return f"[{head}] {v.reason}  Φ={v.phi:.2f}  ground={ground_score(v.phi):.2f}\n  {_c(v.advice, DIM)}"


def _key(args: argparse.Namespace) -> int:
    """Get a key, and say plainly what it does and does not buy.

    WHY THIS COMMAND EXISTS. The README has always told readers "add a key and it also
    mirrors to the API", and until 0.24.0 the package offered no way to get one. The
    endpoint has been public and instant the whole time — POST /v1/keys, no auth, no
    form — so the only thing between a reader and the hosted half was knowing that.
    On 2026-07-29 the numbers on that gap were 6,000 downloads and twelve keys ever
    issued, two of them from testing.

    It prints what the API says the tier allows rather than what the docs claim, because
    those are different sentences that can drift apart, and only one of them is enforced.
    """
    from .services import KEY_PATH, ServiceUnavailable, new_key, save_key, stored_key

    existing = stored_key()
    if existing and not args.new:
        src = 'LASERBRAIN_KEY' if os.environ.get('LASERBRAIN_KEY') else str(KEY_PATH)
        print()
        print("  " + _c("you already have a key", GREEN) + f"   {existing[:11]}…")
        print(f"  {_c('from', DIM)} {src}")
        print()
        print(f"  {_c('laserbrain key --new', GOLD)} gets another one. It will not migrate")
        print("  anything to the new key — a key is the identity, so a second key is a")
        print("  second identity with its own history.")
        print()
        return 0

    try:
        got = new_key()
    except ServiceUnavailable as e:
        print()
        print("  " + _c("could not get a key", RED) + f" — {e}")
        print()
        print("  Nothing is broken locally. The check is a pure function and needs no key:")
        print("  " + _c("Harness().check(...)", GOLD) + " keeps working offline.")
        print()
        return 2

    key = got.get('key')
    if not key:
        print("\n  " + _c("the API answered without a key", RED) + f" — {got}\n")
        return 2

    path = save_key(key)
    tier = got.get('tier') or {}
    print()
    print("  " + _c("key saved", GREEN) + f"   {key}")
    print(f"  {_c('→', DIM)} {path}  {_c('(0600, readable only by you)', DIM)}")
    print()
    print(f"  {_c('this key is on the ' + str(tier.get('name', 'ground')) + ' tier', BOLD)}, and it allows:")
    for label, field, unit in (('reads', 'reads', '/day'), ('writes', 'writes', '/day'),
                               # 'field history' / historyHours is NOT displayed. The
                               # laserfield hub was destroyed 2026-08-03 and the Worker
                               # stopped serving read_field / speak_to_field with it, so a
                               # key buys no field history at any tier. The API still
                               # returns the number; printing it advertises a capability
                               # that does not exist. Remove it from tiers.ts and this
                               # comment goes too.
                               ('drift retained', 'driftDays', ' days')):
        v = tier.get(field)
        if v is not None:
            print(f"    {label:16} {v}{unit}")
    print()
    print("  " + _c("what it adds:", BOLD) + " a place several machines can meet — one view")
    print("  across them, shared history, a ground that outlives the process that set it.")
    print("  " + _c("What stays free:", BOLD) + " the whole instrument. Harness.check is a pure local")
    print("  function, it never calls anything, and the SDK keeps every session on disk.")
    print()
    print("  " + _c("You pay for somewhere to meet, not for the detector.", DIM))
    print("  " + _c("phronesis.world/laserbrain", DIM))
    print()
    return 0


def _verify(args: argparse.Namespace) -> int:
    try:
        with open(args.file) as f:
            chain = json.load(f)
    except Exception as e:
        print(_c(f"could not read {args.file}: {e}", RED))
        return 2
    ok, i = verify_audit(chain)
    if ok:
        print(_c(f"✓ audit intact", GREEN) + f" — {len(chain)} records, hash chain verified end to end")
        return 0
    print(_c(f"✗ audit BROKEN at link {i}", RED) + " — a record was altered, or the file is corrupt")
    return 1


def _store(args: argparse.Namespace) -> int:
    """List, find, or vend a prefabricated workflow or team preset from the store —
    the third surface (Python import and MCP already had it) that could not reach 8
    shipped workflows and 3 recursion-team presets before this command existed."""
    from . import Store
    s = Store()
    action = args.action
    kind_team = args.kind == 'team'

    if action == 'list':
        names = s.list_teams() if kind_team else s.list()
        print()
        print(f"  {_c(('team presets' if kind_team else 'workflows'), BOLD)} — {len(names)}")
        for n in names:
            print(f"    {n}")
        print()
        return 0

    if action == 'find':
        if not args.query:
            print(_c('a task, in words: laserbrain store find "fix a broken build"', RED))
            return 2
        hits = (s.find_team(args.query, top=args.top) if kind_team
                else s.find(args.query, top=args.top))
        print()
        if not hits:
            print(f"  {_c('nothing matched', DIM)} {args.query!r}")
            print()
            return 1
        for h in hits:
            desc = h.get('task') if kind_team else h.get('goal')
            score = _c(f"score {h['score']}", DIM)
            print(f"  {_c(h['name'], GOLD)}  {score}")
            print(f"    {desc}")
        print()
        return 0

    if action == 'vend':
        if not args.query:
            print(_c('a name: laserbrain store vend build-and-ship', RED))
            return 2
        try:
            spec = s.vend_team(args.query) if kind_team else s.vend(args.query)
        except KeyError as e:
            print(_c(str(e), RED))
            return 2
        print()
        print(json.dumps(spec, indent=2))
        print()
        return 0

    print(_c(f"unknown action {action!r} — list, find or vend", RED))
    return 2


def _attention(args: argparse.Namespace) -> int:
    """The check-in schedule, and the agent clock beside it.

    Both are printed, always, and that is the point of the subcommand rather than an
    accident of layout. The human clock is strong and the agent's own clock is flat and
    censored by the gate that produced it; showing only the first would be selling a
    schedule while hiding that the instrument cannot audit its own interval.
    """
    from . import attention as _at
    if args.since is None:
        print()
        print(_at.describe())
        ag = _at.AGENT
        if ag.get('bands'):
            print()
            print('the agent\'s own clock — steps since it last spelled its state')
            print()
            for b in ag['bands']:
                rate = ('unmeasured' if b.get('rate') is None
                        else f"{b['rate'] * 100:5.1f}%")
                print(f"  {b['label']:<14} {b.get('drift', 0):>4}/{b.get('n', 0):<5} {rate}")
            if ag.get('z_between_best_powered') is not None:
                pair = ag.get('best_powered_pair') or ['?', '?']
                print(f"\n  z = {ag['z_between_best_powered']} between {pair[0]} and "
                      f"{pair[1]} (n = {ag.get('best_powered_n')})")
            print(f"\n  {ag.get('censoring', '')}")
        print()
        return 0
    print()
    print(f'  {_at.advise(args.since, args.tolerance)}')
    nxt = _at.next_check_in(args.since, args.tolerance)
    if nxt:
        # Under 90s prints as seconds. Rounding a 30-second wait to "0 min" said the
        # opposite of what it meant — 0 is the value this function returns for "look
        # now" — so a half-minute of headroom read as an alarm.
        print(f'  next look: {nxt:.0f}s' if nxt < 90 else f'  next look: {nxt / 60:.0f} min')
    print()
    return 0


def _coverage(args: argparse.Namespace) -> int:
    """How much of your work the harness actually watched.

    Nobody in this industry can currently answer "is my agent monitoring attached?".
    On 2026-07-24 the honest answer for a full working day was 2% — ten independently
    caught errors, one check. Test coverage became non-negotiable once it was a number
    on a screen; this is the same move, and it is deliberately unflattering.

    READS THE SEGMENTS, since 2026-08-07. It did not, and the number it printed was
    nonsense as a result.

    `reset_task` archives the finished run into `segments[]` and clears the live fields,
    so `checks` holds the CURRENT task and nothing before it. Summing only that reported
    3 steps and 1 check for a session whose true totals were 2,396 checks across 248
    segments — about 0.1% of the work, printed as the whole of it.

    The trap is that the wrong read is the obvious one, and it fails toward ZERO: the
    harness looks unattached when it was attached all day. Worse, the harness ADVISES a
    reset when goal-drift fires, so a drift fire is followed by exactly the operation that
    archives it out of the naive view. Reading top-level only reports 0 fires, which is
    indistinguishable from a quiet instrument.

    This has bitten twice from different causes. lb_coverage.py records the other: a
    substring match on the wrapped MCP response returned False for EVERY fire, costing
    "204 checks across 10 sessions recorded zero fires".
    """
    import glob, os
    paths = sorted(glob.glob(os.path.expanduser(args.dir + '/*.json')))
    if not paths:
        print(f"  no sessions in {args.dir} — is the hook installed?")
        return 2
    rows, tot_steps, tot_checks, tot_inf, tot_catch = [], 0, 0, 0, 0
    for f in paths:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        # The live fields plus every archived segment. A session that was reset ten times
        # has ten segments and a nearly empty top level; counting only the top level counts
        # the last few minutes and calls it the day.
        blocks = [d] + [s for s in (d.get('segments') or []) if isinstance(s, dict)]
        steps = sum(int(b.get('steps', 0) or 0) for b in blocks)
        checks = sum(len(b.get('checks') or []) for b in blocks)
        inf = sum(len(b.get('inferred') or []) for b in blocks)
        catches = sum(len(b.get('catches') or []) for b in blocks)
        tot_steps += steps; tot_checks += checks; tot_inf += inf; tot_catch += catches
        rows.append((os.path.basename(f)[:20], steps, checks, inf, catches,
                     (checks / steps) if steps else 0.0))
    print()
    print(f"    {'session':22}{'steps':>7}{'spelled':>9}{'inferred':>10}{'catches':>9}{'coverage':>10}")
    print("    " + _c("─" * 67, DIM))
    for name, steps, checks, inf, catches, cov in rows:
        bar = GREEN if cov >= 0.5 else (GOLD if cov >= 0.2 else RED)
        print(f"    {name:22}{steps:>7}{checks:>9}{inf:>10}{catches:>9}" + _c(f"{cov:>9.0%}", bar))
    cov = (tot_checks / tot_steps) if tot_steps else 0.0
    print("    " + _c("─" * 67, DIM))
    print(f"    {'all':22}{tot_steps:>7}{tot_checks:>9}{tot_inf:>10}{tot_catch:>9}"
          + _c(f"{cov:>9.0%}", GREEN if cov >= 0.5 else RED))
    print()
    if cov < 0.5:
        print("  " + _c("Below 50%.", BOLD) + " A detection result cannot be computed from this —")
        print("  silence from a harness that was not running says nothing about the harness.")
        print("  Inferred checks are counted separately and do NOT open that gate: they carry")
        print("  no distance, so their \u03a6 is a lower bound and they cannot detect a stall.")
        return 1
    print("  " + _c("Scorable.", BOLD) + " Recall and precision can be computed from these sessions.")
    return 0


def _write(args):
    """Train the chain on what you give it, then write from the ground.

    The chain is trigram-with-backoff and about forty lines — deliberately the dumbest
    thing that works, because the model is not the idea. The decoder is: at every word the
    candidates are scored by model probability AND by displacement from the ground, and the
    one that keeps the text on its goal wins. Untrained, it has nothing to say — so this
    refuses rather than emitting the ground back at you dressed as output.
    """
    import sys
    from .write import Writer

    docs = []
    if args.train:
        for path in args.train:
            try:
                docs.append(open(path.replace("~", __import__("os").path.expanduser("~"))).read())
            except OSError as e:
                print(f"cannot read {path}: {e}", file=sys.stderr)
                return 2
    elif not sys.stdin.isatty():
        docs.append(sys.stdin.read())

    if not any(d.strip() for d in docs):
        print("nothing to train on — pass --train FILE, or pipe text in.\n"
              "  laserbrain write 'the ground state' --train notes.md\n"
              "  cat *.md | laserbrain write 'the ground state'", file=sys.stderr)
        return 2

    w = Writer(seed=args.seed).train(docs)
    out = w.write(args.ground, words=args.words, pull=args.pull)
    print(out)
    # The grounding of what it just wrote, on stderr so a pipe carries only the text.
    print(f"\n  grounding {w.grounding(out, args.ground):.2f}   ground {args.ground!r}",
          file=sys.stderr)
    return 0


def _read(args):
    """Read the shape of a text: circling, connected, loose, or too short to say.

    Connectivity is optional and defaults to 0. The term that catches circling is variety,
    which needs nothing but the text — so a reading without a network call is honest and
    useful, and refusing to give one would not be.
    """
    import json
    import sys
    from .reading import read as _r

    text = args.text
    if text is None:
        if sys.stdin.isatty():
            print("no text — pass it as an argument or pipe it in:\n"
                  "  laserbrain read 'the text to read'\n"
                  "  cat draft.md | laserbrain read", file=sys.stderr)
            return 2
        text = sys.stdin.read()

    r = _r(text, connectivity=args.connectivity)
    if args.json:
        print(json.dumps(r))
        return 0

    print(f"  words         {r['words']}")
    print(f"  variety       {r['variety']:.2f}"
          + ("   the same handful of words is doing the work" if r['circling'] else ""))
    if args.connectivity:
        print(f"  connectivity  {r['connectivity']:.2f}")
    print(f"  shape         {r['shape']}")
    # What the shape supports saying, and nothing beyond it. These are descriptions, not
    # grades: the underlying numbers do not carry quality and must not be reported as if
    # they did. That mistake is the reason the variety term exists at all.
    print("  " + {
        'short': "too short to read a shape from — under 12 words",
        'circling': "circling: coming back to the same terms rather than moving through them",
        'connected': "connected: the terms tie together and vary",
        'loose': "loose: varied, but the terms are not tying to each other",
    }[r['shape']])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="laserbrain", description="the smart recursion harness — in your terminal")
    p.add_argument("-V", "--version", action="version", version=f"laserbrain {__version__}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("demo", help="watch an agent drift off-goal and get returned")
    c = sub.add_parser("check", help="check one spelled state")
    c.add_argument("--goal", required=True, help="the agent's current goal")
    c.add_argument("--progress", default="advancing", choices=["advancing", "stuck", "circling"])
    c.add_argument("--distance", type=int, default=5, help="0–10, distance to done")
    c.add_argument("--against", metavar="GOAL", help="a prior goal to set as ground, to reveal drift")
    v = sub.add_parser("verify", help="verify an exported audit chain")
    v.add_argument("file", help="a JSON file written by Harness.export_audit()")
    cv = sub.add_parser("coverage", help="how much of your work the harness actually watched")
    cv.add_argument("--dir", default="~/.claude/laserbrain",
                    help="where the hook writes sessions (default: ~/.claude/laserbrain)")
    st = sub.add_parser("store", help="prefabricated workflows and team presets — list, find, or vend")
    st.add_argument("action", nargs="?", default="list", choices=["list", "find", "vend"])
    st.add_argument("query", nargs="?", default=None,
                    help="a task in words (find) or a name (vend)")
    st.add_argument("--kind", default="workflow", choices=["workflow", "team"])
    st.add_argument("--top", type=int, default=3, help="find: how many matches (default 3)")
    k = sub.add_parser("key", help="get a free API key, and see what it allows")
    k.add_argument("--new", action="store_true",
                   help="fetch another key even if one is already stored")
    at = sub.add_parser("attention",
                        help="when a person should look, from how long the agent has run")
    at.add_argument("--since", type=float, default=None, metavar="SECONDS",
                    help="seconds since the user last spoke; omit to print the table")
    at.add_argument("--tolerance", type=float, default=0.25,
                    help="drift rate you are willing to accept (default 0.25)")
    sub.add_parser("mcp", help="run as an MCP server on stdin/stdout (offline, no key)")
    # WRITING AND READING, added 2026-08-05. Both already existed in the package and
    # neither could be reached from a terminal: Writer had an MCP tool and no command, and
    # reading had neither — it lived only in the site's TypeScript. A capability with no
    # command line is a capability only a program can use, and the first thing anyone does
    # with an instrument is try it by hand.
    wr = sub.add_parser("write",
                        help="write from a ground state — the harness as a decoder")
    wr.add_argument("ground", help="the ground state to stay near, in words")
    wr.add_argument("--words", type=int, default=60, help="how many words (default 60)")
    wr.add_argument("--pull", type=float, default=1.0,
                    help="how hard the ground pulls against model probability (default 1.0)")
    wr.add_argument("--train", metavar="PATH", action="append", default=None,
                    help="a file to train the chain on; repeatable. omit to read stdin")
    wr.add_argument("--seed", type=int, default=None, help="fix the sampling seed")

    rd = sub.add_parser("read",
                        help="read the shape of a text — is it circling, connected, loose")
    rd.add_argument("text", nargs="?", default=None,
                    help="the text; omit to read stdin")
    rd.add_argument("--connectivity", type=float, default=0.0,
                    help="spectral connectivity 0-1 from the analyzer, if you have it")
    rd.add_argument("--json", action="store_true", help="machine-readable output")

    ins = sub.add_parser("install", help="wire laserbrain into your agent — MCP server + hooks")
    ins.add_argument("--host", default="claude", choices=["claude"])
    ins.add_argument("--dry-run", action="store_true")
    ins.add_argument("--no-hooks", action="store_true",
                     help="MCP server only — the detector without the enforcement")
    sub.add_parser("version", help="print the version")

    args = p.parse_args(argv)
    if args.cmd == "demo":
        return _demo()
    if args.cmd == "write":
        return _write(args)
    if args.cmd == "read":
        return _read(args)
    if args.cmd == "check":
        return _check(args)
    if args.cmd == "coverage":
        args.dir = args.dir.replace("~", __import__("os").path.expanduser("~"))
        return _coverage(args)
    if args.cmd == "attention":
        return _attention(args)
    if args.cmd == "verify":
        return _verify(args)
    if args.cmd == "store":
        return _store(args)
    if args.cmd == "key":
        return _key(args)
    if args.cmd == "mcp":
        # Nothing may print to stdout but JSON-RPC — an MCP client parses it.
        from .mcp import serve
        return serve()
    if args.cmd == "install":
        from .install import main as _install
        argv = ["--host", args.host]
        if args.dry_run: argv.append("--dry-run")
        if args.no_hooks: argv.append("--no-hooks")
        return _install(argv)
    if args.cmd == "version":
        print(f"laserbrain {__version__}")
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
