"""Every moment the user spoke, kept by laserbrain: the record attention.json is measured against.

WHY. attention.json is drift against the time since the user last spoke, and those moments lived only in the
host's transcripts, which Claude Code deletes after cleanupPeriodDays (30 by default). On 2026-10-29 none of
the 3243 user turns behind the shipped table were left, while the drift log, which laserbrain owns, was whole
back to 2026-07-28. So the moments are kept here, in a file laserbrain owns: one line per enqueue record,
with the transcript's own UTC timestamp and whether it was the user or a <task-notification>.

Three writers, one format:
  - lb_coverage.py appends what it sees as it scans each transcript after a tool call;
  - harvest() (python3 -m laserbrain.turns) catches up whatever the hook never scanned: a session that
    made no tool call, a host without the hook. lb_coverage starts it in the background at most once a day;
  - calibrate_attention.py --harvest calls harvest() too.
Readers keep one entry per timestamp, so a line written twice is harmless.

    python3 -m laserbrain.turns [--quiet]
"""
import datetime
import glob
import json
import os
import pathlib
import sys

try:
    from . import _paths
except ImportError:                       # run as a file, not as part of the package
    _paths = None


def record_path():
    if os.environ.get('LASERBRAIN_USER_TURNS'):
        return pathlib.Path(os.environ['LASERBRAIN_USER_TURNS']).expanduser()
    if _paths is not None:
        return _paths.config('user-turns.jsonl')
    return pathlib.Path.home() / '.config' / 'laserbrain' / 'user-turns.jsonl'


def transcripts_root():
    return pathlib.Path(os.environ.get('LASERBRAIN_TRANSCRIPTS')
                        or pathlib.Path.home() / '.claude' / 'projects').expanduser()


def parse_ts(s):
    """An aware datetime, or None. A timestamp with no zone is refused rather than guessed: mixed with the
    transcripts' UTC ones it cannot be ordered, and sorting naive with aware raises."""
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def enqueues(path):
    """(timestamp, kind) for each enqueue record in one transcript; kind is 'notification' for a finished
    background task's <task-notification>, else 'user'."""
    try:
        with open(path, errors='replace') as fh:
            for line in fh:
                if '"queue-operation"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get('operation') != 'enqueue':
                    continue
                ts = d.get('timestamp')
                if parse_ts(ts) is None:
                    continue
                c = d.get('content')
                note = isinstance(c, str) and c.lstrip().startswith('<task-notification')
                yield ts, ('notification' if note else 'user')
    except OSError:
        return


def logged(path=None):
    """{timestamp: kind} from the record. A torn, foreign or zone-less line is skipped."""
    out = {}
    try:
        lines = pathlib.Path(path or record_path()).read_text(errors='replace').splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get('ts') if isinstance(d, dict) else None
        if parse_ts(ts) is not None:
            out.setdefault(ts, d.get('kind') or 'user')
    return out


def transcripts(root=None):
    return glob.glob(str(pathlib.Path(root or transcripts_root()) / '**' / '*.jsonl'), recursive=True)


def harvest(root=None, path=None):
    """Copy every enqueue the transcripts still hold into the record, once. Returns (added, total)."""
    path = pathlib.Path(path or record_path())
    have = logged(path)
    new = {}
    for f in transcripts(root):
        sid = pathlib.Path(f).stem
        for ts, kind in enqueues(f):
            if ts not in have and ts not in new:
                new[ts] = (kind, sid)
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = ''.join(json.dumps({'ts': ts, 'kind': new[ts][0], 'sid': new[ts][1], 'src': 'harvest'}) + '\n'
                       for ts in sorted(new))
        # A torn last line (a writer killed mid-line) would swallow the first appended one.
        try:
            with open(path, 'rb') as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b'\n':
                    data = '\n' + data
        except OSError:
            pass
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data.encode())
        finally:
            os.close(fd)
    return len(new), len(have) + len(new)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    added, total = harvest()
    if '--quiet' not in argv:
        print(f'  {record_path()}: {added} user turn(s) added, {total} kept.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
