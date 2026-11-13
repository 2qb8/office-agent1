from docx import Document

doc = Document()

doc.add_heading("Office Agent Test", level=1)
doc.add_paragraph(
    "This document was generated automatically."
)

doc.add_heading("Results", level=2)

table = doc.add_table(rows=2, cols=2)
table.cell(0, 0).text = "Task"
table.cell(0, 1).text = "Status"
table.cell(1, 0).text = "DOCX generation"
table.cell(1, 1).text = "OK"

doc.save("output/test.docx")

print("Created output/test.docx")