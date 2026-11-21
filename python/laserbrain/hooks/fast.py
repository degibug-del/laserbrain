#!/usr/bin/env python3
"""fast.py: start lb_coverage without the package __init__ (2026-11-19).

    python3 -I -S <repo>/python/laserbrain/hooks/fast.py lb_coverage

`python3 -m laserbrain.hooks.lb_coverage` runs laserbrain/__init__.py first: 2,557 lines and
18 modules that no hook uses (about 11 ms per process, measured 2026-11-19). The hook needs
laserbrain.runtime and its three siblings (observe, _paths, _evidence) and nothing else. So
this registers the package DIRECTORY as a bare package, without executing its __init__, and
imports the hook from it; relative imports inside runtime resolve exactly as before.

-S: no site, so no editable-install finder: the package is found from this file's own path,
which also means a new interpreter version (mise "latest") does not silently lose the hooks.
-I: the agent's working directory and PYTHON* variables are ignored, so a laserbrain copy in
the cwd cannot stand in for this one and PYTHONDONTWRITEBYTECODE (set by the app) does not
stop the modules' bytecode from being kept fresh.

Only names in ALLOWED run. lb_safety is deliberately NOT started through here: it is run as
its own plain file so nothing in this launcher can affect it. Fails open: any error exits 0.
Switch back: point the settings.json command at `-P -m laserbrain.hooks.lb_coverage` again.
"""
import os
import sys
import types

ALLOWED = ('lb_coverage',)


def _bare_package():
    if 'laserbrain' in sys.modules:
        return
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = types.ModuleType('laserbrain')
    m.__path__ = [pkg]
    m.__package__ = 'laserbrain'
    m.__file__ = os.path.join(pkg, '__init__.py')
    sys.modules['laserbrain'] = m


def run(argv):
    name = argv[1] if len(argv) > 1 else ''
    if name not in ALLOWED:
        return
    _bare_package()
    import importlib
    mod = importlib.import_module('laserbrain.hooks.' + name)
    mod.main()


if __name__ == '__main__':
    try:
        run(sys.argv)
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)
