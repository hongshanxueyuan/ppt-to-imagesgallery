import argparse
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from synthesize_imagesgallery_audio import (  # noqa: E402
    build_audio,
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

    def test_build_audio_preserves_risk_report_fields_in_rewritten_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            risk_report_path = tmp_path / "imagesgallery-risk-report.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source_ppt": str(tmp_path / "sample.pptx"),
                        "source_speech": str(tmp_path / "sample.cleaned.md"),
                        "risk_report": str(risk_report_path),
                        "risk_summary": {
                            "risk_count": 2,
                            "highest_severity": "warning",
                            "requires_manual_review": True,
                        },
                        "items": [
                            {
                                "page_number": 1,
                                "image": "images/page-001.png",
                                "speech": "## 标题\n\n第一页正文",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_run_cmd(cmd):
                if "--out" in cmd:
                    out_path = Path(cmd[cmd.index("--out") + 1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"mp3")
                elif "anullsrc=r=24000:cl=mono" in cmd:
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"gap")
                elif "-f" in cmd and "concat" in cmd:
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"final")
                return None

            def fake_build_preview_html(_manifest, _manifest_path):
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                preview_path.write_text("<html></html>", encoding="utf-8")
                return preview_path

            args = argparse.Namespace(
                manifest=str(manifest_path),
                out_dir="",
                voice="longxiaochun_v3",
                rate=1.1,
                model="",
                language="",
                gap_seconds=1.0,
                final_name="full_speech.mp3",
                timeline_name="speech_timestamps.json",
                skip_existing=False,
            )

            with patch("synthesize_imagesgallery_audio.resolve_bin", return_value="fake-bin"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                build_audio(args)

            rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(str(risk_report_path), rewritten["risk_report"])
        self.assertEqual(2, rewritten["risk_summary"]["risk_count"])
        self.assertTrue(rewritten["risk_summary"]["requires_manual_review"])


if __name__ == "__main__":
    unittest.main()
