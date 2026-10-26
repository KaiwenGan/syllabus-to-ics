#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从教务系统导出的课表文本/PDF 抽出课程条目，生成配置草稿。

覆盖国内教务系统最常见的“格子文本”格式（正方 / URP / 强智等）：

    星期一
    1-2
    高等数学AI
    周数: 4-6周(双),7-17周/校区: 主校区/地点: 教2楼205/教师: 陈立/教学班组成:.../学分:4.0

也支持同一节次格子里并排多门课（单双周轮换）。

用法：
    python3 scripts/parse_text.py --pdf 课表.pdf -o draft.config.json
    python3 scripts/parse_text.py --txt 课表.txt -o draft.config.json
    pdftotext -layout 课表.pdf - | python3 scripts/parse_text.py --stdin -o draft.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys

WD = {"星期一": 1, "星期二": 2, "星期三": 3, "星期四": 4, "星期五": 5,
      "星期六": 6, "星期日": 7, "星期天": 7}
PERIOD_RE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")
DETAIL_KEYS = ("周数", "校区", "地点", "教师", "教学班", "选课备注", "学分")


def read_pdf(path: str) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise SystemExit("读取 PDF 需要 PyMuPDF：pip install pymupdf\n"
                         "或者先转成文本：pdftotext -layout 课表.pdf - | "
                         "python3 scripts/parse_text.py --stdin")
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc)


def normalise(text: str) -> list[str]:
    """清洗 + 修复 PDF 折行。

    折行只认三种明确特征，避免把下一门课的名字误当成续行吞掉：
      1. 本行以 “:” 开头（上一行断在字段名后，如 “学分” / “学分:”）；
      2. 上一行以字段名结尾、后面没有值；
      3. 上一行是 “其他课程” 列表且没有以分号收尾。
    """
    lines = [ln.strip() for ln in text.replace("\u3000", " ").splitlines()]
    merged: list[str] = []
    for ln in lines:
        if not ln:
            continue
        prev = merged[-1] if merged else ""
        tail_key = re.search(r"(周数|校区|地点|教师|教学班组成|选课备注|学分)\s*[:：]?\s*$", prev)
        if prev and (ln.startswith(":") or tail_key
                     or (prev.startswith("其他课程") and not prev.endswith((";", "；")))):
            merged[-1] = prev + ln
        else:
            merged.append(ln)
    return merged


def grab(detail: str, key: str) -> str:
    m = re.search(key + r"\s*[:：]\s*([^/]*)", detail)
    return m.group(1).strip() if m else ""


def parse(lines: list[str]):
    courses, others, warnings = [], [], []
    cur_wd = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln in WD or ln.rstrip("：:") in WD:
            cur_wd = WD[ln.rstrip("：:")]
            i += 1
            continue
        m = PERIOD_RE.match(ln)
        if m and cur_wd:
            period = f"{int(m.group(1))}-{int(m.group(2))}"
            j = i + 1
            # 同一节次格子里可能并列多门课
            while j + 1 < len(lines):
                name = lines[j]
                detail = lines[j + 1] if j + 1 < len(lines) else ""
                if not detail.startswith("周数"):
                    break
                courses.append({
                    "weekday": cur_wd,
                    "period": period,
                    "name": name,
                    "weeks": grab(detail, "周数"),
                    "campus": grab(detail, "校区"),
                    "location": grab(detail, "地点"),
                    "teacher": grab(detail, "教师"),
                    "note": (grab(detail, "教学班组成") and
                             f"教学班：{grab(detail, '教学班组成')}") or "",
                })
                j += 2
            i = j
            continue
        if ln.startswith("其他课程"):
            body = ln.split("：", 1)[-1]
            for item in re.split(r"[;；]", body):
                item = item.strip()
                if not item or item.startswith(":") or "打印时间" in item:
                    continue
                wm = re.search(r"/([^/]+)/", item)
                others.append({"raw": item, "weeks": wm.group(1) if wm else ""})
            i += 1
            continue
        i += 1

    for o in others:
        short = re.split(r"\(共", o["raw"])[0]
        if "军训" in o["raw"]:
            warnings.append(
                f"「{short}」（{o['weeks']}）：没有具体钟点，按全天事件处理——"
                "请在配置的 allday 里补上起止日期（军训通常跨两周）。")
        elif "/无" in o["raw"] or o["raw"].rstrip().endswith("/无"):
            warnings.append(
                f"「{short}」（{o['weeks']}）只有周次、没有节次和地点，未排入日历；"
                "若是线上/实践学时，请按学院通知自行决定是否补全天事件。")
    return courses, others, warnings


def main():
    ap = argparse.ArgumentParser(description="课表文本/PDF -> 配置草稿")
    ap.add_argument("--pdf")
    ap.add_argument("--txt")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("-o", "--out", default="draft.config.json")
    args = ap.parse_args()

    if args.pdf:
        text = read_pdf(args.pdf)
    elif args.txt:
        text = open(args.txt, encoding="utf-8").read()
    elif args.stdin:
        text = sys.stdin.read()
    else:
        raise SystemExit("请指定 --pdf / --txt / --stdin")

    courses, others, warnings = parse(normalise(text))
    if not courses:
        raise SystemExit("没解析到课程条目，请检查文本格式（需要“星期X / 节次 / 课程名 / 周数:…”结构）")

    periods = sorted({c["period"] for c in courses}, key=lambda p: int(p.split("-")[0]))
    draft = {
        "_comment": "由 parse_text.py 生成：请补齐 term.first_monday 与 periods 的作息时间后再运行 build.py",
        "calendar": {"name": "课表", "description": "", "timezone": "+08:00"},
        "term": {"first_monday": "", "weeks": 20},
        "seasons": {"winter_ranges": []},
        "periods": {p: {"summer": ["", ""], "winter": ["", ""]} for p in periods},
        "holidays": [],
        "alarm_minutes": 15,
        "courses": courses,
        "allday": [],
        "other_courses": others,
        "warnings": warnings,
    }
    open(args.out, "w", encoding="utf-8").write(json.dumps(draft, ensure_ascii=False, indent=2))
    print(f"✅ {len(courses)} 个上课时段 -> {args.out}")
    print(f"   涉及节次：{', '.join(periods)}（请在 periods 里填上这些节次的起止时间）")
    for w in warnings:
        print("   ⚠ " + w)
    print("   下一步：补 term.first_monday / periods / seasons，再跑 build.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
