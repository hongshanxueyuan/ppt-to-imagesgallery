import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from repair_imagesgallery_materials import main  # noqa: E402


def _write_stage_b_manifest(manifest_path: Path, **overrides: object) -> dict:
    payload = {
        "version": "1.0",
        "source_ppt": "sample.pptx",
        "section_id": "1.2",
        "section_title": "1.2 示例",
        "block_type": "html",
        "audio": {
            "voice": "longxiaochun_v2",
            "rate": 1.1,
            "model": "cosyvoice-v2",
            "gap_seconds_between_segments": 1.0,
            "full_audio": "D:\\old-course\\audio\\full_speech.mp3",
            "timeline_file": "D:\\old-course\\audio\\speech_timestamps.json",
        },
        "items": [
            {
                "page": 1,
                "image": "images/page-001.png",
                "subtitle": "第一页字幕",
                "start": 0,
                "end": 1200,
            },
            {
                "page": 2,
                "image": "images/page-002.png",
                "subtitle": "第二页字幕",
                "start": 2200,
                "end": 3500,
            },
        ],
    }
    payload.update(overrides)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


class TestRepairImagesGalleryMaterials(unittest.TestCase):
    def test_unique_local_audio_repairs_stale_path_without_running_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery_dir = root / "gallery" / "imagesgallery"
            manifest_path = gallery_dir / "imagesgallery.json"
            for name in ("page-001.png", "page-002.png"):
                image_path = gallery_dir / "images" / name
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(b"image")
            local_audio = root / "source-materials" / "full_speech.mp3"
            local_audio.parent.mkdir(parents=True)
            local_audio.write_bytes(b"existing-full-audio")
            _write_stage_b_manifest(manifest_path)

            with patch("repair_imagesgallery_materials.build_audio_stage") as build_audio:
                exit_code = main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--audio-search-root",
                        str(local_audio.parent),
                    ]
                )

            saved = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(str(local_audio.resolve()), saved["audio"]["full_audio"])
        self.assertEqual(0, build_audio.call_count)
        self.assertEqual("第一页字幕", saved["items"][0]["subtitle"])
        self.assertEqual(2200, saved["items"][1]["start"])

    def test_ambiguous_local_audio_paths_stop_without_rewriting_manifest_or_running_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery_dir = root / "gallery" / "imagesgallery"
            manifest_path = gallery_dir / "imagesgallery.json"
            for name in ("page-001.png", "page-002.png"):
                image_path = gallery_dir / "images" / name
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(b"image")
            _write_stage_b_manifest(manifest_path)
            original_manifest = manifest_path.read_bytes()
            search_root = root / "source-materials"
            for folder in ("section-a", "section-b"):
                audio_path = search_root / folder / "full_speech.mp3"
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_path.write_bytes(folder.encode())

            with patch("repair_imagesgallery_materials.build_audio_stage") as build_audio:
                exit_code = main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--audio-search-root",
                        str(search_root),
                    ]
                )

            saved_bytes = manifest_path.read_bytes()

        self.assertEqual(1, exit_code)
        self.assertEqual(original_manifest, saved_bytes)
        self.assertEqual(0, build_audio.call_count)

    def test_missing_images_regenerate_in_staging_and_preserve_stage_b_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery_dir = root / "existing-package" / "imagesgallery"
            manifest_path = gallery_dir / "imagesgallery.json"
            existing_image = gallery_dir / "images" / "page-002.png"
            existing_image.parent.mkdir(parents=True)
            existing_image.write_bytes(b"keep-this-image")
            audio_path = gallery_dir / "audio" / "full_speech.mp3"
            audio_path.parent.mkdir(parents=True)
            audio_path.write_bytes(b"existing-audio")

            manifest = _write_stage_b_manifest(
                manifest_path,
                audio={"full_audio": str(audio_path), "voice": "longxiaochun_v2"},
            )
            ppt_path = root / "sample.pptx"
            ppt_path.write_bytes(b"source-ppt")
            section_json_path = root / "section.json"
            section_json_path.write_text(
                json.dumps(
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 示例",
                        "page_count": 2,
                        "page_content": ["第一页原文", "第二页原文"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            staging_outputs: list[Path] = []

            def fake_build_imagesgallery(args):
                staging_gallery = Path(args.out) / "sample" / "imagesgallery"
                staging_outputs.append(staging_gallery)
                first_image = staging_gallery / "images" / "regenerated-page-001.png"
                second_image = staging_gallery / "images" / "unused-page-002.png"
                first_image.parent.mkdir(parents=True, exist_ok=True)
                first_image.write_bytes(b"regenerated-page-one")
                second_image.write_bytes(b"regenerated-page-two")
                staged_manifest = {
                    "section_id": "1.2",
                    "items": [
                        {"page_number": 1, "image": "images/regenerated-page-001.png"},
                        {"page_number": 2, "image": "images/unused-page-002.png"},
                    ],
                }
                (staging_gallery / "imagesgallery.json").write_text(
                    json.dumps(staged_manifest, ensure_ascii=False),
                    encoding="utf-8",
                )
                return staged_manifest

            with patch(
                "repair_imagesgallery_materials.build_imagesgallery",
                side_effect=fake_build_imagesgallery,
            ) as build_images, patch("repair_imagesgallery_materials.build_audio_stage") as build_audio:
                exit_code = main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--ppt",
                        str(ppt_path),
                        "--section-json",
                        str(section_json_path),
                    ]
                )

            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            repaired_image = gallery_dir / saved["items"][0]["image"]
            repaired_image_bytes = repaired_image.read_bytes()
            existing_image_bytes = existing_image.read_bytes()

        self.assertEqual(0, exit_code)
        self.assertEqual(1, build_images.call_count)
        self.assertEqual(0, build_audio.call_count)
        self.assertTrue(staging_outputs[0].parents[1].name.startswith("imagesgallery-repair-"))
        self.assertNotEqual(gallery_dir.resolve(), staging_outputs[0].resolve())
        self.assertEqual(b"regenerated-page-one", repaired_image_bytes)
        self.assertEqual(b"keep-this-image", existing_image_bytes)
        self.assertEqual(manifest["audio"], saved["audio"])
        self.assertEqual("html", saved["block_type"])
        self.assertEqual("第一页字幕", saved["items"][0]["subtitle"])
        self.assertEqual(0, saved["items"][0]["start"])
        self.assertEqual(1200, saved["items"][0]["end"])
        self.assertEqual("images/page-002.png", saved["items"][1]["image"])

    def test_image_repair_requires_source_identity_and_prefers_matching_section_id(self):
        cases = (
            ("different_title_without_ids", None, None, "1.2 示例", "1.2 不同小节", 1),
            ("matching_title_without_ids", None, None, "1.2 示例", "1.2 示例", 0),
            ("matching_id_takes_precedence", "1.2", "1.2", "1.2 示例", "1.2 已改名", 0),
        )
        for case, manifest_section_id, source_section_id, manifest_title, section_title, expected_exit_code in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                gallery_dir = root / "gallery" / "imagesgallery"
                manifest_path = gallery_dir / "imagesgallery.json"
                audio_path = gallery_dir / "audio" / "full_speech.mp3"
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_path.write_bytes(b"existing-full-audio")
                existing_image = gallery_dir / "images" / "page-002.png"
                existing_image.parent.mkdir(parents=True, exist_ok=True)
                existing_image.write_bytes(b"existing-page-two")
                manifest = _write_stage_b_manifest(
                    manifest_path,
                    section_id=manifest_section_id or "1.2",
                    section_title=manifest_title,
                    audio={"full_audio": str(audio_path)},
                )
                if manifest_section_id is None:
                    manifest.pop("section_id")
                manifest["items"][0]["image"] = "images/missing-page-001.png"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                original_manifest = manifest_path.read_bytes()

                ppt_path = root / "sample.pptx"
                ppt_path.write_bytes(b"source-ppt")
                section_json_path = root / "section.json"
                section_payload = {
                    "section_title": section_title,
                    "page_count": 2,
                    "page_content": ["第一页原文", "第二页原文"],
                }
                if source_section_id is not None:
                    section_payload["section_id"] = source_section_id
                section_json_path.write_text(json.dumps(section_payload, ensure_ascii=False), encoding="utf-8")

                def fake_build_imagesgallery(args):
                    staging_gallery = Path(args.out) / "sample" / "imagesgallery"
                    first_image = staging_gallery / "images" / "regenerated-page-001.png"
                    second_image = staging_gallery / "images" / "unused-page-002.png"
                    first_image.parent.mkdir(parents=True, exist_ok=True)
                    first_image.write_bytes(b"regenerated-page-one")
                    second_image.write_bytes(b"regenerated-page-two")
                    staged_manifest = {
                        "section_title": section_title,
                        "items": [
                            {"page_number": 1, "image": "images/regenerated-page-001.png"},
                            {"page_number": 2, "image": "images/unused-page-002.png"},
                        ],
                    }
                    if source_section_id is not None:
                        staged_manifest["section_id"] = source_section_id
                    (staging_gallery / "imagesgallery.json").write_text(
                        json.dumps(staged_manifest, ensure_ascii=False),
                        encoding="utf-8",
                    )

                stderr = StringIO()
                with patch(
                    "repair_imagesgallery_materials.build_imagesgallery",
                    side_effect=fake_build_imagesgallery,
                ) as build_images, patch("repair_imagesgallery_materials.build_audio_stage") as build_audio:
                    with redirect_stderr(stderr):
                        exit_code = main(
                            [
                                "--manifest",
                                str(manifest_path),
                                "--ppt",
                                str(ppt_path),
                                "--section-json",
                                str(section_json_path),
                            ]
                        )

                saved_bytes = manifest_path.read_bytes()
                if expected_exit_code == 0:
                    saved = json.loads(saved_bytes)
                    repaired_image = gallery_dir / saved["items"][0]["image"]
                    repaired_image_bytes = repaired_image.read_bytes()
                else:
                    repaired_image_bytes = None

            self.assertEqual(expected_exit_code, exit_code)
            self.assertEqual(0, build_audio.call_count)
            if expected_exit_code:
                self.assertEqual(0, build_images.call_count)
                self.assertEqual(original_manifest, saved_bytes)
                self.assertIn("section_title", stderr.getvalue())
            else:
                self.assertEqual(1, build_images.call_count)
                self.assertEqual(b"regenerated-page-one", repaired_image_bytes)
                self.assertEqual("第一页字幕", saved["items"][0]["subtitle"])
                self.assertEqual(0, saved["items"][0]["start"])

    def test_missing_audio_rebuilds_using_existing_segments_and_stubbed_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery_dir = root / "gallery" / "imagesgallery"
            manifest_path = gallery_dir / "imagesgallery.json"
            for name in ("page-001.png", "page-002.png"):
                image_path = gallery_dir / "images" / name
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(b"image")
            segments_dir = gallery_dir / "audio" / "segments"
            segments_dir.mkdir(parents=True)
            (segments_dir / "page-001.mp3").write_bytes(b"existing-segment-1")
            (segments_dir / "page-002.mp3").write_bytes(b"existing-segment-2")
            _write_stage_b_manifest(manifest_path)

            external_commands: list[list[str]] = []

            def fake_run_cmd(command: list[str]) -> None:
                external_commands.append(command)
                if command[:3] == ["fake-bl", "speech", "synthesize"]:
                    output_path = Path(command[command.index("--out") + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(b"synthesized-segment")
                elif command[:3] == ["fake-ffmpeg", "-y", "-f"]:
                    output_path = Path(command[-1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(b"remuxed-full-audio")

            def fake_build_preview_html(_manifest, _manifest_path):
                preview_path = gallery_dir / "audio" / "preview.html"
                preview_path.write_text("<html></html>", encoding="utf-8")
                return preview_path

            with patch(
                "synthesize_imagesgallery_audio.resolve_bin",
                side_effect=lambda name: f"fake-{name}",
            ), patch("synthesize_imagesgallery_audio.run_cmd", side_effect=fake_run_cmd), patch(
                "synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5
            ), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ):
                exit_code = main(["--manifest", str(manifest_path)])

            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            final_audio = Path(saved["audio"]["full_audio"])
            final_audio_bytes = final_audio.read_bytes() if final_audio.is_file() else None

        self.assertEqual(0, exit_code)
        self.assertEqual(b"remuxed-full-audio", final_audio_bytes)
        self.assertFalse(any(command[:3] == ["fake-bl", "speech", "synthesize"] for command in external_commands))
        self.assertEqual([1, 2], [item["page"] for item in saved["items"]])
        self.assertTrue(all("start" in item and "end" in item and "subtitle" in item for item in saved["items"]))

    def test_missing_subtitle_uses_section_json_and_reruns_only_the_audio_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery_dir = root / "gallery" / "imagesgallery"
            manifest_path = gallery_dir / "imagesgallery.json"
            image_path = gallery_dir / "images" / "page-001.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(b"keep-image")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "section_id": "1.2",
                        "audio": {"full_audio": "D:\\old-course\\audio\\full_speech.mp3"},
                        "items": [{"page": 1, "image": "images/page-001.png"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            section_json_path = root / "section.json"
            section_json_path.write_text(
                json.dumps(
                    {
                        "section_id": "1.2",
                        "page_count": 1,
                        "page_content": ["## 标题\n\n从 section JSON 恢复字幕"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            external_commands: list[list[str]] = []
            tts_texts: list[str] = []

            def fake_run_cmd(command: list[str]) -> None:
                external_commands.append(command)
                if command[:3] == ["fake-bl", "speech", "synthesize"]:
                    text_path = Path(command[command.index("--text-file") + 1])
                    tts_texts.append(text_path.read_text(encoding="utf-8"))
                    output_path = Path(command[command.index("--out") + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(b"new-segment")
                elif command[:3] == ["fake-ffmpeg", "-y", "-f"]:
                    output_path = Path(command[-1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(b"new-full-audio")

            def fake_build_preview_html(_manifest, _manifest_path):
                preview_path = gallery_dir / "audio" / "preview.html"
                preview_path.write_text("<html></html>", encoding="utf-8")
                return preview_path

            with patch(
                "synthesize_imagesgallery_audio.resolve_bin",
                side_effect=lambda name: f"fake-{name}",
            ), patch("synthesize_imagesgallery_audio.run_cmd", side_effect=fake_run_cmd), patch(
                "synthesize_imagesgallery_audio.ffprobe_duration", return_value=1.5
            ), patch(
                "synthesize_imagesgallery_audio.build_preview_html",
                side_effect=fake_build_preview_html,
            ), patch("repair_imagesgallery_materials.build_imagesgallery") as build_images:
                exit_code = main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--section-json",
                        str(section_json_path),
                    ]
                )

            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            full_audio = Path(saved["audio"]["full_audio"])
            full_audio_bytes = full_audio.read_bytes() if full_audio.is_file() else None

        self.assertEqual(0, exit_code)
        self.assertEqual(0, build_images.call_count)
        self.assertEqual(1, len(tts_texts))
        self.assertIn("从 section JSON 恢复字幕", tts_texts[0])
        self.assertEqual(b"new-full-audio", full_audio_bytes)
        self.assertEqual("images/page-001.png", saved["items"][0]["image"])
        self.assertIn("从 section JSON 恢复字幕", saved["items"][0]["subtitle"])
        self.assertGreater(saved["items"][0]["end"], saved["items"][0]["start"])


if __name__ == "__main__":
    unittest.main()
