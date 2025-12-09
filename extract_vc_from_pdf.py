import os
import sys
import re
import json
import csv
from typing import List, Tuple, Optional

import pdfplumber
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

client: Optional[OpenAI] = None
if OPENAI_API_KEY:
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

VC_KEYWORDS = [
    "创投",
    "创业投资",
    "投资",
    "投资公司",
    "投资基金",
    "风险投资",
    "风投",
    "资本",
    "基金",
    "高新投",
    "科投",
    "创富",
    "高科",
    "天使",
]

ROLE_KEYWORDS = {
    "board": ["董事", "董事长"],
    "supervisor": ["监事"],
    "executive": ["高级管理人员", "高管", "总经理", "副总", "经理", "执行董事"],
}


def extract_pdf(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        with tqdm(total=total_pages, desc=f"Extracting {os.path.basename(path)}", unit="page") as pbar:
            for page in pdf.pages:
                text += page.extract_text() or ""
                pbar.update(1)
    return text


def extract_code_and_name(filename: str, text: str) -> Tuple[str, str]:
    code = ""
    name = ""

    m_code_file = re.search(r"(\d{6})", filename)
    if m_code_file:
        code = m_code_file.group(1)

    # Try to pull company short name from filename segments like 002009.SZ_华兰生物：xxx.pdf
    if "_" in filename:
        tail = filename.split("_", 1)[1]
        tail = tail.split(":", 1)[0]
        tail = tail.split("：", 1)[0]
        tail = re.sub(r"-\d+.*", "", tail)
        tail = tail.strip(" _-")
        if 2 <= len(tail) <= 12:
            name = tail

    if not code:
        m_code_text = re.search(r"(?:股票代码|证券代码)[:：]?\s*(\d{6})", text)
        if m_code_text:
            code = m_code_text.group(1)

    if not name:
        m_name_text = re.search(r"(?:公司简称|发行人)[:：]?\s*([^\s\(\)；;，、\n]{2,12})", text)
        if m_name_text:
            name = m_name_text.group(1)

    return code, name


def extract_vc_candidates(text: str) -> List[Tuple[str, float]]:
    """
    Heuristic extraction of VC candidates and percents:
    - Match lines with VC keywords and a nearby percent.
    - Prefer percentages <= 100.
    """
    name_pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\\-]{2,50}?(?:基金|创投|资本|投资公司|投资|创业投资|合伙|风投))"
    )
    percent_pattern = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")
    hits: List[Tuple[str, float]] = []

    for line in text.splitlines():
        if not any(k in line for k in VC_KEYWORDS):
            continue

        perc = None
        perc_matches = percent_pattern.findall(line)
        if perc_matches:
            try:
                perc_candidates = [float(p) for p in perc_matches if float(p) <= 100.0]
                if perc_candidates:
                    perc = max(perc_candidates)
            except ValueError:
                perc = None

        m_name = name_pattern.search(line)
        if not m_name:
            continue
        vc_name = m_name.group(1)
        hits.append((vc_name, perc if perc is not None else 0.0))

    # Sort: highest percent first, then original order
    hits_sorted = sorted(hits, key=lambda x: x[1], reverse=True)
    return hits_sorted


def pick_best_candidate(candidates: List[Tuple[str, float]]) -> Tuple[str, float]:
    if not candidates:
        return "", 0.0
    return candidates[0]


def flag_role(text: str, vc_name: str, keywords: List[str]) -> str:
    if not vc_name:
        return "0"
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if vc_name in line and any(k in line for k in keywords):
            return "1"
        if vc_name in line:
            if idx > 0 and any(k in lines[idx - 1] for k in keywords):
                return "1"
            if idx + 1 < len(lines) and any(k in lines[idx + 1] for k in keywords):
                return "1"
    return "0"


def normalize_percent_str(val: Optional[str], fallback: float) -> str:
    if val is None or val == "":
        pct = fallback
    else:
        cleaned = str(val).replace("%", "").strip()
        try:
            pct = float(cleaned)
        except ValueError:
            pct = fallback
    pct = max(0.0, min(100.0, pct))
    return f"{pct:.2f}%"


def rule_based_result(text: str, filename: str) -> dict:
    code, company = extract_code_and_name(filename, text)
    candidates = extract_vc_candidates(text)
    vc_name, vc_percent = pick_best_candidate(candidates)

    board_flag = flag_role(text, vc_name, ROLE_KEYWORDS["board"])
    supervisor_flag = flag_role(text, vc_name, ROLE_KEYWORDS["supervisor"])
    exec_flag = flag_role(text, vc_name, ROLE_KEYWORDS["executive"])

    percent_str = normalize_percent_str(str(vc_percent), 0.0) if vc_name else "0%"

    return {
        "股票代码": code,
        "公司简称": company,
        "最大风投机构名称": vc_name,
        "最大风投机构股权占比": percent_str,
        "风投机构是否委派董事": board_flag,
        "风投机构是否委派监事": supervisor_flag,
        "风投机构是否委派高管": exec_flag,
        "风投机构委派董事的类型": "",
        "风投机构委派监事的类型": "",
        "风投机构委派高管的类型": "",
    }, candidates


def build_llm_prompt(text: str, filename: str, rule_guess: dict, candidates: List[Tuple[str, float]]) -> str:
    # Collect a focused excerpt around VC mentions to keep context small
    focus_lines = []
    for line in text.splitlines():
        if any(k in line for k in VC_KEYWORDS) or "%" in line:
            focus_lines.append(line.strip())
        if len(focus_lines) >= 120:  # cap lines
            break

    cand_str = "; ".join([f"{n} ({p:.2f}%)" for n, p in candidates[:5]]) or "无"
    guess_str = json.dumps(rule_guess, ensure_ascii=False)

    return f"""
你是资本市场研究助手。请阅读下方招股说明书片段，结合文件名信息，输出一个 JSON（不要 Markdown 代码块）。字段要求：
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
规则初步提取: {guess_str}
候选风投列表: {cand_str}
招股说明书片段:
{os.linesep.join(focus_lines)}
"""


def ask_llm(text: str, filename: str, rule_guess: dict, candidates: List[Tuple[str, float]]) -> Optional[dict]:
    if client is None:
        print("[LLM] Skipped (no API key). Using rule-based result.")
        return None

    prompt = build_llm_prompt(text, filename, rule_guess, candidates)
    print(f"[LLM] Calling model='{OPENAI_MODEL}' for file='{filename}'")
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    json_str = response.choices[0].message.content or ""
    cleaned = json_str.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        parsed = json.loads(cleaned)
        print(f"[LLM] Received response for '{filename}'")
        return parsed
    except json.JSONDecodeError:
        print("[ERROR] Failed to parse JSON from model response, falling back to rule-based result")
        print(f"Raw response:\n{json_str}")
        return None


def merge_results(rule: dict, llm: Optional[dict]) -> dict:
    if not llm:
        return rule

    result = dict(rule)

    # Replace fields if llm provided non-empty
    for key in ["股票代码", "公司简称", "最大风投机构名称"]:
        val = llm.get(key, "")
        if isinstance(val, str) and val.strip():
            result[key] = val.strip()

    # Percent normalization
    llm_pct = llm.get("最大风投机构股权占比", "")
    if isinstance(llm_pct, str) and llm_pct.strip():
        result["最大风投机构股权占比"] = normalize_percent_str(llm_pct, 0.0)

    # Flags
    for key in ["风投机构是否委派董事", "风投机构是否委派监事", "风投机构是否委派高管"]:
        val = str(llm.get(key, "")).strip()
        if val in {"0", "1"}:
            result[key] = val

    # Types
    for key in ["风投机构委派董事的类型", "风投机构委派监事的类型", "风投机构委派高管的类型"]:
        val = llm.get(key, "")
        if isinstance(val, str):
            result[key] = val.strip()

    return result


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

            rule_guess, candidates = rule_based_result(pdf_text, fn)
            llm_result = ask_llm(pdf_text, fn, rule_guess, candidates)
            merged = merge_results(rule_guess, llm_result)

            results.append(merged)

            if writer is None:
                csv_file = open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig")
                writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
                writer.writeheader()

            writer.writerow(merged)
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
    print("VC IPO Extractor (hybrid: rules + optional LLM)")
    if client:
        print(f"Model: {OPENAI_MODEL}")
        if OPENAI_BASE_URL:
            print(f"Base URL: {OPENAI_BASE_URL}")
    else:
        print("LLM: disabled (no API key)")
    print(LINE)

    rows = collect_results()
    print(f"[CSV] Finished writing {len(rows)} row(s) to '{OUTPUT_CSV}'")
