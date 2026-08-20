# lasergear

The **instructions** layer of laserbrain — the fourth of six.

laserbrain measures, laserfield serves, lasermind defines, laserstore records, the operator
acts. lasergear is what tells them how. It fails by being **absent or obstructive**: a hook
that does not fire, or one that fires on the wrong thing.

| file | what it does |
|---|---|
| `lb_gate.py` | PostToolUse coverage gate — counts steps, blocks when checking lapses |
| `lb_safety.py` | PreToolUse deny for irreversible shell actions under always-approve |
| `lb_coverage.py` | reads the session record and reports how much was actually watched |
| `methods.py` | phronesis's own workflows, as stored methods |

## Why this is a layer and not a folder

Named 2026-07-27. A part is real when it can vary independently of the others and has a
failure mode none of them share. Before it was named, these three files sat inside
`lasermind`, and the canonical `grammar.json` sat there too — so the canonical file drifted
to 1.4.0 while its own copy reached 1.6.0 and every parity check stayed green, because each
compared a pair that did not include the source.

## The patterns live in the grammar, not here

`lb_safety.py`'s deny list is mirrored into `lasermind/grammar.json` under
`operator_patterns`, because the SDK ships on PyPI and cannot import a Claude Code hook.
One list, two readers. Edit the canonical grammar, then `sync-grammar.mjs`.
