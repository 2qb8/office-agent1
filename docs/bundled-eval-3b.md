Bundled model eval — Qwen2.5-3B-Instruct-Q4_K_M.gguf (1,929,903,264 bytes, Q4_K_M)
Repair loop: on
Content checks: on — every case is read back against the brief
Cases: 5
Validated first try:  4 of 5 (80%) — the fifth never returned a plan
Produced output:      2 of 5 (40%)
Contents right:       1 of 2 checked (the three cases with no output cannot be checked)
Planning:          1,219s for five jobs, 244s each
Everything after:    107s in total, 21s per job
All in:            1,326s for five jobs, 265s each

case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   no     no   -            0   600s   600s  LLMError: no reply within 600s; no plan was ever validated
invoice totals by client       yes    yes  wrong        0   143s   143s  3 steps, wrote summarised_invoices.xlsx
                                                                       check: totals are not sorted largest first
                                                                       excel.read_table → table.aggregate → excel.create_workbook
filter products by units       yes    yes  right        0   194s   194s  4 steps, wrote filtered_products.xlsx, remaining_products.docx
                                                                       check: filtered_products.xlsx matches the brief (Kettle, Lamp, Mug; no Toaster, Chair)
                                                                       excel.read_table → table.filter → excel.create_workbook → word.create_document
clean the contact list         yes    no   -            0   134s   241s  read_contacts: excel.read_table got a .csv
                                                                       excel.read_table → table.filter → excel.create_workbook
reorder note from stock        yes    no   -            0   148s   148s  reorder_note: Output must be DOCX (.md path)
                                                                       excel.read_table → table.filter → word.create_document

What the checks establish
- One brief of five is right on inspection: the filtered products (Units >= 100,
  so Kettle, Lamp and Mug, with the Toaster and the Chair gone).
- One produced a file that looks right and is not: the invoice totals are
  correct but not sorted largest first, which the brief asked for. It is
  reported as wrong, not as a partial win.
- Three produced nothing, so nothing is claimed about them.
- Before the checks existed, the same model scored "produced output 1 of 5"
  and nothing was known about contents. That number was flattering: the one
  file it counted, in the previous run, was an invoice workbook whose totals
  were wrong.

Run-to-run variance is real
- The previous 3B run produced the invoice workbook and nothing else, failing
  filter with an invented word.send_document. This run produces the filter
  answer correctly and leaves the invoice unsorted. Same model, same prompts,
  same machine; the difference is sampling.
- So the honest statement is: at 3B, expect one to two files out of five,
  roughly one of which is right.

Cost
- Planning 244s per job here, against 145s for 1.5B on a 2-core box.
- llama-bench on this box: 3B 39.4 tok/s prompt / 4.06 tok/s generation;
  1.5B 79.4 / 8.11. Twice as slow per token, so at equal hardware the 1.5B is
  roughly half the cost per job.
- The 1.5B verified figures do not change with the new checks: its only
  produced file was the invoice workbook, which the existing check already
  called wrong.

Failures that repeat at both sizes, and are not about size
- A CSV sent to the Excel tool ("Expected .xlsx or .xlsm file, got: .csv").
- A .md path sent to the Word tool ("Output must be DOCX").
- A sort that names the source column instead of the aggregate's own column.
- The shipped example either degenerates into repeated steps (1.5B) or does
  not finish inside 600s (3B). It is the only brief that asks for seven files.

Caveats
- One machine, shared with other work: absolute seconds vary between polls.
  The token rates above are the fair comparison.
- Cases ran one per process so a runner restart could not lose the set; each
  row is an unchanged job and the totals are the sum of those runs.
- The content checks are the briefs' own requirements, worked out by hand:
  invoice totals per client (2000, 430.5, 2250.75, sorted), products with
  Units >= 100, stock items below 25 with quantities, contacts without blank
  emails, and the four regional totals for the sales pack (3530, 2740, 2240,
  930). Each has a unit test.
