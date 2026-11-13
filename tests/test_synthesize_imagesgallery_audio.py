import argparse
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

try:
    from markdown_it import MarkdownIt
except ImportError:
    MarkdownIt = None

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_imagesgallery import build_imagesgallery  # noqa: E402
from plan_batch_jobs import discover_batch_jobs  # noqa: E402
from synthesize_imagesgallery_audio import (  # noqa: E402
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_RATE,
    DEFAULT_TTS_VOICE,
    build_audio,
    build_preview_html,
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
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed to execute the generated preview')
    def test_preview_keeps_ordered_item_continuation_in_the_same_list(self):
        page = '1. 第一项\n   补充说明\n2. 第二项\n   更多说明\n\n结束。 `**代码**` 和 \\*\\*转义\\*\\*。'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview = build_preview_html({
                'source_ppt': 'sample.pptx', 'audio': {'full_audio': 'audio.mp3'},
                'items': [{'page': 1, 'subtitle': page, 'start': 0, 'end': 1000}],
            }, root / 'imagesgallery.json')
            runner = r'''
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const payload = html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const nodes = {};
function element() { return {innerHTML:"", textContent:"", classList:{toggle(){}}, addEventListener(){}, appendChild(){}}; }
global.document = {getElementById(id) { return nodes[id] ||= element(); }, createElement() { return element(); }};
nodes.payload = {textContent: payload};
vm.runInThisContext(script);
process.stdout.write(nodes.subtitleText.innerHTML);
'''
            result = subprocess.run([shutil.which('node'), '-e', runner, str(preview)],
                                    capture_output=True, text=True, encoding='utf8', check=True)
        self.assertEqual('<ol><li>第一项<br>补充说明</li><li>第二项<br>更多说明</li></ol>'
                         '<p>结束。 <code>**代码**</code> 和 **转义**。</p>', result.stdout)

    def test_html_blocks_are_cleaned_but_fenced_html_code_is_preserved(self):
        page = ('<div>\n    <p>第一段</p>\n\n    <script>不该读的脚本</script>\n'
                '    <p>第二段</p>\n</div>\n\n    &amp;lt;script&amp;gt;编码脚本&amp;lt;/script&amp;gt;'
                '\n\n```html\n<script>示例代码</script>\n```')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ppt = root / '1.2 示例.pptx'
            ppt.write_bytes(b'fake-ppt')
            section_list = root / 'section-list.json'
            section_list.write_text(json.dumps({'sections': [{
                'section_id': '1.2', 'section_title': '1.2 示例', 'output_name': ppt.name,
                'page_count': 1, 'page_content': [page],
            }]}, ensure_ascii=False), encoding='utf8')
            with patch('plan_batch_jobs.count_presentation_pages', return_value=1):
                plan = discover_batch_jobs(root)
            self.assertTrue(plan['admission_ready'])
            cleaned = plan['jobs'][0]['page_content'][0]
            self.assertIn('第一段', cleaned)
            self.assertIn('第二段', cleaned)
            self.assertNotIn('<p>', cleaned)
            self.assertNotIn('<div>', cleaned)
            self.assertNotIn('不该读的脚本', cleaned)
            self.assertNotIn('编码脚本', cleaned)
            self.assertIn('```html\n<script>示例代码</script>\n```', cleaned)
            self.assertTrue(all(line == '' for line in cleaned.splitlines() if not line.strip()))

    def test_html_inside_block_is_cleaned_while_indented_code_keeps_encoded_span(self):
        page = ('    &lt;span&gt;代码示例&lt;/span&gt;\n\n<div>\n    <p>第一段</p>\n\n'
                '    提示<script>不该读的脚本</script>\n    <p>第二段</p>\n</div>')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ppt = root / '1.2 示例.pptx'
            ppt.write_bytes(b'fake-ppt')
            (root / 'section-list.json').write_text(json.dumps({'sections': [{
                'section_id': '1.2', 'section_title': '1.2 示例', 'output_name': ppt.name,
                'page_count': 1, 'page_content': [page],
            }]}, ensure_ascii=False), encoding='utf8')
            with patch('plan_batch_jobs.count_presentation_pages', return_value=1):
                plan = discover_batch_jobs(root)
            self.assertTrue(plan['admission_ready'])
            cleaned = plan['jobs'][0]['page_content'][0]
            self.assertIn('    &lt;span&gt;代码示例&lt;/span&gt;', cleaned)
            self.assertIn('第一段', cleaned)
            self.assertIn('提示', cleaned.splitlines())
            self.assertIn('第二段', cleaned)
            self.assertNotIn('不该读的脚本', cleaned)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the generated preview")
    def test_generated_preview_renders_ordered_and_nested_lists_and_hard_breaks(self):
        page = ("# 指南\n\n1. 项目一\n   - 子项\n\n   - 子项二\n     - 子子项\n"
                "2. 项目二\n\n第一行  \n第二行\n\n```html\n> 代码 <tag>\n```\n\n    > 缩进代码")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview = build_preview_html({
                "source_ppt": "sample.pptx",
                "audio": {"full_audio": "audio.mp3"},
                "items": [{"page": 1, "subtitle": page, "start": 0, "end": 1000}],
            }, root / "imagesgallery.json")
            runner = r'''
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const payload = html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const nodes = {};
function element() {
  return {innerHTML:"", textContent:"", classList:{toggle(){}}, addEventListener(){}, appendChild(){}};
}
global.document = {
  getElementById(id) { return nodes[id] ||= element(); },
  createElement() { return element(); }
};
nodes.payload = {textContent: payload};
vm.runInThisContext(script);
process.stdout.write(nodes.subtitleText.innerHTML);
'''
            result = subprocess.run([shutil.which("node"), "-e", runner, str(preview)], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(
            "<h1>指南</h1><ol><li>项目一<ul><li>子项</li><li>子项二<ul><li>子子项</li></ul></li></ul></li>"
            "<li>项目二</li></ol><p>第一行<br>第二行</p><pre><code>&gt; 代码 &lt;tag&gt;</code></pre>"
            "<pre><code>&gt; 缩进代码</code></pre>", result.stdout
        )

    def test_subtitle_keeps_markdown_breaks_and_nested_lists_after_build_and_audio(self):
        raw_page = (
            "    首行代码\n\n## 层级\n\n1. 第一项\n   - 子项\n\n     - <span>子子项</span>\n2. 第二项\n\n"
            "第一行  \n第二行\n\n```html\n> 代码示例\n  <strong>保留 &amp;</strong>\n```\n\n"
            "    保留缩进 <tag> &amp;\n\n`<span>多个   空格</span>`\n\n正文 &#67;ODEPLACEHOLDER0END 和 &#57344;0&#57344;"
        )
        cleaned_page = raw_page.replace("<span>子子项</span>", "子子项").replace("&#67;", "C").replace("&#57344;", "\ue000")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ppt = root / "1.2 示例.pptx"
            ppt.write_bytes(b"fake-ppt")
            section_list = root / "section-list.json"
            section_list.write_text(json.dumps({"sections": [{
                "section_id": "1.2", "section_title": "1.2 示例", "output_name": ppt.name,
                "page_count": 1, "page_content": [raw_page],
            }]}, ensure_ascii=False), encoding="utf-8")
            original_section_list = section_list.read_bytes()
            with patch("plan_batch_jobs.count_presentation_pages", return_value=1):
                plan = discover_batch_jobs(root)
            self.assertTrue(plan["admission_ready"])
            self.assertEqual([cleaned_page], plan["jobs"][0]["page_content"])
            source = root / "section.json"
            source.write_text(json.dumps(plan["jobs"][0], ensure_ascii=False), encoding="utf-8")

            def fake_convert(_ppt_path, images_dir, **kwargs):
                path = images_dir / "page-001.png"
                path.write_bytes(b"fake-image")
                return [path]

            build_args = argparse.Namespace(ppt=str(ppt), section_json=str(source), out=str(root / "out"), dry_run=True)
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                stage_a = build_imagesgallery(build_args)

            self.assertEqual(cleaned_page, stage_a["items"][0]["speech"])
            manifest_path = root / "out" / "1.2 示例" / "imagesgallery" / "imagesgallery.json"
            preview_path = root / "preview.html"
            fake_run, fake_preview = _build_fake_audio_pipeline(preview_path, [])
            args = parse_args(["--manifest", str(manifest_path)])
            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd", side_effect=fake_run
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html", side_effect=fake_preview
            ):
                build_audio(args)
            stage_b = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(cleaned_page, stage_b["items"][0]["subtitle"])
            if MarkdownIt is not None:
                rendered = MarkdownIt("commonmark").render(stage_b["items"][0]["subtitle"])
                self.assertIn("<li>第一项\n<ul>\n<li>\n<p>子项</p>\n<ul>", rendered)
                self.assertIn("第一行<br />\n第二行", rendered)
                self.assertIn("&lt;strong&gt;保留 &amp;amp;&lt;/strong&gt;", rendered)
            self.assertEqual(cleaned_page, json.loads(source.read_text(encoding="utf-8"))["page_content"][0])
            self.assertEqual(original_section_list, section_list.read_bytes())

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
                        "section_title": "1.2 课程A",
                        "block_type": "html",
                        "items": [
                            {
                                "page_number": 1,
                                "image": "images/page-001.jpg",
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
        self.assertEqual("1.2 课程A", rewritten["section_title"])
        self.assertEqual("html", rewritten["block_type"])
        self.assertNotIn("source_speech", rewritten)
        self.assertIn("audio", rewritten)
        self.assertEqual(1, len(rewritten["items"]))
        self.assertEqual("## 标题\n\n第一页正文", rewritten["items"][0]["subtitle"])
        self.assertEqual(0, rewritten["items"][0]["start"])
        self.assertEqual("images/page-001.jpg", rewritten["items"][0]["image"])

    def test_build_audio_sends_cleaned_manifest_speech_to_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            preview_path = tmp_path / "audio" / "preview.html"
            ppt_path.write_bytes(b"fake-ppt")
            section_json_path.write_text(
                json.dumps(
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                        "page_count": 1,
                        "page_content": ["## 标题\n\nTom & Jerry\n\n>> 引用正文\nA < B\nA > B"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            def fake_convert(_ppt_path, images_dir, image_name_prefix="", image_name_timestamp="", **kwargs):
                image_path = images_dir / f"{image_name_prefix}__page-001__{image_name_timestamp}.png"
                image_path.write_bytes(b"fake-image")
                return [image_path]

            build_args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                stage_a_manifest = build_imagesgallery(build_args)

            manifest_path = out_dir / "sample" / "imagesgallery" / "imagesgallery.json"
            self.assertEqual(
                "## 标题\n\nTom & Jerry\n\n引用正文\nA < B\nA > B",
                stage_a_manifest["items"][0]["speech"],
            )

            synth_commands: list[list[str]] = []
            tts_texts: list[str] = []
            fake_run_cmd, fake_build_preview_html = _build_fake_audio_pipeline(preview_path, synth_commands)

            def capture_tts_text(cmd: list[str]) -> None:
                if cmd[:3] == ["fake-bl", "speech", "synthesize"]:
                    text_path = Path(cmd[cmd.index("--text-file") + 1])
                    tts_texts.append(text_path.read_text(encoding="utf-8"))
                fake_run_cmd(cmd)

            args = parse_args(["--manifest", str(manifest_path)])
            with patch("synthesize_imagesgallery_audio.resolve_bin", side_effect=lambda name: f"fake-{name}"), patch(
                "synthesize_imagesgallery_audio.run_cmd", side_effect=capture_tts_text
            ), patch("synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5), patch(
                "synthesize_imagesgallery_audio.build_preview_html", side_effect=fake_build_preview_html
            ):
                build_audio(args)
            rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(["标题\n\nTom & Jerry\n\n引用正文\nA < B\nA > B"], tts_texts)
        self.assertEqual("## 标题\n\nTom & Jerry\n\n引用正文\nA < B\nA > B", rewritten["items"][0]["subtitle"])
        self.assertNotIn("\n>", rewritten["items"][0]["subtitle"])
        self.assertEqual(1, len(synth_commands))

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
