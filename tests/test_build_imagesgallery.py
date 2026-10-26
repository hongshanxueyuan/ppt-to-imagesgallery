import argparse
import io
import json
import random
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys
import zlib
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_imagesgallery import (  # noqa: E402
    _build_image_name_prefix,
    _build_page_image_name,
    build_imagesgallery,
    count_presentation_pages,
    main,
    validate_section_payload,
)


MAX_IMAGE_BYTES = 500_000


def _png_bytes_with_exact_size(image: Image.Image, size: int) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    png = stream.getvalue()
    payload_size = size - len(png) - 12
    if payload_size < 2:
        raise ValueError("requested PNG fixture size is too small")
    payload = b"p\x00" + b"x" * (payload_size - 2)
    chunk_data = b"tEXt" + payload
    text_chunk = (
        struct.pack(">I", len(payload))
        + chunk_data
        + struct.pack(">I", zlib.crc32(chunk_data) & 0xFFFFFFFF)
    )
    return png[:-12] + text_chunk + png[-12:]


def _png_with_exact_size(size: int, dimensions: tuple[int, int] = (32, 24)) -> bytes:
    return _png_bytes_with_exact_size(Image.new("RGB", dimensions, "white"), size)


def _text_slide_png_with_exact_size(size: int) -> bytes:
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=48)
    body_font = ImageFont.load_default(size=30)
    small_font = ImageFont.load_default(size=22)
    draw.rectangle((48, 42, 1232, 158), outline="#333333", width=3)
    draw.text((76, 72), "Slide title: Batch image workflow", fill="#111111", font=title_font)
    draw.text((76, 210), "1. Match each deck to its section", fill="#111111", font=body_font)
    draw.text((76, 270), "2. Render one page image per slide", fill="#111111", font=body_font)
    draw.text((76, 330), "3. Compress oversized pages without resizing", fill="#111111", font=body_font)
    draw.rounded_rectangle((76, 420, 430, 555), radius=12, outline="#245b85", width=4)
    draw.text((100, 468), "Source deck", fill="#111111", font=small_font)
    draw.line((430, 488, 650, 488), fill="#245b85", width=5)
    draw.polygon(((650, 478), (672, 488), (650, 498)), fill="#245b85")
    draw.rounded_rectangle((672, 420, 1100, 555), radius=12, outline="#245b85", width=4)
    draw.text((700, 468), "ImagesGallery pages", fill="#111111", font=small_font)
    return _png_bytes_with_exact_size(image, size)


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

    def test_validate_section_payload_rejects_content_that_cleans_to_blank(self):
        with self.assertRaisesRegex(ValueError, "page_content\\[1\\] must not be blank"):
            validate_section_payload(
                {
                    "section_id": "1.1",
                    "section_title": "1.1 课程A",
                    "page_count": 1,
                    "page_content": ["<script>not spoken</script>&nbsp;<br><!-- hidden -->"],
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

    def test_build_imagesgallery_cleans_html_from_speech_and_preserves_source_json(self):
        raw_page = (
            "## 标题\n\n"
            "<p>Tom &amp;amp; Jerry &#39; &#x4e2d;&#x6587;</p>"
            "<br><span>实体标签&nbsp;&nbsp;正文</span>"
            "<div>第二段</div>"
            "<custom-tag data-note='hidden'>自定义正文</custom-tag>"
            "&lt;strong&gt;转义标签正文&lt;/strong&gt;"
            "&amp;lt;em&amp;gt;双重转义标签&amp;lt;/em&amp;gt;"
            "<!-- 不读注释 -->"
            "<script>console.log('不读脚本')</script>"
            "<style>.x { color: red; }</style>"
            "a < b &unknown; &broken <unknown"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            source_section = {
                "section_id": "1.2",
                "section_title": "1.2 课程A",
                "resource_title": "1.2 课程A",
                "output_name": "1.2 课程A.pptx",
                "page_count": 1,
                "page_content": [raw_page],
            }
            ppt_path.write_bytes(b"fake-ppt")
            section_json_path.write_text(json.dumps(source_section, ensure_ascii=False), encoding="utf-8")

            def fake_convert(_ppt_path, images_dir, image_name_prefix="", image_name_timestamp="", **kwargs):
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
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                manifest = build_imagesgallery(args)

            source_after_build = json.loads(section_json_path.read_text(encoding="utf-8"))

        speech = manifest["items"][0]["speech"]
        self.assertEqual(
            "## 标题\n\n"
            "Tom & Jerry ' 中文\n"
            "实体标签 正文\n"
            "第二段\n"
            "自定义正文转义标签正文双重转义标签\n"
            "a < b &unknown; &broken <unknown",
            speech,
        )
        self.assertNotIn("amp", speech)
        self.assertNotIn("nbsp", speech)
        self.assertEqual(source_section, source_after_build)

    def test_builder_leaves_page_images_at_or_below_limit_unchanged(self):
        for size in (MAX_IMAGE_BYTES - 1, MAX_IMAGE_BYTES):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                ppt_path = tmp_path / "sample.pptx"
                section_json_path = tmp_path / "section.json"
                out_dir = tmp_path / "out"
                ppt_path.write_bytes(b"source-ppt")
                section_json_path.write_text(
                    json.dumps({"page_count": 1, "page_content": ["第一页正文"]}),
                    encoding="utf-8",
                )
                source_bytes = _png_with_exact_size(size)

                def fake_convert(_ppt_path, images_dir, **kwargs):
                    image_path = images_dir / "page-001.png"
                    image_path.write_bytes(source_bytes)
                    return [image_path]

                args = argparse.Namespace(
                    ppt=str(ppt_path),
                    section_json=str(section_json_path),
                    out=str(out_dir),
                    dry_run=True,
                )
                with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                    "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
                ):
                    manifest = build_imagesgallery(args)

                image_path = out_dir / "sample" / "imagesgallery" / manifest["items"][0]["image"]
                self.assertEqual(".png", image_path.suffix)
                self.assertEqual(source_bytes, image_path.read_bytes())
                self.assertEqual("source-ppt", ppt_path.read_bytes().decode())

    def test_builder_compresses_oversized_page_to_dimension_preserving_jpg(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"source-ppt")
            section_json_path.write_text(
                json.dumps({"page_count": 1, "page_content": ["第一页正文"]}),
                encoding="utf-8",
            )
            source_bytes = _text_slide_png_with_exact_size(MAX_IMAGE_BYTES + 1)

            def fake_convert(_ppt_path, images_dir, **kwargs):
                image_path = images_dir / "page-001.png"
                image_path.write_bytes(source_bytes)
                return [image_path]

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                manifest = build_imagesgallery(args)

            gallery_dir = out_dir / "sample" / "imagesgallery"
            image_path = gallery_dir / manifest["items"][0]["image"]
            with Image.open(image_path) as image:
                self.assertEqual((1280, 720), image.size)
                self.assertEqual("JPEG", image.format)
                with Image.open(io.BytesIO(source_bytes)) as source_file:
                    source_image = source_file.convert("RGB")
                final_image = image.convert("RGB")
                title_difference = ImageChops.difference(
                    source_image.crop((70, 60, 900, 145)),
                    final_image.crop((70, 60, 900, 145)),
                )
                self.assertLess(ImageStat.Stat(title_difference).mean[0], 5)
                text_crop = final_image.convert("L").crop((70, 60, 900, 145))
                self.assertLess(text_crop.getextrema()[0], 80)
            self.assertLessEqual(image_path.stat().st_size, MAX_IMAGE_BYTES)
            self.assertFalse(image_path.with_suffix(".png").exists())
            self.assertEqual("source-ppt", ppt_path.read_bytes().decode())

    def test_builder_uses_highest_jpeg_quality_that_fits_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"source-ppt")
            section_json_path.write_text(
                json.dumps({"page_count": 1, "page_content": ["合成测试页"]}),
                encoding="utf-8",
            )

            source_image = Image.frombytes(
                "RGB",
                (768, 768),
                random.Random(271828).randbytes(768 * 768 * 3),
            )
            source_stream = io.BytesIO()
            source_image.save(source_stream, format="PNG", compress_level=1)
            source_bytes = source_stream.getvalue()

            reference_encodings = {}
            for quality in (95, 90):
                reference = io.BytesIO()
                source_image.save(
                    reference,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )
                reference_encodings[quality] = reference.getvalue()

            self.assertGreater(len(source_bytes), MAX_IMAGE_BYTES)
            self.assertGreater(len(reference_encodings[95]), MAX_IMAGE_BYTES)
            self.assertLessEqual(len(reference_encodings[90]), MAX_IMAGE_BYTES)

            def fake_convert(_ppt_path, images_dir, **kwargs):
                image_path = images_dir / "page-001.png"
                image_path.write_bytes(source_bytes)
                return [image_path]

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                manifest = build_imagesgallery(args)

            gallery_dir = out_dir / "sample" / "imagesgallery"
            image_path = gallery_dir / manifest["items"][0]["image"]
            self.assertEqual("images/page-001.jpg", manifest["items"][0]["image"])
            self.assertEqual(reference_encodings[90], image_path.read_bytes())
            self.assertLessEqual(image_path.stat().st_size, MAX_IMAGE_BYTES)

    def test_builder_downsamples_oversized_page_to_2560_pixel_long_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"source-ppt")
            section_json_path.write_text(
                json.dumps({"page_count": 1, "page_content": ["第一页正文"]}),
                encoding="utf-8",
            )
            source_bytes = _png_with_exact_size(MAX_IMAGE_BYTES + 1, dimensions=(5333, 3000))

            def fake_convert(_ppt_path, images_dir, **kwargs):
                image_path = images_dir / "page-001.png"
                image_path.write_bytes(source_bytes)
                return [image_path]

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                manifest = build_imagesgallery(args)

            gallery_dir = out_dir / "sample" / "imagesgallery"
            image_path = gallery_dir / manifest["items"][0]["image"]
            with Image.open(image_path) as image:
                self.assertEqual((2560, 1440), image.size)
                self.assertEqual("JPEG", image.format)
                self.assertLess(abs(image.width / image.height - 5333 / 3000), 0.001)
            self.assertLessEqual(image_path.stat().st_size, MAX_IMAGE_BYTES)
            self.assertEqual("images/page-001.jpg", manifest["items"][0]["image"])

    def test_builder_reports_compression_failure_and_removes_partial_gallery(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            section_json_path = tmp_path / "section.json"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"source-ppt")
            section_json_path.write_text(
                json.dumps({"page_count": 2, "page_content": ["第一页正文", "第二页正文"]}),
                encoding="utf-8",
            )
            first_page_bytes = _text_slide_png_with_exact_size(MAX_IMAGE_BYTES + 1)
            noisy_image = Image.frombytes("RGB", (1024, 1024), random.Random(7).randbytes(1024 * 1024 * 3))
            noisy_stream = io.BytesIO()
            noisy_image.save(noisy_stream, format="PNG", compress_level=1)
            second_page_bytes = noisy_stream.getvalue()

            def fake_convert(_ppt_path, images_dir, **kwargs):
                image_paths = []
                for page_number in (1, 2):
                    image_path = images_dir / f"page-{page_number:03d}.png"
                    image_path.write_bytes(first_page_bytes if page_number == 1 else second_page_bytes)
                    image_paths.append(image_path)
                return image_paths

            args = argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(out_dir),
                dry_run=True,
            )
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"sample\.pptx.*page-002\.png.*500000 bytes.*JPEG remains \d+ bytes above.*minimum quality 80",
                ) as caught:
                    build_imagesgallery(args)

            gallery_dir = out_dir / "sample" / "imagesgallery"
            self.assertFalse((gallery_dir / "imagesgallery.json").exists())
            self.assertFalse(gallery_dir.exists())
            self.assertIn(f"{len(second_page_bytes)} bytes", str(caught.exception))
            self.assertEqual("source-ppt", ppt_path.read_bytes().decode())

    def test_documented_batch_loop_continues_after_failed_builder_and_summarizes(self):
        # The batch workflow is skill-driven, so exercise its documented per-deck CLI loop.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            section_json_path = tmp_path / "section.json"
            section_json_path.write_text(
                json.dumps({"page_count": 1, "page_content": ["第一页正文"]}),
                encoding="utf-8",
            )
            failed_ppt = tmp_path / "failed.pptx"
            later_ppt = tmp_path / "later.pptx"
            failed_ppt.write_bytes(b"source-ppt")
            later_ppt.write_bytes(b"source-ppt")
            oversized_png = _png_with_exact_size(MAX_IMAGE_BYTES + 1)
            small_png = _png_with_exact_size(1024)

            def fake_convert(ppt_path, images_dir, **kwargs):
                image_path = images_dir / "page-001.png"
                image_path.write_bytes(oversized_png if ppt_path.stem == "failed" else small_png)
                return [image_path]

            completed_decks = []
            failed_decks = []
            for ppt_path in (failed_ppt, later_ppt):
                stdout = io.StringIO()
                stderr = io.StringIO()
                args = [
                    "--ppt",
                    str(ppt_path),
                    "--section-json",
                    str(section_json_path),
                    "--out",
                    str(out_dir),
                ]
                with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                    "build_imagesgallery.resolve_bin", return_value="fake-bin"
                ), patch("build_imagesgallery.convert_ppt_to_images", side_effect=fake_convert):
                    if ppt_path == failed_ppt:
                        with patch("PIL.Image.Image.save", side_effect=OSError("encoder unavailable")):
                            exit_code = main(args)
                    else:
                        exit_code = main(args)

                if exit_code == 0:
                    completed_decks.append(ppt_path.stem)
                else:
                    failed_decks.append({"deck": ppt_path.name, "reason": stderr.getvalue().strip()})

            summary = {
                "status": "incomplete" if failed_decks else "complete",
                "completed": completed_decks,
                "failed": failed_decks,
            }
            failure = summary["failed"][0]
            self.assertEqual(["later"], summary["completed"])
            self.assertEqual("incomplete", summary["status"])
            self.assertEqual("failed.pptx", failure["deck"])
            self.assertIn("failed.pptx", failure["reason"])
            self.assertIn("500001 bytes", failure["reason"])
            self.assertIn("500000 bytes", failure["reason"])
            self.assertIn("encoder unavailable", failure["reason"])
            self.assertFalse((out_dir / "failed" / "imagesgallery").exists())
            later_manifest_path = out_dir / "later" / "imagesgallery" / "imagesgallery.json"
            self.assertTrue(later_manifest_path.exists())
            later_manifest = json.loads(later_manifest_path.read_text(encoding="utf-8"))
            self.assertTrue((later_manifest_path.parent / later_manifest["items"][0]["image"]).exists())

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
        self.assertIn("压缩页图", skill_doc)
        self.assertIn("继续处理后续 admitted deck", skill_doc)
        self.assertIn("批次未全部成功", skill_doc)
        self.assertIn("音频与预览", skill_doc)
        self.assertIn("批量 Studio 规划", skill_doc)
        self.assertIn("run 默认声音", skill_doc)
        self.assertIn("单个 PPT 声音覆盖", skill_doc)
        self.assertIn("page 声音覆盖", skill_doc)
        self.assertIn("男声", skill_doc)
        self.assertIn("女声", skill_doc)
        self.assertNotIn("source_speech", skill_doc)
        self.assertNotIn("prompt_full_speech_session", skill_doc)

    def test_legacy_prompt_reference_file_is_deleted(self):
        self.assertFalse((SCRIPT_DIR.parent / "references" / "prompt_full_speech_session.md").exists())

    def test_agent_prompt_surface_matches_batch_only_contract(self):
        agent_yaml = (SCRIPT_DIR.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("section-list", agent_yaml)
        self.assertIn("调用 $ppt-to-imagesgallery", agent_yaml)
        self.assertIn("run 默认声音", agent_yaml)
        self.assertIn("单个 PPT 声音覆盖", agent_yaml)
        self.assertIn("page 声音覆盖", agent_yaml)
        self.assertNotIn("manuscript", agent_yaml)


if __name__ == "__main__":
    unittest.main()
