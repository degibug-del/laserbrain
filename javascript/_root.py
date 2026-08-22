"""lb_paths.py, made importable from the scripts in this directory.

The resolver lives with the HOOKS because they are the one thing that must not depend on
anything else. The analysis scripts here read the same files — the drift log, the outcomes
log, the session corpus — so they must resolve them the same way, or
`LASERBRAIN_HOME=/tmp/x python3 corpus-map.py` silently reports on the live corpus instead
of the one you pointed it at.

ADAPTED, NOT COPIED, 2026-08-21. The working tree's version loads
`../lasergear/lb_paths.py`; this repo has no lasergear/ — the reorg carried the hooks into
python/laserbrain/hooks/ and left this module behind entirely, so `import _root` raised
ModuleNotFoundError and took calibrate_attention.py, quarantine_contexts.py and
quarantine_drift_log.py down with it. The calibrator is the only thing permitted to write
attention.json, which is why the shipped table and the source copy were free to drift apart
for five days with nothing able to notice.

Both locations are tried, repo first, so this works in either tree. Loaded by absolute path
rather than by name because these scripts run from several working directories and only an
absolute path resolves in all of them.
"""
import importlib.util as _u
import pathlib as _p

_HERE = _p.Path(__file__).resolve().parent
_CANDIDATES = [
    _HERE.parent / 'python' / 'laserbrain' / 'hooks' / 'lb_paths.py',   # this repo
    _HERE.parent / 'lasergear' / 'lb_paths.py',                         # the working tree
]
_target = next((c for c in _CANDIDATES if c.exists()), None)
if _target is None:
    raise ImportError(
        'lb_paths.py not found in any known location: '
        + ', '.join(str(c) for c in _CANDIDATES))

_sp = _u.spec_from_file_location('lb_paths', str(_target))
_m = _u.module_from_spec(_sp)
_sp.loader.exec_module(_m)

home = _m.home
config_dir = _m.config_dir
sessions_dir = _m.sessions_dir
config = _m.config
