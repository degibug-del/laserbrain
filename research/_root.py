"""lasergear/lb_paths.py, made importable from lasermind.

The resolver lives in lasergear because the HOOKS need it and they are the one thing that
must not depend on anything else. The analysis scripts here read the same files — the
drift log, the outcomes log, the session corpus — so they must resolve them the same way,
or `LASERBRAIN_HOME=/tmp/x python3 corpus-map.py` silently reports on the live corpus
instead of the one you pointed it at.

Loaded by absolute path, not by name: these scripts run from lasermind, from the repo
root, and from run-tests.sh, and only an absolute path resolves in all three.
"""
import importlib.util as _u
import pathlib as _p

_sp = _u.spec_from_file_location(
    'lb_paths', str(_p.Path(__file__).resolve().parent.parent / 'lasergear' / 'lb_paths.py'))
_m = _u.module_from_spec(_sp)
_sp.loader.exec_module(_m)

home = _m.home
config_dir = _m.config_dir
sessions_dir = _m.sessions_dir
config = _m.config
