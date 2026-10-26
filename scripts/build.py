#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课表配置 -> .ics + 核对报告（+ 可选 HTML 总表）。

用法：
    python3 scripts/build.py --config assets/example.config.json --out schedule.ics
    python3 scripts/build.py -c cfg.json -o s.ics -r report.md --html overview.html

配置格式见 README.md / assets/example.config.json。
核心原则：只按配置里给的节次与作息换算，缺字段直接报错，不做任何推测。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from icsgen import IcsBuilder, validate  # noqa: E402

WD_CN = "一二三四五六日"
WD_MAP = {"周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 7,
          "星期一": 1, "星期二": 2, "星期三": 3, "星期四": 4, "星期五": 5, "星期六": 6, "星期日": 7,
          "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7,
          "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


def parse_weekday(v) -> int:
    if isinstance(v, int):
        if 1 <= v <= 7:
            return v
        raise ValueError(f"weekday 超出 1-7: {v}")
    s = str(v).strip()
    if s.isdigit():
        return parse_weekday(int(s))
    key = s.lower()
    if key in WD_MAP:
        return WD_MAP[key]
    raise ValueError(f"无法识别 weekday: {v}")


def parse_weeks(text: str) -> list[int]:
    """解析周次表达式。支持：
    4-6周(双),7-17周 / 第5周 / 5周,9-15周(单) / 1-16 / 3,5,7 / 1-16(odd)
    """
    out: set[int] = set()
    for part in re.split(r"[,，;；、]", str(text)):
        p = part.strip()
        if not p:
            continue
        parity = None
        for token, val in (("(双)", "even"), ("(单)", "odd"), ("(even)", "even"),
                           ("(odd)", "odd"), ("单周", "odd"), ("双周", "even")):
            if token in p:
                parity = val
                p = p.replace(token, "")
        p = p.replace("第", "").replace("周", "").strip()
        if "-" in p:
            a, b = p.split("-")[:2]
            rng = range(int(a), int(b) + 1)
        else:
            rng = [int(p)]
        for w in rng:
            if parity == "even" and w % 2:
                continue
            if parity == "odd" and not w % 2:
                continue
            out.add(w)
    if not out:
        raise ValueError(f"周次解析为空: {text}")
    return sorted(out)


def parse_hhmm(s: str):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s.strip())
    if not m:
        raise ValueError(f"时间格式应为 HH:MM: {s}")
    return int(m.group(1)), int(m.group(2))


def in_md_range(d: date, start_md: str, end_md: str) -> bool:
    """判断日期是否落在「月-日」区间，支持跨年（如 10-01 ~ 04-30）。"""
    cur = (d.month, d.day)
    a = tuple(int(x) for x in start_md.split("-")[:2])
    b = tuple(int(x) for x in end_md.split("-")[:2])
    if a <= b:
        return a <= cur <= b
    return cur >= a or cur <= b


class Config:
    def __init__(self, data: dict):
        self.raw = data
        cal = data.get("calendar", {})
        self.name = cal.get("name") or "课表"
        self.desc = cal.get("description", "")
        self.tz = cal.get("timezone", "+08:00")
        self.prodid = cal.get("prodid", "-//syllabus-to-ics//CN")
        self.location_prefix = cal.get("location_prefix", "")

        term = data.get("term", {})
        if "first_monday" not in term:
            raise SystemExit("配置缺少 term.first_monday（第一教学周的周一日期，如 2026-09-07）")
        self.term_start = date.fromisoformat(term["first_monday"])
        self.term_weeks = int(term.get("weeks", 20))

        seasons = data.get("seasons", {})
        self.season_ranges = [(r[0], r[1]) for r in seasons.get("winter_ranges", [])]
        # 没有 seasons 配置时视为全年同一作息
        self.periods = self._load_periods(data.get("periods", {}))

        self.holidays = []
        for h in data.get("holidays", []):
            self.holidays.append({
                "start": date.fromisoformat(h["start"]),
                "end": date.fromisoformat(h["end"]),
                "name": h.get("name", "假期"),
                "skip": bool(h.get("skip_classes", True)),
            })

        self.alarm = data.get("alarm_minutes", 15)
        self.courses = data.get("courses", [])
        self.allday = data.get("allday", [])

    @staticmethod
    def _load_periods(raw: dict) -> dict:
        out = {}
        for key, val in raw.items():
            key = key.strip()
            if isinstance(val, dict):
                summer = val.get("summer") or val.get("all")
                winter = val.get("winter") or val.get("all") or summer
                if not summer or not winter:
                    raise SystemExit(f"节次 {key} 缺少 summer/winter 时间")
                out[key] = {"summer": tuple(map(parse_hhmm, summer)),
                            "winter": tuple(map(parse_hhmm, winter))}
            else:
                pair = tuple(map(parse_hhmm, val))
                out[key] = {"summer": pair, "winter": pair}
        return out

    def is_winter(self, d: date) -> bool:
        for a, b in self.season_ranges:
            if in_md_range(d, a, b):
                return True
        return False

    def holiday_of(self, d: date):
        for h in self.holidays:
            if h["start"] <= d <= h["end"]:
                return h
        return None


def week_of(term_start: date, d: date) -> int:
    return (d - term_start).days // 7 + 1


def build(cfg: Config):
    tb = IcsBuilder(cfg.name, cfg.desc, cfg.tz, cfg.prodid)
    tb.header()

    rows = []          # 展开后的每一节课
    conflicts = []     # 同一天同一时刻两门课
    skipped = []       # 被假期吞掉的课
    occupied = {}      # (date, HH:MM) -> course name

    for c in cfg.courses:
        name = c.get("name") or "未命名课程"
        period = str(c.get("period", "")).strip()
        if not period:
            raise SystemExit(f"课程「{name}」缺少 period（如 '3-4'），不推测节次")
        if period not in cfg.periods:
            raise SystemExit(
                f"节次 {period} 未在 periods 中定义（课程：{name}）。请先在配置里补上该节次的作息时间。")
        try:
            wd = parse_weekday(c["weekday"])
        except KeyError:
            raise SystemExit(f"课程「{name}」缺少 weekday")
        weeks = parse_weeks(c.get("weeks", ""))
        loc = c.get("location", "")
        teacher = c.get("teacher", "")
        note = c.get("note", "")

        for w in weeks:
            d = cfg.term_start + timedelta(days=(w - 1) * 7 + (wd - 1))
            hol = cfg.holiday_of(d)
            if hol and hol["skip"]:
                skipped.append((d, name, hol["name"]))
                continue
            key = "winter" if cfg.is_winter(d) else "summer"
            sh, sm = cfg.periods[period][key][0]
            eh, em = cfg.periods[period][key][1]
            start = datetime(d.year, d.month, d.day, sh, sm)
            end = datetime(d.year, d.month, d.day, eh, em)
            season_cn = "冬令时" if key == "winter" else "夏令时"

            desc_lines = []
            if teacher:
                desc_lines.append(f"教师：{teacher}")
            desc_lines.append(f"节次：第{period}节（{start:%H:%M}–{end:%H:%M}，{season_cn}）")
            desc_lines.append(f"周次：第{w}周（课表原值：{c.get('weeks','')}）")
            if note:
                desc_lines.append(note)
            full_loc = f"{cfg.location_prefix}{c.get('campus','')} {loc}".strip()

            sig = (d, f"{sh:02d}:{sm:02d}")
            if sig in occupied and occupied[sig] != name:
                conflicts.append((d, f"{sh:02d}:{sm:02d}", occupied[sig], name))
            occupied[sig] = name

            tb.add_event(name, start, end, full_loc, "\n".join(desc_lines),
                         cfg.alarm, uid_key=f"{name}|{loc}|{w}|{wd}|{period}")
            rows.append({"date": d, "week": w, "weekday": wd, "start": start, "end": end,
                         "name": name, "loc": full_loc, "teacher": teacher, "period": period})

    for ev in cfg.allday:
        tb.add_allday(ev["summary"], date.fromisoformat(ev["start"]),
                      date.fromisoformat(ev["end"]),
                      ev.get("description", ""), ev.get("location", ""),
                      uid_key=f"allday|{ev['summary']}|{ev['start']}")

    rows.sort(key=lambda r: (r["start"], r["name"]))
    return tb, rows, conflicts, skipped


def report(cfg: Config, tb, rows, conflicts, skipped, ics_path: str) -> str:
    stat = validate(ics_path)
    by_course = Counter(r["name"] for r in rows)
    by_week = Counter(r["week"] for r in rows)
    L = []
    A = L.append
    A(f"# 课表核对报告 · {cfg.name}\n")
    A(f"- 学期首周周一：{cfg.term_start.isoformat()}（共 {cfg.term_weeks} 周）")
    A(f"- 节次时段：{len(cfg.periods)} 种；冬令时区间："
      + ("、".join(f"{a}~{b}" for a, b in cfg.season_ranges) if cfg.season_ranges else "年统一"))
    A(f"- 展开课程节次：**{len(rows)}** 节；全天事件：**{len(cfg.allday)}** 条")
    A(f"- 每节提醒：{cfg.alarm} 分钟前\n")

    A("## 文件体检\n")
    A("| 项目 | 结果 |\n|---|---|")
    A(f"| VEVENT 数 | {stat['events']} |")
    A(f"| VALARM 数 | {stat['alarms']} |")
    A(f"| UID 唯一 | {stat['unique_uids']}/{stat['uids']} {'✅' if stat['unique_uids']==stat['uids'] else '❌ 有重复，导入会丢事件'} |")
    A(f"| 仅 CRLF 换行 | {'✅' if stat['crlf_only'] else '❌'} |")
    A(f"| 超 75 octet 的行 | {stat['over_75']} {'✅' if stat['over_75']==0 else '❌'} |")
    A(f"| 时间为 UTC 绝对时间 | {'✅' if stat['has_utc'] else '❌'} |\n")

    A("## 课程次数\n")
    A("| 课程 | 节次 |\n|---|---|")
    for k, v in by_course.most_common():
        A(f"| {k} | {v} |")
    A(f"| **合计** | **{sum(by_course.values())}** |\n")

    A("## 每周课时\n")
    A("| 周 | 起止 | 节数 |\n|---|---|---|")
    for w in range(1, cfg.term_weeks + 1):
        if by_week.get(w, 0) == 0:
            continue
        d0 = cfg.term_start + timedelta(days=(w - 1) * 7)
        d1 = d0 + timedelta(days=6)
        A(f"| 第{w}周 | {d0:%m/%d}–{d1:%m/%d} | {by_week[w]} |")
    A("")

    if conflicts:
        A("## ⚠ 时间冲突\n")
        for d, t, a, b in conflicts:
            A(f"- {d.isoformat()} {t}：{a} ↔ {b}")
        A("")
    if skipped:
        A("## 假期顺延（已剔除）\n")
        for d, name, hol in skipped[:50]:
            A(f"- {d.isoformat()} {name}（{hol}）")
        A("")

    A("## 未排期的课程\n")
    unrouted = [c for c in cfg.courses if not c.get("period")]
    A("无。" if not unrouted else "\n".join(f"- {c.get('name')}" for c in unrouted))
    return "\n".join(L)


HTML_HEAD = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{--g:#2f7d4f;--ink:#1d2b24;--line:#dfe7e2}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;
background:#f5f8f6;color:var(--ink);line-height:1.6}}
.wrap{{max-width:1060px;margin:0 auto;padding:26px 18px 60px}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{color:#5d6f65;font-size:13.5px;margin-bottom:20px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:18px}}
h2{{font-size:15.5px;margin:0 0 10px;padding-left:9px;border-left:4px solid var(--g)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#eef4f0;text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:7px 8px;border-bottom:1px solid #eef2ef;vertical-align:top}}
td.n{{white-space:nowrap;font-variant-numeric:tabular-nums;color:#4a5c52}}
tr.wk td{{background:#eef4f0;font-weight:600;color:#33513f}}
</style></head><body><div class="wrap"><h1>{title}</h1>
<div class="sub">{sub}</div>"""


def write_html(path: str, cfg: Config, rows, conflicts):
    out = [HTML_HEAD.format(title=cfg.name, sub=(
        f"首周 {cfg.term_start} ｜ 共 {len(rows)} 节 ｜ 提醒 {cfg.alarm} 分钟前 ｜ "
        f"冬令时：{'、'.join(f'{a}~{b}' for a, b in cfg.season_ranges) or '全年统一'}"))]
    out.append('<div class="card"><h2>课程清单</h2><table><thead><tr>'
               '<th>星期</th><th>节次</th><th>课程</th><th>地点</th><th>教师</th><th>周次</th></tr></thead><tbody>')
    for c in cfg.courses:
        out.append(f'<tr><td>{WD_CN[parse_weekday(c["weekday"])-1]}</td>'
                   f'<td class="n">第{c.get("period","")}节</td><td><b>{c.get("name","")}</b></td>'
                   f'<td>{c.get("location","")}</td><td>{c.get("teacher","")}</td>'
                   f'<td class="n">{c.get("weeks","")}</td></tr>')
    out.append('</tbody></table></div>')

    out.append('<div class="card"><h2>逐日账本</h2><table><thead><tr>'
               '<th>日期</th><th>星期</th><th>时间</th><th>课程</th><th>地点</th></tr></thead><tbody>')
    cur = None
    for r in rows:
        if r["week"] != cur:
            cur = r["week"]
            d0 = cfg.term_start + timedelta(days=(cur - 1) * 7)
            n = sum(1 for x in rows if x["week"] == cur)
            out.append(f'<tr class="wk"><td colspan="5">第 {cur} 周（{d0:%m/%d}–{d0+timedelta(days=6):%m/%d}）· {n} 节</td></tr>')
        out.append(f'<tr><td class="n">{r["date"]:%m-%d}</td><td>{WD_CN[r["weekday"]-1]}</td>'
                   f'<td class="n">{r["start"]:%H:%M}–{r["end"]:%H:%M}</td>'
                   f'<td><b>{r["name"]}</b></td><td class="n">{r["loc"]}</td></tr>')
    out.append('</tbody></table></div>')
    if conflicts:
        out.append('<div class="card"><h2>时间冲突</h2><ul>')
        for d, t, a, b in conflicts:
            out.append(f'<li>{d} {t}：{a} ↔ {b}</li>')
        out.append('</ul></div>')
    out.append('</div></body></html>')
    open(path, "w", encoding="utf-8").write("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description="课表配置 -> .ics")
    ap.add_argument("-c", "--config", required=True, help="配置文件（JSON）")
    ap.add_argument("-o", "--out", default="schedule.ics", help="输出 .ics 路径")
    ap.add_argument("-r", "--report", default="", help="输出核对报告 .md 路径")
    ap.add_argument("--html", default="", help="输出 HTML 总表路径")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        data = json.load(fh)
    cfg = Config(data)
    tb, rows, conflicts, skipped = build(cfg)
    tb.save(args.out)
    stat = validate(args.out)

    print(f"✅ 写入 {args.out}")
    print(f"   事件 {stat['events']}（课程 {len(rows)} + 全天 {len(cfg.allday)}）｜"
          f"提醒 {stat['alarms']}｜UID {stat['unique_uids']}/{stat['uids']}")
    if stat["unique_uids"] != stat["uids"]:
        print("   ❌ UID 重复，导入会被合并！")
    if conflicts:
        print(f"   ⚠ 时间冲突 {len(conflicts)} 处")
    if args.report:
        open(args.report, "w", encoding="utf-8").write(
            report(cfg, tb, rows, conflicts, skipped, args.out))
        print(f"   报告 {args.report}")
    if args.html:
        write_html(args.html, cfg, rows, conflicts)
        print(f"   总表 {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
