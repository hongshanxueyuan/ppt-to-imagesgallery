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
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_RATE,
    DEFAULT_TTS_VOICE,
    build_audio,
    clean_speech_for_tts,
    normalize_subtitle_for_display,
    parse_args,
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
        raw = "## 标题\n\n- 列表项\n\n**重点**"
        subtitle = normalize_subtitle_for_display(raw)
        self.assertIn("## 标题", subtitle)
        self.assertIn("- 列表项", subtitle)
        self.assertIn("**重点**", subtitle)

    def test_build_audio_rewrites_manifest_without_source_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source_ppt": str(tmp_path / "sample.pptx"),
                        "section_id": "1.2",
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
                voice=DEFAULT_TTS_VOICE,
                rate=1.1,
                model=DEFAULT_TTS_MODEL,
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

        self.assertEqual("1.2", rewritten["section_id"])
        self.assertNotIn("source_speech", rewritten)
        self.assertIn("audio", rewritten)
        self.assertEqual(1, len(rewritten["items"]))
        self.assertEqual("## 标题\n\n第一页正文", rewritten["items"][0]["subtitle"])
        self.assertEqual(0, rewritten["items"][0]["start"])

    def test_parse_args_defaults_to_online_female_voice_config(self):
        args = parse_args(["--manifest", "sample.json"])
        self.assertEqual(DEFAULT_TTS_VOICE, args.voice)
        self.assertEqual(DEFAULT_TTS_MODEL, args.model)
        self.assertEqual(DEFAULT_TTS_RATE, args.rate)

    def test_build_audio_passes_online_default_tts_config_to_bailian_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source_ppt": str(tmp_path / "sample.pptx"),
                        "items": [
                            {
                                "page_number": 1,
                                "image": "images/page-001.png",
                                "speech": "第一页正文",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            synth_commands = []

            def fake_resolve_bin(name):
                return f"fake-{name}"

            def fake_run_cmd(cmd):
                if cmd[:3] == ["fake-bl", "speech", "synthesize"]:
                    synth_commands.append(cmd)
                    out_path = Path(cmd[cmd.index("--out") + 1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"mp3")
                elif cmd[:3] == ["fake-ffmpeg", "-y", "-f"] and "concat" in cmd:
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"final")
                return None

            def fake_build_preview_html(_manifest, _manifest_path):
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                preview_path.write_text("<html></html>", encoding="utf-8")
                return preview_path

            args = parse_args(["--manifest", str(manifest_path)])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=fake_resolve_bin), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                build_audio(args)

        self.assertEqual(1, len(synth_commands))
        self.assertIn("--voice", synth_commands[0])
        self.assertEqual(DEFAULT_TTS_VOICE, synth_commands[0][synth_commands[0].index("--voice") + 1])
        self.assertIn("--model", synth_commands[0])
        self.assertEqual(DEFAULT_TTS_MODEL, synth_commands[0][synth_commands[0].index("--model") + 1])
        self.assertIn("--rate", synth_commands[0])
        self.assertEqual(str(DEFAULT_TTS_RATE), synth_commands[0][synth_commands[0].index("--rate") + 1])


if __name__ == "__main__":
    unittest.main()
