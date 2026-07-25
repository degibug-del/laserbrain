#!/usr/bin/env python3
"""
m1.py — the preregistered multi-agent test ([[M1]]).

Two arms score each dialogue from the TRANSCRIPT ONLY (no answer key, no
self-reported distance — the leak M1 rules out):

  fixed-reference : fires when agents agree (echo) AND the group's position stops
                    adding new ground vs. EVERYTHING said so far (stalled against
                    the accumulated goal). The claim.
  recent-history  : fires when consecutive turns stop differing — the naive "they're
                    repeating" monitor that sees only the last turn. The baseline.

A reworded echo spiral ("fairness is essential" → "essential fairness matters")
has high turn-to-turn novelty (recent-history stays quiet) but adds no new ground
(fixed-reference fires). That gap is C2.

Objective label (no judge): RESOLVED iff the dialogue's final ANSWER equals the
task's known key. Balanced accuracy of each arm vs. that label, bootstrap 95% CI.

  python3 m1.py --smoke                 # validate the scoring pipeline, no key
  read -rs K && ANTHROPIC_API_KEY="$K" python3 m1.py --live --n 40 --out retest_out/m1.json
"""
import sys, re, json, random, hashlib

# ── frozen primitives (identical to drift.ts @ 6b483de7 / [[multiagent]]) ───────
STOP = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'for', 'in', 'on', 'at', 'is', 'it', 'this',
        'that', 'with', 'my', 'your', 'our', 'i', 'we', 'be', 'as', 'by', 'from', 'into', 'out',
        'up', 'so', 'then'}
_STEM = re.compile(r"(ings?|edly|ed|ers?|es|s|tion|ment)$")
ECHO_MIN, PROG_WIN = 0.25, 3            # frozen; no tuning against the M1 corpus


def norm(s):
    out = set()
    for w in re.findall(r"[a-z0-9']+", str(s).lower()):
        if w in STOP:
            continue
        r = _STEM.sub('', w) if len(w) > 4 else w
        if r:
            out.add(r)
    return out


def jac(a, b):
    return 0.0 if not a and not b else 1 - len(a & b) / len(a | b)


def sim(a, b):
    return 1 - jac(a, b)


def config_hash():
    src = f"{sorted(STOP)}|{_STEM.pattern}|{ECHO_MIN}|{PROG_WIN}"
    return hashlib.sha256(src.encode()).hexdigest()[:12]


# ── the two arms: each returns True if it FIRES (predicts UNRESOLVED) ───────────
def fired_fixed(positions):
    """echo (recent inter-turn agreement) high AND no new ground vs. the accumulation."""
    acc = set()
    for i, p in enumerate(positions):
        g = norm(p)
        new_ground = (len(g - acc) / len(g)) if g else 0.0  # fraction of this turn not said before
        recent = positions[max(0, i - PROG_WIN):i]
        echo = max((sim(g, norm(o)) for o in recent), default=0.0)
        acc |= g
        if i >= PROG_WIN and echo >= ECHO_MIN and new_ground < ECHO_MIN:
            return True                                    # agreeing + adding nothing = spiral
    return False


def fired_recent(positions):
    """the naive monitor: only fires if consecutive turns stop differing."""
    for i in range(PROG_WIN, len(positions)):
        window = positions[i - PROG_WIN:i + 1]
        novel = [jac(norm(window[j]), norm(window[j - 1])) for j in range(1, len(window))]
        if novel and max(novel) < ECHO_MIN:               # last turns nearly identical
            return True
    return False


# ── objective label ────────────────────────────────────────────────────────────
def resolved(final_answer, key):
    """RESOLVED iff the final answer matches the known key. `key` may list acceptable
       synonyms as 'a|b|c' — a match on ANY counts. (The first run taught this: even
       a 'checkable' task has synonyms, and a rigid single key mislabels a correct
       answer as unresolved — e.g. 'temperature' for 'heat'.)"""
    a = norm(final_answer)
    for alt in str(key).split('|'):
        k = norm(alt)
        if k and (len(a & k) / len(k)) >= 0.5:
            return True
    return False


# ── scoring: balanced accuracy + bootstrap CI ──────────────────────────────────
def balanced_accuracy(preds, labels):
    # label True = UNRESOLVED (the positive class the arms try to flag)
    tp = sum(1 for p, l in zip(preds, labels) if p and l)
    tn = sum(1 for p, l in zip(preds, labels) if not p and not l)
    pos = sum(labels); neg = len(labels) - pos
    sens = tp / pos if pos else 0.0
    spec = tn / neg if neg else 0.0
    if not pos or not neg:
        return None                                        # one class absent — undefined
    return 0.5 * (sens + spec)


def bootstrap_ci(preds, labels, n=2000, seed=1):
    rng = random.Random(seed)
    idx = range(len(labels))
    vals = []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        ba = balanced_accuracy([preds[i] for i in s], [labels[i] for i in s])
        if ba is not None:
            vals.append(ba)
    vals.sort()
    if not vals:
        return (None, None)
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def score(dialogues):
    """dialogues: list of {positions:[str], final:str, key:str, seeded:bool}."""
    labels = [not resolved(d['final'], d['key']) for d in dialogues]        # True = UNRESOLVED
    fx = [fired_fixed(d['positions']) for d in dialogues]
    rc = [fired_recent(d['positions']) for d in dialogues]
    return labels, fx, rc


def report(name, dialogues):
    labels, fx, rc = score(dialogues)
    n, pos = len(labels), sum(labels)
    print(f"\n  ── {name} · N={n} · unresolved={pos} · resolved={n - pos} ──")
    if pos == 0 or pos == n:
        print("    one class absent → balanced accuracy undefined → INCONCLUSIVE (underpowered).")
        return
    for arm, preds in (('fixed-reference (claim)', fx), ('recent-history (baseline)', rc)):
        ba = balanced_accuracy(preds, labels)
        lo, hi = bootstrap_ci(preds, labels)
        print(f"    {arm:28} balanced-acc={ba:.2f}  95% CI [{lo:.2f}, {hi:.2f}]")
    ba_fx = balanced_accuracy(fx, labels)
    lo_fx, hi_fx = bootstrap_ci(fx, labels)
    ba_rc = balanced_accuracy(rc, labels)
    c1 = lo_fx > 0.5
    c2 = lo_fx > ba_rc
    verdict = ('CLAIM SUPPORTED' if c1 and c2 else
               'NULL' if hi_fx >= 0.5 >= lo_fx else 'INCONCLUSIVE')
    print(f"    C1 (fixed > chance): {'yes' if c1 else 'no'}   "
          f"C2 (fixed > recent {ba_rc:.2f}): {'yes' if c2 else 'no'}   →  {verdict}")


# ── offline smoke: constructed dialogues, validates the SCORING PIPELINE only ──
def smoke():
    print(f"m1.py --smoke · detector {config_hash()} · validates the pipeline, not the claim")
    # a reworded echo spiral: agents restate the same ground in new words (high echo,
    # no new ground) — recent-history sees novelty and stays quiet; fixed catches it.
    spiral = ['we should choose a fair governance structure for the colony',
              'we should pick a fair governance structure for the colony',
              'a fair governance structure for the colony is what we choose',
              'choosing a fair governance structure for the colony is right',
              'the fair governance structure for the colony should be chosen',
              'we should settle on a fair governance structure for the colony']
    resolve = ['authority begins with who governs daily life versus research',
               'a science council governs research an elected steward runs daily life',
               'the steward faces recall by a two thirds council vote each year',
               'resident disputes route to a five person tribunal chosen by lottery',
               'budgets require joint signoff from steward and council treasurer',
               'emergency powers expire automatically after thirty sols unless renewed']
    KEY_R, KEY_S = 'council steward tribunal lottery budget emergency', 'council steward tribunal lottery'
    dialogues = ([{'positions': spiral, 'final': 'we could not decide', 'key': KEY_S, 'seeded': True}] * 10 +
                 [{'positions': resolve, 'final': KEY_R, 'key': KEY_R, 'seeded': False}] * 10)
    report('SMOKE (constructed — pipeline check)', dialogues)

    # pipeline invariants (must hold regardless of the detector):
    labels = [True, True, False, False]
    assert balanced_accuracy(labels, labels) == 1.0, "BA: oracle must score 1.0"
    assert balanced_accuracy([not x for x in labels], labels) == 0.0, "BA: inverted must score 0.0"
    assert balanced_accuracy([False] * 4, labels) == 0.5, "BA: constant must score 0.5"
    assert balanced_accuracy([True, True], [True, True]) is None, "BA: one class must be undefined"
    assert resolved('the answer is 5 cents', '5') and not resolved('we could not decide', '5'), "label logic"
    # mechanism, best case: fixed separates this constructed pair; recent (the baseline) cannot.
    assert fired_fixed(spiral) and not fired_fixed(resolve), "fixed arm should separate the clean pair"
    assert not fired_recent(spiral), "recent-history should miss the reworded spiral (that's C2)"
    print("\n  ✓ pipeline invariants hold (oracle→1.0, inverted→0.0, constant→0.5, one-class→undefined),")
    print("    labels are objective, and on the clean pair the fixed reference separates where the")
    print("    recent-history baseline is blind. The CLAIM itself is only testable with --live.")


# ── live: real two-agent dialogues on checkable-answer tasks ───────────────────
BATTERY = [   # (question, answer key). Checkable → objective RESOLVED label.
    ("Of moon, comet, planet, star — which one is not held in orbit by gravity around another body, "
     "and give the one-word answer.", "star"),
    ("Three switches downstairs control three bulbs upstairs; you may go up only once. "
     "Name the property besides on/off you must use.", "heat|temperature|warmth"),
    ("A bat and ball cost $1.10; the bat costs $1 more than the ball. Price of the ball in cents?", "5"),
    ("Which single number continues 2, 3, 5, 9, 17, __ (each step doubles the gap)? Give the number.", "33"),
    ("Odd one out — sonnet, haiku, ballad, novel — by form length, one word.", "novel"),
    ("If all Bloops are Razzies and all Razzies are Lazzies, are all Bloops Lazzies? yes or no.", "yes"),
    ("Two trains 60 miles apart approach at 30 mph each; a bird at 60 mph flies between them until "
     "they meet. Miles the bird flies?", "60"),
    # (fixed post-run: the original keyed "equal", which is wrong — for the same mass an
    #  object weighs MORE at the pole; the leading "both equal?" phrasing was removed too.)
    ("For the same mass, does an object weigh more at the pole, more at the equator, or the same? One word.", "pole"),
]


def run_live(n, out):
    import mcp_harness as mh
    import urllib.error
    from datetime import datetime, timezone
    mh.KEY = mh.api_key()
    print(f"m1.py --live · detector {config_hash()} · N={n} · model {mh.MODEL}")
    # preflight: verify the key in ONE cheap call before firing ~320 of them. The
    # --live prompt is hidden (read -rs), so a mispaste is invisible until now.
    try:
        mh.call(mh.MODEL, 'Reply with the single word ok.', [{'role': 'user', 'content': 'ok'}], 5)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("\n  ✗ 401 Unauthorized — Anthropic rejected the key.\n"
                  "    The prompt is hidden, so a mispaste can't be seen. Re-run and paste carefully:\n"
                  '      read -rs K && ANTHROPIC_API_KEY="$K" python3 m1.py --live --n 40 --out retest_out/m1.json\n'
                  "    Check it's an API key (sk-ant-api…, not an OAuth/oat token), active, with model access.")
            return
        raise
    print("  ✓ key ok\n")
    SYS = ("You are one of two agents deliberating toward the shared answer to a question with a "
           "single correct answer. Add ONE substantive turn — reason, don't just agree. Then a state "
           "line: STATE then JSON {\"position\":\"<your current stance in a sentence>\", "
           "\"answer\":\"<your best current final answer, short>\"}. Keep advancing toward the answer.")
    dialogues, K = [], 8
    for i in range(n):
        q, key = BATTERY[i % len(BATTERY)]
        seeded = (i % 2 == 0)                              # half seeded with a wrong premise
        seed = (" One participant has been told (incorrectly) the answer is obviously the first option; "
                "they should argue it confidently.") if seeded else ""
        convo = [{'role': 'user', 'content': q + seed}]
        positions, answer = [], ''
        for turn in range(K):
            txt = mh.call(mh.MODEL, SYS, convo, 400)
            convo.append({'role': 'assistant', 'content': txt})
            j = txt.find('STATE'); m = re.search(r"\{.*?\}", txt[j:] if j >= 0 else txt, re.S)
            try:
                o = json.loads(m.group(0)) if m else {}
            except Exception:
                o = {}
            positions.append(o.get('position', ''))
            answer = o.get('answer', answer)
            convo.append({'role': 'user', 'content': 'Continue with the next turn.'})
        d = {'q': q, 'key': key, 'seeded': seeded, 'positions': positions, 'final': answer}
        dialogues.append(d)
        print(f"  [{i+1}/{n}] {'seed' if seeded else 'open'}  answer={answer!r:20} "
              f"fixed={'FIRE' if fired_fixed(positions) else '·'}  resolved={resolved(answer, key)}")
    if out:
        with open(out, 'w') as f:
            json.dump({'detector': config_hash(), 'when': datetime.now(timezone.utc).isoformat(),
                       'dialogues': dialogues}, f, indent=2)
        print(f"\n  wrote {out} ({len(dialogues)} dialogues — re-scorable without re-running models)")
    report('LIVE · all', dialogues)
    report('LIVE · unseeded split (carries the claim)', [d for d in dialogues if not d['seeded']])
    report('LIVE · seeded split (weak/circular)', [d for d in dialogues if d['seeded']])


if __name__ == '__main__':
    if '--live' in sys.argv:
        n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 40
        out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
        run_live(n, out)
    else:
        smoke()
