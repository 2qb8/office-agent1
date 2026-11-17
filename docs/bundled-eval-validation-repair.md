Validation repair — measured, then removed as a net loss at 1.5B–3B

What was tried
- A plan the validator refused was sent back to the planner once with the
  validator's message ("step 'append_rows_to_note' uses unknown action
  'text.append_lines'. text has: write, read, read_table, verify").
- The format and unknown-action messages also joined REPAIRABLE_ERRORS so
  execution-time failures of that kind could be revised.

What it cost and changed, with the content checks on and repair enabled
              1.5B without   1.5B with   3B without   3B with
Validated       3 of 5         3 of 5      4 of 5       3 of 5
Produced file   2 of 5         1 of 5      3 of 5       3 of 5
Contents right  1 of 2         0 of 1      1 of 3       1 of 3
All in          ~221s/job      248s/job    243s/job     255s/job

The two cases that engaged the mechanism
- 1.5B contacts, 117s: rejected for unregistered tool 'text.read'; the
  revision sent 'text.read' again and was rejected again.
- 3B reorder, 294s against 184s before: rejected for unknown action
  'text.append_lines'; the revision sent 'append_lines' again. About 110s
  for the second call and the same outcome.

The full run with the feature on, for the record
Qwen2.5-1.5B-Instruct-Q4_K_M
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   no     no   -            0   600s   600s  no reply within 600s
invoice totals by client       yes    yes  wrong        0   113s   113s  check: the summary has no data rows
filter products by units       yes    no   -            2    91s   226s  failed steps filter_products
clean the contact list         no     no   -            1   117s   117s  rejected: unregistered tool 'text.read'; the revision was rejected too
reorder note from stock        yes    no   -            2    72s   183s  failed steps filter_stock

Qwen2.5-3B-Instruct-Q4_K_M
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   yes    no   -            0   493s   493s  failed steps create_docx_table_xlsx (12-step plan)
invoice totals by client       yes    yes  wrong        0   157s   157s  check: totals are not sorted largest first
filter products by units       yes    yes  right        0   196s   196s  check: filtered_products.xlsx matches the brief
clean the contact list         yes    yes  wrong        0   136s   136s  check: missing Ana Silva, Cara Diaz and still has Ben Okafor, Dan Wu
reorder note from stock        no     no   -            1   294s   294s  rejected: unknown action 'text.append_lines'; the revision was rejected too

Decision: remove the attempt, do not gate it
- Gating on "format or action errors the model can plausibly fix" would not
  have saved either call: both rejections were exactly that class — an
  unregistered tool name and an unknown action name — and both models
  repeated the mistake when shown it. A gate would have let both through.
- A gate keyed on anything narrower (say, only when the fix is a one-token
  edit) cannot be written from the plan alone, and would add branching to
  the most model-dependent part of the runtime for a benefit no run has
  shown.
- So the simpler version wins: a rejected plan is refused, once, and the
  user sees the validator's message, which already names the step and the
  actions the tool has. That message is the useful artefact; a second
  identical guess is not.

Kept from the experiment
- The wider REPAIRABLE_ERRORS list, so an execution-time "Output must be
  DOCX" or "Expected .xlsx or .xlsm" failure can still be revised by the
  existing loop. Neither model produced one of those in these runs.
- The eval reports the number of corrections attempted on a failed run, so
  the cost of a refused revision is visible if this is ever tried again.
- A test that pins the behaviour: a rejected plan costs exactly one model
  call and records no revision.

When to revisit
- With a model that can diff an error message against an allowed list. The
  message format is already what such a model needs; nothing else would have
  to change but the decision to spend the call.

Caveats
- One shared machine, cases run one per process, totals sum those runs.
- The "without" columns come from the previous run of the same eval, not a
  paired run, so sampling differences sit in both directions.
- Three of five 3B cases produced files, so two are verified wrong; the two
  without output are execution failures, not measured content.
