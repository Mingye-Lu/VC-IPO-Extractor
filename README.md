# VC IPO Extractor

Extract key venture capital information from IPO prospectus PDFs using a hybrid approach: fast rule-based heuristics with an optional OpenAI-compatible LLM refinement.

## Setup
1) Create and activate a virtual environment.
2) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3) (Optional for LLM refinement) Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL` (if not using api.openai.com; include `/v1` if required)
   - `OPENAI_MODEL` (your deployed model name)

Without an API key, the tool runs in rules-only mode.

## Usage
1) Drop prospectus PDFs into the `input/` folder.
2) Run the extractor:
   ```bash
   python extract_vc_from_pdf.py
   ```
3) Watch the console for per-file page-extraction progress. Results stream into `results.csv` as each file finishes.

## How it works
- **Rules pass**: filename/code regex + keyword/percentage heuristics to pick top VC holder; basic detection of 董事/监事/高管 flags around the VC name.
- **Optional LLM pass**: a concise prompt with candidates and rule guess to refine the JSON row; results are merged with validation (percent normalized, flags limited to 0/1).
- **Output fields**: 股票代码, 公司简称, 最大风投机构名称, 最大风投机构股权占比, 风投机构是否委派董事, 风投机构是否委派监事, 风投机构是否委派高管, 风投机构委派董事的类型, 风投机构委派监事的类型, 风投机构委派高管的类型.

## Notes
- Heuristics are intentionally conservative; review edge cases manually.
- If `results.csv` is open in another program (e.g., Excel), close it before running; the script clears the file at start.
