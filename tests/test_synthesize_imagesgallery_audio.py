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


def _write_manifest(manifest_path: Path, items: list[dict], **extra: object) -> None:
    payload = {
        "version": "1.0",
        "source_ppt": str(manifest_path.parent / "sample.pptx"),
        "items": items,
    }
    payload.update(extra)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_fake_audio_pipeline(preview_path: Path, synth_commands: list[list[str]]):
    def fake_run_cmd(cmd):
        if cmd[:3] == ["fake-bl", "speech", "synthesize"]:
            synth_commands.append(cmd)
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"mp3")
        elif cmd[:3] == ["fake-ffmpeg", "-y", "-f"] and "anullsrc=r=24000:cl=mono" in cmd:
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"gap")
        elif cmd[:3] == ["fake-ffmpeg", "-y", "-f"] and "concat" in cmd:
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"final")
        return None

    def fake_build_preview_html(_manifest, _manifest_path):
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text("<html></html>", encoding="utf-8")
        return preview_path

    return fake_run_cmd, fake_build_preview_html


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

    def test_parse_args_leaves_run_voice_source_unset_until_resolution(self):
        args = parse_args(["--manifest", "sample.json"])
        self.assertEqual("", args.voice)
        self.assertEqual("", args.voice_preset)
        self.assertEqual(DEFAULT_TTS_MODEL, args.model)
        self.assertEqual(DEFAULT_TTS_RATE, args.rate)

    def test_build_audio_passes_online_default_tts_config_to_bailian_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    }
                ],
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)

            args = parse_args(["--manifest", str(manifest_path)])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
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

    def test_build_audio_uses_run_default_voice_when_manifest_has_no_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    }
                ],
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(["--manifest", str(manifest_path), "--voice-preset", "男声"])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                build_audio(args)

        self.assertEqual(1, len(synth_commands))
        self.assertEqual("longshu_v2", synth_commands[0][synth_commands[0].index("--voice") + 1])

    def test_build_audio_applies_run_then_ppt_then_page_voice_resolution_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    },
                    {
                        "page_number": 2,
                        "image": "images/page-002.png",
                        "speech": "第二页正文",
                        "voice_preset": "男声",
                    },
                    {
                        "page_number": 3,
                        "image": "images/page-003.png",
                        "speech": "第三页正文",
                    },
                ],
                voice=DEFAULT_TTS_VOICE,
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(["--manifest", str(manifest_path), "--voice-preset", "男声"])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                build_audio(args)

        self.assertEqual(3, len(synth_commands))
        observed_voices = [cmd[cmd.index("--voice") + 1] for cmd in synth_commands]
        self.assertEqual([DEFAULT_TTS_VOICE, "longshu_v2", DEFAULT_TTS_VOICE], observed_voices)

    def test_build_audio_stops_entire_run_before_any_synthesis_when_page_voice_config_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    },
                    {
                        "page_number": 2,
                        "image": "images/page-002.png",
                        "speech": "第二页正文",
                        "voice_preset": "男声",
                        "voice": DEFAULT_TTS_VOICE,
                    },
                ],
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(["--manifest", str(manifest_path)])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                with self.assertRaisesRegex(ValueError, "page 2 声音覆盖.*请修正后再继续"):
                    build_audio(args)

        self.assertEqual([], synth_commands)

    def test_build_audio_stops_entire_run_when_run_default_voice_config_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    }
                ],
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(
                ["--manifest", str(manifest_path), "--voice-preset", "男声", "--voice", DEFAULT_TTS_VOICE]
            )

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                with self.assertRaisesRegex(ValueError, "run 默认声音"):
                    build_audio(args)

        self.assertEqual([], synth_commands)

    def test_build_audio_stops_entire_run_when_single_ppt_voice_config_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                    }
                ],
                voice_preset="男声",
                voice=DEFAULT_TTS_VOICE,
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(["--manifest", str(manifest_path)])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                with self.assertRaisesRegex(ValueError, "单个 PPT 声音覆盖"):
                    build_audio(args)

        self.assertEqual([], synth_commands)

    def test_build_audio_allows_equal_preset_and_explicit_voice_on_same_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "imagesgallery.json"
            preview_path = tmp_path / "audio" / "preview.html"
            _write_manifest(
                manifest_path,
                [
                    {
                        "page_number": 1,
                        "image": "images/page-001.png",
                        "speech": "第一页正文",
                        "voice_preset": "男声",
                        "voice": "longshu_v2",
                    }
                ],
            )

            synth_commands = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)
            args = parse_args(["--manifest", str(manifest_path)])

            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd",
                side_effect=fake_run_cmd,
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                build_audio(args)

        self.assertEqual(1, len(synth_commands))
        self.assertEqual("longshu_v2", synth_commands[0][synth_commands[0].index("--voice") + 1])


if __name__ == "__main__":
    unittest.main()
