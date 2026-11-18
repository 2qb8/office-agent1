# Bundled eval after the stricter validator

Same five briefs, same harness, same machine, `--repair` on and content
checks on, run against Qwen2.5-1.5B-Instruct-Q4_K_M and
Qwen2.5-3B-Instruct-Q4_K_M. The change under test: `validate_plan` now
refuses a file extension the chosen tool cannot write, and a table step
naming a column that its input cannot have (with headers inferred for
`table.aggregate`).

```
OFFICE_AGENT_BUNDLED_MODEL=1 OFFICE_AGENT_MODELS=/tmp/models \
OFFICE_AGENT_LLAMA_SERVER=/tmp/llama/bin/llama-server \
  .venv/bin/python scripts/bundled_eval.py --model 1.5b --repair --only <case> --out /tmp/h15-<case>.md
```

## 1.5B

| case | valid | output | contents | repairs | plan | total | why |
| --- | --- | --- | --- | --- | --- | --- | --- |
| invoice totals by client | yes | yes | wrong | 0 | 100s | 100s | totals are the last invoice per client, not the sum |
| filter products by units | yes | no | – | 2 | 118s | 317s | failed steps: filter_products |
| clean the contact list | no | no | – | 0 | 67s | 67s | unknown action `excel.filter` |
| reorder note from stock | yes | yes | **right** | 0 | 67s | 67s | lists both items and quantities |
| sales-pack (shipped example) | no | no | – | 0 | 260s | 260s | step writes a file but has no `destination_path` |

3/5 validated, 2/5 produced a file, 1/2 of those were right.

Before (docs/bundled-eval-validation-repair.md): 3/5 validated, 1/5
produced, 0/1 right.

## 3B

| case | valid | output | contents | repairs | plan | total | why |
| --- | --- | --- | --- | --- | --- | --- | --- |
| invoice totals by client | yes | yes | wrong | 0 | 146s | 146s | totals right, not sorted largest first |
| filter products by units | yes | yes | **right** | 0 | 191s | 191s | workbook matches the brief |
| clean the contact list | yes | yes | wrong | 0 | 126s | 126s | filter inverted: dropped the good rows, kept the blanks |
| reorder note from stock | no | no | – | 0 | 149s | 149s | unknown action `text.append_lines` |
| sales-pack (shipped example) | no | no | – | 0 | 479s | 479s | `word.export_text` asked to write `.xlsx` (new check) |

4/5 validated, 3/5 produced a file, 1/3 of those were right.

Before: 3/5 validated, 3/5 produced, 1/3 right.

## What the new checks actually did

- **Extension check fired once**, on 3B and the shipped example: it asked
  `word.export_text` to write `docx-table.xlsx`. Every earlier run failed
  that brief too, but later and after executing steps; the refusal names the
  step, the file and the formats the tool does write.
- **Column check fired zero times.** The aggregate failures in this run were
  "no sort step at all" (3B invoice) and "the aggregate itself is wrong"
  (1.5B invoice), which no static check can see. The check is kept anyway: it
  is exact when it applies, costs nothing when it does not, and is the one
  guard that would have caught the classic `sort(column="Revenue")` after a
  `sum` aggregate if a model writes it again.
- **Nothing got worse on any axis**, for either model: validated 3→3 and
  3→4, produced 1→2 and 3→3, right 0→1 and 1→1.
- **Rejections stayed in the same classes as before**: `excel.filter`,
  `text.append_lines`, a missing `destination_path`. The stricter validator
  did not add a single new rejection class in five briefs per model.

## What is still the limit

Every remaining failure is a misunderstanding of the brief rather than of the
plan format: aggregate vs. last-row (1.5B invoice), no sort (3B invoice),
inverted filter (3B clean). One rejected plan still ends the run, and neither
model corrected the same mistake when given the correction message
(`docs/bundled-eval-validation-repair.md`), so a retry is not the fix. The
honest summary is unchanged: about one brief in five comes out right at these
sizes, and the validator's job is to make the failures cheap to read, not to
make the models right.

## Prompt rules for the two misreadings

Both failures above are in the brief, not the format, so the prompt now says
what "total per client" and "the contacts with an email" mean, and names the
near-miss to avoid (one row per group; `op="empty"`). Re-run on just those
two briefs, both models, `--repair` on:

| model | case | before | after |
| --- | --- | --- | --- |
| 3B | invoice totals by client | wrong (unsorted) | **right**: filter → aggregate → sort, 220 s |
| 3B | clean the contact list | wrong (inverted filter) | **right**: `not_empty` filter, 145 s |
| 1.5B | invoice totals by client | wrong (last invoice per client) | no output: three runs, three different failures (failed step; forward reference; wrong totals from filter → sort → select) |
| 1.5B | clean the contact list | rejected, `excel.filter` | rejected, `text.read` used as a tool name |

At 3B the rules did what they were written to do, on both briefs, and the
invoice plan now goes through `table.aggregate` rather than around it. At
1.5B nothing improved: three repeats of the invoice brief produced no
correct plan, and the failure moved from "wrong totals" to "no aggregate at
all". Two samples cannot tell a regression from noise, but the 1.5B model
was never right on that brief, so there is nothing to lose by keeping rules
that the recommended 3B model reads correctly.

## Reproducing

llama.cpp from conda-forge (`llama-server`), both models downloaded and
checksum-verified by `ensure_model`, 8 vCPU / 16 GB shared. 1.5B plans in
about 70–100 s, except the brief where two repairs were attempted (317 s);
3B in about 130–190 s, and 479 s on the shipped example.
