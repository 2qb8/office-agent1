Bundled model eval — Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
Repair loop: on
Cases: 5
Validated first try:  4 of 5 (80%)
Correct output:       1 of 5 (20%)
Planning:             724s for five jobs, 145s each
Everything after:     362s in total, 72s per job
All in:              1086s for five jobs, 217s each

case                           valid  ok   fix    plan  total  note
sales-pack (shipped example)   no     no      0   385s   385s  PlanValidationError: step 'evidence' must write inside output/ but uses: <job>/evidence/sales-report.png
                                                               16 steps, ending in the same word.create_document five times
invoice totals by client       yes    yes     1   103s   210s  wrote summary.xlsx; the fix replaced the sort step after "Column 'Amount' not found"
                                                               excel.read_table → table.filter → table.aggregate → table.sort → excel.create_workbook
filter products by units       yes    no      2    83s   223s  $inspect_products.headers not found; both fixes repeated the same reference
                                                               excel.inspect → excel.filter → word.create_document
clean the contact list         yes    no      2    73s   188s  read_contacts: excel.read_table got a .csv; still failing after two fixes
                                                               excel.read_table → table.filter → excel.create_workbook
reorder note from stock        yes    no      0    80s    80s  create_markdown: Output must be DOCX (.md path); not classified as repairable, so no fix was attempted
                                                               excel.read_table → table.filter → word.create_document

Why repair helped once
- Validation failures happen before execution, so the repair loop never sees
  them: the shipped example dies on an evidence path and is not retried.
- "Output must be DOCX" and "expected .xlsx" are argument-shape mistakes, not
  missing names, so repair either does not run or the model repeats itself.
- The one plan repair fixed was the one whose error named an available
  alternative ('Available columns: [sum(Client)]'), which is the shape the
  correction prompt is built for.

The shipped example shows a second failure mode on top of the bad path: the
plan runs to sixteen steps and repeats word.create_document five times, which
is why planning it alone took six and a half minutes.

The five cases were run in three invocations because the runner restarted
mid-run; each row is a single unchanged job, and the totals are the sum of
those runs.
