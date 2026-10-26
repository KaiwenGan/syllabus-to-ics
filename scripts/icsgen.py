# -*- coding: utf-8 -*-
"""ICS 写出层：只负责把「已确定的本地时间」写成合规的 iCalendar 文本。

设计约束（这些约束来自真实踩坑，改动前请读 references/pitfalls.md）：
1. UID 必须全局唯一 —— 用「课程+地点+周次+日期+时刻」拼，任何维度缺失都会让
   Apple 日历在导入时把不同天的事件当成同一事件合并掉（会静默丢课）。
2. 时间一律写成 UTC 绝对时间（...Z），不依赖 TZID/VTIMEZONE。某些客户端解析
   自定义 VTIMEZONE 失败会把整份课表平移 8 小时。
3. 行折叠按 75 octets，且不能把一个 UTF-8 多字节字符劈成两半。
4. 换行必须是 CRLF；写文件时不要再用 newline="\\r\\n"，否则会出现 \\r\\r\\n。
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone


def esc(text: str) -> str:
    """按 RFC 5545 转义 TEXT 值。"""
    return (str(text).replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def fold(line: str, limit: int = 73) -> list[str]:
    """按字节折叠长行；续行以单个空格开头。不切断多字节字符。"""
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return [line]
    out, cur, cur_len = [], "", 0
    for ch in line:
        cl = len(ch.encode("utf-8"))
        if cur_len + cl > limit:
            out.append(cur)
            cur, cur_len = " " + ch, 1 + cl
        else:
            cur += ch
            cur_len += cl
    out.append(cur)
    return out


def tzinfo_from(spec: str):
    """'Asia/Shanghai' 或 '+08:00' -> tzinfo。"""
    spec = (spec or "+08:00").strip()
    if "/" in spec:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(spec)
        except Exception as exc:  # pragma: no cover
            raise SystemExit(f"无法加载时区 {spec}: {exc}（可改用 '+08:00' 形式）")
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", spec)
    if not m:
        raise SystemExit(f"时区格式不认识: {spec}")
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


class IcsBuilder:
    def __init__(self, name: str, description: str = "", tz: str = "+08:00",
                 prodid: str = "-//syllabus-to-ics//CN"):
        self.name = name
        self.description = description
        self.tz = tzinfo_from(tz)
        self.prodid = prodid
        self.lines: list[str] = []
        self.event_count = 0
        self.alarm_count = 0
        self._uids: set[str] = set()
        self.duplicate_uid: list[str] = []

    # ---------- UID ----------
    def _uid(self, *parts: str) -> str:
        key = "|".join(str(p) for p in parts)
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:24]
        uid = f"{digest}@syllabus-to-ics"
        if uid in self._uids:
            self.duplicate_uid.append(key)
        self._uids.add(uid)
        return uid

    # ---------- 头 ----------
    def header(self) -> None:
        a = self.lines.append
        a("BEGIN:VCALENDAR")
        a("VERSION:2.0")
        a(f"PRODID:{self.prodid}")
        a("CALSCALE:GREGORIAN")
        a("METHOD:PUBLISH")
        a(f"X-WR-CALNAME:{esc(self.name)}")
        if self.description:
            a(f"X-WR-CALDESC:{esc(self.description)}")
        a("X-WR-TIMEZONE:Asia/Shanghai")
        self._stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _utc(self, local: datetime) -> str:
        return local.replace(tzinfo=self.tz).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # ---------- 事件 ----------
    def add_event(self, summary: str, start: datetime, end: datetime,
                  location: str = "", description: str = "",
                  alarm_minutes: int | None = 15, uid_key: str = "") -> None:
        a = self.lines.append
        uid = self._uid(uid_key or summary, location, start.strftime("%Y%m%d%H%M"))
        a("BEGIN:VEVENT")
        a(f"UID:{uid}")
        a(f"DTSTAMP:{self._stamp}")
        a(f"DTSTART:{self._utc(start)}")
        a(f"DTEND:{self._utc(end)}")
        a(f"SUMMARY:{esc(summary)}")
        if location:
            a(f"LOCATION:{esc(location)}")
        if description:
            a(f"DESCRIPTION:{esc(description)}")
        a("STATUS:CONFIRMED")
        a("TRANSP:OPAQUE")
        if alarm_minutes is not None:
            a("BEGIN:VALARM")
            a("ACTION:DISPLAY")
            a(f"TRIGGER:-PT{int(alarm_minutes)}M")
            a(f"DESCRIPTION:{esc(f'{alarm_minutes} 分钟后开始：{summary}')}")
            a(f"X-WR-ALARMUID:{uid}-alarm")
            a("END:VALARM")
            self.alarm_count += 1
        a("END:VEVENT")
        self.event_count += 1

    def add_allday(self, summary: str, start: date, end_inclusive: date,
                   description: str = "", location: str = "", uid_key: str = "") -> None:
        """全天事件。end_inclusive 是最后一天（内部转成排他 DTEND）。"""
        a = self.lines.append
        uid = self._uid(uid_key or summary, "allday", start.isoformat())
        a("BEGIN:VEVENT")
        a(f"UID:{uid}")
        a(f"DTSTAMP:{self._stamp}")
        a(f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}")
        a(f"DTEND;VALUE=DATE:{(end_inclusive + timedelta(days=1)).strftime('%Y%m%d')}")
        a(f"SUMMARY:{esc(summary)}")
        if location:
            a(f"LOCATION:{esc(location)}")
        if description:
            a(f"DESCRIPTION:{esc(description)}")
        a("STATUS:CONFIRMED")
        a("TRANSP:TRANSPARENT")
        a("END:VEVENT")
        self.event_count += 1

    # ---------- 输出 ----------
    def render(self) -> bytes:
        self.lines.append("END:VCALENDAR")
        chunks = []
        for line in self.lines:
            for piece in fold(line):
                chunks.append(piece + "\r\n")
        return "".join(chunks).encode("utf-8")

    def save(self, path: str) -> None:
        with open(path, "wb") as fh:      # 二进制写，杜绝 \r\r\n
            fh.write(self.render())


def validate(path: str) -> dict:
    """对已写出的 .ics 做静态体检，返回问题列表。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    unfolded = text.replace("\r\n ", "")
    uids = re.findall(r"^UID:(.+)$", unfolded, flags=re.M)
    events = unfolded.count("BEGIN:VEVENT")
    alarms = unfolded.count("BEGIN:VALARM")
    return {
        "bytes": len(raw),
        "events": events,
        "alarms": alarms,
        "uids": len(uids),
        "unique_uids": len(set(uids)),
        "crlf_only": raw.count(b"\r\n") == raw.count(b"\n") and b"\r\r" not in raw,
        "over_75": sum(1 for ln in raw.split(b"\r\n") if len(ln) > 75),
        "has_utc": "DTSTART:" in unfolded and "TZID=" not in unfolded,
    }
