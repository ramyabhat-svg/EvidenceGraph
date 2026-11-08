# scripts/pdf_spike.py   usage: python scripts/pdf_spike.py paper.pdf
import sys
import pdfplumber

with pdfplumber.open(sys.argv[1]) as pdf:
    for n, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ''
        tables = page.find_tables()
        print(f'--- page {n}: {len(text)} chars, {len(tables)} tables')
        for i, t in enumerate(tables):
            rows = t.extract()
            print(f'  table {i}: {len(rows)} rows x {len(rows[0]) if rows else 0} cols')
            for row in rows[:4]:
                print('   ', row)