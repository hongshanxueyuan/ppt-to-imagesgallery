#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


VERSION = "1.0"
PAGINATION_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:"
    r"第\s*\d+\s*页(?:\s*/\s*共\s*\d+\s*页)?"
    r"|page\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r"|slide\s*\d+(?:\s*(?:/|of)\s*\d+)?"
    r")\s*$"
)


def resolve_bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found

    fallback = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin" / name
    if fallback.exists():
        return str(fallback)

    raise FileNotFoundError(f"required executable not found: {name}")


def run_cmd(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
        match = pattern.search(path.name)
        return int(match.group(1)) if match else 10**9

    return sorted(paths, key=key)


def _build_image_name_prefix(source_stem: str) -> str:
    stem = (source_stem or "").strip()
    digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8] if stem else "00000000"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:40]
    return f"{slug}-{digest}" if slug else f"deck-{digest}"


def _build_image_name_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def _build_page_image_name(image_name_prefix: str, page_number: int, image_name_timestamp: str) -> str:
    return f"{image_name_prefix}__page-{page_number:03d}__{image_name_timestamp}.png"


def _export_ppt_via_powerpoint_com(
    ppt_path: Path,
    images_dir: Path,
    image_name_prefix: str,
    image_name_timestamp: str,
) -> List[Path]:
    if not sys.platform.startswith("win"):
        raise RuntimeError("PowerPoint COM export is only supported on Windows")

    ppt_escaped = str(ppt_path).replace("'", "''")
    out_escaped = str(images_dir).replace("'", "''")
    prefix_escaped = image_name_prefix.replace("'", "''")
    timestamp_escaped = image_name_timestamp.replace("'", "''")
    ps_script = f"""
$ErrorActionPreference='Stop'
$ppt='{ppt_escaped}'
$out='{out_escaped}'
$prefix='{prefix_escaped}'
$stamp='{timestamp_escaped}'
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($ppt, $false, $false, $false)
try {{
  $count = $pres.Slides.Count
  for ($i = 1; $i -le $count; $i++) {{
    $dest = Join-Path $out ("{{0}}__page-{{1:D3}}__{{2}}.png" -f $prefix, $i, $stamp)
    $pres.Slides.Item($i).Export($dest, "PNG")
  }}
  Write-Output $count
}} finally {{
  $pres.Close()
  $app.Quit()
}}
"""
    result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
    count_lines = (result.stdout or "").strip().splitlines()
    if not count_lines:
        raise RuntimeError("PowerPoint COM export did not report slide count")

    try:
        slide_count = int(count_lines[-1].strip())
    except ValueError as exc:
        raise RuntimeError(f"PowerPoint COM export returned invalid slide count: {result.stdout}") from exc

    images = [images_dir / _build_page_image_name(image_name_prefix, idx, image_name_timestamp) for idx in range(1, slide_count + 1)]
    if not images or any(not path.exists() for path in images):
        raise RuntimeError("PowerPoint COM export produced no PNG files")
    return images


def _count_ppt_via_powerpoint_com(ppt_path: Path) -> int:
    if not sys.platform.startswith("win"):
        raise RuntimeError("PowerPoint COM slide counting is only supported on Windows")

    ppt_escaped = str(ppt_path).replace("'", "''")
    ps_script = f"""
$ErrorActionPreference='Stop'
$ppt='{ppt_escaped}'
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($ppt, $false, $false, $false)
try {{
  Write-Output $pres.Slides.Count
}} finally {{
  $pres.Close()
  $app.Quit()
}}
"""
    result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
    count_lines = (result.stdout or "").strip().splitlines()
    if not count_lines:
        raise RuntimeError("PowerPoint COM slide counting did not report slide count")

    try:
        return int(count_lines[-1].strip())
    except ValueError as exc:
        raise RuntimeError(f"PowerPoint COM slide counting returned invalid slide count: {result.stdout}") from exc


def _count_pptx_slides_from_zip(ppt_path: Path) -> int:
    try:
        with zipfile.ZipFile(ppt_path) as archive:
            slide_members = [
                info.filename
                for info in archive.infolist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename)
            ]
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"pptx package is invalid: {ppt_path}") from exc

    if not slide_members:
        raise RuntimeError(f"pptx package contains no slide entries: {ppt_path}")
    return len(slide_members)


def convert_ppt_to_images(
    ppt_path: Path,
    images_dir: Path,
    soffice_bin: str | None,
    pdftoppm_bin: str | None,
    image_name_prefix: str,
    image_name_timestamp: str,
) -> List[Path]:
    suffix = ppt_path.suffix.lower()
    if suffix not in {".ppt", ".pptx"}:
        raise ValueError(f"unsupported input type: {ppt_path.suffix}; expected .ppt/.pptx")

    images_dir.mkdir(parents=True, exist_ok=True)

    if not soffice_bin:
        return _export_ppt_via_powerpoint_com(
            ppt_path,
            images_dir,
            image_name_prefix=image_name_prefix,
            image_name_timestamp=image_name_timestamp,
        )

    if not pdftoppm_bin:
        raise FileNotFoundError("required executable not found: pdftoppm")

    with tempfile.TemporaryDirectory(prefix="ppt-to-imagesgallery-") as tmp:
        tmp_dir = Path(tmp)
        run_cmd(
            [
                soffice_bin,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_dir),
                str(ppt_path),
            ]
        )
        expected_pdf = tmp_dir / f"{ppt_path.stem}.pdf"
        if expected_pdf.exists():
            pdf_path = expected_pdf
        else:
            candidates = sorted(tmp_dir.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
            if not candidates:
                raise RuntimeError("soffice conversion succeeded but no PDF output was found")
            pdf_path = candidates[0]

        ppm_prefix = tmp_dir / "slide"
        run_cmd([pdftoppm_bin, "-png", str(pdf_path), str(ppm_prefix)])
        raw_images = _sorted_page_images(tmp_dir.glob("slide-*.png"))
        if not raw_images:
            raise RuntimeError("pdftoppm produced no PNG files")

        output_images: List[Path] = []
        for idx, raw in enumerate(raw_images, start=1):
            out_path = images_dir / _build_page_image_name(image_name_prefix, idx, image_name_timestamp)
            shutil.copy2(raw, out_path)
            output_images.append(out_path)
        return output_images


def _strip_page_markers(text: str) -> str:
    return PAGINATION_LINE_RE.sub("", text or "")


def validate_section_payload(section: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(section, Mapping):
        raise ValueError("section payload must be an object")

    page_count = section.get("page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        raise ValueError("page_count must be a positive integer")

    raw_page_content = section.get("page_content")
    if not isinstance(raw_page_content, list):
        raise ValueError("page_content must be a list")
    if len(raw_page_content) != page_count:
        raise ValueError(f"page_count {page_count} does not match len(page_content) {len(raw_page_content)}")

    page_content: List[str] = []
    for index, page in enumerate(raw_page_content, start=1):
        if not isinstance(page, str):
            raise ValueError(f"page_content[{index}] must be a string")
        normalized = _strip_page_markers(page).strip()
        if not normalized:
            raise ValueError(f"page_content[{index}] must not be blank")
        page_content.append(page.strip())

    return {
        "section_id": str(section.get("section_id", "")).strip(),
        "section_title": str(section.get("section_title", "")).strip(),
        "resource_title": str(section.get("resource_title", "")).strip(),
        "output_name": str(section.get("output_name", "")).strip(),
        "page_count": page_count,
        "page_content": page_content,
    }


def load_section_payload(section_json_path: Path) -> Dict[str, Any]:
    if not section_json_path.exists():
        raise FileNotFoundError(f"section json not found: {section_json_path}")
    data = json.loads(section_json_path.read_text(encoding="utf-8"))
    return validate_section_payload(data)


def count_presentation_pages(ppt_path: Path) -> int:
    ppt_path = Path(ppt_path).expanduser().resolve()
    if not ppt_path.exists():
        raise FileNotFoundError(f"ppt file not found: {ppt_path}")

    suffix = ppt_path.suffix.lower()
    if suffix == ".pptx":
        # Preflight must stop before any rendering work, so count OOXML slides directly.
        return _count_pptx_slides_from_zip(ppt_path)

    try:
        soffice_bin = resolve_bin("soffice")
    except FileNotFoundError:
        if sys.platform.startswith("win") and suffix in {".ppt", ".pptx"}:
            soffice_bin = None
        else:
            raise

    if soffice_bin is None:
        return _count_ppt_via_powerpoint_com(ppt_path)

    raise RuntimeError(
        "non-rendering slide counting is unavailable for legacy .ppt files when the LibreOffice backend is active"
    )


def build_imagesgallery(args: argparse.Namespace) -> Dict[str, object]:
    ppt_path = Path(args.ppt).expanduser().resolve()
    section_json_path = Path(args.section_json).expanduser().resolve()
    out_base = Path(args.out).expanduser().resolve()
    deck_root = out_base / (ppt_path.stem.strip() or "ppt")
    gallery_dir = deck_root / "imagesgallery"
    images_dir = gallery_dir / "images"

    if not ppt_path.exists():
        raise FileNotFoundError(f"ppt file not found: {ppt_path}")

    section = load_section_payload(section_json_path)
    if gallery_dir.exists():
        shutil.rmtree(gallery_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    try:
        soffice_bin = resolve_bin("soffice")
    except FileNotFoundError:
        if sys.platform.startswith("win"):
            soffice_bin = None
        else:
            raise

    pdftoppm_bin = resolve_bin("pdftoppm") if soffice_bin is not None else None
    image_name_prefix = _build_image_name_prefix(ppt_path.stem)
    image_name_timestamp = _build_image_name_timestamp()
    image_abs_paths = convert_ppt_to_images(
        ppt_path,
        images_dir,
        soffice_bin=soffice_bin,
        pdftoppm_bin=pdftoppm_bin,
        image_name_prefix=image_name_prefix,
        image_name_timestamp=image_name_timestamp,
    )

    rendered_slide_count = len(image_abs_paths)
    expected_page_count = int(section["page_count"])
    if rendered_slide_count != expected_page_count:
        raise ValueError(
            f"rendered slide count {rendered_slide_count} does not match page_count {expected_page_count} for {ppt_path}"
        )

    items: List[Dict[str, object]] = []
    for page_number, (image_abs_path, speech) in enumerate(zip(image_abs_paths, section["page_content"], strict=True), start=1):
        items.append(
            {
                "page_number": page_number,
                "image": image_abs_path.relative_to(gallery_dir).as_posix(),
                "speech": speech,
            }
        )

    manifest = {
        "version": VERSION,
        "source_ppt": str(ppt_path),
        "items": items,
    }
    manifest_path = gallery_dir / "imagesgallery.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build stage-A imagesgallery output from one PPT and one resolved section record")
    parser.add_argument("--ppt", required=True, help="input .ppt/.pptx file")
    parser.add_argument("--section-json", required=True, help="resolved section json containing page_count and page_content")
    parser.add_argument("--out", required=True, help="output base directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="accepted for compatibility; the script always renders images and writes stage-A manifest output",
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

    manifest_path = Path(args.out).expanduser().resolve() / (Path(args.ppt).expanduser().resolve().stem or "ppt") / "imagesgallery" / "imagesgallery.json"
    print(f"OK: built stage-A imagesgallery with {len(manifest['items'])} items -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
