# VC IPO Extractor

Extract key venture capital information from IPO prospectus PDFs using an OpenAI-compatible LLM.

## Setup
1) Create and activate a virtual environment.
2) Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3) Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL` (if not using api.openai.com; include `/v1` if required)
   - `OPENAI_MODEL` (your deployed model name)

## Usage
1) Drop prospectus PDFs into the `input/` folder.
2) Run the extractor:
   ```bash
   python extract_vc_from_pdf.py
   ```
3) Watch the console for per-file extraction progress and LLM calls. Results stream into `results.csv` as each file finishes.

## Output
- `results.csv` contains the structured fields: 股票代码, 公司简称, 最大风投机构名称, 最大风投机构股权占比, 风投机构是否委派董事, 风投机构是否委派监事, 风投机构是否委派高管, 风投机构委派董事的类型, 风投机构委派监事的类型, 风投机构委派高管的类型.

## Notes
- The prompt expects Chinese-language prospectus content and uses the filename to help infer 股票代码/公司简称.
- If `results.csv` is open in another program (e.g., Excel), close it before running; the script clears the file at start.
