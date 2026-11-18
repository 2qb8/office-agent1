# Bundled eval with the plan grammar

Same five briefs, same harness, same machine, `--repair` on and content
checks on, run against Qwen2.5-1.5B-Instruct-Q4_K_M and
Qwen2.5-3B-Instruct-Q4_K_M. The change under test: the bundled client sends
`response_format` with a JSON schema built from the tool registry
(`agent/plan_schema.py`), which llama-server turns into a grammar. A reply is
then always one JSON object with `goal` and a non-empty `steps`, every step
carries all six fields, and its `tool` and `action` name a pair the registry
really has. Planning and repair both go through that client.

```
OFFICE_AGENT_BUNDLED_MODEL=1 OFFICE_AGENT_MODELS=/tmp/models \
OFFICE_AGENT_LLAMA_SERVER=/tmp/llama/bin/llama-server \
  .venv/bin/python scripts/bundled_eval.py --model 1.5b --repair --out /tmp/eval-15.md
```

## 1.5B

| case | valid | output | contents | repairs | plan | total | why |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sales-pack (shipped example) | no | no | – | 0 | 362s | 362s | validator: `word.create_document` asked to write `.xlsx` |
| invoice totals by client | yes | no | – | 0 | 97s | 97s | `table.filter` with `op="is"`; no such comparison |
| filter products by units | yes | yes | **right** | 0 | 81s | 81s | 3 steps, `filtered_products.docx` matches the brief |
| clean the contact list | yes | no | – | 0 | 60s | 60s | `table.filter` with `op="empty"`; the tool has `is_empty` |
| reorder note from stock | yes | yes | **right** | 0 | 57s | 57s | lists both items and their quantities |

4/5 validated, 2/5 produced a file, 2/2 of those were right.

Before (`docs/bundled-eval-stricter-validation.md`, same model and prompt):
3/5 validated, 2/5 produced, 1/2 right.

What changed: the two rejected plans are gone. Nothing in the shape is left
to complain about — no prose before the JSON, no unknown action, no missing
field. Both remaining failures are argument-level (`op`), and both file-type
mistakes are caught by the validator before anything runs.

## 3B

| case | valid | output | contents | repairs | plan | total | why |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sales-pack (shipped example) | no | no | – | 0 | 502s | 502s | validator: `word.export_text` asked to write `.xlsx` |
| invoice totals by client | yes | yes | **right** | 0 | 141s | 141s | aggregate → sort → workbook; totals match, largest first |
| filter products by units | yes | yes | **right** | 0 | 202s | 202s | workbook matches; two extra files are harmless |
| clean the contact list | yes | yes | **right** | 0 | 103s | 103s | blank emails dropped, the rest kept |
| reorder note from stock | yes | yes | **right** | 0 | 139s | 139s | lists both items and their quantities |

4/5 validated, 4/5 produced a file, 4/4 of those were right.

Before (`docs/bundled-eval-stricter-validation.md`): 4/5 validated, 3/5
produced, 1/3 right. Two of those three content misses had just been fixed by
the prompt rules in `dbc0b3d` in a two-case rerun; this is the first full five
briefs since, and both hold.

## The operator enum, which was tried and removed

A table `op` the tool does not have is as unrunnable as an invented action,
so the first version also constrained `arguments` for `table.filter` and
`table.aggregate` to the tool's own operator lists. 1.5B, same five briefs:

| case | valid | output | why |
| --- | --- | --- | --- |
| sales-pack | no | no | validator: `.xlsx` sent to `word.create_document` |
| invoice totals by client | yes | no | `'headers' must be a non-empty list` |
| filter products by units | yes | no | `'headers' must be a non-empty list` |
| clean the contact list | no | no | validator: writer step has no `output_path` |
| reorder note from stock | no | no | validator: writer step has no `output_path` |

2/5 validated, 0/5 produced. Naming any property inside `arguments` made the
model emit *only* that property: the filter steps lost `headers` and `rows`,
and writer steps lost `output_path`. A grammar that pins one argument buys a
valid operator and costs the rest of the call, so the constraint was removed
and `arguments` is free-form again. The measured numbers above are from the
code without it.

## Retrying argument errors

The tool's argument errors were outside `REPAIRABLE_ERRORS`, so a plan that
failed on `table.filter(op="is")` was refused a revision instead of being
retried. `unknown comparison` and `unknown aggregation` were added to that
list (`agent/runtime.py`), which lets the existing loop spend its revisions on
them. 1.5B, `--repair`, the two briefs that failed this way:

| case | failed step | error | revisions | what the revision did | total |
| --- | --- | --- | --- | --- | --- |
| invoice totals by client | `filter_totals` (`table.filter`) | `Unknown comparison 'is'` | 2 | sent the identical operator again, twice | 292s |
| clean the contact list | – (plan rejected) | no `output_path` on `text.write` | 0 | never executed, so never repaired | 75s |

Neither case produced a file, the same as before the change; the invoice run
only got about 180s slower. The error text reaches the model — the revision
prompt carries it word for word — and 1.5B copies its own broken call back
instead of reading the allowed list. The clean brief failed before execution
this time, which no repair can reach: a plan the validator rejects is never
run, and validation failures are still not repairable.

3B does not fail either brief when asked to plan it: with `--repair` it wrote
the invoice in 202s (aggregate → sort → workbook, totals right) and the
contact list in 140s (blank emails dropped, CSV right), no revision in
either, so it never met the error on its own. To test the reading rather than
the draw, 3B's own clean plan was rerun with a single argument changed,
`op: not_empty` to `op: is` on the same filter: one revision, 108s, came back
`is_empty`, and the job finished with the two rows that have an address. Both
models receive the same revision prompt and the same allowed list in the
error; the 3B reads it and the 1.5B copies its own call back, so the hints
stay.

## What is still the limit

- **The shipped example never passes.** Both models write the DOCX table step
  as an `.xlsx` path and the validator refuses it. Nothing about the plan
  format is wrong; the model is choosing the wrong writer for a path, which is
  the same class the prompt's FORMATS table addresses and the validator
  catches. It costs a full five-minute planning call to find out.
- **1.5B produces nothing more often than it did.** Same 2/5, different two:
  its content checks now pass when it does produce. The grammar fixed its
  rejections, not its understanding.
- **Arguments are still the model's.** `op="is"` and `op="empty"` are what
  the grammar cannot see. The repair loop now retries them (see below);
  1.5B answers with the same operator again, so the retry buys time and no
  plan.
- One sample per brief per model, CPU-only, so timings wander by tens of
  seconds between runs; the valid/output/right columns did not wander across
  the three runs recorded here.

## What this does not change

Hosted providers get no `response_format`, because their schemas vary and
the prompt plus validator is what they already had. A llama-server too old to
know the field answers HTTP 400; the client retries that request once without
it and says so on stdout, so an old binary keeps working rather than failing
every plan.
