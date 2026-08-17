#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from align_manuscript import normalize_for_alignment, strip_pagination_noise


VERSION = "1.0"
MANUSCRIPT_PREPROCESS_VERSION = "2026-08-17-risk-report-v1"
PROMPT_FULL_SPEECH_SESSION_PATH = SCRIPT_DIR.parent / "references" / "prompt_full_speech_session.md"
PAGINATION_MARKER_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:"
    r"第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?"
    r"|page\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r"|slide\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r")\s*$"
)
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
HORIZONTAL_RULE_RE = re.compile(r"^\s*(?:\*{3,}|-{3,})\s*$")
RISK_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


@dataclass(frozen=True)
class PreparedManuscript:
    source_path: Path
    text: str
    was_preprocessed: bool
    risks: tuple[Dict[str, Any], ...] = ()


def load_full_speech_session_prompt() -> str:
    return PROMPT_FULL_SPEECH_SESSION_PATH.read_text(encoding="utf-8").strip()


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty model output")

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1].strip()
    raise ValueError("json object not found in model output")


def parse_bl_omni_stdout(output: str) -> str:
    text = (output or "").strip()
    if not text:
        raise ValueError("empty bl omni output")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text

    if isinstance(payload, dict):
        for key in ("content", "output_text", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return text


def validate_batch_result(payload: Dict[str, Any], expected_page_numbers: Sequence[int]) -> List[str]:
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise ValueError("payload.pages must be a list")

    ordered: List[str] = []
    got_page_numbers: List[int] = []
    for item in pages:
        if not isinstance(item, dict):
            raise ValueError("each page item must be an object")
        page_number = item.get("page_number")
        if not isinstance(page_number, int):
            raise ValueError("page_number must be an integer")
        speech = item.get("speech")
        if not isinstance(speech, str) or not speech.strip():
            raise ValueError(f"speech must be a non-empty string for page {page_number}")
        got_page_numbers.append(page_number)
        ordered.append(speech.strip())

    if list(expected_page_numbers) != got_page_numbers:
        raise ValueError(f"page_number sequence mismatch: expected {list(expected_page_numbers)}, got {got_page_numbers}")
    return ordered


def run_batch_with_retries(
    invoke: Callable[[str], str],
    expected_page_numbers: Sequence[int],
    max_retries: int = 2,
    post_validate: Callable[[Sequence[str]], None] | None = None,
) -> List[str]:
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    prompt_text = load_full_speech_session_prompt()
    retry_note = ""
    last_exc: Exception | None = None

    for _attempt in range(1, max_retries + 1):
        try:
            raw = invoke(f"{prompt_text}{retry_note}")
            payload = json.loads(_extract_json_text(parse_bl_omni_stdout(raw)))
            ordered = validate_batch_result(payload, expected_page_numbers)
            if post_validate is not None:
                post_validate(ordered)
            return ordered
        except Exception as exc:
            last_exc = exc
            retry_note = (
                "\n\n## 上次输出修正要求\n"
                f"- 上次输出未通过校验：{exc}\n"
                "- 请继续严格遵守以上 canonical prompt，只返回修正后的 JSON。\n"
            )

    raise RuntimeError(f"batch slicing failed after {max_retries} attempt(s): {last_exc}")


def _normalize_heading_for_match(text: str) -> str:
    heading = re.sub(r"^\s*#{1,6}\s*", "", text or "").strip()
    if not heading:
        return ""
    heading = re.sub(r"\.(?:md|markdown|txt|docx|pptx?|pdf)$", "", heading, flags=re.IGNORECASE)
    heading = re.sub(r"[_\-\s]*(?:水印版|讲稿版|讲稿|文稿)$", "", heading)
    heading = re.sub(r"^[（(]?\d+(?:\.\d+)+[)）]?\s*", "", heading)
    heading = re.sub(r"[《》【】“”\"'`*_#\s:：\-—_]+", "", heading)
    return heading.lower()


def _headings_look_equivalent(doc_title: str, page_title: str, source_stem: str = "") -> bool:
    doc_norm = _normalize_heading_for_match(doc_title)
    page_norm = _normalize_heading_for_match(page_title)
    stem_norm = _normalize_heading_for_match(source_stem)
    if not doc_norm or not page_norm:
        return False
    if doc_norm == page_norm or doc_norm in page_norm or page_norm in doc_norm:
        return True
    if stem_norm and doc_norm == stem_norm and (page_norm == stem_norm or page_norm in stem_norm or stem_norm in page_norm):
        return True
    return False


def strip_redundant_document_title(text: str, source_stem: str = "") -> str:
    """Drop a file-level title before page 1 when page 1 repeats the same heading."""
    if not text:
        return ""

    lines = text.splitlines()
    first_page_line = next((idx for idx, line in enumerate(lines) if PAGINATION_MARKER_RE.match(line)), -1)
    if first_page_line <= 0:
        return text

    pre_lines = lines[:first_page_line]
    pre_nonempty = [line.strip() for line in pre_lines if line.strip()]
    if len(pre_nonempty) != 1:
        return text

    doc_title = pre_nonempty[0]
    if not MARKDOWN_HEADING_RE.match(doc_title):
        return text

    post_nonempty = [line.strip() for line in lines[first_page_line + 1 :] if line.strip()]
    first_page_title = next((line for line in post_nonempty if MARKDOWN_HEADING_RE.match(line)), "")
    if not first_page_title:
        return text

    if not _headings_look_equivalent(doc_title, first_page_title, source_stem=source_stem):
        return text

    return "\n".join(lines[first_page_line:]).lstrip()


def _extract_pagination_number(line: str) -> int | None:
    if not PAGINATION_MARKER_RE.match(line or ""):
        return None
    match = re.search(r"\d+", line)
    if not match:
        return None
    return int(match.group(0))


def is_paginated_markdown(text: str) -> bool:
    if not text:
        return False

    lines = text.splitlines()
    pagination_hits = [
        (idx, page_no)
        for idx, line in enumerate(lines)
        if (page_no := _extract_pagination_number(line)) is not None
    ]
    if len(pagination_hits) >= 2:
        numbers = [page_no for _idx, page_no in pagination_hits]
        return all(right > left for left, right in zip(numbers, numbers[1:]))
    if len(pagination_hits) != 1:
        return False

    marker_idx, first_number = pagination_hits[0]
    if first_number != 1:
        return False

    next_nonempty = next((line.strip() for line in lines[marker_idx + 1 :] if line.strip()), "")
    return bool(next_nonempty and MARKDOWN_HEADING_RE.match(next_nonempty))


def _significant_lines_after(lines: Sequence[str], marker_idx: int, limit: int = 3) -> List[str]:
    excerpt: List[str] = []
    for line in lines[marker_idx + 1 :]:
        stripped = line.strip()
        if not stripped or HORIZONTAL_RULE_RE.match(stripped):
            continue
        excerpt.append(stripped)
        if len(excerpt) >= limit:
            break
    return excerpt


def _normalize_duplicate_match_line(line: str) -> str:
    deheaded = re.sub(r"^\s*#{1,6}\s*", "", line or "").strip()
    normalized = normalize_for_alignment(deheaded)
    return re.sub(r"\s+", "", normalized)


def detect_duplicate_tail_restart(text: str, source_stem: str = "") -> Dict[str, Any] | None:
    if not text:
        return None

    lines = text.splitlines()
    pagination_hits = [
        (idx, page_no)
        for idx, line in enumerate(lines)
        if (page_no := _extract_pagination_number(line)) is not None
    ]
    if len(pagination_hits) < 2:
        return None

    first_marker_idx, _first_page_no = pagination_hits[0]
    anchor_excerpt = _significant_lines_after(lines, first_marker_idx, limit=3)
    anchor_heading = next((line for line in anchor_excerpt if MARKDOWN_HEADING_RE.match(line)), "")
    anchor_body = [_normalize_duplicate_match_line(line) for line in anchor_excerpt if not MARKDOWN_HEADING_RE.match(line)]
    anchor_body = [line for line in anchor_body if line]
    if not anchor_heading or not anchor_body:
        return None

    for marker_idx, page_no in pagination_hits[1:]:
        candidate_excerpt = _significant_lines_after(lines, marker_idx, limit=3)
        candidate_heading = next((line for line in candidate_excerpt if MARKDOWN_HEADING_RE.match(line)), "")
        if not candidate_heading or not _headings_look_equivalent(anchor_heading, candidate_heading, source_stem=source_stem):
            continue

        candidate_body = [_normalize_duplicate_match_line(line) for line in candidate_excerpt if not MARKDOWN_HEADING_RE.match(line)]
        candidate_body = [line for line in candidate_body if line]
        if not candidate_body:
            continue

        matched_body_lines = 0
        for left, right in zip(anchor_body, candidate_body):
            if left == right or left.startswith(right) or right.startswith(left):
                matched_body_lines += 1

        if matched_body_lines < 1:
            continue

        return {
            "marker_line_index": marker_idx,
            "marker_line_number": marker_idx + 1,
            "marker_page_number": page_no,
            "heading": candidate_heading,
            "excerpt": candidate_excerpt,
            "removed_line_count": len(lines[marker_idx:]),
        }
    return None


def _build_duplicate_tail_removed_risk(finding: Dict[str, Any]) -> Dict[str, Any]:
    page_no = finding["marker_page_number"]
    heading = finding.get("heading", "")
    line_no = finding["marker_line_number"]
    return {
        "code": "manuscript_duplicate_tail_removed",
        "severity": "warning",
        "title": "原始 Markdown 在后段重复起稿",
        "summary": (
            f"原始分页 Markdown 在第 {page_no} 页附近又重新出现了一级标题和开场正文。"
            "清洗稿已经自动裁掉这段重复尾稿，但这通常说明源讲稿本身有异常。"
        ),
        "evidence": {
            "marker_page_number": page_no,
            "marker_line_number": line_no,
            "heading": heading,
            "excerpt": finding.get("excerpt", []),
            "removed_line_count": finding.get("removed_line_count", 0),
        },
        "recommended_action": (
            "请抽查原始 Markdown、PPT 最后几页，以及最终字幕/音频是否一致。"
            "如果末尾页仍有讲稿错位，优先修正原始讲稿后再重跑。"
        ),
    }


def _build_page_marker_slide_count_risk(text: str, rendered_slide_count: int) -> Dict[str, Any] | None:
    if not text or rendered_slide_count <= 0:
        return None

    page_numbers = [
        page_no
        for line in text.splitlines()
        if (page_no := _extract_pagination_number(line)) is not None
    ]
    if len(page_numbers) < 2:
        return None

    unique_numbers = sorted(set(page_numbers))
    max_marker = max(unique_numbers)
    if max_marker == rendered_slide_count and len(unique_numbers) == rendered_slide_count:
        return None

    return {
        "code": "page_markers_slide_count_mismatch",
        "severity": "warning",
        "title": "稿件分页锚点与 PPT 页数不一致",
        "summary": (
            f"原始稿件里的分页锚点最高到第 {max_marker} 页（共识别到 {len(unique_numbers)} 个页码标记），"
            f"但当前 PPT 渲染出了 {rendered_slide_count} 页。"
            "这可能是讲稿合并/拆分页，也可能是原始 Markdown 生成异常。"
        ),
        "evidence": {
            "marker_pages": unique_numbers,
            "max_marker_page": max_marker,
            "marker_count": len(unique_numbers),
            "rendered_slide_count": rendered_slide_count,
        },
        "recommended_action": (
            "请关注最终字幕、页间切分和音频节奏是否与 PPT 对应；"
            "如果最后几页明显不匹配，优先回看原始讲稿来源。"
        ),
    }


def preprocess_paginated_markdown(
    text: str,
    source_stem: str = "",
    rendered_slide_count: int | None = None,
) -> tuple[str, List[Dict[str, Any]]]:
    if not text:
        return "", []

    risks: List[Dict[str, Any]] = []
    if rendered_slide_count is not None:
        mismatch_risk = _build_page_marker_slide_count_risk(text, rendered_slide_count)
        if mismatch_risk is not None:
            risks.append(mismatch_risk)

    cleaned = strip_redundant_document_title(text, source_stem=source_stem)
    duplicate_tail = detect_duplicate_tail_restart(cleaned, source_stem=source_stem)
    if duplicate_tail is not None:
        cleaned_lines = cleaned.splitlines()
        cleaned = "\n".join(cleaned_lines[: duplicate_tail["marker_line_index"]]).rstrip()
        risks.append(_build_duplicate_tail_removed_risk(duplicate_tail))

    cleaned = strip_pagination_noise(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), risks


def clean_paginated_markdown(text: str, source_stem: str = "") -> str:
    cleaned, _risks = preprocess_paginated_markdown(text, source_stem=source_stem)
    return cleaned


def _cached_clean_manuscript_path(deck_root: Path, speech_path: Path) -> Path:
    cleaned_suffix = speech_path.suffix.lower() or ".md"
    return deck_root / "_cache" / "manuscript" / f"{speech_path.stem}.cleaned{cleaned_suffix}"


def _cached_clean_manuscript_meta_path(deck_root: Path, speech_path: Path) -> Path:
    return deck_root / "_cache" / "manuscript" / f"{speech_path.stem}.cleaned.meta.json"


def _read_cached_clean_manuscript(cleaned_path: Path, meta_path: Path, source_path: Path) -> str | None:
    if not cleaned_path.exists() or cleaned_path.stat().st_mtime < source_path.stat().st_mtime:
        return None
    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if meta.get("preprocess_version") != MANUSCRIPT_PREPROCESS_VERSION:
        return None

    cached = read_manuscript(cleaned_path)
    return cached if cached.strip() else None


def _write_cached_clean_manuscript(
    cleaned_path: Path,
    meta_path: Path,
    cleaned_text: str,
    source_path: Path,
    risks: Sequence[Dict[str, Any]],
) -> None:
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_text(cleaned_text.rstrip() + "\n", encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "preprocess_version": MANUSCRIPT_PREPROCESS_VERSION,
                "source_path": str(source_path),
                "risk_codes": [str(risk.get("code", "")) for risk in risks],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _risk_summary(risks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    highest = "info"
    if risks:
        highest = max(risks, key=lambda risk: RISK_SEVERITY_ORDER.get(str(risk.get("severity", "info")), 0)).get(
            "severity",
            "warning",
        )
    return {
        "risk_count": len(risks),
        "highest_severity": highest,
        "requires_manual_review": bool(risks),
    }


def _risk_report_path(deck_root: Path) -> Path:
    return deck_root / "imagesgallery-risk-report.json"


def _write_risk_report(
    deck_root: Path,
    ppt_path: Path,
    speech_path: Path,
    prepared_manuscript: PreparedManuscript,
    rendered_slide_count: int,
) -> tuple[Path | None, Dict[str, Any] | None]:
    report_path = _risk_report_path(deck_root)
    if not prepared_manuscript.risks:
        if report_path.exists():
            report_path.unlink()
        return None, None

    summary = _risk_summary(prepared_manuscript.risks)
    payload = {
        "version": VERSION,
        "report_type": "imagesgallery_manuscript_risk_report",
        "source_ppt": str(ppt_path),
        "source_speech": str(speech_path),
        "prepared_source_speech": str(prepared_manuscript.source_path),
        "rendered_slide_count": rendered_slide_count,
        "summary": summary,
        "risks": list(prepared_manuscript.risks),
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path, summary


def prepare_session_manuscript(
    path: Path,
    deck_root: Path,
    rendered_slide_count: int | None = None,
) -> PreparedManuscript:
    raw = read_manuscript(path)
    if path.suffix.lower() not in {".md", ".markdown"}:
        return PreparedManuscript(source_path=path, text=raw, was_preprocessed=False)
    if not is_paginated_markdown(raw):
        return PreparedManuscript(source_path=path, text=raw, was_preprocessed=False)

    cleaned, risks = preprocess_paginated_markdown(
        raw,
        source_stem=path.stem,
        rendered_slide_count=rendered_slide_count,
    )
    if not cleaned.strip():
        raise ValueError(f"preprocessed markdown became empty: {path}")

    cleaned_path = _cached_clean_manuscript_path(deck_root, path)
    meta_path = _cached_clean_manuscript_meta_path(deck_root, path)
    cached = _read_cached_clean_manuscript(cleaned_path, meta_path, path)
    if cached is not None:
        return PreparedManuscript(
            source_path=cleaned_path,
            text=cached,
            was_preprocessed=True,
            risks=tuple(risks),
        )

    _write_cached_clean_manuscript(cleaned_path, meta_path, cleaned, path, risks)
    return PreparedManuscript(
        source_path=cleaned_path,
        text=cleaned,
        was_preprocessed=True,
        risks=tuple(risks),
    )


def resolve_bin(name: str) -> str:
    """Resolve executable from PATH or Codex runtime fallback."""
    found = shutil.which(name)
    if found:
        return found

    fallback = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin" / name
    if fallback.exists():
        return str(fallback)

    raise FileNotFoundError(f"required executable not found: {name}")


def run_cmd(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed:\n"
            f"cmd: {' '.join(cmd)}\n"
            f"code: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )
    return proc


def _sorted_page_images(paths: Iterable[Path]) -> List[Path]:
    pattern = re.compile(r"-(\d+)\.png$", re.IGNORECASE)

    def key(path: Path) -> int:
        m = pattern.search(path.name)
        if not m:
            return 10**9
        return int(m.group(1))

    return sorted(paths, key=key)


def _export_ppt_via_powerpoint_com(ppt_path: Path, images_dir: Path) -> List[Path]:
    """Windows fallback: export slides directly via PowerPoint COM when soffice is unavailable."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("PowerPoint COM export is only supported on Windows")

    ppt_escaped = str(ppt_path).replace("'", "''")
    out_escaped = str(images_dir).replace("'", "''")
    ps_script = f"""
$ErrorActionPreference='Stop'
$ppt='{ppt_escaped}'
$out='{out_escaped}'
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($ppt, $false, $false, $false)
try {{
  $count = $pres.Slides.Count
  for ($i = 1; $i -le $count; $i++) {{
    $dest = Join-Path $out ("page-{{0:D3}}.png" -f $i)
    $pres.Slides.Item($i).Export($dest, "PNG")
  }}
  Write-Output $count
}} finally {{
  $pres.Close()
  $app.Quit()
}}
"""
    run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
    images = _sorted_page_images(images_dir.glob("page-*.png"))
    if not images:
        raise RuntimeError("PowerPoint COM export produced no PNG files")
    return images


def convert_ppt_to_images(
    ppt_path: Path,
    images_dir: Path,
    soffice_bin: str | None,
    pdftoppm_bin: str | None,
) -> List[Path]:
    """Convert PPT/PDF to sequential PNG files under images_dir."""
    suffix = ppt_path.suffix.lower()
    if suffix not in {".ppt", ".pptx", ".pdf"}:
        raise ValueError(f"unsupported input type: {ppt_path.suffix}; expected .ppt/.pptx/.pdf")

    images_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ppt-to-imagesgallery-") as tmp:
        tmp_dir = Path(tmp)
        if suffix == ".pdf":
            pdf_path = ppt_path
        else:
            if not soffice_bin:
                # Fallback for Windows ops machines without LibreOffice.
                return _export_ppt_via_powerpoint_com(ppt_path, images_dir)
            run_cmd([
                soffice_bin,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_dir),
                str(ppt_path),
            ])
            expected_pdf = tmp_dir / f"{ppt_path.stem}.pdf"
            if expected_pdf.exists():
                pdf_path = expected_pdf
            else:
                candidates = sorted(tmp_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    raise RuntimeError("soffice conversion succeeded but no PDF output was found")
                pdf_path = candidates[0]

        if not pdftoppm_bin:
            raise FileNotFoundError("required executable not found: pdftoppm")
        ppm_prefix = tmp_dir / "slide"
        run_cmd([pdftoppm_bin, "-png", str(pdf_path), str(ppm_prefix)])

        raw_images = _sorted_page_images(tmp_dir.glob("slide-*.png"))
        if not raw_images:
            raise RuntimeError("pdftoppm produced no PNG files")

        output_images: List[Path] = []
        for idx, raw in enumerate(raw_images, start=1):
            out_name = f"page-{idx:03d}.png"
            out_path = images_dir / out_name
            shutil.copy2(raw, out_path)
            output_images.append(out_path)

        return output_images


def _read_docx_manuscript(path: Path) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    wns = ns["w"]

    def _w(tag: str) -> str:
        return f"{{{wns}}}{tag}"

    def _escape_md_cell(text: str) -> str:
        t = (text or "").strip()
        t = t.replace("|", r"\|")
        t = t.replace("\n", "<br>")
        return t

    def _heading_level_from_style_token(token: str) -> int:
        if not token:
            return 0
        cleaned = token.strip()
        patterns = (
            r"Heading\s*([1-6])$",
            r"heading\s*([1-6])$",
            r"标题\s*([1-6])$",
            r"标题([1-6])$",
        )
        for pattern in patterns:
            match = re.match(pattern, cleaned, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return 0

    def _load_style_heading_levels(zf: zipfile.ZipFile) -> Dict[str, int]:
        try:
            styles_root = ET.fromstring(zf.read("word/styles.xml"))
        except KeyError:
            return {}

        direct_levels: Dict[str, int] = {}
        based_on: Dict[str, str] = {}

        for style in styles_root.findall("./w:style", ns):
            style_id = style.attrib.get(_w("styleId"), "").strip()
            if not style_id:
                continue

            level = _heading_level_from_style_token(style_id)
            if not level:
                name = style.find("./w:name", ns)
                if name is not None:
                    level = _heading_level_from_style_token(name.attrib.get(_w("val"), ""))
            if not level:
                outline = style.find("./w:pPr/w:outlineLvl", ns)
                if outline is not None:
                    outline_val = outline.attrib.get(_w("val"), "").strip()
                    if outline_val.isdigit():
                        level = int(outline_val) + 1

            direct_levels[style_id] = level

            parent = style.find("./w:basedOn", ns)
            if parent is not None:
                parent_id = parent.attrib.get(_w("val"), "").strip()
                if parent_id:
                    based_on[style_id] = parent_id

        resolved: Dict[str, int] = {}

        def resolve(style_id: str) -> int:
            if style_id in resolved:
                return resolved[style_id]
            level = direct_levels.get(style_id, 0)
            if level:
                resolved[style_id] = level
                return level
            parent_id = based_on.get(style_id, "")
            if not parent_id or parent_id == style_id:
                resolved[style_id] = 0
                return 0
            level = resolve(parent_id)
            resolved[style_id] = level
            return level

        for style_id in set(direct_levels) | set(based_on):
            resolve(style_id)
        return resolved

    def _parse_run_text(run: ET.Element) -> str:
        chunks: List[str] = []
        for node in run:
            if node.tag == _w("t"):
                chunks.append(node.text or "")
            elif node.tag == _w("tab"):
                chunks.append(" ")
            elif node.tag in {_w("br"), _w("cr")}:
                chunks.append("\n")
        text = "".join(chunks)
        if not text:
            return ""
        # Keep emphasis stable for downstream slicing/TTS:
        # prefer bold marker; avoid nested/stacked stars that produce *** / **** noise.
        if run.find("./w:rPr/w:b", ns) is not None:
            text = f"**{text}**"
        return text

    def _parse_paragraph(para: ET.Element, style_heading_levels: Dict[str, int]) -> str:
        texts: List[str] = []
        is_list = para.find(".//w:numPr", ns) is not None

        pstyle = para.find("./w:pPr/w:pStyle", ns)
        heading_level = 0
        if pstyle is not None:
            style_val = pstyle.attrib.get(f"{{{wns}}}val", "")
            heading_level = _heading_level_from_style_token(style_val)
            if not heading_level:
                heading_level = style_heading_levels.get(style_val, 0)
        if not heading_level:
            outline = para.find("./w:pPr/w:outlineLvl", ns)
            if outline is not None:
                outline_val = outline.attrib.get(_w("val"), "").strip()
                if outline_val.isdigit():
                    heading_level = int(outline_val) + 1

        for run in para.findall("./w:r", ns):
            run_text = _parse_run_text(run)
            if run_text:
                texts.append(run_text)

        para_text = "".join(texts).strip()
        if not para_text:
            return ""
        if heading_level:
            return f"{'#' * heading_level} {para_text}"
        if is_list:
            return f"- {para_text}"
        return para_text

    def _parse_table(tbl: ET.Element) -> List[str]:
        rows: List[List[str]] = []
        max_cols = 0
        for tr in tbl.findall("./w:tr", ns):
            row_cells: List[str] = []
            for tc in tr.findall("./w:tc", ns):
                cell_paras: List[str] = []
                for p in tc.findall("./w:p", ns):
                    txt = _parse_paragraph(p)
                    if txt:
                        cell_paras.append(txt)
                row_cells.append("\n".join(cell_paras).strip())
            if row_cells:
                max_cols = max(max_cols, len(row_cells))
                rows.append(row_cells)

        if not rows or max_cols == 0:
            return []

        normalized_rows: List[List[str]] = []
        for row in rows:
            normalized_rows.append(row + [""] * (max_cols - len(row)))

        header = normalized_rows[0]
        sep = ["---"] * max_cols
        md_lines = [
            "| " + " | ".join(_escape_md_cell(c) for c in header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for row in normalized_rows[1:]:
            md_lines.append("| " + " | ".join(_escape_md_cell(c) for c in row) + " |")
        return md_lines

    with zipfile.ZipFile(path) as zf:
        style_heading_levels = _load_style_heading_levels(zf)
        with zf.open("word/document.xml") as f:
            root = ET.parse(f).getroot()

    lines: List[str] = []
    body = root.find(".//w:body", ns)
    if body is None:
        return ""

    for child in list(body):
        if child.tag == _w("p"):
            para_text = _parse_paragraph(child, style_heading_levels)
            if para_text:
                lines.append(para_text)
            else:
                lines.append("")
        elif child.tag == _w("tbl"):
            table_lines = _parse_table(child)
            if table_lines:
                lines.extend(table_lines)
                lines.append("")

    # Collapse excessive blanks while keeping paragraph boundaries.
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # Normalize accidental emphasis stacking produced by rich-text copies.
    out = re.sub(r"\*{4,}", "**", out)
    out = re.sub(r"(?<!\*)\*\*\*(?!\*)", "**", out)
    out = re.sub(r"\u00a0", " ", out)
    return out.strip()


def read_manuscript(path: Path) -> str:
    suffix = path.suffix.lower()
    raw = ""
    if suffix in {".txt", ".md", ".markdown"}:
        raw = path.read_text(encoding="utf-8")
    elif suffix == ".docx":
        raw = _read_docx_manuscript(path)
    else:
        raise ValueError(f"unsupported speech type: {path.suffix}; expected .txt/.md/.docx")
    return raw


def build_imagesgallery(args: argparse.Namespace) -> Dict[str, object]:
    ppt_path = Path(args.ppt).expanduser().resolve()
    speech_path = Path(args.speech).expanduser().resolve()
    out_base = Path(args.out).expanduser().resolve()
    ppt_dir_name = ppt_path.stem.strip() or "ppt"
    deck_root = out_base / ppt_dir_name
    gallery_dir = deck_root / "imagesgallery"
    images_dir = gallery_dir / "images"

    if not ppt_path.exists():
        raise FileNotFoundError(f"ppt file not found: {ppt_path}")
    if not speech_path.exists():
        raise FileNotFoundError(f"speech file not found: {speech_path}")

    if gallery_dir.exists():
        shutil.rmtree(gallery_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    try:
        soffice_bin = resolve_bin("soffice")
    except FileNotFoundError:
        if sys.platform.startswith("win") and ppt_path.suffix.lower() in {".ppt", ".pptx"}:
            soffice_bin = None
        else:
            raise
    need_pdftoppm = (ppt_path.suffix.lower() == ".pdf") or (soffice_bin is not None)
    pdftoppm_bin = resolve_bin("pdftoppm") if need_pdftoppm else None
    image_abs_paths = convert_ppt_to_images(ppt_path, images_dir, soffice_bin=soffice_bin, pdftoppm_bin=pdftoppm_bin)

    prepared_manuscript = prepare_session_manuscript(
        speech_path,
        deck_root,
        rendered_slide_count=len(image_abs_paths),
    )
    manuscript_raw = prepared_manuscript.text
    manuscript_norm = normalize_for_alignment(manuscript_raw)
    if not manuscript_norm:
        raise ValueError("speech content is empty after normalization")

    items: List[Dict[str, object]] = []

    for page_number, image_abs in enumerate(image_abs_paths, start=1):
        rel_image = image_abs.relative_to(gallery_dir).as_posix()
        items.append(
            {
                "page_number": page_number,
                "image": rel_image,
                "speech": f"[DRY_RUN] page {page_number}",
            }
        )

    manifest = {
        "version": VERSION,
        "source_ppt": str(ppt_path),
        "source_speech": str(prepared_manuscript.source_path),
        "items": items,
    }
    risk_report_path, risk_summary = _write_risk_report(
        deck_root,
        ppt_path,
        speech_path,
        prepared_manuscript,
        rendered_slide_count=len(image_abs_paths),
    )
    if risk_report_path is not None and risk_summary is not None:
        manifest["risk_report"] = str(risk_report_path)
        manifest["risk_summary"] = risk_summary

    manifest_path = gallery_dir / "imagesgallery.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build imagesgallery skeleton from PPT + manuscript")
    parser.add_argument("--ppt", required=True, help="input .ppt/.pptx/.pdf file")
    parser.add_argument("--speech", required=True, help="input manuscript .txt/.md/.docx file")
    parser.add_argument("--out", required=True, help="output base directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="accepted for compatibility; script always generates images + skeleton manifest only",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(argv)
        manifest = build_imagesgallery(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: built imagesgallery with {len(manifest['items'])} items -> "
        f"{Path(args.out).expanduser().resolve() / (Path(args.ppt).expanduser().resolve().stem or 'ppt') / 'imagesgallery' / 'imagesgallery.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
