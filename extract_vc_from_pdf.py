import os
import sys
import re
import csv
import pdfplumber
from tqdm import tqdm

INPUT_DIR = "input/"
OUTPUT_CSV = "results.csv"
LINE = "-" * 60

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


def extract_code_and_name(filename: str, text: str) -> tuple[str, str]:
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


def extract_vc_candidates(text: str):
    """
    Heuristic extraction of VC name and percent:
    - Match lines with VC keywords and a nearby percent.
    - Prefer percentages <= 100.
    - If multiple hits, pick the highest percent; otherwise fall back to the first VC-like name.
    """
    name_pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,50}?(?:基金|创投|资本|投资公司|投资|创业投资|合伙|风投))"
    )
    percent_pattern = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")
    line_hits = []

    for line in text.splitlines():
        if not any(k in line for k in VC_KEYWORDS):
            continue

        perc = None
        perc_matches = percent_pattern.findall(line)
        if perc_matches:
            try:
                perc = max(float(p) for p in perc_matches if float(p) <= 100.0)
            except ValueError:
                perc = None

        m_name = name_pattern.search(line)
        if not m_name:
            continue

        vc_name = m_name.group(1)
        line_hits.append((vc_name, perc))

    if not line_hits:
        return "", 0.0

    with_percent = [h for h in line_hits if h[1] is not None]
    if with_percent:
        best = max(with_percent, key=lambda x: x[1])
        return best[0], best[1]

    return line_hits[0][0], 0.0


def flag_role(text: str, vc_name: str, keywords: list[str]) -> str:
    if not vc_name:
        return "0"
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if vc_name in line and any(k in line for k in keywords):
            return "1"
        # Look at neighboring lines for scattered mentions
        if vc_name in line:
            if idx > 0 and any(k in lines[idx - 1] for k in keywords):
                return "1"
            if idx + 1 < len(lines) and any(k in lines[idx + 1] for k in keywords):
                return "1"
    return "0"


def analyze_prospectus(text: str, filename: str) -> dict:
    code, company = extract_code_and_name(filename, text)
    vc_name, vc_percent = extract_vc_candidates(text)

    board_flag = flag_role(text, vc_name, ROLE_KEYWORDS["board"])
    supervisor_flag = flag_role(text, vc_name, ROLE_KEYWORDS["supervisor"])
    exec_flag = flag_role(text, vc_name, ROLE_KEYWORDS["executive"])

    percent_str = f"{vc_percent:.2f}%" if vc_name else "0%"
    if vc_percent == 0.0 and not vc_name:
        percent_str = "0%"

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
    }


def collect_results():
    results = []
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".pdf")]
    total = len(files)
    print(LINE)
    print(f"Found {total} PDF file(s) in '{INPUT_DIR}'")
    print(LINE)

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
            row = analyze_prospectus(pdf_text, fn)
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
    print("VC IPO Extractor (rule-based)")
    print(LINE)

    rows = collect_results()
    print(f"[CSV] Finished writing {len(rows)} row(s) to '{OUTPUT_CSV}'")
