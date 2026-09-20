import argparse
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_imagesgallery import (  # noqa: E402
    _build_image_name_prefix,
    _build_page_image_name,
    build_imagesgallery,
    count_presentation_pages,
    validate_section_payload,
)


class TestBuildImagesGallery(unittest.TestCase):
    def test_validate_section_payload_rejects_blank_page_content(self):
        with self.assertRaisesRegex(ValueError, "page_content\\[2\\] must not be blank"):
            validate_section_payload(
                {
                    "section_id": "1.1",
                    "section_title": "1.1 课程A",
                    "page_count": 2,
                    "page_content": ["## 第一页", "   "],
                }
            )

    def test_build_page_image_name_uses_prefix_and_timestamp_suffix(self):
        prefix = _build_image_name_prefix("1.3 流程智能体与普通AI助手的区别_水印版")
        self.assertRegex(prefix, r"^[a-z0-9-]+$")
        self.assertRegex(prefix, r"[0-9a-f]{8}$")
        self.assertEqual(
            f"{prefix}__page-012__20260817-163045-123.png",
            _build_page_image_name(prefix, 12, "20260817-163045-123"),
        )

    def test_build_imagesgallery_creates_stage_a_manifest_from_section_page_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"fake-ppt")
            section_json_path.write_text(
                json.dumps(
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "resource_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                        "page_count": 2,
                        "page_content": ["## 第一页\n\n第一页正文", "## 第二页\n\n第二页正文"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_convert(
                _ppt_path,
                images_dir,
                soffice_bin=None,
                pdftoppm_bin=None,
                image_name_prefix="",
                image_name_timestamp="",
            ):
                image_paths = []
                for idx in range(1, 3):
                    image_path = images_dir / f"{image_name_prefix}__page-{idx:03d}__{image_name_timestamp}.png"
                    image_path.write_bytes(b"fake-image")
                    image_paths.append(image_path)
                return image_paths

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images",
                side_effect=fake_convert,
            ):
                manifest = build_imagesgallery(args)

        self.assertEqual("1.0", manifest["version"])
        self.assertEqual(str(ppt_path.resolve()), manifest["source_ppt"])
        self.assertNotIn("source_speech", manifest)
        self.assertEqual(2, len(manifest["items"]))
        self.assertEqual("## 第一页\n\n第一页正文", manifest["items"][0]["speech"])
        self.assertEqual("## 第二页\n\n第二页正文", manifest["items"][1]["speech"])
        self.assertRegex(manifest["items"][0]["image"], r"images/.+__page-001__\d{8}-\d{6}-\d{3}\.png")

    def test_build_imagesgallery_rejects_rendered_slide_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"fake-ppt")
            section_json_path.write_text(
                json.dumps(
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "resource_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                        "page_count": 2,
                        "page_content": ["## 第一页", "## 第二页"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_convert(
                _ppt_path,
                images_dir,
                soffice_bin=None,
                pdftoppm_bin=None,
                image_name_prefix="",
                image_name_timestamp="",
            ):
                image_path = images_dir / f"{image_name_prefix}__page-001__{image_name_timestamp}.png"
                image_path.write_bytes(b"fake-image")
                return [image_path]

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images",
                side_effect=fake_convert,
            ):
                with self.assertRaisesRegex(ValueError, "rendered slide count 1 does not match page_count 2"):
                    build_imagesgallery(args)

    def test_count_presentation_pages_reads_pptx_metadata_without_rendering_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            ppt_path = Path(tmp) / "sample.pptx"
            with zipfile.ZipFile(ppt_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("ppt/presentation.xml", "<presentation/>")
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
                archive.writestr("ppt/slides/slide2.xml", "<slide/>")
                archive.writestr("ppt/slides/slide3.xml", "<slide/>")

            with patch(
                "build_imagesgallery.convert_ppt_to_images",
                side_effect=AssertionError("counting should not render images"),
            ):
                observed = count_presentation_pages(ppt_path)

        self.assertEqual(3, observed)

    def test_skill_doc_teaches_batch_only_section_list_workflow(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", skill_doc)
        self.assertIn("section-list.json", skill_doc)
        self.assertIn("preflight", skill_doc)
        self.assertIn("本地 `.ppt` / `.pptx`", skill_doc)
        self.assertIn("stage-A manifest", skill_doc)
        self.assertIn("单 deck 构建", skill_doc)
        self.assertIn("音频与预览", skill_doc)
        self.assertIn("批量 Studio 规划", skill_doc)
        self.assertNotIn("source_speech", skill_doc)
        self.assertNotIn("prompt_full_speech_session", skill_doc)

    def test_legacy_prompt_reference_file_is_deleted(self):
        self.assertFalse((SCRIPT_DIR.parent / "references" / "prompt_full_speech_session.md").exists())

    def test_agent_prompt_surface_matches_batch_only_contract(self):
        agent_yaml = (SCRIPT_DIR.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("section-list", agent_yaml)
        self.assertIn("调用 $ppt-to-imagesgallery", agent_yaml)
        self.assertNotIn("manuscript", agent_yaml)


if __name__ == "__main__":
    unittest.main()
