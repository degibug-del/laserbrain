# instructions — phronesis's own methods, and the corpus reader

Absorbed from `degibug-del/laserbrain-instructions` at `c157bdbd5` on 2026-08-30.
That repository was named `lasergear` at that commit; it was renamed the same day.

lasergear held twelve files. Nine were the hook modules, `hosts.json` and a shared
markdown note, all of which already live in this repository — the hooks at
`python/laserbrain/hooks/`, shipped inside the wheel. A second copy in a second repository
is a divergence with nothing making it converge, and it diverged: `lb_gate.py` there fell
146 lines behind, with the `ToolSearch` deadlock live the whole time.

These three files were the part that was genuinely only there.

| file | what it does |
|---|---|
| `methods.py` | phronesis's own workflows, written into laserstore where anything can vend them |
| `bindings.py` | the implementations those methods name, kept in a separate file so the method stays declarative |
| `read_corpus.py` | what laserbrain's own record actually says — the evidence half of self-design |

They live under `research/` because they are laserbrain applied to itself rather than
laserbrain offered to anyone else. The corpus they read stays in the corpus repository; this
is the reader, not the data.
