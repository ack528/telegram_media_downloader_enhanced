import asyncio
import unittest
from datetime import datetime

from pyrogram.parser.html import HTML

from module.app import TaskNode
from module.bot_status import (
    FileProgress,
    display_file_name,
    format_eta,
    human_bytes,
    progress_bar,
    render_task_status,
)

GB = 1024**3


def _node(**overrides):
    node = TaskNode(chat_id=-100123, task_id=1, start_offset_id=1000)
    node.chat_title = "摄影作品精选"
    node.is_running = True
    node.scan_finished = True
    node.total_task = 195
    node.total_download_task = 187
    node.success_download_task = 180
    node.skip_download_task = 7
    node.total_download_byte = int(12.45 * GB)
    for key, value in overrides.items():
        setattr(node, key, value)
    return node


def _render(node, downloads=(), **kwargs):
    options = {
        "uploads": [],
        "cloud_uploads": [],
        "software_speed": 649 * 1024,
        "clash_speed": 968 * 1024,
        "clash_enabled": True,
        "now": datetime(2026, 9, 26, 19, 37, 52),
    }
    options.update(kwargs)
    return render_task_status(node, downloads=list(downloads), **options)


class HelpersTestCase(unittest.TestCase):
    def test_file_name_keeps_start_and_extension(self):
        name = display_file_name(
            "D:/dl/188 - 城市夜景延时摄影合集 第三部分 4K HDR 高码率版本.mp4", 188
        )
        self.assertTrue(name.startswith("城市夜景"))
        self.assertTrue(name.endswith(".mp4"))
        self.assertIn("…", name)

    def test_file_name_drops_message_id_prefix_only(self):
        self.assertEqual(display_file_name("189 - clip.mp4", 189), "clip.mp4")
        self.assertEqual(display_file_name("1890 - clip.mp4", 189), "1890 - clip.mp4")
        self.assertEqual(display_file_name("3.mp4", 3), "3.mp4")

    def test_nameless_media_is_labelled(self):
        self.assertEqual(display_file_name("189 - .mp4", 189), "未命名.mp4")

    def test_formatting_helpers(self):
        self.assertEqual(human_bytes(968 * 1024), "968 KB")
        self.assertEqual(human_bytes(2.19 * GB), "2.19 GB")
        self.assertEqual(format_eta(3 * 60 + 5), "3:05")
        self.assertEqual(format_eta(3600 + 61), "1:01:01")
        self.assertEqual(progress_bar(0.001, 10), "▰" + "▱" * 9)
        self.assertEqual(progress_bar(0.999, 10), "▰" * 9 + "▱")


class RenderTestCase(unittest.TestCase):
    def test_card_layout(self):
        text = _render(
            _node(),
            [FileProgress(189, "189 - clip.mp4", int(2.19 * GB), int(1.95 * GB), 142 * 1024)],
        )
        self.assertTrue(text.startswith("📥 <b>任务 #1 · 摄影作品精选</b>\n下载中 · 187/195 · 95%\n"))
        self.assertIn("\n⚡ 649 KB/s · 代理总 968 KB/s · 💾 12.4 GB\n", text)
        # Zero counters are left out.
        self.assertIn("\n✅ 180  ⏭ 7\n", text)
        self.assertNotIn("❌", text)
        self.assertIn("<blockquote>clip.mp4\n▰▰▰▰▰▰▰▰▰▱ 89%\n142 KB/s · 剩余 ", text)
        self.assertTrue(text.endswith("<i>19:37:52 更新</i>"))

    def test_scanning_shows_message_range(self):
        node = _node(scan_finished=False, end_offset_id=2100, scan_message_id=1124)
        text = _render(node, [FileProgress(1124, "a.mp4", 100, 50, 10)])
        self.assertIn("\n下载中 · 消息 1124/2100 · 11%\n", text)

    def test_scanning_without_range_end_or_downloads(self):
        text = _render(_node(scan_finished=False, scan_message_id=1124))
        self.assertIn("\n扫描中 · 已扫描到消息 1124\n", text)
        self.assertNotIn("%", text)

    def test_quiet_header_hides_empty_details(self):
        node = _node(
            chat_title="",
            success_download_task=0,
            skip_download_task=0,
            total_download_byte=0,
        )
        text = _render(node, software_speed=2.36 * 1024**2, clash_speed=2.34 * 1024**2)
        self.assertTrue(
            text.startswith("📥 <b>任务 #1</b>\n下载中 · 187/195 · 95%\n⚡ 2.36 MB/s\n\n")
        )

    def test_proxy_hidden_when_disabled(self):
        self.assertNotIn("代理", _render(_node(), clash_enabled=False, clash_speed=None))

    def test_user_text_is_escaped_and_parses_as_telegram_html(self):
        node = _node(chat_title="<b>A&B</b>")
        text = _render(node, [FileProgress(5, "5 - a<i>b.mp4", 100, 50, 10)])
        self.assertIn("&lt;b&gt;A&amp;B&lt;/b&gt;", text)
        result = asyncio.run(HTML(None).parse(text))
        self.assertIn("<b>A&B</b>", result["message"])
        self.assertIn("a<i>b.mp4", result["message"])
        self.assertTrue(result["entities"])


if __name__ == "__main__":
    unittest.main()
