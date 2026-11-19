from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import daily
from screen_frames import FrameTracker


class DailyTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "daily.sqlite3"
        self.day = date(2026, 11, 19)
        self.config = {"group": "项目测试群", "ollama_model": "qwen3:8b"}

    def test_duplicates_and_calendar_cutoff(self):
        start, end = daily.day_window(self.day)
        first = {"kind": "message", "id": "123", "from": "成员甲", "at": start, "text": "确认周五交付"}
        second = {**first, "id": "124", "at": end, "text": "次日消息"}
        daily.persist_events([json.dumps(item) for item in (first, first, second)], self.path)
        with closing(daily.open_db(self.path)) as db, patch.object(daily, "summarize_batch", return_value="已确认周五交付") as model:
            report = daily.render_report(db, self.day, self.config)
        self.assertIn("采集到 1 条文字", report)
        self.assertIn("估计未覆盖 1440 分钟", report)
        self.assertIn("确认周五交付", model.call_args.args[1][0])
        self.assertNotIn("次日消息", str(model.call_args))

    def test_coverage_and_empty_day(self):
        start, end = daily.day_window(self.day)
        self.assertEqual(daily.coverage_gaps(start, end, [(start - 60,), (start + 90,)]),
                         [(start + 60, start + 90), (start + 210, end)])
        with closing(daily.open_db(self.path)) as db, patch.object(daily, "summarize_batch") as model:
            report = daily.render_report(db, self.day, self.config)
        self.assertIn("没有收到", report)
        model.assert_not_called()

    def test_state_directory_rejects_group_changes(self):
        with closing(daily.open_db(self.path)) as db:
            daily.bind_group(db, "内部测试群")
            daily.bind_group(db, "内部测试群")
            with self.assertRaises(ValueError):
                daily.bind_group(db, "另一个群")

    def test_manual_import_deduplicates_and_does_not_fabricate_source_time(self):
        with closing(daily.open_db(self.path)) as db:
            daily.bind_source(db, "manual")
            self.assertTrue(daily.import_text(db, self.day, "项目周五交付"))
            self.assertFalse(daily.import_text(db, self.day, "项目周五交付\n"))
            self.assertTrue(daily.import_text(db, self.day + timedelta(days=1), "项目周五交付"))
            with patch.object(daily, "summarize_batch", return_value="项目周五交付") as model:
                report = daily.render_report(db, self.day, self.config, manual=True)
            with self.assertRaises(ValueError):
                daily.bind_source(db, "wechat")
        self.assertIn("根据人工提交的 1 批文字生成", report)
        self.assertNotIn("未覆盖", report)
        self.assertIsNone(json.loads(model.call_args.args[1][0])["time"])

    def test_manual_schedule_waits_for_input_and_sends_once(self):
        config = {**self.config, "report_time": time(0, 10)}
        current = datetime(2026, 11, 20, 9, 0, tzinfo=daily.SHANGHAI)
        with closing(daily.open_db(self.path)) as db, patch.object(daily, "datetime", wraps=datetime) as clock, \
                patch.object(daily.time, "sleep", side_effect=KeyboardInterrupt), \
                patch.object(daily, "summarize_batch", return_value="日报内容"), \
                patch.object(daily, "post_feishu") as send:
            clock.now.return_value = current
            with self.assertRaises(KeyboardInterrupt):
                daily.service_loop(db, config)
            send.assert_not_called()
            daily.import_text(db, self.day, "确认周五交付")
            for _ in range(2):
                with self.assertRaises(KeyboardInterrupt):
                    daily.service_loop(db, config)
        send.assert_called_once()
        self.assertIn("根据人工提交", send.call_args.args[1])

    def test_screen_overlap_keeps_a_new_occurrence_of_repeated_text(self):
        tracker = FrameTracker()
        self.assertEqual(tracker.advance(["消息甲内容", "消息乙内容", "消息丙内容"]), ([], False))
        self.assertEqual(tracker.advance(["消息乙内容", "消息丙内容", "消息乙内容"]), (["消息乙内容"], False))
        self.assertEqual(tracker.advance(["消息乙内容", "消息丙内容", "消息乙内容"]), ([], False))
        self.assertEqual(tracker.advance(["消息丙内容"]), ([], False))
        self.assertEqual(tracker.advance(["画面全部换新", "没有可验证重叠"]), ([], True))

    def test_screen_ingest_pauses_and_reports_gaps_with_observation_time(self):
        start, _ = daily.day_window(self.day)
        frames = [
            {"kind": "frame", "at": start, "lines": ["开机前的旧消息"]},
            {"kind": "frame", "at": start + 5, "lines": ["开机前的旧消息", "新消息约周五验收"]},
            {"kind": "title-mismatch", "at": start + 10, "lines": ["别的群消息"]},
            {"kind": "title-mismatch", "at": start + 15, "lines": ["别的群消息"]},
            {"kind": "frame", "at": start + 20, "lines": ["重新进入群时的旧画面"]},
            {"kind": "frame", "at": start + 25, "lines": ["重新进入群时的旧画面", "负责人待确认"]},
            {"kind": "frame", "at": start + 30, "lines": ["脱节时不导入"]},
        ]
        with patch("sys.stderr"):
            daily.persist_events((json.dumps(frame) for frame in frames), self.path, screen=True)
        with closing(daily.open_db(self.path)) as db, patch.object(daily, "summarize_batch", return_value="日报") as model:
            records = db.execute("SELECT body FROM messages ORDER BY at").fetchall()
            self.assertEqual(records, [("新消息约周五验收",), ("负责人待确认",)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heartbeat").fetchone()[0], 5)
            report = daily.render_report(db, self.day, self.config, screen=True)
        content = json.loads(model.call_args.args[1][0])
        self.assertIsNone(content["time"])
        self.assertEqual(content["observed_at"], "00:00")
        self.assertIn("屏幕文字 2 批", report)
        self.assertIn("记录到 2 次采集间隙", report)

    def test_screen_regions_reject_an_overlap_between_title_and_body(self):
        config = {**self.config, "screen": {"header_region": [0, 0, 1, 0.3]}}
        with self.assertRaisesRegex(ValueError, "群名识别区域"):
            daily.screen_parameters(config)

    def test_batches_preserve_all_source_messages(self):
        start, _ = daily.day_window(self.day)
        rows = [(start + number, f"成员{number}", "资料" * 600) for number in range(50)]
        with patch.object(daily, "summarize_batch", return_value="工作要点") as model:
            self.assertEqual(daily.summary_for("test", rows), "工作要点")
        sources = [line for call in model.call_args_list for line in call.args[1] if line.startswith("{")]
        self.assertEqual(len(sources), 50)
        self.assertEqual(json.loads(sources[-1])["sender"], "成员49")
        self.assertFalse(model.call_args.kwargs["partial"])

    def test_send_once_and_recovery_states(self):
        with closing(daily.open_db(self.path)) as db, patch.object(daily, "post_feishu") as send:
            daily.deliver_once(db, "success", self.config, "摘要")
            daily.deliver_once(db, "success", self.config, "摘要")
            send.assert_called_once()
            self.assertEqual(daily.delivery_state(db, "success"), "sent")
            send.side_effect = daily.Rejected("rejected")
            with self.assertRaises(daily.Rejected):
                daily.deliver_once(db, "rejected", self.config, "摘要")
            self.assertIsNone(daily.delivery_state(db, "rejected"))
            send.side_effect = RuntimeError("unknown")
            with self.assertRaises(RuntimeError):
                daily.deliver_once(db, "unknown", self.config, "摘要")
            daily.deliver_once(db, "unknown", self.config, "摘要")
            self.assertEqual(daily.delivery_state(db, "unknown"), "uncertain")
            self.assertEqual(send.call_count, 3)


if __name__ == "__main__":
    unittest.main()
