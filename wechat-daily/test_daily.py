from contextlib import closing
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import daily


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
