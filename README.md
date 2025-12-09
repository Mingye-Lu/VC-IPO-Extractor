# VC IPO Extractor

Extract key venture capital information from IPO prospectus PDFs using a rule-based parser (no LLMs).

## Setup
1) Create and activate a virtual environment.
2) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
1) Drop prospectus PDFs into the `input/` folder.
2) Run the extractor:
   ```bash
   python extract_vc_from_pdf.py
   ```
3) Watch the console for per-file page-extraction progress. Results stream into `results.csv` as each file finishes.

## Output fields
- 股票代码
- 公司简称
- 最大风投机构名称
- 最大风投机构股权占比
- 风投机构是否委派董事
- 风投机构是否委派监事
- 风投机构是否委派高管
- 风投机构委派董事的类型
- 风投机构委派监事的类型
- 风投机构委派高管的类型

## Notes
- Heuristics use filename cues (6-digit code and company name) plus keyword/percentage searches in the text to infer the biggest VC holder and board/监事/高管 flags. Manual review is recommended for edge cases.
- If `results.csv` is open in another program (e.g., Excel), close it before running; the script clears the file at start.
