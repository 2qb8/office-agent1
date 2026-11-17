Bundled model eval — validation failures now get one repair
Changes under test: a plan the validator refuses is sent back to the planner
once with the validator's message; the format and unknown-action errors are
classified as repairable for execution failures too.
Repair loop: on. Content checks: on. Cases run one per process.

              1.5B before   1.5B after   3B before   3B after
Validated       3 of 5        3 of 5       4 of 5      3 of 5
Produced file   2 of 5        1 of 5       3 of 5      3 of 5
Contents right  1 of 2        0 of 1       1 of 3      1 of 3
Planning        ~199s/job     199s/job     243s/job    255s/job
All in          ~221s/job     248s/job     243s/job    255s/job

Qwen2.5-1.5B-Instruct-Q4_K_M
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   no     no   -            0   600s   600s  no reply within 600s
invoice totals by client       yes    yes  wrong        0   113s   113s  wrote summary.xlsx
                                                                       check: the summary has no data rows
filter products by units       yes    no   -            2    91s   226s  failed steps filter_products
clean the contact list         no     no   -            1   117s   117s  rejected: unregistered tool 'text.read'; the revision was rejected too
reorder note from stock        yes    no   -            2    72s   183s  failed steps filter_stock

Qwen2.5-3B-Instruct-Q4_K_M
case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   yes    no   -            0   493s   493s  failed steps create_docx_table_xlsx (12-step plan)
invoice totals by client       yes    yes  wrong        0   157s   157s  wrote summarised_invoices.xlsx
                                                                       check: totals are not sorted largest first
filter products by units       yes    yes  right        0   196s   196s  wrote filtered_products.xlsx, products_to_send.docx
                                                                       check: filtered_products.xlsx matches the brief
clean the contact list         yes    yes  wrong        0   136s   136s  wrote cleaned_contacts.csv
                                                                       check: missing Ana Silva, Cara Diaz and still has Ben Okafor, Dan Wu
reorder note from stock        no     no   -            1   294s   294s  rejected: unknown action 'text.append_lines'; the revision was rejected too

Did it move the number? No.
- The mechanism works: both rejected cases went back to the planner with the
  validator's message, and the log shows "Repair attempt 1/1 after a rejected
  plan" followed by "The revised plan was rejected too".
- The models repeat the same mistake. The 1.5B sent 'text.read' as a tool
  name again (117s for two attempts); the 3B sent 'text.append_lines' again
  (294s against 184s before, so about 110s for the second call).
- So a rejection now costs one extra model call and the same outcome. At
  1.5B the count went from "one produced file, one checked, wrong" to "one
  produced file, checked, wrong"; at 3B it was unchanged at one of three.
- Everything else is sampling: 1.5B's filter case was right last run and
  failed this one, and the 3B reorder case is a rejection both times.

What it does buy
- A better model gets a real second chance at no design cost: the message
  names the offending step and lists the actions the tool does have
  ("text has: write, read, read_table, verify"), which is the kind of
  correction a 7B+ model can act on.
- Rejections are recorded: plan.json and the eval's fix column count the
  attempt even when the answer is refused, so the cost is visible.
- Execution-time format errors ("Output must be DOCX", "Expected .xlsx")
  are now repairable, so the existing loop can switch the writer instead of
  giving up. Neither model produced one in these runs; the 3B reorder case
  was caught before execution.

Caveats
- One shared machine, cases run one per process, totals sum those runs.
- Three of five 3B cases produced files, so two are verified wrong; the two
  without output are execution failures, not measured content.
- The "before" columns come from the previous run of the same eval, not from
  a paired run in the same session, so sampling differences are part of the
  gap in both directions.
