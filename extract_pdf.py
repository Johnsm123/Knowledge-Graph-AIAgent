import pdfplumber, os

pdfs = {
    'cg': '../2025-HEDIS-Coding-Guide_3.28.25.pdf',
    'ts': '../2025-hedis-quality-measures-tip-sheet.pdf',
    'bcs': '../MULTI-BC-CR-075425-24-CPN74734-Breast-Cancer-Screening-(BCS-E)-2025-CR_FINAL.pdf'
}

for key, path in pdfs.items():
    with pdfplumber.open(path) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
    out = f'{key}.txt'
    with open(out, 'w', encoding='utf-8', errors='replace') as f:
        f.write(text)
    print(f'{out} written: {len(text)} chars')
