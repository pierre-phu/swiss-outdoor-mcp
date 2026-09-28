# Eval results, 2026-09-28

Five tasks from `docs/SPEC.md`, graded on the tool-call trace (`evals/tasks.yaml`). The server ran
in offline mode, and the agent was told today is Friday 2026-09-25, so "Saturday" is 2026-09-26.
Every run is a single attempt per task; the model's own sampling is the only source of variance.

## Result

**Claude Haiku 4.5 (the default): 27 of 30 task runs passed over 6 full runs. Every run passed
at least 3 of 5; the last 3 runs passed 5 of 5.** Claude Sonnet 5: 5 of 5 in its single run.

| Task | Haiku 4.5 (6 runs) | Sonnet 5 (1 run) |
| --- | --- | --- |
| `valais-sites` | 6/6 | 1/1 |
| `flyable-saturday` | **4/6** | 1/1 |
| `train-to-site` | 6/6 | 1/1 |
| `plan-saturday` | 6/6 | 1/1 |
| `unknown-site-recovery` | **5/6** | 1/1 |

Cost per full run: about $0.08–0.09 with Haiku 4.5 (66k input and 3.8k output tokens on
average), $0.19 with Sonnet 5. About half the input tokens are the planning task, which reads
several `get_flyability` results.

All seven runs used the same server code, commit `5f88c08`. The first three reports say
`533b5dc+dirty` because they ran just before that commit, on identical changes.

## What still fails, and why

- **`flyable-saturday`, 2 of 6: the date.** Told "Today is Friday 2026-09-25", Haiku asked for
  2026-09-27, a Sunday, in its very first call. The `weekday` field added to `get_flyability`
  made the mistake visible: both times the answer told the user the forecast was for Sunday. It
  did not re-ask for the Saturday. This is date arithmetic in the model; Sonnet 5 got it right.
- **`unknown-site-recovery`, 1 of 6: asked instead of acting.** After `Unknown site_id
  'fiesch-kuehboden'. Call list_sites to get valid ids.`, the agent offered the user a menu of
  options instead of calling `list_sites`. Nothing was left unrecovered by mistake; it asked for
  permission.

The tools were not bent to these two, on purpose. A scenario-specific hint ("Saturday after
Friday 25th is the 26th") would pass the eval without making the server better.

## What the eval changed

Found on the first runs and fixed in the server, not in the assertions (commit `5f88c08`):

1. `plan-saturday` ("where can I go paragliding by train?") was answered from `list_sites`
   alone, or by calling `get_connections` for all six sites without checking the weather. It
   failed the first run; with a first wording change to `list_sites` alone it passed 1 of the
   next 2. `list_sites` now says it is the catalogue only, and the server
   `instructions` give the order: sites, then flyability, then connections to one or two stops.
   The last rule also keeps agents from fanning out over a timetable API with no stated rate
   limit. After the fix it passed 6 of 6.
2. `get_flyability` returns `weekday`, for the date problem above.

## Reproduce

```sh
uv run --env-file .env python -m evals.run_eval                          # Haiku 4.5
uv run --env-file .env python -m evals.run_eval --model claude-sonnet-5
```

Each run costs money and writes its report to `evals/runs/`, which git ignores.
