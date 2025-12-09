import os
import sys
import json
import csv
import pdfplumber
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

client_config = {"api_key": OPENAI_API_KEY}
if OPENAI_BASE_URL:
    client_config["base_url"] = OPENAI_BASE_URL

client = OpenAI(**client_config)

INPUT_DIR = "input/"
OUTPUT_CSV = "results.csv"
LINE = "-" * 60


def extract_pdf(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        with tqdm(total=total_pages, desc=f"Extracting {os.path.basename(path)}", unit="page") as pbar:
            for page in pdf.pages:
                text += page.extract_text() or ""
                pbar.update(1)
    return text


def ask_llm(text, filename):
    print(f"[LLM] Calling model='{OPENAI_MODEL}' for file='{filename}'")
    prompt = f"""
你是资本市场研究助手。请阅读下方招股说明书文本，结合文件名信息，输出一个 JSON。字段要求：
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
风投派遣董监高包括直接或通过关联方委派。仅输出 JSON，不要附加说明或 Markdown。

文件名: {filename}
招股说明书正文:
{text}
"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    json_str = response.choices[0].message.content or ""
    cleaned = json_str.strip()

    # Remove common Markdown code fences like ```json ... ``` or ``` ... ```
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    print(f"[LLM] Received response for '{filename}'")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print("[ERROR] Failed to parse JSON from model response")
        print(f"Raw response:\n{json_str}")
        raise


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
            row = ask_llm(pdf_text, fn)
            results.append(row)

            if writer is None:
                fieldnames = list(row.keys())
                csv_file = open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig")
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
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
    print("VC IPO Extractor")
    print(f"Model: {OPENAI_MODEL}")
    if OPENAI_BASE_URL:
        print(f"Base URL: {OPENAI_BASE_URL}")
    print(LINE)

    rows = collect_results()
    print(f"[CSV] Finished writing {len(rows)} row(s) to '{OUTPUT_CSV}'")
