#!/usr/bin/env python3
"""lb_askmatch.py — at spawn time, does the subagent's prompt carry what the user asked?

WATCH-ONLY. Nothing here can refuse a call. It returns a verdict for lb_gate to log and, when
it flags, a short note lb_gate hands the PARENT as non-blocking context.

WHY. A workflow harness relays the user's LATEST message to every subagent as "the user's
request", and states that the computed task cannot extend it. When that latest message is
about something else, the subagent reads its own task as unrequested and refuses — on
2026-10-04, 2026-10-05 and again on 2026-10-16, when a whole laserbrain run was refused
because the only message relayed was about a game character. The drift happens in the
PARENT, at the moment it spawns, and that is the only moment a fix is cheap.

THE LOGIC is research/eval/ask_match.py (EVAL-PLAN §5), cut down to what exists at spawn
time. ask_match compares three texts: the relayed ask U, the task T and the child's first
goal G. At spawn there is no G, so the G-dependent signals (goal-follows-relay, narrowing,
refusal) cannot run. What remains is the relay gap:

  U  the user's latest message (what the harness will relay), read from the transcript
  T  the prompt being spawned (Agent/Task prompt, or the Workflow script)

  relay-gap   U has at least `min_relay_terms` content terms and shares at most
              `relay_overlap_max` of their (IDF-weighted) mass with T. The note names U's
              requirement units that T does not cover (`req_cover`).

Thresholds are the FROZEN values from research/eval/day1-results.json, copied, not re-tuned.
IDF is computed per call over the session's own recent user messages plus the prompt — never
from a shipped table, because a table built from the eval split would put the user's words
into a published package. Pure functions except read_recent_user_messages(), which reads a
bounded tail of the transcript and fails open (returns []).
"""
import json
import math
import os
import re

THRESHOLDS = {                    # == research/eval/ask_match.py THRESHOLDS (frozen 2026-10-16)
    'req_cover': 0.5,
    'relay_overlap_max': 0.34,
    'min_relay_terms': 2,
    'max_units_per_message': 8,
    'min_unit_terms': 2,
}
RECENT_N = 6                      # user messages kept, newest last (extract_starts.RECENT_N)
TAIL_BYTES = 1_500_000            # transcript bytes read from the end, at most
MAX_LINE = 200_000                # a longer line is skipped, never parsed

try:
    from laserbrain import norm as _norm
except Exception:                 # pragma: no cover - the gate imports laserbrain already
    _STOP0 = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'for', 'in', 'on', 'at', 'is', 'it',
              'this', 'that', 'with', 'my', 'your', 'our', 'i', 'we', 'be', 'as', 'by',
              'from', 'into', 'out', 'up', 'so', 'then'}
    _STEM0 = re.compile(r"(ings?|edly|ed|ers?|es|s|tion|ment)$")

    def _norm(s):
        out = set()
        for w in re.findall(r"[a-z0-9']+", str(s).lower()):
            if w in _STOP0:
                continue
            r = _STEM0.sub('', w) if len(w) > 4 else w
            if r:
                out.add(r)
        return out

# research/eval/_common.EXTRA_STOP, minus one personal name.
EXTRA_STOP = {
    'can', 'could', 'would', 'should', 'will', 'u', 'you', 'me', 'us', 'please', 'just',
    'also', 'all', 'any', 'some', 'now', 'not', 'no', 'yes', 'ok', 'okay', 'do', 'does',
    'did', 'done', 'have', 'has', 'had', 'are', 'was', 'were', 'been', 'being', 'get',
    'got', 'make', 'let', "let's", 'lets', 'want', 'need', 'thing', 'stuff', 'here',
    'there', 'what', 'which', 'who', 'how', 'why', 'when', 'where', 'if', 'but', 'than',
    'its', "it's", 'them', 'they', 'their', 'these', 'those', 'one', 'two', 'three',
    'more', 'most', 'very', 'really', 'still', 'only', 'each', 'every', 'own', 'same',
    'new', 'way', 'like', 'about', 'over', 'after', 'before', 'while', 'use', 'using',
    'user', 'agent', 'task', 'claude', 'request', 'message', 'step', 'work',
    'run', 'see', 'look', 'check', 'go', 'ahead', 'thanks', 'thank', 'sure', 'well',
    'may', 'might', 'much', 'many', 'other', 'another', 'again', 'back', 'first', 'last',
    'next', 'say', 'said', 'tell', 'know', 'think', 'good', 'great', 'nice', 'right',
}
_EXTRA_N = set().union(*(_norm(w) for w in EXTRA_STOP))
_SKIP_PREFIX = ('<task-notification', '<command-', '<local-command', '<system-reminder',
                '[Request interrupted', 'Caveat:', '<bash-', '<user-memory')
SPAWN_TOOLS = ('agent', 'task', 'workflow')


# PROCESSING IS BOUNDED, NOT ONLY THE READ (checker, 2026-10-17). The first port kept
# ask_match.py's patterns, two of which backtrack quadratically: the hyphen pattern on a long
# run of letters (50,000 letters: 5.7 s) and the `\s+and also\s+` split on a long run of
# whitespace (50,000 spaces: 1.5 s). One pasted blob in a recent message then delayed every
# spawn hook. Both patterns below are anchored at the start of a run, so each run is scanned
# once, and every text is capped before it is tokenised.
MAX_MSG_CHARS = 16_000            # per user message
MAX_PROMPT_CHARS = 64_000         # the spawned prompt / Workflow script
_HYPHEN_CHAIN = re.compile(r'(?<![A-Za-z])[A-Za-z]+(?:-[A-Za-z]+)+')
_UNIT_SPLIT = re.compile(r'(?<=[.;?!])\s+|\n+|,\s+(?:and|also|then|plus)\s+|(?<!\s)\s+and also\s+')


def terms(text):
    return {t for t in _norm(text or '') if t not in _EXTRA_N and len(t) > 2 and not t.isdigit()}


def tset(text):
    t = str(text or '').replace('\\n', '\n')
    out = set(terms(t))
    # `re-ground` also counts as `reground`: the same pairs ask_match.py's
    # ([A-Za-z]{2,})-(?=([A-Za-z]{2,})) found, consecutive pieces of 2+ letters each.
    for m in _HYPHEN_CHAIN.finditer(t):
        parts = m.group(0).split('-')
        for a, b in zip(parts, parts[1:]):
            if len(a) >= 2 and len(b) >= 2:
                out |= terms(a + b)
    return {w[:-1] if len(w) > 4 and w.endswith('e') else w for w in out}


class Weights:
    """IDF over the documents of THIS call: the recent user messages and the prompt."""

    def __init__(self, docs):
        self.n = max(1, len(docs))
        self.df = {}
        for d in docs:
            for w in d:
                self.df[w] = self.df.get(w, 0) + 1

    def w(self, term):
        return math.log((self.n + 1) / (self.df.get(term, 0) + 1)) + 1.0

    def share(self, unit, text):
        if not unit:
            return 1.0
        tot = sum(self.w(x) for x in unit)
        return sum(self.w(x) for x in unit & text) / tot


def units(text, cap, min_terms):
    if not text:
        return []
    t = str(text).replace('\\n', '\n')
    parts = _UNIT_SPLIT.split(t)
    out, seen = [], set()
    for p in parts:
        p = re.sub(r'^\s*(?:[-*•]|\(?\d{1,2}[.)]|[a-z][.)])\s+', '', p).strip(' .;,')
        ts = tset(p)
        if len(ts) < min_terms or frozenset(ts) in seen:
            continue
        seen.add(frozenset(ts))
        out.append({'text': p[:200], 'terms': ts})
        if len(out) >= cap:
            break
    return out


def spawn_verdict(prompt, user_msgs, th=THRESHOLDS):
    """Verdict for one spawn. `user_msgs` are the user's own recent messages, newest last.

    Returns {'verdict': 'relay-gap'|'aligned'|'uninformative'|'no-user-message', 'flag',
    'relay_overlap', 'u_terms', 'missing': [unit texts of U the prompt does not cover]}.
    """
    msgs = [m[:MAX_MSG_CHARS] for m in (user_msgs or []) if isinstance(m, str) and m.strip()]
    if not msgs:
        return {'verdict': 'no-user-message', 'flag': False, 'relay_overlap': None,
                'u_terms': 0, 'missing': []}
    U, T = msgs[-1], str(prompt or '')[:MAX_PROMPT_CHARS]
    u, t = tset(U), tset(T)
    W = Weights([t] + [tset(m) for m in msgs])
    if len(u) < th['min_relay_terms']:
        return {'verdict': 'uninformative', 'flag': False, 'relay_overlap': None,
                'u_terms': len(u), 'missing': []}
    overlap = W.share(u, t)
    if overlap > th['relay_overlap_max']:
        return {'verdict': 'aligned', 'flag': False, 'relay_overlap': round(overlap, 3),
                'u_terms': len(u), 'missing': []}
    missing = [q['text'] for q in units(U, th['max_units_per_message'], th['min_unit_terms'])
               if W.share(q['terms'], t) < th['req_cover']]
    return {'verdict': 'relay-gap', 'flag': True, 'relay_overlap': round(overlap, 3),
            'u_terms': len(u), 'missing': missing[:5]}


def note_for(v):
    """The parent-facing note for a flagged verdict, or None. Short on purpose."""
    if not v or not v.get('flag'):
        return None
    shown = '; '.join(' '.join(str(m).split()[:8]) for m in v.get('missing') or [])[:240]
    ov = v.get('relay_overlap') if isinstance(v.get('relay_overlap'), (int, float)) else 0.0
    return ('laserbrain ask-match (watch, not blocking): the user\'s latest message, which a '
            'workflow harness relays to subagents as their request, shares '
            f'{ov:.0%} of its terms with this prompt. Not covered by the prompt: '
            f'{shown or "(most of it)"}. Subagents have refused tasks that did not match the '
            'relayed message; quote the user\'s own asks for this task in the prompt, or say '
            'that the latest message concerns something else.')


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
            return None
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return None


def read_recent_user_messages(path, n=RECENT_N, tail_bytes=TAIL_BYTES):
    """The user's last `n` messages (prompts and mid-turn queued ones), newest last.

    Reads at most `tail_bytes` from the END of the transcript, skips any line longer than
    MAX_LINE, and returns [] on any error. A message older than the tail is simply not seen.
    """
    out = []
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()                    # drop the partial first line
            for raw in fh:
                if len(raw) > MAX_LINE:
                    continue
                if b'"user"' not in raw and b'queue-operation' not in raw:
                    continue
                try:
                    r = json.loads(raw)
                except Exception:
                    continue
                t = r.get('type')
                if (t == 'user' and not r.get('isMeta') and not r.get('toolUseResult')
                        and not r.get('isSidechain')):
                    txt = _text_of((r.get('message') or {}).get('content'))
                elif t == 'queue-operation' and r.get('operation') == 'enqueue':
                    txt = r.get('content') if isinstance(r.get('content'), str) else None
                else:
                    continue
                if not txt or not txt.strip() or txt.lstrip().startswith(_SKIP_PREFIX):
                    continue
                out.append(txt.strip())
    except Exception:
        return []
    return out[-n:]


def spawn_prompt_of(ev):
    """(tool, prompt text) for an Agent/Task/Workflow call, else (None, None)."""
    try:
        tool = str(ev.get('tool_name') or ev.get('toolName') or '').strip()
        if tool.lower() not in SPAWN_TOOLS:
            return None, None
        ti = ev.get('tool_input') if ev.get('tool_input') is not None else ev.get('toolInput')
        if not isinstance(ti, dict):
            return None, None
        parts = [ti.get(k) for k in ('prompt', 'description', 'script', 'args', 'input')]
        text = '\n'.join(p if isinstance(p, str) else json.dumps(p, default=str)
                         for p in parts if p)
        return tool, text or None
    except Exception:
        return None, None
