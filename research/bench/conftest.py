# Task and fixture trees hold deliberately failing tests (repo/ is the unsolved starting
# point; hidden/accept_test.py needs BENCH_SANDBOX). Keep a plain `pytest research/` from
# collecting them; the harness's own tests live in tests/.
collect_ignore_glob = ['fixtures/*', 'tasks/*']
