"""The prose about the step-count gate must say what the default does since 2026-10-16.

WHY THIS SUITE EXISTS. When the default became `nudge` the shipped attention.json was edited
by hand, and the script that writes it (javascript/calibrate_attention.py) still said "the
gate forces a check every four steps": the next calibration run would have quietly put the
old wording back in both copies. Three other places still said the hooks refuse tool calls
by default. A checker found all four on 2026-10-17. This pins them:

  1. calibrate_attention.py builds exactly the censoring and overhead text both
     attention.json copies carry, so regenerating cannot revert it;
  2. infra/README.md, the hooks package docstring and lb_gate's mode comment name nudge as
     the default and LASERBRAIN_GATE_MODE=hard as the way to get refusals.

Run:  python3 test_gate_docs.py
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
TOP = HERE.parent
ok = True


def show(label, passed, detail=''):
    global ok
    ok = ok and passed
    print(f"  {'ok  ' if passed else 'FAIL'} {label}" + (f'   ({detail})' if detail and not passed else ''))


def find(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        for v in o.values():
            r = find(v, k)
            if r is not None:
                return r
    return None


src = (TOP / 'javascript' / 'calibrate_attention.py').read_text()
m = re.search(r"'censoring': \((.*?)\n\s*% \(long_gaps", src, re.S)
m2 = re.search(r"'note': \(('Runs under ten.*?)\),\n", src, re.S)
show('calibrate_attention.py still has the censoring and overhead strings', bool(m and m2))
if m and m2:
    tmpl, note = eval('(' + m.group(1) + ')'), eval('(' + m2.group(1) + ')')  # literals only
    show('...neither says the gate forces a check (present tense)',
         'forces a check' not in tmpl and 'forces a check' not in note)
    for rel in ('json/attention.json', 'python/laserbrain/attention.json'):
        j = json.loads((TOP / rel).read_text())
        cens, n = find(j, 'censoring'), find(j, 'note')
        nums = re.search(r'are ([\d.]+)% of the sample \((\d+) of (\d+)\)', cens or '')
        same = bool(nums) and cens == tmpl % (int(nums.group(2)) / int(nums.group(3)) * 100,
                                              int(nums.group(2)), int(nums.group(3)))
        show(f'{rel}: censoring text is what the script writes', same)
        show(f'{rel}: overhead note is what the script writes', n == note)

readme = (TOP / 'infra' / 'README.md').read_text()
row = next((ln for ln in readme.splitlines() if ln.startswith('| `lb_gate.py`')), '')
show('infra/README.md: the lb_gate row names nudge and LASERBRAIN_GATE_MODE=hard',
     'nudge' in row and 'LASERBRAIN_GATE_MODE=hard' in row, row[:80])
init = (HERE / 'laserbrain' / 'hooks' / '__init__.py').read_text()
show('hooks/__init__.py: refusal is tied to LASERBRAIN_GATE_MODE=hard, nudge is the default',
     'LASERBRAIN_GATE_MODE=hard' in init and 'nudge' in init)
gate = (HERE / 'laserbrain' / 'hooks' / 'lb_gate.py').read_text()
show("lb_gate.py: no comment says gate_mode() is 'hard' unless the variable says otherwise",
     "'hard' unless LASERBRAIN_GATE_MODE" not in gate)

print('\n  ' + ('PASS' if ok else 'FAIL — see above.'))
raise SystemExit(0 if ok else 1)
