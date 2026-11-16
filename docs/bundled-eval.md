Bundled model eval — Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
Cases: 5
Validated first try:  4 of 5 (80%)
Ran to completion:    0 of 5 (0%)

case                           valid  ran    time  note
sales-pack (shipped example)   no     no     384s  PlanValidationError: Plan validation failed: step 'evidence' must write inside output/ but uses: /tmp/bundled-eval-91xwk7ya/sales-pack/evidence/sales-report.png
invoice totals by client       yes    no     101s  failed: failed steps sort_totals
                                                   excel.read_table → table.filter → table.aggregate → table.sort → excel.create_workbook
filter products by units       yes    no     145s  no such action: word.send_document
                                                   excel.read_table → table.filter → table.select → excel.read_table → table.filter → table.select → word.create_document → word.send_document
clean the contact list         yes    no      58s  failed: failed steps read_contacts
                                                   excel.read_table → table.filter → excel.create_workbook
reorder note from stock        yes    no      63s  failed: failed steps create_markdown
                                                   excel.read_table → table.filter → word.create_document
