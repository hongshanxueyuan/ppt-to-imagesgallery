import unittest
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from synthesize_imagesgallery_audio import (  # noqa: E402
    clean_speech_for_tts,
    normalize_subtitle_for_display,
)


class TestSynthesizeImagesGalleryAudio(unittest.TestCase):
    def test_clean_speech_for_tts_strips_markdown_control_chars(self):
        raw = """## 标题

**重点**
- 列表项
1. 编号项

| 维度 | 普通AI助手 | 流程智能体 |
| --- | --- | --- |
| 关注点 | 生成内容 | 推动流程 |
"""
        cleaned = clean_speech_for_tts(raw)
        self.assertIn("标题", cleaned)
        self.assertIn("重点", cleaned)
        self.assertIn("列表项", cleaned)
        self.assertIn("编号项", cleaned)
        self.assertIn("维度：普通AI助手；流程智能体", cleaned)
        self.assertIn("关注点：生成内容；推动流程", cleaned)
        self.assertNotIn("##", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("|", cleaned)

    def test_normalize_subtitle_for_display_preserves_markdown(self):
        raw = "- 第 1 页\n\n## 标题\n\n- 列表项\n\n**重点**"
        subtitle = normalize_subtitle_for_display(raw)
        self.assertNotIn("第 1 页", subtitle)
        self.assertIn("## 标题", subtitle)
        self.assertIn("- 列表项", subtitle)
        self.assertIn("**重点**", subtitle)


if __name__ == "__main__":
    unittest.main()
