"""Where laserbrain keeps its state, in one place.

WHY THIS EXISTS — a two-day flake and eleven files

State lived at two hardcoded roots with no way to move either:

    ~/.config/laserbrain    user-turn, evidence.json, contexts.json, drift-log.jsonl,
                            verdict-outcomes.jsonl, the link log, the key, gate-off
    ~/.claude/laserbrain    session files, probe-arms.jsonl, blind-arms.jsonl, gate-errors.jsonl, refusals.jsonl

Eleven files referenced them directly; two honoured an environment override. The cost
showed up as `test_parent_overlap` failing intermittently for two days: one suite wrote
`user-turn`, another read it, and a set flag turns `excursion` into `reground`. Nothing
could run hermetically, so any suite could poison any other and the failure looked like a
broken excursion rule rather than a shared file.

THE RESOLUTION ORDER, and it is chosen so nothing already working moves:

    1. the specific override, where one already exists (LASERBRAIN_STATE_DIR,
       LASERBRAIN_DRIFT_LOG, ...) — these predate this file and keep winning
    2. LASERBRAIN_HOME, which relocates BOTH roots at once: <home>/config and
       <home>/sessions
    3. the historical defaults, byte-identical to what shipped before

So an unset environment behaves exactly as it did, a test sets one variable and gets a
private world, and a second agent on the same machine can be given its own tree without
editing anything.

THREE COPIES OF THIS LOGIC EXIST, deliberately. The hooks cannot import the SDK — an
ImportError here would fail the gate open, which is the one thing it must never do
silently — and the published package cannot import lasergear, which is not shipped. So
lasergear, laserbrain-sdk and mcp-server.mjs each resolve it themselves. Three deployment
units that genuinely cannot reach each other is a different situation from four copies of
one rule in one repo; the shape is identical and the excuse is not.
"""
import os
import pathlib


def home():
    """The root under which both trees live, or None when the historical layout applies."""
    h = os.environ.get('LASERBRAIN_HOME')
    return pathlib.Path(h).expanduser() if h else None


def config_dir():
    """Cross-session state: flags, evidence, contexts, logs, the key."""
    h = home()
    return (h / 'config') if h else (pathlib.Path.home() / '.config' / 'laserbrain')


def sessions_dir():
    """Per-session files, plus the append-only logs that must not lose the write race."""
    d = os.environ.get('LASERBRAIN_STATE_DIR')
    if d:
        return pathlib.Path(d).expanduser()
    h = home()
    return (h / 'sessions') if h else (pathlib.Path.home() / '.claude' / 'laserbrain')


def config(*parts):
    """A file under the config root — config('user-turn'), config('evidence.json')."""
    return config_dir().joinpath(*parts)
