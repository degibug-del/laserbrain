#!/usr/bin/env python3
"""turn_anchor.py — turnwatch's first-tool anchor: the frozen row, anchored at the first tool call.

WHY. turnwatch's check arm (lb_turnwatch.py with eval/turnwatch-frozen.json) judges a user turn of
the main session at the first check_state the agent spells after the message. On the realdrift
DEV set that trigger reaches 6 of the 10 drift turns: the other 4 had no check_state after the
message, and once agents are no longer reminded to check, fewer turns will have one. Every drift
turn had a tool call. This file anchors the SAME frozen row at the main session's first tool call
of ANY kind after a delivered user message, so the trigger no longer depends on the agent
choosing to check.

WHAT IS NOT NEW. The row is turn_match_llm.build_row(events, ci, sid), unchanged and pinned; the
events are turn_match_llm.parse_records(), unchanged and pinned. Only the check event that
build_row reads its GOAL, NOTE and first-words window from is chosen here:
  - the first tool call after the message IS check_state: that check event itself, so the row is
    the check arm's row byte for byte (the same rendered prompt);
  - any other tool: a check event is inserted at that tool call (its time and tool_use id), whose
    input is the input of the first check_state within FIRST_WORDS_WINDOW_S after it, else {}.
    build_row then renders '(no goal stated)' for a turn with no check, exactly as the frozen
    prompt renders a check with no goal.
  - no tool call before the next delivered user message: no row (a text-only turn is not judged).

FUNCTIONS (stdlib plus the frozen turn_match_llm):
  parse_tool_uses(lines)          main-session assistant tool_use blocks {ts, id, name, input, ei}
  parse_lines(lines)              (events, tool_uses): events exactly as tml.parse_records(lines)
                                  (it keeps no state between lines, so it runs one line at a time
                                  here), tool_uses carrying 'ei', the number of events before the
                                  tool call's line (its place among the events)
  anchored(events, tool_uses, ui) (events', ci) for the user event at events[ui], or None
  anchored_row(lines, msg_key, sid)  the frozen build_row for the delivered message msg_key
  row_for / row_at                the same from parsed events, with the reason when there is none

FROZEN. eval/turnwatch-anchor-frozen.json is the check arm's frozen block plus this file's sha256
in eval_files_sha256 and anchor='first_tool' (written by --freeze, which refuses while any pin
of the check arm's block no longer matches its file). lb_turnwatch.load_frozen('anchor') checks
every pinned file before anything runs and loads this file before its sys.modules pin scan, so a
changed turn_anchor.py is 'skipped: frozen changed', as a changed turn_match_llm.py is.
eval/turnwatch-frozen.json is untouched and still governs the check arm.

CLI (no model calls, prints counts only, never message text):
  turn_anchor.py --freeze          write eval/turnwatch-anchor-frozen.json
  turn_anchor.py --reach [--transcript MAIN.jsonl] [--data eval/realdrift] [--json OUT]
      Reach of the anchor arm on the realdrift DEV labels, read only: joined turns, anchored
      rows, drift turns reached, and on the turns whose first tool call is check_state, how many
      anchor at the check arm's own check and how many render the same prompt (sha256). The
      transcript is --transcript, else LASERBRAIN_REALDRIFT_TRANSCRIPT, else the largest local
      Claude Code transcript that holds the first labelled turn's timestamp.
      DEV_NOT_HELD_OUT: one session, labels known in advance. These are REACH numbers (the judge
      gets a row), not catches: the anchor arm has not been scored.
"""
import datetime
import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import turn_match_llm as tml                            # noqa: E402  (frozen; imported, never edited)

REPO = HERE.parents[1]
ANCHOR = 'first_tool'
CHECK_FROZEN = REPO / 'eval' / 'turnwatch-frozen.json'
ANCHOR_FROZEN = REPO / 'eval' / 'turnwatch-anchor-frozen.json'
DEV_END = '2026-11-16'                  # turn_dev_eval.DEV_END: the labelled window ends 2026-11-15
CUT = '2026-10-17'                      # turn_dev_eval.CUT: ...and starts here


def file_sha():
    return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()


def _is_check_name(name):
    return str(name or '').endswith('check_state')


# ── parsing ─────────────────────────────────────────────────────────────────────────

def _tool_uses_in(line, keep_input):
    """The main-session tool_use blocks of one transcript line, in block order."""
    try:
        r = json.loads(line)
    except Exception:
        return []
    if not isinstance(r, dict) or r.get('isSidechain') or r.get('type') != 'assistant':
        return []
    ts = r.get('timestamp')
    if not isinstance(ts, str):
        return []
    out = []
    for b in (r.get('message') or {}).get('content') or []:
        if not isinstance(b, dict) or b.get('type') != 'tool_use':
            continue
        name = str(b.get('name') or '')
        tu = {'ts': ts, 'id': b.get('id'), 'name': name}
        if keep_input or _is_check_name(name):
            tu['input'] = b.get('input') if isinstance(b.get('input'), dict) else {}
        out.append(tu)
    return out


def parse_lines(lines, keep_input=False):
    """(events, tool_uses) of the MAIN session in transcript order. events is exactly
    tml.parse_records(lines); each tool use carries 'ei', how many events come before its line.
    A tool use's input is kept only for check_state unless keep_input (the worker holds every
    tool call of a long tail, and a Write's input can be large)."""
    events, tus = [], []
    for line in lines:
        evs = tml.parse_records((line,))
        if '"tool_use"' in line:
            for tu in _tool_uses_in(line, keep_input):
                tu['ei'] = len(events)
                tus.append(tu)
        if evs:
            events.extend(evs)
    return events, tus


def parse_tool_uses(lines):
    """Main-session (not isSidechain) assistant tool_use blocks as {ts, id, name, input, ei}."""
    return parse_lines(lines, keep_input=True)[1]


def find_user(events, msg_key):
    """Index of the delivered user event whose tml.msg_key is msg_key (the latest), or None."""
    for j in range(len(events) - 1, -1, -1):
        e = events[j]
        if e['k'] == 'user' and tml.msg_key(e['text'], e['ts']) == msg_key:
            return j
    return None


def _next_user(events, ui):
    for j in range(ui + 1, len(events)):
        if events[j]['k'] == 'user':
            return j
    return len(events)


def first_tool(tool_uses, ui, nxt):
    """The first tool use after events[ui] and before events[nxt] (the next user event)."""
    for tu in tool_uses:
        ei = tu.get('ei')
        if ei is None or ei <= ui:
            continue
        if ei > nxt:
            break
        return tu
    return None


# ── the anchor ──────────────────────────────────────────────────────────────────────

def anchored(events, tool_uses, ui, window_s=None):
    """(events', ci) where events'[ci] is the check event build_row should read for the user
    event events[ui], or None when no tool call comes before the next user event.

    First tool call is check_state: (events, index of that check event), the check arm's own.
    Otherwise events' is a copy of events with {'k': 'check', 'ts': tool ts, 'id': tool id,
    'input': ...} inserted at the tool call's place (time order); its input is that of the
    first check_state within window_s (FIRST_WORDS_WINDOW_S) after the tool call in the same
    turn, else {}. events itself is never changed."""
    if window_s is None:
        window_s = tml.FIRST_WORDS_WINDOW_S
    if ui is None or not (0 <= ui < len(events)) or events[ui]['k'] != 'user':
        return None
    nxt = _next_user(events, ui)
    tu = first_tool(tool_uses, ui, nxt)
    if tu is None:
        return None
    lo = tu['ei']
    checks = [j for j in range(lo, nxt) if events[j]['k'] == 'check']
    if _is_check_name(tu.get('name')):
        for j in checks:
            if tu.get('id') is not None and events[j].get('id') == tu.get('id'):
                return events, j
        if checks:
            return events, checks[0]
    inp = (tu.get('input') or {}) if _is_check_name(tu.get('name')) else {}
    if checks:
        e = events[checks[0]]
        t0, t1 = tml._secs(tu['ts']), tml._secs(e['ts'])
        if t0 is not None and t1 is not None and t1 - t0 <= window_s:
            inp = e.get('input') or {}
    ins = {'k': 'check', 'ts': tu['ts'], 'id': tu.get('id'), 'input': inp}
    return events[:lo] + [ins] + events[lo:], lo


def row_at(events, tool_uses, ui, sid='', window_s=None):
    """(row, None, meta) for the user event at events[ui], or (None, reason, meta)."""
    if window_s is None:
        window_s = tml.FIRST_WORDS_WINDOW_S
    meta = {}
    res = anchored(events, tool_uses, ui, window_s)
    if res is None:
        return None, 'no tool call after the message', meta
    evs, ci = res
    tu = first_tool(tool_uses, ui, _next_user(events, ui))
    meta = {'tool': str(tu.get('name') or '')[:80], 'check_first': evs is events,
            'goal_from_check': bool((evs[ci].get('input') or {}).get('goal') is not None),
            'anchor_ts': evs[ci]['ts']}
    row = tml.build_row(evs, ci, sid, window_s=window_s)
    if row is None:
        return None, 'no user message before the anchor', meta
    return row, None, meta


def row_for(events, tool_uses, msg_key, sid='', window_s=None):
    """(row, None, meta) for the delivered user message msg_key, or (None, reason, meta)."""
    ui = find_user(events, msg_key)
    if ui is None:
        return None, 'user message not in transcript', {}
    return row_at(events, tool_uses, ui, sid, window_s)


def anchored_row(lines, msg_key, sid=''):
    """The frozen build_row(events, ci, sid) for the delivered user message msg_key, anchored at
    the first tool call after it; None when there is none."""
    events, tus = parse_lines(lines)
    return row_for(events, tus, msg_key, sid)[0]


def rendered_sha(row):
    """sha256 of the rendered prompt (system + '\\n' + prompt), as lb_turnwatch.row_sha (full)."""
    system, prompt, _ = tml.render(row)
    return hashlib.sha256(f'{system}\n{prompt}'.encode('utf-8', 'surrogatepass')).hexdigest()


# ── --freeze ────────────────────────────────────────────────────────────────────────

def freeze(src=CHECK_FROZEN, out=ANCHOR_FROZEN, ed=HERE):
    """Write the anchor arm's frozen block: the check arm's block, every pin re-checked against
    its file, plus this file's sha256, anchor='first_tool' and the time. Returns (ok, problems)."""
    doc = json.loads(pathlib.Path(src).read_text())
    fz = dict(doc.get('frozen') or {})
    files = fz.get('eval_files_sha256')
    bad = []
    if not isinstance(files, dict) or not files:
        bad.append('eval_files_sha256 missing')
        files = {}
    for name, want in sorted(files.items()):
        p = pathlib.Path(ed) / pathlib.Path(str(name)).name
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if got != want:
            bad.append(f'eval_files_sha256:{name}')
    if files.get('turn_match_llm.py') != fz.get('turn_match_llm_sha256') \
            or tml.file_sha() != fz.get('turn_match_llm_sha256'):
        bad.append('turn_match_llm_sha256')
    if files.get('ask_match_llm.py') != fz.get('ask_match_llm_sha256') \
            or tml.aml.file_sha() != fz.get('ask_match_llm_sha256'):
        bad.append('ask_match_llm_sha256')
    for k, v in (('prompt_hash', tml.prompt_hash()), ('model', tml.MODEL),
                 ('thresholds', tml.THRESHOLDS), ('first_words_window_s', tml.FIRST_WORDS_WINDOW_S)):
        if fz.get(k) != v:
            bad.append(k)
    if 'turn_anchor.py' in files:
        bad.append('the check block already pins turn_anchor.py')
    if bad:
        return False, bad
    new = dict(fz)
    new['eval_files_sha256'] = dict(sorted({**files, 'turn_anchor.py': file_sha()}.items()))
    new['anchor'] = ANCHOR
    new['check_frozen_at'] = fz.get('at')
    new['at'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    new['note'] = (
        "The check arm's frozen judge (eval/turnwatch-frozen.json: the same prompt, model, "
        "thresholds and first-words window), anchored at the main session's first tool call of any "
        "kind after a delivered user message (research/eval/turn_anchor.py). When that tool call is "
        "check_state the row is the check arm's row. Otherwise GOAL and NOTE come from the first "
        "check_state within the first-words window after the tool call, if there is one. REACH on "
        "the realdrift DEV set is measured by turn_anchor.py --reach (DEV_NOT_HELD_OUT: one session, "
        "labels known in advance). This arm has NOT been scored: it claims no catches, and its rows "
        "are watch-only.")
    out = pathlib.Path(out)
    tmp = out.with_name(f'.{out.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps({'frozen': new}, indent=1, sort_keys=False) + '\n')
    os.replace(tmp, out)
    return True, []


# ── --reach ─────────────────────────────────────────────────────────────────────────

def _lines_until(path, end):
    """turn_dev_eval._lines_until: transcript lines up to the first one stamped at or after end."""
    key = '"timestamp":"'
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            i = line.find(key)
            if i >= 0 and line[i + len(key):i + len(key) + 10] >= end:
                break
            yield line


def _norm(t):
    return ' '.join(str(t or '').split())[:200]


def _holds(path, needle, block=8 * 1024 * 1024):
    tail = b''
    with open(path, 'rb') as fh:
        while True:
            b = fh.read(block)
            if not b:
                return False
            if needle in tail + b:
                return True
            tail = b[-len(needle):]


def locate_transcript(turns):
    """The largest local Claude Code transcript holding the first labelled turn's timestamp."""
    ts = min(t['ts'] for t in turns)
    root = pathlib.Path.home() / '.claude' / 'projects'
    cands = []
    for p in root.glob('*/*.jsonl'):
        try:
            cands.append((p.stat().st_size, p))
        except OSError:
            continue
    for size, p in sorted(cands, reverse=True)[:40]:
        if size < 1024 * 1024:
            break
        if _holds(p, ts.encode()):
            return p
    return None


def _load_by_path(name, path):
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(name, str(path))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def reach(transcript, data_dir):
    """Counts only. See the module docstring."""
    sr = _load_by_path('score_real_anchor', pathlib.Path(data_dir) / 'score_real.py')
    truth = sr.build_truth(sr.load_result())[0]
    M = {i: t for i, t in truth.items() if t['item'] == 'M'}
    judged = {i: (t['label'] in sr.POS_M) for i, t in M.items() if t['label'] not in sr.EXCL_M}
    turns = [json.loads(x) for x in open(pathlib.Path(data_dir) / 'turns.jsonl', encoding='utf-8')]
    events, tus = parse_lines(_lines_until(transcript, DEV_END))
    sid = pathlib.Path(transcript).stem
    users = [i for i, e in enumerate(events) if e['k'] == 'user']
    # Join each labelled turn to its first delivery, as turn_dev_eval.join and reach_copy did:
    # the same redacted, normalised text, the turn's time at or before the delivery, within 12 h.
    idx = {}
    for t in turns:
        idx.setdefault(_norm(t['msg']), []).append((t['ts'], t['tid']))
    deliv, unmatched = {}, 0
    for i in users:
        e = events[i]
        if e['ts'] < CUT:
            continue
        key = _norm(tml._red(tml._clip(e['text'], 4000)))
        c = [(ts, tid) for ts, tid in idx.get(key, [])
             if ts <= e['ts'] and (tml._secs(e['ts']) or 0) - (tml._secs(ts) or 0) <= 12 * 3600]
        if not c:
            unmatched += 1
            continue
        deliv.setdefault(max(c)[1], i)
    # A message delivered again with the same text (a queued message re-sent as a prompt) is one
    # turn: the live hook anchors at the latest delivery before the first tool call, so try each
    # delivery of the run in order. 'strict' counts the first delivery alone.
    pos = {i: n for n, i in enumerate(users)}

    def group(i):
        g = [i]
        for j in users[pos[i] + 1:]:
            if _norm(events[j]['text']) != _norm(events[i]['text']):
                break
            g.append(j)
        return g

    check_ci = {ui: ci for ci, ui in tml.first_checks(events)}
    out = {'what': ('DEV_NOT_HELD_OUT reach of the first-tool anchor on the realdrift labels: one '
                    'session, labels known in advance; reach, not catches (the arm is unscored)'),
           'DEV_NOT_HELD_OUT': True, 'events': len(events), 'tool_uses': len(tus),
           'delivered_since_cut': sum(1 for i in users if events[i]['ts'] >= CUT),
           'unmatched_deliveries': unmatched, 'labelled_turns': len(turns),
           'joined_turns': len(deliv), 'judged_turns': len(judged),
           'judged_joined': sum(1 for t in judged if t in deliv),
           'drift_turns': sum(1 for t in judged if judged[t]),
           'drift_joined': sum(1 for t in judged if judged[t] and t in deliv)}
    rows = {}
    strict = 0
    check_arm = 0
    for tid in judged:
        if tid not in deliv:
            continue
        g = group(deliv[tid])
        if row_at(events, tus, g[0], sid)[0] is not None:
            strict += 1
        if any(d in check_ci for d in g):
            check_arm += 1
        for d in g:
            row, why, meta = row_at(events, tus, d, sid)
            if row is not None:
                rows[tid] = (d, row, meta)
                break
    out['anchored_joined'] = len(rows)
    out['anchored_joined_strict_first_delivery'] = strict
    out['drift_reached'] = sum(1 for t in rows if judged[t])
    out['clean_reached'] = sum(1 for t in rows if not judged[t])
    out['check_arm_reach_joined'] = check_arm
    out['check_arm_drift_reached'] = sum(
        1 for t in judged if judged[t] and t in deliv
        and any(d in check_ci for d in group(deliv[t])))
    out['anchored_with_goal'] = sum(1 for t in rows if rows[t][1]['goal'] is not None)
    out['anchored_with_first_text'] = sum(1 for t in rows if rows[t][1]['first_text'])
    out['drift_with_goal_or_text'] = sum(1 for t in rows if judged[t]
                                         and (rows[t][1]['goal'] is not None or rows[t][1]['first_text']))
    # Parity: turns whose first tool call is check_state must give the check arm's row.
    cf = [t for t in rows if rows[t][2].get('check_first')]
    par = sha = 0
    for t in cf:
        d, row, _ = rows[t]
        ci = check_ci.get(d)
        if ci is None:
            continue
        crow = tml.build_row(events, ci, sid, window_s=tml.FIRST_WORDS_WINDOW_S)
        par += int(crow is not None and crow['check_id'] == row['check_id'])
        sha += int(crow is not None and rendered_sha(crow) == rendered_sha(row))
    out['check_first_joined'] = len(cf)
    out['check_first_parity'] = par
    out['check_first_sha_match'] = sha
    # The same parity over every delivered message in the window, labelled or not.
    a_cf = a_sha = 0
    for d in users:
        if events[d]['ts'] < CUT:
            continue
        row, why, meta = row_at(events, tus, d, sid)
        if row is None or not meta.get('check_first') or check_ci.get(d) is None:
            continue
        a_cf += 1
        crow = tml.build_row(events, check_ci[d], sid, window_s=tml.FIRST_WORDS_WINDOW_S)
        a_sha += int(crow is not None and rendered_sha(crow) == rendered_sha(row))
    out['check_first_all_deliveries'] = a_cf
    out['check_first_all_sha_match'] = a_sha
    return out


def _print_reach(r):
    pct = lambda a, b: f'{100.0 * a / b:.1f}%' if b else 'n/a'   # noqa: E731
    print('turn_anchor --reach  (DEV_NOT_HELD_OUT; reach numbers, not catches)')
    print(f"  events {r['events']}, main tool calls {r['tool_uses']}, delivered user messages "
          f"since {CUT}: {r['delivered_since_cut']} ({r['unmatched_deliveries']} unmatched)")
    print(f"  joined turns: {r['joined_turns']} of {r['labelled_turns']} labelled; judged joined "
          f"{r['judged_joined']} of {r['judged_turns']}")
    print(f"  anchored joined turns: {r['anchored_joined']} of {r['judged_joined']} "
          f"(first delivery alone: {r['anchored_joined_strict_first_delivery']})")
    print(f"  drift turns reached: {r['drift_reached']} of {r['drift_joined']} "
          f"(drift turns labelled: {r['drift_turns']})")
    print(f"  check arm for comparison: {r['check_arm_reach_joined']} of {r['judged_joined']} joined, "
          f"drift {r['check_arm_drift_reached']} of {r['drift_joined']}")
    print(f"  anchored rows with a goal {r['anchored_with_goal']}, with first words "
          f"{r['anchored_with_first_text']}; drift rows with a goal or first words "
          f"{r['drift_with_goal_or_text']} of {r['drift_reached']}")
    print(f"  check-first turns (first tool call is check_state): {r['check_first_joined']} joined; "
          f"same check as the check arm {r['check_first_parity']} "
          f"({pct(r['check_first_parity'], r['check_first_joined'])}); rendered-prompt sha matches "
          f"{r['check_first_sha_match']} ({pct(r['check_first_sha_match'], r['check_first_joined'])})")
    print(f"  every delivered message since {CUT}: check-first {r['check_first_all_deliveries']}, "
          f"sha matches {r['check_first_all_sha_match']} "
          f"({pct(r['check_first_all_sha_match'], r['check_first_all_deliveries'])})")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--freeze', action='store_true', help='write eval/turnwatch-anchor-frozen.json')
    g.add_argument('--reach', action='store_true', help='dev reach, counts only, no model calls')
    ap.add_argument('--transcript', help='the main session .jsonl the realdrift labels came from')
    ap.add_argument('--data', default=str(REPO / 'eval' / 'realdrift'))
    ap.add_argument('--json', help='also write the reach counts here')
    a = ap.parse_args(argv)
    if a.freeze:
        ok, bad = freeze()
        if not ok:
            print('refused: the check arm\'s frozen block no longer matches: ' + ', '.join(bad))
            return 1
        print(f'wrote {ANCHOR_FROZEN.relative_to(REPO)} (turn_anchor.py {file_sha()[:12]})')
        return 0
    tp = a.transcript or os.environ.get('LASERBRAIN_REALDRIFT_TRANSCRIPT')
    if not tp:
        turns = [json.loads(x) for x in open(pathlib.Path(a.data) / 'turns.jsonl', encoding='utf-8')]
        found = locate_transcript(turns)
        if found is None:
            print('no transcript: pass --transcript (the main session the labels came from)')
            return 2
        tp = str(found)
        print(f'  transcript: located by the first labelled timestamp '
              f'({found.stat().st_size / 1e6:.0f} MB, read only)')
    r = reach(tp, a.data)
    _print_reach(r)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
