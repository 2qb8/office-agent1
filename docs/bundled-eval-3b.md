Bundled model eval — Qwen2.5-3B-Instruct-Q4_K_M.gguf (1,929,903,264 bytes, same Q4_K_M setup as the 1.5B run)
Repair loop: on
Cases: 5
Validated first try:  4 of 5 (80%) — the fifth never returned a plan
Produced output:      1 of 5 (20%) — a non-empty file, contents not implied
Contents right:       0 checked (the only produced case has no content check)
Planning:          1,288s for five jobs, 258s each
Everything after:    436s in total, 87s per job
All in:            1,724s for five jobs, 345s each

case                           valid  out  content    fix   plan  total  note
sales-pack (shipped example)   no     no   -            0   600s   600s  LLMError: no reply within 600s; the plan was never returned, so nothing was validated
invoice totals by client       yes    no   -            2   193s   520s  sort_totals: Column 'Amount' not found. Available columns: ['sum(Amount)']
                                                                       excel.read_table → table.filter → table.aggregate → table.sort → excel.create_workbook
filter products by units       yes    yes  unchecked    0   195s   195s  4 steps, wrote filtered_products.xlsx, products_to_send.docx
                                                                       excel.read_table → table.filter → excel.create_workbook → word.create_document
clean the contact list         yes    no   -            0   132s   241s  read_contacts: excel.read_table got a .csv
                                                                       excel.read_table → table.filter → excel.create_workbook
reorder note from stock        yes    no   -            0   168s   168s  reorder_note: Output must be DOCX (.md path)
                                                                       excel.read_table → table.filter → word.create_document → text.write

Did the tool-choice and argument mistakes disappear? No — one of five improved.

- filter products: fixed. The 1.5B invented word.send_document and wrote nothing;
  the 3B planned four steps, ran them without a repair, and wrote both a
  workbook and the Word document. Its contents are unchecked.
- invoice totals: closer, still broken. The 1.5B aggregated the wrong column
  (sum(Client)); the 3B aggregated the right one (sum(Amount)) and then sorted
  by 'Amount', so the next step could not find it. Two repairs repeated the
  same mistake.
- clean the contact list: unchanged. Both sizes call excel.read_table on a .csv,
  which the tool refuses.
- reorder note from stock: unchanged in effect. The 3B adds a text.write step
  but still builds the .md with word.create_document, which refuses anything
  but .docx.
- sales-pack: worse. The 1.5B produced a degenerate sixteen-step plan and was
  rejected by validation; the 3B's client gave up after 600s with no reply, so
  there is no 3B plan to judge at all.

Time, measured two ways
- This box, llama-bench, 8 threads, shared VM: 1.5B 79.4 tok/s prompt and
  8.11 tok/s generation; 3B 39.4 and 4.06. The 3B is twice as slow per token
  on identical hardware.
- Wall clock per job: 3B 345s all in (258s planning), against 1.5B 217s all in
  (145s planning) measured earlier on a 2-core box. The 3B number comes from a
  faster box, so the equal-hardware cost of the 1.5B is roughly half, matching
  the token rates.
- Repair is the expensive part of the 3B run: the invoice case spent 327s of
  its 520s being corrected, and still failed.

Accuracy per minute: the 3B fixed one brief and broke one, while planning cost
roughly twice as much per job at equal hardware. Nothing in this set produced
a verified right answer at either size.

Caveats
- The machine changed between runs (2 vCPU for the 1.5B numbers, 8 vCPU and
  16 GB for these), and it is shared, so absolute seconds are not portable.
  The token rates above are the fair comparison.
- Cases were run one per process so a runner restart could not lose the whole
  set; each row is an unchanged job, and the totals are the sum of those runs.
- Only the invoice case has a content check, and it produced no file here, so
  this run verifies nothing about correctness of contents.
