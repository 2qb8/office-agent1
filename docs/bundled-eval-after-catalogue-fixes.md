Bundled model eval — after the catalogue fixes
Changes under test: unknown action names are rejected by the validator before
anything runs, the planner prompt carries a format table (which tool reads and
writes xlsx, docx, csv/tsv, md/txt), the aggregate column naming rule, and
text.read_table exists so a CSV can be read as headers and rows.
Repair loop: on. Content checks: on, every case.

              1.5B (before)   1.5B (after)   3B (before)   3B (after)
Validated       4 of 5          3 of 5         4 of 5        4 of 5
Produced file   1 of 5          2 of 5         2 of 5        3 of 5
Contents right  0 of 1          1 of 2         1 of 2        1 of 3
All in          217s/job        221s/job       265s/job      243s/job

Qwen2.5-1.5B-Instruct-Q4_K_M, plan 194s/job, total 221s/job
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   no     no   -            0   600s   600s  no reply within 600s
invoice totals by client       yes    yes  wrong        0   108s   108s  wrote invoice_summary.xlsx
                                                                       check: the summary has no data rows
                                                                       excel.read_table → table.filter → table.sort → table.select → excel.create_workbook
filter products by units       yes    yes  right        0   109s   109s  wrote document.docx
                                                                       check: document.docx matches the brief
                                                                       excel.read_table → table.filter → excel.read_table → word.create_document
clean the contact list         no     no   -            0    68s    68s  PlanValidationError: step 'remove_empty_emails' references '$contacts', which is not an earlier step
reorder note from stock        yes    no   -            2    84s   219s  failed steps filter_stock
                                                                       excel.inspect → table.filter → word.create_document

Qwen2.5-3B-Instruct-Q4_K_M, plan 243s/job, total 243s/job (no repair ever ran)
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   yes    no   -            0   529s   529s  12 steps, failed at create_docx_table_xlsx
                                                                       excel.read_table → table.filter → table.aggregate → excel.create_workbook → word.create_document → text.write ×4 → filesystem.copy_file → screenshot.workbook → word.set_metadata
invoice totals by client       yes    yes  wrong        0   155s   155s  wrote summarised_invoices.xlsx
                                                                       check: totals are not sorted largest first
filter products by units       yes    yes  right        0   218s   218s  wrote filtered_products.xlsx, products_to_send.docx
                                                                       check: filtered_products.xlsx matches the brief
clean the contact list         yes    yes  wrong        0   131s   131s  wrote cleaned_contacts.csv
                                                                       check: missing Ana Silva, Cara Diaz and still has Ben Okafor, Dan Wu
                                                                       text.read_table → table.filter → text.write
reorder note from stock        no     no   -            0   184s   184s  PlanValidationError: unknown action 'text.append_elements'. text has: write, read, read_table, verify

What moved
- The CSV path exists and gets used: the 3B now reads contacts.csv with
  text.read_table and writes a CSV with text.write. Its filtering is wrong
  (blank emails survive), but the catalogue mistake is gone.
- The shipped example stops being a planning failure at 3B: twelve sensible
  steps covering all seven outputs, 529s, instead of a 600s timeout or sixteen
  repeated steps. It fails later, at a docx table read through excel.
- The validator rejects unknown actions before execution: the 3B's
  text.append_elements is now a plan rejection at 184s, not a mid-run failure.
  It is still not repaired, because validation happens before the repair loop.
- filter products is right at both sizes now, on contents, where the 1.5B had
  never produced anything for it.

What did not move
- Ordering: the invoice totals are right and unsorted at 3B, and empty at
  1.5B. The brief says "sorted from the largest total down".
- Row selection: the 3B keeps the blank-email contacts.
- Wrong tool for a table inside a docx: excel.read_table on summary.docx.
- Repair fixed nothing in either set: no revision ran at 3B, and the 1.5B's
  two attempts on the stock brief did not rescue it.
- The shipped example still produces no output at either size.

Cost
- 1.5B: 194s planning, 221s all in per job. 3B: 243s planning, 243s total.
- Unchanged from earlier: 3B is about twice as slow per generated token, so
  at equal hardware the 1.5B costs roughly half.

Caveats
- One shared machine; the wall clock varies with load and the runner restarted
  several times, so cases were run one per process and the totals sum those
  runs. Absolute seconds are not portable.
- Three of five 3B cases produced files, so two of them are verified wrong;
  the two without output are failures of execution, not measured content.
- Sampling varies between runs: the earlier 3B pass had the invoice file and no
  filter answer, this one has both plus a wrong contacts file.
