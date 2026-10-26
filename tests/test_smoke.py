# -*- coding: utf-8 -*-
"""冒烟测试：用示例配置跑完整链路，校验关键不变量。

    python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from icsgen import validate  # noqa: E402

EXAMPLE = os.path.join(ROOT, "assets", "example.config.json")


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ics = os.path.join(self.tmp, "out.ics")
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build.py"),
                        "-c", EXAMPLE, "-o", self.ics],
                       check=True, capture_output=True)
        self.stat = validate(self.ics)
        with open(self.ics, "rb") as fh:
            self.raw = fh.read()

    def test_uid_unique(self):
        """UID 重复会让 Apple 日历导入时合并事件（丢课）。"""
        self.assertEqual(self.stat["uids"], self.stat["unique_uids"])

    def test_every_timed_event_has_alarm(self):
        self.assertEqual(self.stat["events"] - 2, self.stat["alarms"])  # 2 条全天

    def test_line_width_and_newlines(self):
        self.assertEqual(self.stat["over_75"], 0)
        self.assertTrue(self.stat["crlf_only"])
        self.assertNotIn(b"\r\r", self.raw)

    def test_utc_only(self):
        self.assertTrue(self.stat["has_utc"])
        self.assertNotIn(b"TZID=", self.raw)

    def test_season_switch(self):
        """9/30 之前的 6-7 节应是 14:00，10/1 起应是 13:30。"""
        text = self.raw.decode("utf-8").replace("\r\n ", "")
        # 第4周周三 9/30：夏令时，6-7 节 14:00 -> 06:00Z
        self.assertIn("DTSTART:20260930T060000Z", text)
        # 第6周周三 10/14：冬令时，6-7 节 13:30 -> 05:30Z
        self.assertIn("DTSTART:20261014T053000Z", text)

    def test_allday_exclusive_end(self):
        text = self.raw.decode("utf-8").replace("\r\n ", "")
        self.assertIn("DTSTART;VALUE=DATE:20260914", text)
        self.assertIn("DTEND;VALUE=DATE:20260928", text)  # 含 9/27 -> 排他到 9/28

    def test_audit_passes(self):
        """独立对账脚本必须报 0 缺失。"""
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "audit.py"),
                              "-c", EXAMPLE, "-i", self.ics],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("缺失 0", out.stdout)


if __name__ == "__main__":
    unittest.main()
