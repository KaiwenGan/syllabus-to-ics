#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立体检：把配置展开成「应该有的课」，再和 .ics 里「实际写进去的课」逐格对账。

不依赖第三方库（自带极简 ICS 解析），所以可以和 build.py 交叉验证：
build 负责写，audit 负责查有没有漏写、重写、时间错位。

用法：
    python3 scripts/audit.py --config cfg.json --ics schedule.ics
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from build import Config, parse_weeks, parse_weekday  # noqa: E402


def parse_ics(path: str):
    """极简解析：返回 (events, alarms_count, raw_bytes)。"""
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    unfolded = text.replace("\r\n ", "").replace("\r\n\t", "")
    blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, flags=re.S)
    events = []
    for b in blocks:
        def field(name):
            m = re.search(rf"^{name}[;:](.*)$", b, flags=re.M)
            return m.group(1).strip() if m else ""
        dtstart_raw = re.search(r"^DTSTART[^:]*:(.*)$", b, flags=re.M)
        dtend_raw = re.search(r"^DTEND[^:]*:(.*)$", b, flags=re.M)
        events.append({
            "uid": field("UID"),
            "summary": field("SUMMARY"),
            "location": field("LOCATION"),
            "desc": field("DESCRIPTION"),
            "start_raw": dtstart_raw.group(1).strip() if dtstart_raw else "",
            "end_raw": dtend_raw.group(1).strip() if dtend_raw else "",
            "allday": "VALUE=DATE" in b,
            "alarm": "BEGIN:VALARM" in b,
        })
    return events, raw, unfolded


def to_local(raw: str, tz):
    """'20260928T015000Z' -> 本地 naive datetime；DATE 值原样返回。"""
    if len(raw) == 8:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=__import__("datetime").timezone.utc)
    return dt.astimezone(tz).replace(tzinfo=None)


def main():
    ap = argparse.ArgumentParser(description="课表 ICS 与配置对账")
    ap.add_argument("-c", "--config", required=True)
    ap.add_argument("-i", "--ics", required=True)
    args = ap.parse_args()

    cfg = Config(json.load(open(args.config, encoding="utf-8")))
    from icsgen import tzinfo_from
    tz = tzinfo_from(cfg.tz)

    # ---- 期望 ----
    expect = {}
    for c in cfg.courses:
        name = c["name"]
        per = str(c["period"])
        wd = parse_weekday(c["weekday"])
        loc = f"{cfg.location_prefix}{c.get('campus','')} {c.get('location','')}".strip()
        for w in parse_weeks(c.get("weeks", "")):
            d = cfg.term_start + timedelta(days=(w - 1) * 7 + (wd - 1))
            h = cfg.holiday_of(d)
            if h and h["skip"]:
                continue
            key = "winter" if cfg.is_winter(d) else "summer"
            sh, sm = cfg.periods[per][key][0]
            eh, em = cfg.periods[per][key][1]
            expect[(d.isoformat(), f"{sh:02d}:{sm:02d}")] = {
                "name": name, "end": f"{eh:02d}:{em:02d}", "loc": loc}

    # ---- 实际 ----
    events, raw, unfolded = parse_ics(args.ics)
    got = {}
    dup_uid = [u for u, n in Counter(e["uid"] for e in events).items() if n > 1]
    for e in events:
        if e["allday"]:
            continue
        s = to_local(e["start_raw"], tz)
        got[(s.date().isoformat(), s.strftime("%H:%M"))] = {
            "name": e["summary"], "end": to_local(e["end_raw"], tz).strftime("%H:%M"),
            "loc": e["location"], "alarm": e["alarm"], "uid": e["uid"]}

    miss = sorted(set(expect) - set(got))
    extra = sorted(set(got) - set(expect))
    mismatch = []
    for k, v in expect.items():
        g = got.get(k)
        if not g:
            continue
        if g["name"] != v["name"] or g["end"] != v["end"] or g["loc"] != v["loc"]:
            mismatch.append((k, v, g))

    no_alarm = [k for k, g in got.items() if not g["alarm"]]
    allday = [e for e in events if e["allday"]]

    print(f"配置应有 {len(expect)} 节 | ICS 实有 {len(got)} 节 | 全天 {len(allday)} 条")
    print(f"缺失 {len(miss)} | 多余 {len(extra)} | 字段不符 {len(mismatch)} | 无提醒 {len(no_alarm)}")
    ok = not (miss or extra or mismatch or no_alarm or dup_uid)
    for k in miss[:20]:
        print("  缺", *k, expect[k]["name"])
    for k in extra[:20]:
        print("  多", *k, got[k]["name"])
    for k, v, g in mismatch[:20]:
        print("  差异", *k, "期望:", v, "实际:", g)
    if dup_uid:
        print(f"  ❌ UID 重复 {len(dup_uid)} 组 —— Apple 日历导入时会合并，导致静默丢课")
    if no_alarm[:5]:
        print("  无提醒:", no_alarm[:5])
    crlf_ok = raw.count(b"\r\n") == raw.count(b"\n") and b"\r\r" not in raw
    width_ok = all(len(l) <= 75 for l in raw.split(b"\r\n"))
    utc_ok = "TZID=" not in unfolded
    print("静态体检：", f"CRLF={'✅' if crlf_ok else '❌'}",
          f"行宽≤75={'✅' if width_ok else '❌'}",
          f"UTC={'✅' if utc_ok else '❌'}")
    print("结论：", "✅ 全部对得上" if ok else "❌ 存在问题，见上")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
