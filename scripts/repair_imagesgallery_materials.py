#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Mapping, Sequence

from build_imagesgallery import build_imagesgallery, load_section_payload
from synthesize_imagesgallery_audio import (
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_RATE,
    build_audio as build_audio_stage,
)


def _page_number(item: Mapping[str, Any], index: int, label: str) -> int:
    raw_page = item.get("page", item.get("page_number"))
    if isinstance(raw_page, bool):
        raise ValueError(f"{label} item {index} has an invalid page number: {raw_page!r}")
    try:
        page_number = int(raw_page)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} item {index} has an invalid page number: {raw_page!r}") from exc
    if page_number < 1:
        raise ValueError(f"{label} item {index} has an invalid page number: {page_number}")
    return page_number


def _items_by_page(items: object, label: str) -> Dict[int, Dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{label} items must be a non-empty array")

    by_page: Dict[int, Dict[str, Any]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label} item {index} must be an object")
        page_number = _page_number(item, index, label)
        if page_number in by_page:
            raise ValueError(f"{label} has duplicate page number {page_number}")
        by_page[page_number] = item

    expected_pages = set(range(1, len(by_page) + 1))
    if set(by_page) != expected_pages:
        raise ValueError(f"{label} page numbers must be continuous from 1..N; got={sorted(by_page)}")
    return by_page


def _resolve_material_path(reference: str, base_dir: Path) -> Path:
    raw = reference.strip()
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()

    if os.sep == "/":
        raw = raw.replace("\\", "/")
    return (base_dir / Path(raw)).resolve()


def _has_text(item: Mapping[str, Any]) -> bool:
    for key in ("subtitle", "speech"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _has_stage_b_timing(item: Mapping[str, Any]) -> bool:
    if not isinstance(item.get("subtitle"), str) or not item["subtitle"].strip():
        return False
    start = item.get("start")
    end = item.get("end")
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return False
    return math.isfinite(float(start)) and math.isfinite(float(end)) and start >= 0 and end > start


def _load_section_for_manifest(section_json_path: Path, manifest: Mapping[str, Any], page_count: int) -> Dict[str, Any]:
    section = load_section_payload(section_json_path)
    if section["page_count"] != page_count:
        raise ValueError(
            f"section JSON page_count {section['page_count']} does not match gallery page count {page_count}"
        )

    manifest_section_id = manifest.get("section_id")
    source_section_id = section.get("section_id")
    manifest_section_id = manifest_section_id.strip() if isinstance(manifest_section_id, str) else ""
    source_section_id = source_section_id.strip() if isinstance(source_section_id, str) else ""
    if manifest_section_id and source_section_id:
        if manifest_section_id != source_section_id:
            raise ValueError(
                "section JSON does not match manifest.section_id: "
                f"{source_section_id!r} != {manifest_section_id!r}"
            )
        return section

    manifest_section_title = manifest.get("section_title")
    source_section_title = section.get("section_title")
    manifest_section_title = manifest_section_title.strip() if isinstance(manifest_section_title, str) else ""
    source_section_title = source_section_title.strip() if isinstance(source_section_title, str) else ""
    if not manifest_section_title or not source_section_title or manifest_section_title != source_section_title:
        raise ValueError(
            "section identity cannot be verified: section_id is unavailable and section_title does not uniquely match "
            f"({manifest_section_title!r} != {source_section_title!r})"
        )
    return section


def _staging_gallery_dir(staging_root: Path, ppt_path: Path) -> Path:
    deck_name = ppt_path.stem.strip() or "ppt"
    return staging_root / deck_name / "imagesgallery"


def _repair_missing_images(
    *,
    manifest: Dict[str, Any],
    manifest_path: Path,
    items_by_page: Mapping[int, Dict[str, Any]],
    missing_pages: Sequence[int],
    ppt_path: Path,
    section_json_path: Path,
) -> None:
    section = _load_section_for_manifest(section_json_path, manifest, len(items_by_page))
    if not ppt_path.is_file():
        raise FileNotFoundError(f"ppt file not found: {ppt_path}")

    gallery_dir = manifest_path.parent
    with tempfile.TemporaryDirectory(prefix="imagesgallery-repair-") as tmp:
        staging_root = Path(tmp)
        build_imagesgallery(
            argparse.Namespace(
                ppt=str(ppt_path),
                section_json=str(section_json_path),
                out=str(staging_root),
                dry_run=False,
            )
        )

        staged_gallery_dir = _staging_gallery_dir(staging_root, ppt_path)
        staged_manifest_path = staged_gallery_dir / "imagesgallery.json"
        if not staged_manifest_path.is_file():
            raise RuntimeError(f"image builder did not write a staged manifest: {staged_manifest_path}")
        staged_manifest = json.loads(staged_manifest_path.read_text(encoding="utf-8"))
        staged_items = _items_by_page(staged_manifest.get("items"), "staged manifest")
        if set(staged_items) != set(items_by_page):
            raise ValueError(
                "staged image page numbers do not match the existing Gallery: "
                f"{sorted(staged_items)} != {sorted(items_by_page)}"
            )
        staged_section_id = str(staged_manifest.get("section_id", "")).strip()
        if section["section_id"] and staged_section_id and section["section_id"] != staged_section_id:
            raise ValueError("staged manifest section_id does not match the resolved section JSON")

        for page_number in missing_pages:
            staged_item = staged_items[page_number]
            image_reference = staged_item.get("image")
            if not isinstance(image_reference, str) or not image_reference.strip():
                raise ValueError(f"staged manifest has no image path for page {page_number}")
            staged_image_path = _resolve_material_path(image_reference, staged_gallery_dir)
            try:
                staged_image_path.relative_to(staged_gallery_dir.resolve())
            except ValueError as exc:
                raise ValueError(f"staged image path escapes its staging Gallery: {image_reference}") from exc
            if not staged_image_path.is_file():
                raise FileNotFoundError(f"staged image for page {page_number} is missing: {staged_image_path}")

            image_relative_path = Path(image_reference.replace("\\", "/"))
            if image_relative_path.is_absolute() or ".." in image_relative_path.parts:
                raise ValueError(f"staged image path must be relative to the Gallery: {image_reference}")
            destination_path = gallery_dir / image_relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged_image_path, destination_path)
            items_by_page[page_number]["image"] = image_relative_path.as_posix()


def _audio_basename(reference: str) -> str:
    raw = reference.strip()
    if not raw:
        return "full_speech.mp3"
    if "\\" in raw:
        return PureWindowsPath(raw).name
    return Path(raw).name


def _find_audio_candidates(search_root: Path, basename: str) -> List[Path]:
    if not search_root.is_dir():
        raise NotADirectoryError(f"audio search root is not a directory: {search_root}")

    candidates: Dict[str, Path] = {}
    for path in search_root.rglob("*"):
        if path.is_file() and path.name.casefold() == basename.casefold():
            resolved = path.resolve()
            candidates[str(resolved).casefold()] = resolved
    return sorted(candidates.values(), key=lambda path: str(path).casefold())


def _validated_output_name(reference: str, suffix: str, fallback: str) -> str:
    basename = _audio_basename(reference)
    if basename and Path(basename).suffix.lower() == suffix and Path(basename).name == basename:
        return basename
    return fallback


def _audio_output_name(reference: str) -> str:
    return _validated_output_name(reference, ".mp3", "full_speech.mp3")


def _timeline_output_name(reference: str) -> str:
    return _validated_output_name(reference, ".json", "speech_timestamps.json")


def _run_audio_stage(manifest_path: Path, audio: Mapping[str, Any]) -> Dict[str, Any]:
    rate_value = audio.get("rate", DEFAULT_TTS_RATE)
    model_value = audio.get("model", DEFAULT_TTS_MODEL)
    gap_value = audio.get("gap_seconds_between_segments", 1.0)
    try:
        rate = float(rate_value)
        gap_seconds = float(gap_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("existing audio rate and gap configuration must be numeric") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("existing audio rate must be a positive finite number")
    if not math.isfinite(gap_seconds) or gap_seconds < 0:
        raise ValueError("existing audio gap_seconds_between_segments must be a non-negative finite number")

    voice = audio.get("voice", "")
    if not isinstance(voice, str):
        voice = ""
    model = model_value if isinstance(model_value, str) and model_value.strip() else DEFAULT_TTS_MODEL
    timeline_reference = audio.get("timeline_file", "")
    if not isinstance(timeline_reference, str):
        timeline_reference = ""

    args = argparse.Namespace(
        manifest=str(manifest_path),
        out_dir=str(manifest_path.parent / "audio"),
        voice=voice,
        voice_preset="",
        rate=rate,
        model=model,
        language="",
        gap_seconds=gap_seconds,
        final_name=_audio_output_name(str(audio.get("full_audio", ""))),
        timeline_name=_timeline_output_name(timeline_reference),
        skip_existing=True,
    )
    return build_audio_stage(args)


def _write_manifest(manifest_path: Path, manifest: Mapping[str, Any]) -> None:
    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=manifest_path.parent,
        prefix=f".{manifest_path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    try:
        with temporary_file:
            json.dump(manifest, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        temporary_path.replace(manifest_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def repair_materials(args: argparse.Namespace) -> Dict[str, Any]:
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    if args.ppt and not args.section_json:
        raise ValueError("--ppt requires --section-json")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    items_by_page = _items_by_page(data.get("items"), "manifest")
    gallery_dir = manifest_path.parent

    missing_image_pages = []
    for page_number, item in items_by_page.items():
        image_reference = item.get("image")
        if not isinstance(image_reference, str) or not image_reference.strip():
            missing_image_pages.append(page_number)
            continue
        if not _resolve_material_path(image_reference, gallery_dir).is_file():
            missing_image_pages.append(page_number)

    image_source: tuple[Path, Path] | None = None
    if missing_image_pages:
        if not args.ppt or not args.section_json:
            raise ValueError(
                "missing page images require both --ppt and --section-json; "
                f"missing pages: {missing_image_pages}"
            )
        image_source = (
            Path(args.ppt).expanduser().resolve(),
            Path(args.section_json).expanduser().resolve(),
        )

    audio_value = data.get("audio")
    audio = dict(audio_value) if isinstance(audio_value, dict) else {}
    full_audio_reference = audio.get("full_audio", "")
    if not isinstance(full_audio_reference, str):
        full_audio_reference = ""
    full_audio_path = _resolve_material_path(full_audio_reference, gallery_dir) if full_audio_reference else None
    full_audio_exists = bool(full_audio_path and full_audio_path.is_file())
    audio_path_repaired = False

    if not full_audio_exists:
        search_root = Path(args.audio_search_root).expanduser().resolve() if args.audio_search_root else gallery_dir
        candidates = _find_audio_candidates(search_root, _audio_basename(full_audio_reference))
        if len(candidates) > 1:
            paths = ", ".join(str(path) for path in candidates)
            raise ValueError(f"audio path is ambiguous; found multiple local files named {_audio_basename(full_audio_reference)!r}: {paths}")
        if len(candidates) == 1:
            audio["full_audio"] = str(candidates[0])
            data["audio"] = audio
            full_audio_exists = True
            audio_path_repaired = True

    audio_data_complete = all(_has_stage_b_timing(item) for item in items_by_page.values())
    audio_stage_required = not full_audio_exists or not audio_data_complete
    section: Dict[str, Any] | None = None
    source_text_added = False
    if audio_stage_required and any(not _has_text(item) for item in items_by_page.values()):
        if not args.section_json:
            missing_text_pages = [
                page_number for page_number, item in items_by_page.items() if not _has_text(item)
            ]
            raise ValueError(
                "missing subtitle text requires --section-json; "
                f"missing pages: {missing_text_pages}"
            )
        section_json_path = Path(args.section_json).expanduser().resolve()
        section = _load_section_for_manifest(section_json_path, data, len(items_by_page))
        for page_number, item in items_by_page.items():
            if not _has_text(item):
                item["speech"] = section["page_content"][page_number - 1]
                source_text_added = True

    if image_source:
        _repair_missing_images(
            manifest=data,
            manifest_path=manifest_path,
            items_by_page=items_by_page,
            missing_pages=missing_image_pages,
            ppt_path=image_source[0],
            section_json_path=image_source[1],
        )

    if missing_image_pages or audio_path_repaired or source_text_added or audio_stage_required:
        data["items"] = list(items_by_page.values())
        if audio or "audio" in data:
            data["audio"] = audio
        _write_manifest(manifest_path, data)

    audio_rebuilt = False
    if audio_stage_required:
        _run_audio_stage(manifest_path, audio)
        audio_rebuilt = True
        audio_path_repaired = False

    return {
        "manifest_path": str(manifest_path),
        "image_pages_regenerated": len(missing_image_pages),
        "audio_path_repaired": audio_path_repaired,
        "audio_rebuilt": audio_rebuilt,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair only the missing local ImagesGallery images, subtitles, timings, or audio."
    )
    parser.add_argument("--manifest", required=True, help="path to the existing ImagesGallery manifest")
    parser.add_argument("--ppt", default="", help="source PPT; required with --section-json when page images are missing")
    parser.add_argument(
        "--section-json",
        default="",
        help="resolved source section; supplies missing subtitle text and is required with --ppt for image rendering",
    )
    parser.add_argument(
        "--audio-search-root",
        default="",
        help="optional directory to search for one matching local full-audio file; defaults to the Gallery package",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(argv)
        result = repair_materials(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    details = [f"{result['image_pages_regenerated']} page image(s) regenerated"]
    if result["audio_path_repaired"]:
        details.append("existing audio path repaired")
    if result["audio_rebuilt"]:
        details.append("audio and timing rebuilt")
    if not result["image_pages_regenerated"] and not result["audio_path_repaired"] and not result["audio_rebuilt"]:
        print(f"OK: no local material repair needed -> {result['manifest_path']}")
    else:
        print(f"OK: {'; '.join(details)} -> {result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
