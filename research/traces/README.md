# traces/

Input for `replay.py`. One JSON object per line.

## `fixtures.jsonl` IS NOT EVIDENCE

It contains two runs that I wrote, with the answers I expected, to prove the replay
machinery runs at all. `replay.py` reports **100% recall and 100% precision** on it. That
number means nothing whatsoever about the grammar, and it is exactly the shape of number
that gets screenshotted without its denominator.

Both runs were constructed so the answer was obvious: one keeps every goal inside the same
vocabulary, the other walks from a JSON parser to Terraform in three steps. A detector that
failed either would be broken past the point of being interesting. Passing them says the
pipeline is wired, and nothing else.

Real evidence requires runs somebody else produced and somebody else labelled.

## Schema

```json
{"run": "r1", "step": 1, "goal": "...", "drifted": false,
 "progress": "advancing", "distance": 6, "label": "free text"}
```

| field | required | meaning |
|---|---|---|
| `run` | yes | groups rows into one task |
| `step` | yes | order within the run |
| `goal` | yes | the goal AS STATED at that step |
| `drifted` | yes | the external judgement about the whole run; must agree on every row |
| `progress` | no | `advancing` / `stuck` / `circling`; derived as `advancing` if absent |
| `distance` | no | 0–10; derived as a linear countdown if absent |
| `label` | no | carried through, never read |

`goal` is required and never derived. The grammar measures displacement *from* a goal, so
a harness that invented one would be scoring this project against its own writing — which
is the precise weakness external traces exist to remove.

## Why there is no adapter here yet

Two public suites were checked, and neither yields what per-step scoring needs:

**[agent-drift](https://github.com/jhammant/agent-drift)** measures whether an agent
violates its *system prompt* under adversarial pressure across six value dimensions
(privacy, security, honesty, boundaries, loyalty, compliance), scored by an LLM judge as a
per-run percentage. That is jailbreak resistance. An agent can hold every one of those
values while quietly wandering off the errand, and can stay perfectly on-task while being
argued out of a constraint. Different phenomenon — not adapted.

**[goal-drift-evals](https://github.com/RaunoArike/goal-drift-evals)** is the right
phenomenon: the AIES paper's own code, agents pursuing a goal under competing objectives.
But `GD_actions` and `GD_inaction` are computed per *run* against a baseline run, and
`--interrogate` asks the model its objective at the end. There is no per-timestep label in
it. Its checkpoints are `.pkl` files under `checkpoints/`, and producing them needs an API
key and a paid model run.

So `replay.py` scores **per-run agreement**, which is what the available ground truth
supports, and says so rather than reporting a per-step precision it cannot back.

## Adapting goal-drift-evals

Unwritten on purpose. It needs a paid simulation run to produce a single checkpoint, and
an adapter validated against zero real files would be a guess wearing the costume of an
integration — the `.pkl` layout above is from the repo's documentation, not from a file I
have opened. When there is budget for a run, the shape to emit is the schema above, with
`drifted` taken from the run's GD metric against its baseline.

Related: [Skip paywalled steps, move on](../../claude/memories.md).
