#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from urllib.parse import urlparse


PRESENTATION_SUFFIXES = (".pptx", ".ppt", ".pdf")
SPEECH_SUFFIX_PREFERENCE = (".docx", ".md", ".markdown", ".txt")
BATCH_METADATA_DIRNAME = "_batch"
STUDIO_TARGETS_FILENAME = "imagegallery-push-studio-targets.json"

IGNORED_REPORT_JSON_PATTERNS = (
    re.compile(r"(?i)^course-json-report\.json$"),
    re.compile(r"(?i)^create-report(?:[-_].+)?\.json$"),
    re.compile(r"(?i)^finalize-report(?:[-_].+)?\.json$"),
    re.compile(r"(?i)^upload-report\.json$"),
)

CANDIDATE_STRUCTURE_JSON_PATTERNS = (
    re.compile(r"(?i)^course\.json$"),
    re.compile(r"(?i)^section-list\.json$"),
    re.compile(r"(?i)^fira_course-.*\.json$"),
)
SECTION_ID_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)")
VERTICAL_BLOCK_LOCATION_RE = re.compile(r"^block-v1:[^+]+\+[^+]+\+[^+]+(?P<suffix>\+type@vertical\+block@.+)$")
COURSE_JSON_FILENAME_RE = re.compile(r"(?i)^fira_(course-v1_[^_]+_[^_]+_[^_]+)\.json$")


def classify_json_file(path: Path) -> str:
    name = path.name
    for pattern in IGNORED_REPORT_JSON_PATTERNS:
        if pattern.match(name):
            return "ignored_report"
    for pattern in CANDIDATE_STRUCTURE_JSON_PATTERNS:
        if pattern.match(name):
            return "candidate_structure"
    return "other_json"


def _iter_files(root: Path, recursive: bool) -> List[Path]:
    items = root.rglob("*") if recursive else root.iterdir()
    return sorted((path for path in items if path.is_file()), key=lambda p: (str(p.parent).lower(), p.name.lower()))


def _deck_priority(path: Path) -> int:
    try:
        return PRESENTATION_SUFFIXES.index(path.suffix.lower())
    except ValueError:
        return len(PRESENTATION_SUFFIXES)


def _speech_priority(path: Path) -> int:
    try:
        return SPEECH_SUFFIX_PREFERENCE.index(path.suffix.lower())
    except ValueError:
        return len(SPEECH_SUFFIX_PREFERENCE)


def _normalize_batch_name(text: str) -> str:
    raw = str(text or "").strip()
    lower = raw.lower()
    for suffix in sorted(PRESENTATION_SUFFIXES + SPEECH_SUFFIX_PREFERENCE, key=len, reverse=True):
        if lower.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    raw = raw.strip()
    raw = re.sub(r"[_\-\s]*(?:水印版|讲稿版|讲稿|文稿)$", "", raw)
    raw = raw.replace("：", ":")
    raw = re.sub(r"[《》【】“”\"'`*_#\s:：\-—_]+", "", raw)
    return raw.lower()


def _extract_section_id(text: str) -> str:
    match = SECTION_ID_PREFIX_RE.match((text or "").strip())
    return match.group(1) if match else ""


def parse_studio_course_url(url: str) -> Dict[str, str]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("studio course url must be an absolute http(s) URL")

    path = (parsed.path or "").rstrip("/")
    marker = "/course/"
    idx = path.find(marker)
    if idx < 0:
        raise ValueError("studio course url must contain /course/course-v1:...")

    course_key = path[idx + len(marker) :].strip("/")
    if not course_key.startswith("course-v1:"):
        raise ValueError("studio course url must end with course-v1:<org>+<course>+<run>")

    block_course_key = course_key.split(":", 1)[1]
    return {
        "studio_base": f"{parsed.scheme}://{parsed.netloc}",
        "course_key": course_key,
        "block_course_key": block_course_key,
    }


def _parse_course_key_parts(course_key: str) -> Tuple[str, str, str]:
    normalized = (course_key or "").strip()
    if normalized.startswith("block-v1:"):
        normalized = f"course-v1:{normalized.split(':', 1)[1].split('+type@', 1)[0]}"
    if not normalized.startswith("course-v1:"):
        raise ValueError(f"invalid course key: {course_key}")
    raw = normalized.split(":", 1)[1]
    parts = raw.split("+")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"course key must have org+course+run parts: {course_key}")
    return parts[0], parts[1], parts[2]


def _course_keys_match(left: str, right: str) -> bool:
    return _parse_course_key_parts(left) == _parse_course_key_parts(right)


def _course_key_to_block_prefix(course_key: str) -> str:
    return "+".join(_parse_course_key_parts(course_key))


def _rewrite_vertical_block_course_key(block_location: str, target_course_key: str) -> str:
    raw = str(block_location or "").strip()
    match = VERTICAL_BLOCK_LOCATION_RE.match(raw)
    if not match:
        raise ValueError(f"not a vertical block locator: {block_location}")
    return f"block-v1:{_course_key_to_block_prefix(target_course_key)}{match.group('suffix')}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_course_key_from_structure_json(course_structure_path: Path) -> str:
    data = _load_json(course_structure_path)
    course_id = ""
    if isinstance(data, dict):
        course_id = str(data.get("course_id", "")).strip()
    if course_id:
        _parse_course_key_parts(course_id)
        return course_id

    match = COURSE_JSON_FILENAME_RE.match(course_structure_path.name)
    if match:
        course_key = match.group(1).replace("_", "+", 3).replace("course-v1+", "course-v1:", 1)
        _parse_course_key_parts(course_key)
        return course_key

    raise ValueError(f"unable to infer course_id from course structure json: {course_structure_path}")


def _pick_single_candidate(candidates: Sequence[str], label: str, prefer_pattern: str | None = None) -> str:
    if not candidates:
        raise ValueError(f"missing required {label}")
    if prefer_pattern:
        preferred = [item for item in candidates if re.search(prefer_pattern, Path(item).name, flags=re.IGNORECASE)]
        if len(preferred) == 1:
            return preferred[0]
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one {label}, got {len(candidates)}")
    return candidates[0]


def _load_section_list_entries(section_list_path: Path) -> List[Dict[str, Any]]:
    data = _load_json(section_list_path)
    entries = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"section-list json missing sections[]: {section_list_path}")
    return entries


def _select_primary_vertical(section: Dict[str, Any]) -> Dict[str, Any]:
    verticals = section.get("verticals", [])
    if not isinstance(verticals, list) or not verticals:
        raise ValueError(f"section missing verticals: {section.get('name')}")

    def score(vertical: Dict[str, Any]) -> Tuple[int, str]:
        name = str(vertical.get("name", ""))
        blocks = vertical.get("blocks", [])
        categories = {str(block.get("category", "")).lower() for block in blocks if isinstance(block, dict)}
        block_names = {str(block.get("name", "")) for block in blocks if isinstance(block, dict)}
        has_imagesgallery = "imagesgallery" in categories
        has_gallery_name = any("有声幻灯片" in block_name for block_name in block_names)
        is_enable_vertical = "赋能内容" in name
        return (
            3 if has_imagesgallery else 0,
            2 if has_gallery_name else 0,
            1 if is_enable_vertical else 0,
            vertical.get("block_order", ""),
        )

    return max(verticals, key=score)


def _build_source_section_index(course_structure_path: Path) -> Dict[str, Dict[str, Any]]:
    data = _load_json(course_structure_path)
    chapters = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"course structure json missing chapters[]: {course_structure_path}")

    index: Dict[str, Dict[str, Any]] = {}
    for chapter in chapters:
        for section in chapter.get("sections", []):
            if not isinstance(section, dict):
                continue
            name = str(section.get("name", "")).strip()
            section_id = _extract_section_id(name)
            primary_vertical = _select_primary_vertical(section)
            record = {
                "section_name": name,
                "section_id": section_id,
                "section_block_location": section.get("block_location", ""),
                "section_block_order": section.get("block_order", ""),
                "vertical_name": primary_vertical.get("name", ""),
                "vertical_block_location": primary_vertical.get("block_location", ""),
                "vertical_block_order": primary_vertical.get("block_order", ""),
            }
            keys = {name, _normalize_batch_name(name)}
            if section_id:
                keys.add(section_id)
            for key in keys:
                if key:
                    index[key] = record
    return index


def _build_section_list_index(entries: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        section_id = str(entry.get("section_id", "")).strip()
        section_title = str(entry.get("section_title", "")).strip()
        resource_title = str(entry.get("resource_title", "")).strip()
        output_name = str(entry.get("output_name", "")).strip()
        keys = {
            section_id,
            section_title,
            resource_title,
            output_name,
            Path(output_name).stem if output_name else "",
            _normalize_batch_name(section_title),
            _normalize_batch_name(resource_title),
            _normalize_batch_name(output_name),
        }
        for key in keys:
            if key:
                index[key] = dict(entry)
    return index


def default_studio_targets_path(out_base: Path) -> Path:
    return out_base.expanduser().resolve() / BATCH_METADATA_DIRNAME / STUDIO_TARGETS_FILENAME


def build_studio_targets_payload(plan: Dict[str, Any]) -> Dict[str, Any]:
    studio_publish = dict(plan.get("studio_publish") or {})
    jobs = list(plan.get("jobs") or [])
    shards = list(plan.get("shards") or [])
    targets = [
        {
            "name": job.get("name", ""),
            "section_id": job.get("section_id", ""),
            "section_title": job.get("section_title", ""),
            "ppt": job.get("ppt", ""),
            "speech": job.get("speech", ""),
            "manifest": job.get("manifest", ""),
            "route_mode": job.get("route_mode", ""),
            "course_id_remapped": bool(job.get("course_id_remapped", False)),
            "source_vertical_block_location": job.get("source_vertical_block_location", ""),
            "target_vertical_block_location": job.get("target_vertical_block_location", ""),
            "studio_vertical_url": job.get("studio_vertical_url", ""),
        }
        for job in jobs
    ]
    return {
        "confirmation_required": False,
        "execution_mode_confirmation_required": False,
        "targets_review_optional": True,
        "auto_continue_after_targets": True,
        "default_execution_mode": "parallel",
        "default_agent_count": 3,
        "local_generation_execution_mode": "parallel",
        "local_generation_agent_count": 3,
        "publish_execution_mode": "sequential",
        "publish_agent_count": 1,
        "publish_auth_retry_max_retries": 4,
        "publish_auth_retry_delay_seconds": 3,
        "max_agent_count": 3,
        "ready_for_publish": not studio_publish.get("unresolved_jobs"),
        "root": plan.get("root", ""),
        "out_base": plan.get("out_base", ""),
        "studio_course_url": studio_publish.get("studio_course_url", ""),
        "target_course_key": studio_publish.get("target_course_key", ""),
        "source_course_key": studio_publish.get("source_course_key", ""),
        "course_id_verified": bool(studio_publish.get("course_id_verified", False)),
        "course_id_remapped": bool(studio_publish.get("course_id_remapped", False)),
        "course_id_remap_confirmed": bool(studio_publish.get("course_id_remap_confirmed", False)),
        "route_mode": studio_publish.get("route_mode", ""),
        "section_list_json": studio_publish.get("section_list_json", ""),
        "course_structure_json": studio_publish.get("course_structure_json", ""),
        "targets": targets,
        "execution_modes": [
            {
                "mode": "sequential",
                "agent_count": 1,
                "label": "顺序执行",
                "description": "仅用于本地生成阶段的自动降级；Studio 推送阶段本来就固定串行。",
            },
            {
                "mode": "parallel",
                "agent_count": 3,
                "label": "三 agent 执行",
                "description": "仅用于本地生成阶段；最多拆成 3 个 shard 并行处理，随后 Studio 推送仍按顺序逐个执行。",
            },
        ],
        "shards": shards,
        "unresolved_jobs": studio_publish.get("unresolved_jobs", []),
    }


def write_studio_targets_file(plan: Dict[str, Any], output_path: Path | None = None) -> Path:
    studio_publish = plan.get("studio_publish") or {}
    if not studio_publish.get("studio_course_url"):
        raise ValueError("studio targets file requires studio_publish metadata")

    out_base = Path(str(plan.get("out_base", ""))).expanduser().resolve()
    target_path = (output_path or default_studio_targets_path(out_base)).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_studio_targets_payload(plan)
    payload["targets_file"] = str(target_path)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def enrich_jobs_with_studio_routes(
    jobs: Sequence[Dict[str, str]],
    studio_course_url: str,
    section_list_path: Path,
    course_structure_path: Path,
    allow_course_id_remap: bool = False,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    course_info = parse_studio_course_url(studio_course_url)
    source_course_key = _extract_course_key_from_structure_json(course_structure_path)
    course_id_verified = _course_keys_match(course_info["course_key"], source_course_key)
    course_id_remapped = bool(allow_course_id_remap and not course_id_verified)
    route_mode = "exact_match" if course_id_verified else "course_id_remapped"

    if not course_id_verified and not allow_course_id_remap:
        raise ValueError(
            "studio course url does not match folder course structure json: "
            f"url={course_info['course_key']} vs json={source_course_key}. "
            "Batch publish stopped because the target course appears to be wrong. "
            "If this is an imported copy of the same course and the vertical block suffixes are unchanged, "
            "ask the user to confirm explicitly, then rerun with --allow-course-id-remap."
        )
    section_index = _build_section_list_index(_load_section_list_entries(section_list_path))
    source_index = _build_source_section_index(course_structure_path)

    enriched_jobs: List[Dict[str, str]] = []
    unresolved_jobs: List[Dict[str, str]] = []

    for job in jobs:
        name = job.get("name", "")
        lookup_keys = [
            name,
            _normalize_batch_name(name),
            _extract_section_id(name),
        ]
        section_entry = next((section_index[key] for key in lookup_keys if key and key in section_index), None)
        if not section_entry:
            unresolved_jobs.append({"job": name, "reason": "section_list_not_found"})
            enriched_jobs.append(dict(job))
            continue

        section_keys = [
            section_entry.get("section_id", ""),
            section_entry.get("section_title", ""),
            section_entry.get("resource_title", ""),
            Path(str(section_entry.get("output_name", ""))).stem,
            _normalize_batch_name(str(section_entry.get("section_title", ""))),
        ]
        source_entry = next((source_index[key] for key in section_keys if key and key in source_index), None)
        if not source_entry:
            unresolved_jobs.append({"job": name, "reason": "course_structure_not_found", "section_id": section_entry.get("section_id", "")})
            enriched_jobs.append(dict(job))
            continue

        source_vertical_block_location = str(source_entry.get("vertical_block_location", "")).strip()
        if not VERTICAL_BLOCK_LOCATION_RE.match(source_vertical_block_location):
            unresolved_jobs.append({"job": name, "reason": f"not a vertical block locator: {source_vertical_block_location}"})
            enriched_jobs.append(dict(job))
            continue
        target_vertical_block_location = (
            _rewrite_vertical_block_course_key(source_vertical_block_location, course_info["course_key"])
            if course_id_remapped
            else source_vertical_block_location
        )

        enriched = dict(job)
        enriched.update(
            {
                "section_id": str(section_entry.get("section_id", "")),
                "section_title": str(section_entry.get("section_title", "")),
                "resource_title": str(section_entry.get("resource_title", "")),
                "route_mode": route_mode,
                "course_id_remapped": course_id_remapped,
                "source_vertical_name": str(source_entry.get("vertical_name", "")),
                "source_vertical_block_order": str(source_entry.get("vertical_block_order", "")),
                "source_vertical_block_location": source_vertical_block_location,
                "target_course_key": course_info["course_key"],
                "target_vertical_block_location": target_vertical_block_location,
                "studio_vertical_url": f"{course_info['studio_base']}/container/{target_vertical_block_location}",
            }
        )
        enriched_jobs.append(enriched)

    metadata = {
        "studio_course_url": studio_course_url,
        "studio_base": course_info["studio_base"],
        "target_course_key": course_info["course_key"],
        "source_course_key": source_course_key,
        "course_id_verified": course_id_verified,
        "course_id_remapped": course_id_remapped,
        "course_id_remap_confirmed": course_id_remapped,
        "route_mode": route_mode,
        "confirmation_required": False,
        "execution_mode_confirmation_required": False,
        "targets_review_optional": True,
        "auto_continue_after_targets": True,
        "default_execution_mode": "parallel",
        "default_agent_count": 3,
        "local_generation_execution_mode": "parallel",
        "local_generation_agent_count": 3,
        "publish_execution_mode": "sequential",
        "publish_agent_count": 1,
        "publish_auth_retry_max_retries": 4,
        "publish_auth_retry_delay_seconds": 3,
        "max_agent_count": 3,
        "section_list_json": str(section_list_path),
        "course_structure_json": str(course_structure_path),
        "unresolved_jobs": unresolved_jobs,
    }
    return enriched_jobs, metadata


def discover_batch_jobs(
    root: Path,
    recursive: bool = False,
    out_base: Path | None = None,
    shards: int = 1,
    studio_course_url: str = "",
    section_list_json: Path | None = None,
    course_structure_json: Path | None = None,
    allow_course_id_remap: bool = False,
) -> Dict[str, object]:
    root = root.expanduser().resolve()
    out_base = (out_base or root).expanduser().resolve()
    shard_count = max(1, int(shards))

    decks: Dict[Tuple[str, str], Path] = {}
    speeches: Dict[Tuple[str, str], List[Path]] = {}
    ignored_report_json: List[str] = []
    candidate_structure_json: List[str] = []
    other_json: List[str] = []

    for path in _iter_files(root, recursive=recursive):
        suffix = path.suffix.lower()
        key = (str(path.parent.resolve()), path.stem)
        resolved = path.resolve()

        if suffix in PRESENTATION_SUFFIXES:
            current = decks.get(key)
            if current is None or _deck_priority(resolved) < _deck_priority(current):
                decks[key] = resolved
            continue

        if suffix in SPEECH_SUFFIX_PREFERENCE:
            speeches.setdefault(key, []).append(resolved)
            continue

        if suffix == ".json":
            bucket = classify_json_file(resolved)
            if bucket == "ignored_report":
                ignored_report_json.append(str(resolved))
            elif bucket == "candidate_structure":
                candidate_structure_json.append(str(resolved))
            else:
                other_json.append(str(resolved))

    jobs: List[Dict[str, str]] = []
    unmatched_presentations: List[str] = []
    matched_speech_keys = set()

    for key in sorted(decks, key=lambda item: (item[0].lower(), item[1].lower())):
        ppt_path = decks[key]
        speech_candidates = sorted(speeches.get(key, []), key=lambda p: (_speech_priority(p), p.name.lower()))
        if not speech_candidates:
            unmatched_presentations.append(str(ppt_path))
            continue

        speech_path = speech_candidates[0]
        matched_speech_keys.add(key)
        stem = ppt_path.stem.strip() or "ppt"
        gallery_dir = out_base / stem / "imagesgallery"
        jobs.append(
            {
                "name": stem,
                "ppt": str(ppt_path),
                "speech": str(speech_path),
                "out_base": str(out_base),
                "gallery_dir": str(gallery_dir),
                "images_dir": str(gallery_dir / "images"),
                "manifest": str(gallery_dir / "imagesgallery.json"),
            }
        )

    unmatched_speeches: List[str] = []
    for key in sorted(speeches, key=lambda item: (item[0].lower(), item[1].lower())):
        if key in matched_speech_keys or key in decks:
            continue
        unmatched_speeches.extend(str(path) for path in sorted(speeches[key], key=lambda p: (_speech_priority(p), p.name.lower())))

    shard_rows: List[Dict[str, object]] = [{"index": idx + 1, "jobs": []} for idx in range(shard_count)]
    studio_publish: Dict[str, Any] = {}

    if studio_course_url:
        section_list_candidate = section_list_json or Path(
            _pick_single_candidate(candidate_structure_json, "section-list json", prefer_pattern=r"section-list\.json$")
        )
        course_structure_candidate = course_structure_json or Path(
            _pick_single_candidate(candidate_structure_json, "course structure json", prefer_pattern=r"fira_course-.*\.json$")
        )
        jobs, studio_publish = enrich_jobs_with_studio_routes(
            jobs,
            studio_course_url=studio_course_url,
            section_list_path=section_list_candidate.expanduser().resolve(),
            course_structure_path=course_structure_candidate.expanduser().resolve(),
            allow_course_id_remap=allow_course_id_remap,
        )

    for idx, job in enumerate(jobs):
        shard_rows[idx % shard_count]["jobs"].append(job)

    return {
        "root": str(root),
        "out_base": str(out_base),
        "jobs": jobs,
        "shards": shard_rows,
        "ignored_report_json": sorted(ignored_report_json),
        "candidate_structure_json": sorted(candidate_structure_json),
        "other_json": sorted(other_json),
        "unmatched_presentations": unmatched_presentations,
        "unmatched_speeches": unmatched_speeches,
        "studio_publish": studio_publish,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan batch imagesgallery jobs from a mixed output folder")
    parser.add_argument("--root", required=True, help="folder containing ppt/md pairs and other artifacts")
    parser.add_argument("--out-base", help="override output base directory; defaults to --root")
    parser.add_argument("--recursive", action="store_true", help="scan recursively under --root")
    parser.add_argument("--shards", type=int, default=1, help="split discovered jobs into N round-robin shards")
    parser.add_argument("--studio-course-url", help="optional Studio course URL; when set, derive per-job Studio vertical URLs")
    parser.add_argument("--section-list-json", help="optional explicit section-list.json path for batch Studio route mapping")
    parser.add_argument("--course-structure-json", help="optional explicit fira_course-*.json path for batch Studio route mapping")
    parser.add_argument(
        "--allow-course-id-remap",
        action="store_true",
        help="after explicit user confirmation, allow remapping vertical block locators to the target studio course id while preserving the +type@vertical+block@... suffix",
    )
    parser.add_argument(
        "--write-studio-targets",
        nargs="?",
        const="__AUTO__",
        help="when --studio-course-url is set, write imagegallery-push-studio-targets.json; omit value to use the default _batch path under out-base",
    )
    parser.add_argument("--write-plan", help="optional output path for the rendered plan JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    if args.allow_course_id_remap and not args.studio_course_url:
        raise SystemExit("--allow-course-id-remap requires --studio-course-url")
    plan = discover_batch_jobs(
        Path(args.root),
        recursive=args.recursive,
        out_base=Path(args.out_base).expanduser().resolve() if args.out_base else None,
        shards=args.shards,
        studio_course_url=args.studio_course_url or "",
        section_list_json=Path(args.section_list_json).expanduser().resolve() if args.section_list_json else None,
        course_structure_json=Path(args.course_structure_json).expanduser().resolve() if args.course_structure_json else None,
        allow_course_id_remap=args.allow_course_id_remap,
    )
    if args.write_studio_targets is not None:
        if not args.studio_course_url:
            raise SystemExit("--write-studio-targets requires --studio-course-url")
        target_file = write_studio_targets_file(
            plan,
            None if args.write_studio_targets == "__AUTO__" else Path(args.write_studio_targets).expanduser().resolve(),
        )
        plan.setdefault("studio_publish", {})["targets_file"] = str(target_file)
    rendered = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.write_plan:
        out_path = Path(args.write_plan).expanduser().resolve()
        out_path.write_text(rendered, encoding="utf-8")
        print(f"OK: wrote batch plan -> {out_path}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
