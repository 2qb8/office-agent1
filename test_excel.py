from pathlib import Path
import xlwings as xw


output = Path("output/test.xlsx").resolve()

app = xw.App(visible=False)

try:
    wb = app.books.add()

    sheet = wb.sheets[0]
    sheet.name = "Results"

    sheet["A1"].value = "Test"
    sheet["B1"].value = 123

    sheet["A2"].value = "Profit"
    sheet["B2"].formula = "=B1*2"

    wb.save(output)
    wb.close()

finally:
    app.quit()

print(f"Created: {output}")