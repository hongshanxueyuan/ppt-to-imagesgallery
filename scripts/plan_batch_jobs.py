#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import urlparse

from build_imagesgallery import count_presentation_pages


PRESENTATION_SUFFIXES = (".pptx", ".ppt")
BATCH_METADATA_DIRNAME = "_batch"
PREFLIGHT_REPORT_FILENAME = "imagegallery-preflight-report.json"
STUDIO_TARGETS_FILENAME = "imagegallery-push-studio-targets.json"
SECTION_ID_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)")
VERTICAL_BLOCK_LOCATION_RE = re.compile(r"^block-v1:[^+]+\+[^+]+\+[^+]+(?P<suffix>\+type@vertical\+block@.+)$")
COURSE_JSON_FILENAME_RE = re.compile(r"(?i)^fira_(course-v1_[^_]+_[^_]+_[^_]+)\.json$")

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

PAGINATION_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:"
    r"第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?"
    r"|page\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r"|slide\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r")\s*$"
)


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
    return sorted((path for path in items if path.is_file()), key=lambda path: (str(path.parent).lower(), path.name.lower()))


def _normalize_batch_name(text: str) -> str:
    raw = str(text or "").strip()
    lower = raw.lower()
    for suffix in sorted(PRESENTATION_SUFFIXES, key=len, reverse=True):
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


def _section_output_name_keys(section: Mapping[str, Any]) -> List[str]:
    output_name = str(section.get("output_name", "")).strip()
    return [
        Path(output_name).stem if output_name else "",
        _normalize_batch_name(output_name),
    ]


def _section_tie_break_keys(section: Mapping[str, Any]) -> List[str]:
    section_title = str(section.get("section_title", "")).strip()
    resource_title = str(section.get("resource_title", "")).strip()
    section_id = str(section.get("section_id", "")).strip()
    return [
        section_id,
        section_title,
        resource_title,
        _normalize_batch_name(section_title),
        _normalize_batch_name(resource_title),
    ]


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_section_list_entries(section_list_path: Path) -> List[Dict[str, Any]]:
    data = _load_json(section_list_path)
    entries = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"section-list json missing sections[]: {section_list_path}")

    normalized_entries: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError(f"section-list entry must be an object: {section_list_path}")
        normalized_entries.append(
            {
                "section_id": str(entry.get("section_id", "")).strip(),
                "section_title": str(entry.get("section_title", "")).strip(),
                "resource_title": str(entry.get("resource_title", "")).strip(),
                "output_name": str(entry.get("output_name", "")).strip(),
                "page_count": entry.get("page_count"),
                "page_content": entry.get("page_content"),
            }
        )
    return normalized_entries


def _find_section_candidates(ppt_path: Path, sections: Sequence[Mapping[str, Any]]) -> List[Tuple[int, Mapping[str, Any]]]:
    local_stem = ppt_path.stem.strip()
    local_output_name_keys = {key for key in [local_stem, _normalize_batch_name(local_stem)] if key}
    candidates: List[Tuple[int, Mapping[str, Any]]] = []
    for index, section in enumerate(sections):
        if local_output_name_keys & {key for key in _section_output_name_keys(section) if key}:
            candidates.append((index, section))
    if len(candidates) <= 1:
        return candidates

    local_section_id = _extract_section_id(local_stem)
    if local_section_id:
        exact_id_matches = [(index, section) for index, section in candidates if str(section.get("section_id", "")).strip() == local_section_id]
        if len(exact_id_matches) == 1:
            return exact_id_matches

    local_tie_break_keys = {key for key in [local_stem, _normalize_batch_name(local_stem)] if key}
    exact_title_matches = [
        (index, section)
        for index, section in candidates
        if local_tie_break_keys & {key for key in _section_tie_break_keys(section) if key}
    ]
    if len(exact_title_matches) == 1:
        return exact_title_matches
    return candidates


def default_preflight_report_path(out_base: Path) -> Path:
    return out_base.expanduser().resolve() / BATCH_METADATA_DIRNAME / PREFLIGHT_REPORT_FILENAME


def _strip_page_markers(text: str) -> str:
    return PAGINATION_LINE_RE.sub("", text or "")


def _validate_job_structure(job: Mapping[str, Any]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    page_count = job.get("page_count")
    page_content = job.get("page_content")

    if not isinstance(page_count, int):
        failures.append({"code": "missing_page_count", "reason": "page_count is missing"})
    elif page_count <= 0:
        failures.append({"code": "invalid_page_count", "reason": "page_count must be a positive integer"})

    if page_content is None:
        failures.append({"code": "missing_page_content", "reason": "page_content is missing"})
    elif not isinstance(page_content, list):
        failures.append({"code": "invalid_page_content", "reason": "page_content must be a list"})
    else:
        if isinstance(page_count, int) and page_count > 0 and len(page_content) != page_count:
            failures.append(
                {
                    "code": "page_content_length_mismatch",
                    "reason": f"page_count {page_count} does not match len(page_content) {len(page_content)}",
                }
            )
        for index, page in enumerate(page_content, start=1):
            if not isinstance(page, str):
                failures.append({"code": "invalid_page_content", "reason": f"page_content[{index}] must be a string"})
                continue
            if not _strip_page_markers(page).strip():
                failures.append({"code": "blank_page_content", "reason": f"page_content[{index}] is blank"})
    return failures


def _as_failure(job: Mapping[str, Any], code: str, reason: str, observed_slide_count: int | None = None) -> Dict[str, Any]:
    payload = {
        "code": code,
        "reason": reason,
        "deck_name": str(job.get("name", "")),
        "ppt": str(job.get("ppt", "")),
        "section_id": str(job.get("section_id", "")),
        "section_title": str(job.get("section_title", "")),
        "expected_page_count": job.get("page_count"),
    }
    if observed_slide_count is not None:
        payload["observed_slide_count"] = observed_slide_count
    return payload


def _run_preflight(jobs: Sequence[Dict[str, Any]], out_base: Path, section_list_path: Path) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    for job in jobs:
        structural_failures = _validate_job_structure(job)
        failures.extend(_as_failure(job, item["code"], item["reason"]) for item in structural_failures)

        page_count = job.get("page_count")
        if not isinstance(page_count, int) or page_count <= 0:
            continue

        try:
            observed_slide_count = count_presentation_pages(Path(str(job["ppt"])))
        except Exception as exc:
            failures.append(_as_failure(job, "slide_count_unavailable", str(exc)))
            continue

        if observed_slide_count != page_count:
            failures.append(
                _as_failure(
                    job,
                    "page_count_mismatch",
                    f"expected {page_count} slide(s), observed {observed_slide_count}",
                    observed_slide_count=observed_slide_count,
                )
            )

    report_path = default_preflight_report_path(out_base)
    if failures:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "failed",
            "root": str(out_base),
            "section_list_json": str(section_list_path),
            "failure_count": len(failures),
            "failures": failures,
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "failed",
            "failure_count": len(failures),
            "report_path": str(report_path),
            "failures": failures,
        }

    if report_path.exists():
        report_path.unlink()
    return {"status": "clean", "failure_count": 0, "report_path": "", "failures": []}


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
    parts = normalized.split(":", 1)[1].split("+")
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


def _select_primary_vertical(section: Mapping[str, Any]) -> Dict[str, Any]:
    verticals = section.get("verticals", [])
    if not isinstance(verticals, list) or not verticals:
        raise ValueError(f"section missing verticals: {section.get('name')}")

    def score(vertical: Mapping[str, Any]) -> Tuple[int, int, int, str]:
        name = str(vertical.get("name", ""))
        blocks = vertical.get("blocks", [])
        categories = {str(block.get("category", "")).lower() for block in blocks if isinstance(block, Mapping)}
        block_names = {str(block.get("name", "")) for block in blocks if isinstance(block, Mapping)}
        return (
            1 if "imagesgallery" in categories else 0,
            1 if any("有声幻灯片" in block_name for block_name in block_names) else 0,
            1 if "赋能内容" in name else 0,
            str(vertical.get("block_order", "")),
        )

    return dict(max(verticals, key=score))


def _build_source_section_index(course_structure_path: Path) -> Dict[str, Dict[str, Any]]:
    data = _load_json(course_structure_path)
    chapters = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"course structure json missing chapters[]: {course_structure_path}")

    index: Dict[str, Dict[str, Any]] = {}
    for chapter in chapters:
        for section in chapter.get("sections", []):
            if not isinstance(section, Mapping):
                continue
            name = str(section.get("name", "")).strip()
            section_id = _extract_section_id(name)
            primary_vertical = _select_primary_vertical(section)
            record = {
                "section_name": name,
                "section_id": section_id,
                "section_block_location": str(section.get("block_location", "")),
                "section_block_order": str(section.get("block_order", "")),
                "vertical_name": str(primary_vertical.get("name", "")),
                "vertical_block_location": str(primary_vertical.get("block_location", "")),
                "vertical_block_order": str(primary_vertical.get("block_order", "")),
            }
            for key in {
                name,
                section_id,
                _normalize_batch_name(name),
            }:
                if key:
                    index[key] = record
    return index


def default_studio_targets_path(out_base: Path) -> Path:
    return out_base.expanduser().resolve() / BATCH_METADATA_DIRNAME / STUDIO_TARGETS_FILENAME


def enrich_jobs_with_studio_routes(
    jobs: Sequence[Dict[str, Any]],
    studio_course_url: str,
    course_structure_path: Path,
    allow_course_id_remap: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
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

    source_index = _build_source_section_index(course_structure_path)
    enriched_jobs: List[Dict[str, Any]] = []
    unresolved_jobs: List[Dict[str, str]] = []
    for job in jobs:
        lookup_keys = [
            str(job.get("section_id", "")),
            str(job.get("section_title", "")),
            _normalize_batch_name(str(job.get("section_title", ""))),
            Path(str(job.get("output_name", ""))).stem if job.get("output_name") else "",
        ]
        source_entry = next((source_index[key] for key in lookup_keys if key and key in source_index), None)
        if not source_entry:
            unresolved_jobs.append({"job": str(job.get("name", "")), "reason": "course_structure_not_found"})
            enriched_jobs.append(dict(job))
            continue

        source_vertical_block_location = str(source_entry.get("vertical_block_location", "")).strip()
        if not VERTICAL_BLOCK_LOCATION_RE.match(source_vertical_block_location):
            unresolved_jobs.append({"job": str(job.get("name", "")), "reason": f"not a vertical block locator: {source_vertical_block_location}"})
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
        "course_structure_json": str(course_structure_path),
        "unresolved_jobs": unresolved_jobs,
    }
    return enriched_jobs, metadata


def build_studio_targets_payload(plan: Dict[str, Any]) -> Dict[str, Any]:
    studio_publish = dict(plan.get("studio_publish") or {})
    jobs = list(plan.get("jobs") or [])
    targets = [
        {
            "name": job.get("name", ""),
            "section_id": job.get("section_id", ""),
            "section_title": job.get("section_title", ""),
            "ppt": job.get("ppt", ""),
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
        "ready_for_publish": bool(plan.get("admission_ready")) and not studio_publish.get("unresolved_jobs"),
        "root": plan.get("root", ""),
        "out_base": plan.get("out_base", ""),
        "studio_course_url": studio_publish.get("studio_course_url", ""),
        "target_course_key": studio_publish.get("target_course_key", ""),
        "source_course_key": studio_publish.get("source_course_key", ""),
        "course_id_verified": bool(studio_publish.get("course_id_verified", False)),
        "course_id_remapped": bool(studio_publish.get("course_id_remapped", False)),
        "course_id_remap_confirmed": bool(studio_publish.get("course_id_remap_confirmed", False)),
        "route_mode": studio_publish.get("route_mode", ""),
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
        "shards": list(plan.get("shards") or []),
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


def _discover_local_presentations(root: Path, recursive: bool) -> Tuple[List[Path], List[str], List[str], List[str]]:
    presentations: List[Path] = []
    ignored_report_json: List[str] = []
    candidate_structure_json: List[str] = []
    other_json: List[str] = []

    for path in _iter_files(root, recursive=recursive):
        suffix = path.suffix.lower()
        if suffix in PRESENTATION_SUFFIXES:
            presentations.append(path.resolve())
            continue
        if suffix == ".json":
            bucket = classify_json_file(path)
            if bucket == "ignored_report":
                ignored_report_json.append(str(path.resolve()))
            elif bucket == "candidate_structure":
                candidate_structure_json.append(str(path.resolve()))
            else:
                other_json.append(str(path.resolve()))

    presentations.sort(key=lambda path: path.name.lower())
    return presentations, sorted(ignored_report_json), sorted(candidate_structure_json), sorted(other_json)


def _build_job(section_index: int, section: Mapping[str, Any], ppt_path: Path, out_base: Path) -> Dict[str, Any]:
    gallery_dir = out_base / ppt_path.stem / "imagesgallery"
    return {
        "name": ppt_path.stem,
        "ppt": str(ppt_path),
        "out_base": str(out_base),
        "gallery_dir": str(gallery_dir),
        "images_dir": str(gallery_dir / "images"),
        "manifest": str(gallery_dir / "imagesgallery.json"),
        "section_order": section_index,
        "section_id": str(section.get("section_id", "")),
        "section_title": str(section.get("section_title", "")),
        "resource_title": str(section.get("resource_title", "")),
        "output_name": str(section.get("output_name", "")),
        "page_count": section.get("page_count"),
        "page_content": section.get("page_content"),
    }


def discover_batch_jobs(
    root: Path,
    recursive: bool = False,
    out_base: Path | None = None,
    shards: int = 1,
    studio_course_url: str = "",
    section_list_json: Path | None = None,
    course_structure_json: Path | None = None,
    allow_course_id_remap: bool = False,
) -> Dict[str, Any]:
    root = root.expanduser().resolve()
    out_base = (out_base or root).expanduser().resolve()
    shard_count = max(1, int(shards))

    presentations, ignored_report_json, candidate_structure_json, other_json = _discover_local_presentations(root, recursive=recursive)
    section_list_path = (
        section_list_json.expanduser().resolve()
        if section_list_json
        else Path(_pick_single_candidate(candidate_structure_json, "section-list json", prefer_pattern=r"section-list\.json$")).expanduser().resolve()
    )
    sections = _load_section_list_entries(section_list_path)

    jobs: List[Dict[str, Any]] = []
    discovery_failures: List[Dict[str, Any]] = []
    matched_section_indices: set[int] = set()

    for ppt_path in presentations:
        candidates = _find_section_candidates(ppt_path, sections)
        if not candidates:
            discovery_failures.append(
                {
                    "code": "section_list_match_not_found",
                    "deck_name": ppt_path.stem,
                    "ppt": str(ppt_path),
                    "reason": "local ppt did not match any section-list entry",
                }
            )
            continue
        if len(candidates) > 1:
            discovery_failures.append(
                {
                    "code": "section_list_match_ambiguous",
                    "deck_name": ppt_path.stem,
                    "ppt": str(ppt_path),
                    "reason": "local ppt matched multiple section-list entries",
                    "candidate_section_ids": [str(section.get("section_id", "")) for _index, section in candidates],
                }
            )
            continue

        section_index, section = candidates[0]
        matched_section_indices.add(section_index)
        jobs.append(_build_job(section_index, section, ppt_path, out_base))

    jobs.sort(key=lambda job: (int(job["section_order"]), str(job["name"]).lower()))
    ignored_upstream_sections = [dict(section) for index, section in enumerate(sections) if index not in matched_section_indices]
    preflight = _run_preflight(jobs, out_base=out_base, section_list_path=section_list_path)
    admission_ready = not discovery_failures and preflight["status"] == "clean"

    studio_publish: Dict[str, Any] = {}
    if studio_course_url and admission_ready:
        course_structure_candidate = (
            course_structure_json.expanduser().resolve()
            if course_structure_json
            else Path(_pick_single_candidate(candidate_structure_json, "course structure json", prefer_pattern=r"fira_course-.*\.json$")).expanduser().resolve()
        )
        jobs, studio_publish = enrich_jobs_with_studio_routes(
            jobs,
            studio_course_url=studio_course_url,
            course_structure_path=course_structure_candidate,
            allow_course_id_remap=allow_course_id_remap,
        )

    shard_rows: List[Dict[str, Any]] = []
    if admission_ready:
        shard_rows = [{"index": idx + 1, "jobs": []} for idx in range(shard_count)]
        for index, job in enumerate(jobs):
            shard_rows[index % shard_count]["jobs"].append(job)

    return {
        "root": str(root),
        "out_base": str(out_base),
        "section_list_json": str(section_list_path),
        "jobs": jobs,
        "shards": shard_rows,
        "ignored_report_json": ignored_report_json,
        "candidate_structure_json": candidate_structure_json,
        "other_json": other_json,
        "ignored_upstream_sections": ignored_upstream_sections,
        "discovery_failures": discovery_failures,
        "preflight": preflight,
        "admission_ready": admission_ready,
        "studio_publish": studio_publish,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan a batch-only section-list-driven imagesgallery run")
    parser.add_argument("--root", required=True, help="folder containing local .ppt/.pptx files and section-list.json")
    parser.add_argument("--out-base", help="override output base directory; defaults to --root")
    parser.add_argument("--recursive", action="store_true", help="scan recursively under --root")
    parser.add_argument("--shards", type=int, default=1, help="split admitted jobs into N round-robin shards after preflight passes")
    parser.add_argument("--studio-course-url", help="optional Studio course URL; when set, derive per-job Studio vertical URLs")
    parser.add_argument("--section-list-json", help="optional explicit section-list.json path")
    parser.add_argument("--course-structure-json", help="optional explicit fira_course-*.json path for Studio route mapping")
    parser.add_argument(
        "--allow-course-id-remap",
        action="store_true",
        help="after explicit user confirmation, allow remapping vertical block locators to the target Studio course id while preserving the +type@vertical+block@... suffix",
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

    if plan["admission_ready"]:
        return 0

    if plan["discovery_failures"]:
        print("ERROR: batch admission failed during local PPT to section-list matching", file=sys.stderr)
    elif plan["preflight"]["status"] == "failed":
        print(
            "ERROR: preflight finished, the batch failed admission, and the run stopped before any media generation. "
            f"See {plan['preflight']['report_path']}",
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
