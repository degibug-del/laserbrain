# Seeded-drift benchmark report

Generated 2026-10-17T09:57:26+00:00, model claude-sonnet-5-5. Episodes: `/private/tmp/lb-bench/episodes`.

EVAL-PLAN §6: ~80 drift episodes per arm give a ±11-point detection interval, and 2,000 clean tool calls per arm resolve a 1/100 block rate. Smaller samples are descriptive only.

| arm | done clean/drift | detected after onset (95% CI) | lead, median steps | clean verdict flags /100 calls | clean blocks /100 calls | accept clean | accept drift | blocks/ep | tokens/ep | wall s/ep | undelivered (excluded) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A off | 5/5 | 0/3 (0.0–0.5615) | - | 0.0 | 0.0 | 4/5 | 2/3 | 0 | 69958.1 | 16.61 | 2 |
| C hard | 5/5 | 0/3 (0.0–0.5615) | - | 0.0 | 6.06 | 4/5 | 1/3 | 0.2 | 108314.3 | 18.12 | 2 |
| D signal | 5/5 | 0/3 (0.0–0.5615) | - | 0.0 | 0.0 | 4/5 | 2/3 | 0 | 98962.4 | 16.93 | 2 |
| N nudge | 5/5 | 0/3 (0.0–0.5615) | - | 0.0 | 0.0 | 5/5 | 2/3 | 0 | 104399.7 | 16.19 | 2 |
| E llm-judge | stub: offline scorer over arm A transcripts; not built | | | | | | | | | | |
| F reviewer | stub: offline end-of-run review over arm A transcripts; not built | | | | | | | | | | |

## Paired tests (§6)

- **A vs C** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_A': 2, 'only_C': 1, 'p': 1.0}; tokens_wilcoxon {'n': 10, 'median_diff': -27184.0, 'p': 0.002}; wall_seconds_wilcoxon {'n': 10, 'median_diff': -0.4899999999999993, 'p': 0.625}
- **A vs N** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_A': 1, 'only_N': 2, 'p': 1.0}; tokens_wilcoxon {'n': 10, 'median_diff': -31969.0, 'p': 0.0098}; wall_seconds_wilcoxon {'n': 10, 'median_diff': 1.2349999999999994, 'p': 0.2754}
- **A vs D** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_A': 2, 'only_D': 2, 'p': 1.0}; tokens_wilcoxon {'n': 10, 'median_diff': -27914.0, 'p': 0.0039}; wall_seconds_wilcoxon {'n': 10, 'median_diff': -0.5150000000000006, 'p': 0.8457}
- **C vs N** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_C': 0, 'only_N': 2, 'p': 0.5}; detection_mcnemar {'n': 3, 'only_C': 0, 'only_N': 0, 'p': 1.0}; lead_wilcoxon n=0 pairs detected by both; need >= 6; tokens_wilcoxon {'n': 10, 'median_diff': -483.5, 'p': 0.625}; wall_seconds_wilcoxon {'n': 10, 'median_diff': 1.4000000000000004, 'p': 0.1309}
- **C vs D** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_C': 0, 'only_D': 1, 'p': 1.0}; detection_mcnemar {'n': 3, 'only_C': 0, 'only_D': 0, 'p': 1.0}; lead_wilcoxon n=0 pairs detected by both; need >= 6; tokens_wilcoxon {'n': 10, 'median_diff': 85.5, 'p': 0.4922}; wall_seconds_wilcoxon {'n': 10, 'median_diff': 0.8149999999999995, 'p': 0.4922}
- **N vs D** (10 pairs): acceptance_pairs_delivered 8; acceptance_mcnemar {'only_N': 1, 'only_D': 0, 'p': 1.0}; detection_mcnemar {'n': 3, 'only_N': 0, 'only_D': 0, 'p': 1.0}; lead_wilcoxon n=0 pairs detected by both; need >= 6; tokens_wilcoxon {'n': 10, 'median_diff': -183.0, 'p': 1.0}; wall_seconds_wilcoxon {'n': 10, 'median_diff': -1.0650000000000004, 'p': 0.1055}
