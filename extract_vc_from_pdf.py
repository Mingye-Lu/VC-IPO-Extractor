import os
import sys
import json
import csv
import pdfplumber
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

if not OPENAI_API_KEY:
    print("[ERROR] OPENAI_API_KEY is required for LLM extraction.")
    sys.exit(1)

client_config = {"api_key": OPENAI_API_KEY}
if OPENAI_BASE_URL:
    client_config["base_url"] = OPENAI_BASE_URL
client = OpenAI(**client_config)

INPUT_DIR = "input/"
OUTPUT_CSV = "results.csv"
LINE = "-" * 60

FIELDNAMES = [
    "股票代码",
    "公司简称",
    "最大风投机构名称",
    "最大风投机构股权占比",
    "风投机构是否委派董事",
    "风投机构是否委派监事",
    "风投机构是否委派高管",
    "风投机构委派董事的类型",
    "风投机构委派监事的类型",
    "风投机构委派高管的类型",
]


def extract_pdf(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        with tqdm(total=total_pages, desc=f"Extracting {os.path.basename(path)}", unit="page") as pbar:
            for page in pdf.pages:
                text += page.extract_text() or ""
                pbar.update(1)
    return text


def build_prompt(text: str, filename: str) -> str:
    return f"""
你是资本市场研究助手。请阅读下方招股说明书全文，结合文件名信息，输出一个 JSON（不要 Markdown 代码块）。字段要求：
- "股票代码": 从正文或文件名提取，6位数字；无法确定则空字符串。
- "公司简称": 从正文或文件名提取；无法确定则空字符串。
- "最大风投机构名称": 只填风投/创投机构名称（非自然人、非产业方）。若无风投股东填""或"（无）"。
- "最大风投机构股权占比": 该风投持股比例，形式如"8.00%"；若无填"0%"。
- "风投机构是否委派董事": 若任一风投派出董事填"1"，否则填"0"。
- "风投机构是否委派监事": 若任一风投派出监事填"1"，否则填"0"。
- "风投机构是否委派高管": 若任一风投派出高管填"1"，否则填"0"。
- "风投机构委派董事的类型": 填"财务型"/"技术型"/"复合型"；无则空。
- "风投机构委派监事的类型": 同上；无则空。
- "风投机构委派高管的类型": 同上；无则空。

类型判别：仅金融/投资背景为"财务型"；仅技术/研发背景为"技术型"；兼具或多人各占一种为"复合型"。
风投派遣董监高包括直接或通过关联方委派。只输出 JSON。

文件名: {filename}
招股说明书全文:
{text}
"""


def parse_json_response(raw: str, filename: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    parsed = json.loads(cleaned)
    print(f"[LLM] Parsed row for '{filename}': {parsed}")
    return parsed


def ask_llm_non_stream(prompt: str, filename: str) -> dict:
    print(f"[LLM] Fallback (non-stream) call for file='{filename}'")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = resp.choices[0].message.content or ""
    print(raw)
    return parse_json_response(raw, filename)


def ask_llm_stream(text: str, filename: str) -> dict:
    prompt = build_prompt(text, filename)
    print(f"[LLM] Calling model='{OPENAI_MODEL}' for file='{filename}' (streaming)...")
    chunks = []
    try:
        stream = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            content = delta.content or ""
            if content:
                print(content, end="", flush=True)
                chunks.append(content)
        print()  # newline after stream
        raw = "".join(chunks)
        return parse_json_response(raw, filename)
    except Exception as exc:
        print(f"[LLM][WARN] Streaming failed for '{filename}': {exc}")
        return ask_llm_non_stream(prompt, filename)


def collect_results():
    results = []
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".pdf")]
    total = len(files)
    print(LINE)
    print(f"Found {total} PDF file(s) in '{INPUT_DIR}'")
    print(LINE)

    # Clear any existing results file before writing new rows
    if os.path.exists(OUTPUT_CSV):
        try:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig"):
                pass
            print(f"[CSV] Cleared existing '{OUTPUT_CSV}'")
        except PermissionError:
            print(f"[ERROR] Cannot clear '{OUTPUT_CSV}'. Close any program using it (e.g., Excel) and rerun.")
            sys.exit(1)

    writer = None
    csv_file = None

    try:
        for fn in files:
            print(f"[PDF] Processing '{fn}'")
            pdf_text = extract_pdf(os.path.join(INPUT_DIR, fn))
            row = ask_llm_stream(pdf_text, fn)
            results.append(row)

            if writer is None:
                csv_file = open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig")
                writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
                writer.writeheader()

            writer.writerow(row)
            if csv_file:
                csv_file.flush()

            print(f"[DONE] Finished '{fn}'")
            print(LINE)
    finally:
        if csv_file:
            csv_file.close()

    return results


if __name__ == "__main__":
    print(LINE)
    print("VC IPO Extractor (LLM full-text, streaming)")
    print(f"Model: {OPENAI_MODEL}")
    if OPENAI_BASE_URL:
        print(f"Base URL: {OPENAI_BASE_URL}")
    print(LINE)

    rows = collect_results()
    print(f"[CSV] Finished writing {len(rows)} row(s) to '{OUTPUT_CSV}'")
