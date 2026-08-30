# research — the algorithms

The measurement and study code from `degibug-del/laserbrain-corpus`, merged here on 2026-08-29
with `git subtree add --prefix=research`, so its history came with it.

**Algorithms only. No data.** The session corpus, the traces, `attention.json` and
`corpus-facts.json` stay in laserbrain-corpus, and so do the twenty tests that read them. What is
here is the code: the calibrators, the graders, the benchmarks, the study harnesses, and
the eighteen tests that pass standalone.

`grammar.json` is not here either, for a different reason: it is the contract and it lives
at `json/grammar.json`, one copy, canonical since 2026-08-29.

## Why the split is drawn at data rather than at subject

A repository that carries its own measurements can be tuned until they agree with it.
Keeping the corpus in a separate tree means the algorithms here can be read, reviewed and
re-run by someone who never sees our numbers, which is the only way a result of ours is
worth anything to them.

## Running it

    python3 test_<name>.py

Eighteen pass with nothing but this checkout. Anything needing the corpus is in laserbrain-corpus.
