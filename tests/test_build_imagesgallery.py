import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_imagesgallery import (  # noqa: E402
    MANUSCRIPT_PREPROCESS_VERSION,
    _extract_json_text,
    build_imagesgallery,
    clean_paginated_markdown,
    is_paginated_markdown,
    load_full_speech_session_prompt,
    parse_bl_omni_stdout,
    prepare_session_manuscript,
    read_manuscript,
    run_batch_with_retries,
    validate_batch_result,
)


class TestBuildImagesGalleryHelpers(unittest.TestCase):
    def test_docx_numeric_heading_style_ids_become_markdown_headings(self):
        styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="2">
    <w:name w:val="heading 2"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="3">
    <w:name w:val="heading 3"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="4">
    <w:name w:val="Normal"/>
  </w:style>
</w:styles>
"""
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="2"/></w:pPr>
      <w:r><w:t>章节标题</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="4"/></w:pPr>
      <w:r><w:t>正文段落</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="3"/></w:pPr>
      <w:r><w:t>小节标题</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""
        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "sample.docx"
            with zipfile.ZipFile(docx_path, "w") as zf:
                zf.writestr("word/document.xml", document_xml)
                zf.writestr("word/styles.xml", styles_xml)

            manuscript = read_manuscript(docx_path)

        self.assertIn("## 章节标题", manuscript)
        self.assertIn("正文段落", manuscript)
        self.assertIn("### 小节标题", manuscript)

    def test_read_manuscript_keeps_raw_markdown_before_preprocessing(self):
        raw = """# 2.4 从AI给建议转向建议执行监督闭环

- 第 1 页

# 从AI给建议转向建议执行监督闭环

本节介绍的内容
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "2.4 从AI给建议转向建议执行监督闭环_水印版.md"
            md_path.write_text(raw, encoding="utf-8")
            manuscript = read_manuscript(md_path)

        self.assertTrue(manuscript.startswith("# 2.4 从AI给建议转向建议执行监督闭环"))
        self.assertIn("- 第 1 页", manuscript)
        self.assertIn("# 从AI给建议转向建议执行监督闭环", manuscript)

    def test_prepare_session_manuscript_cleans_paginated_markdown(self):
        raw = """# 2.4 从AI给建议转向建议执行监督闭环

- 第 1 页

# 从AI给建议转向建议执行监督闭环

本节介绍的内容

- 第 2 页

## 第二页标题

第二页正文
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "2.4 从AI给建议转向建议执行监督闭环_水印版.md"
            deck_root = Path(tmp) / "out" / "demo"
            md_path.write_text(raw, encoding="utf-8")

            prepared = prepare_session_manuscript(md_path, deck_root)
            cleaned_exists = prepared.source_path.exists()

        self.assertTrue(is_paginated_markdown(raw))
        self.assertTrue(prepared.was_preprocessed)
        self.assertEqual(deck_root / "_cache" / "manuscript" / "2.4 从AI给建议转向建议执行监督闭环_水印版.cleaned.md", prepared.source_path)
        self.assertTrue(cleaned_exists)
        self.assertFalse(prepared.text.startswith("# 2.4 从AI给建议转向建议执行监督闭环"))
        self.assertNotIn("第 1 页", prepared.text)
        self.assertNotIn("第 2 页", prepared.text)
        self.assertIn("# 从AI给建议转向建议执行监督闭环", prepared.text)
        self.assertIn("## 第二页标题", prepared.text)

    def test_prepare_session_manuscript_keeps_distinct_preface_before_page_one(self):
        raw = """# 课程前言

- 第 1 页

# 正式标题

本节介绍的内容
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "课程前言.md"
            deck_root = Path(tmp) / "out" / "demo"
            md_path.write_text(raw, encoding="utf-8")
            prepared = prepare_session_manuscript(md_path, deck_root)

        self.assertTrue(prepared.was_preprocessed)
        self.assertTrue(prepared.text.startswith("# 课程前言"))
        self.assertNotIn("- 第 1 页", prepared.text)
        self.assertIn("# 正式标题", prepared.text)

    def test_prepare_session_manuscript_reuses_cached_cleaned_markdown(self):
        raw = """# 文件标题

- 第 1 页

# 文件标题

正文
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "sample.md"
            deck_root = Path(tmp) / "out" / "demo"
            md_path.write_text(raw, encoding="utf-8")

            prepared = prepare_session_manuscript(md_path, deck_root)
            prepared.source_path.write_text("# cached\n\n复用后的内容\n", encoding="utf-8")
            meta_path = deck_root / "_cache" / "manuscript" / "sample.cleaned.meta.json"
            meta_path.write_text(
                json.dumps({"preprocess_version": MANUSCRIPT_PREPROCESS_VERSION}, ensure_ascii=False),
                encoding="utf-8",
            )
            source_mtime = md_path.stat().st_mtime
            os.utime(prepared.source_path, (source_mtime + 10, source_mtime + 10))
            os.utime(meta_path, (source_mtime + 10, source_mtime + 10))

            reused = prepare_session_manuscript(md_path, deck_root)

        self.assertTrue(reused.was_preprocessed)
        self.assertEqual("# cached\n\n复用后的内容\n", reused.text)

    def test_build_imagesgallery_uses_cleaned_markdown_as_source_speech(self):
        raw = """# 示例标题

- 第 1 页

# 示例标题

第一页正文

- 第 2 页

## 第二页

第二页正文
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            speech_path = tmp_path / "sample.md"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"fake-ppt")
            speech_path.write_text(raw, encoding="utf-8")

            def fake_convert(_ppt_path, images_dir, soffice_bin=None, pdftoppm_bin=None):
                image_path = images_dir / "page-001.png"
                image_path.write_bytes(b"fake-image")
                return [image_path]

            args = argparse.Namespace(ppt=str(ppt_path), speech=str(speech_path), out=str(out_dir), dry_run=True)
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images",
                side_effect=fake_convert,
            ):
                manifest = build_imagesgallery(args)

            cleaned_path = out_dir / "sample" / "_cache" / "manuscript" / "sample.cleaned.md"
            self.assertEqual(str(cleaned_path.resolve()), manifest["source_speech"])
            self.assertTrue(cleaned_path.exists())
            self.assertNotIn("第 1 页", cleaned_path.read_text(encoding="utf-8"))

    def test_clean_paginated_markdown_removes_page_markers_and_duplicate_cover_title(self):
        raw = """# 文件标题

- 第 1 页

# 文件标题

正文

Page 2

## 第二页

更多正文
"""
        cleaned = clean_paginated_markdown(raw, source_stem="文件标题")
        self.assertEqual(1, cleaned.count("# 文件标题"))
        self.assertNotIn("第 1 页", cleaned)
        self.assertNotIn("Page 2", cleaned)
        self.assertIn("## 第二页", cleaned)

    def test_clean_paginated_markdown_removes_duplicate_tail_restart(self):
        raw = """# 2.2 从人找信息转向智能体持续感知

- 第 1 页

# 从人找信息转向智能体持续感知

本节介绍的是从人找信息转向智能体持续感知。

## 一、第一页小节

第一页正文

- 第 2 页

## 二、第二页小节

第二页正文

- 第 3 页

# 从人找信息转向智能体持续感知

本节介绍的是从人找信息转向智能体持续感知。
"""
        cleaned = clean_paginated_markdown(raw, source_stem="2.2 从人找信息转向智能体持续感知")
        self.assertEqual(1, cleaned.count("# 从人找信息转向智能体持续感知"))
        self.assertEqual(1, cleaned.count("本节介绍的是从人找信息转向智能体持续感知。"))
        self.assertIn("## 二、第二页小节", cleaned)
        self.assertNotIn("第 3 页", cleaned)

    def test_build_imagesgallery_writes_risk_report_for_suspicious_paginated_markdown(self):
        raw = """# 2.2 从人找信息转向智能体持续感知

- 第 1 页

# 从人找信息转向智能体持续感知

本节介绍的是从人找信息转向智能体持续感知。

- 第 2 页

## 一、持续感知到底在盯什么

第二页正文

- 第 3 页

# 从人找信息转向智能体持续感知

本节介绍的是从人找信息转向智能体持续感知。
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ppt_path = tmp_path / "sample.pptx"
            speech_path = tmp_path / "sample.md"
            out_dir = tmp_path / "out"
            ppt_path.write_bytes(b"fake-ppt")
            speech_path.write_text(raw, encoding="utf-8")

            def fake_convert(_ppt_path, images_dir, soffice_bin=None, pdftoppm_bin=None):
                image_paths = []
                for idx in range(1, 5):
                    image_path = images_dir / f"page-{idx:03d}.png"
                    image_path.write_bytes(b"fake-image")
                    image_paths.append(image_path)
                return image_paths

            args = argparse.Namespace(ppt=str(ppt_path), speech=str(speech_path), out=str(out_dir), dry_run=True)
            with patch("build_imagesgallery.resolve_bin", return_value="fake-bin"), patch(
                "build_imagesgallery.convert_ppt_to_images",
                side_effect=fake_convert,
            ):
                manifest = build_imagesgallery(args)

            report_path = out_dir / "sample" / "imagesgallery-risk-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(str(report_path), manifest["risk_report"])
        self.assertEqual(2, manifest["risk_summary"]["risk_count"])
        self.assertTrue(manifest["risk_summary"]["requires_manual_review"])
        self.assertEqual(2, report["summary"]["risk_count"])
        codes = {risk["code"] for risk in report["risks"]}
        self.assertIn("manuscript_duplicate_tail_removed", codes)
        self.assertIn("page_markers_slide_count_mismatch", codes)

    def test_parse_bl_omni_stdout(self):
        output = json.dumps({"content": "{\"pages\":[{\"page_number\":1,\"speech\":\"a\"}]}"})
        content = parse_bl_omni_stdout(output)
        self.assertIn("pages", content)

    def test_extract_json_text_from_fence(self):
        raw = "```json\n{\"pages\":[{\"page_number\":1,\"speech\":\"ok\"}]}\n```"
        extracted = _extract_json_text(raw)
        payload = json.loads(extracted)
        self.assertEqual(1, payload["pages"][0]["page_number"])

    def test_validate_batch_result(self):
        payload = {
            "pages": [
                {"page_number": 1, "speech": "a"},
                {"page_number": 2, "speech": "b"},
            ]
        }
        ordered = validate_batch_result(payload, [1, 2])
        self.assertEqual(["a", "b"], ordered)

    def test_retry_then_success(self):
        calls = {"n": 0}

        def invoke(extra_prompt: str) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return "not-json"
            return "{\"pages\":[{\"page_number\":1,\"speech\":\"ok\"}]}"

        ordered = run_batch_with_retries(invoke, expected_page_numbers=[1], max_retries=2)
        self.assertEqual(["ok"], ordered)
        self.assertEqual(2, calls["n"])

    def test_retry_on_post_validate_failure(self):
        calls = {"n": 0}

        def invoke(extra_prompt: str) -> str:
            calls["n"] += 1
            return "{\"pages\":[{\"page_number\":1,\"speech\":\"ok\"}]}"

        def post_validate(speeches):
            if calls["n"] == 1:
                raise ValueError("alignment failed")

        ordered = run_batch_with_retries(
            invoke,
            expected_page_numbers=[1],
            max_retries=2,
            post_validate=post_validate,
        )
        self.assertEqual(["ok"], ordered)
        self.assertEqual(2, calls["n"])

    def test_run_batch_with_retries_uses_canonical_prompt_file(self):
        prompts = []

        def invoke(prompt_text: str) -> str:
            prompts.append(prompt_text)
            return "{\"pages\":[{\"page_number\":1,\"speech\":\"ok\"}]}"

        ordered = run_batch_with_retries(invoke, expected_page_numbers=[1], max_retries=1)
        self.assertEqual(["ok"], ordered)
        self.assertEqual(1, len(prompts))

        canonical_prompt = load_full_speech_session_prompt()
        self.assertTrue(prompts[0].startswith(canonical_prompt))
        self.assertIn("只返回 JSON", prompts[0])

    def test_canonical_prompt_is_generic_full_manuscript_prompt(self):
        canonical_prompt = load_full_speech_session_prompt()
        self.assertNotIn("## 预判类型", canonical_prompt)
        self.assertNotIn("A 类：已分页稿", canonical_prompt)
        self.assertNotIn("页码标记仅是**顺序锚点**", canonical_prompt)
        self.assertIn("全文覆盖与顺序", canonical_prompt)
        self.assertIn("全局分镜对齐", canonical_prompt)

    def test_skill_doc_mentions_studio_publish_dependency(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("studio-imagegallery-publish", skill_doc)
        self.assertIn("https://github.com/hongshanxueyuan/studio-imagegallery-publish", skill_doc)
        self.assertIn("推送到 Studio", skill_doc)
        self.assertIn("必需配套 skill", skill_doc)
        self.assertIn("必须同时安装 `studio-imagegallery-publish`", skill_doc)
        self.assertIn("浏览器自动化不是这个 skill 允许的推送兜底方案", skill_doc)
        self.assertIn("预加载或阅读 `browser-use` / `browser` / `chrome`", skill_doc)
        self.assertIn("不要继续任何后续批量动作", skill_doc)

    def test_skill_doc_mentions_batch_planner_and_json_hygiene(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("plan_batch_jobs.py", skill_doc)
        self.assertIn("upload-report.json", skill_doc)
        self.assertIn("绝对路径", skill_doc)
        self.assertIn("imagegallery-push-studio-targets.json", skill_doc)
        self.assertIn("course id 不匹配", skill_doc)
        self.assertIn("打开或分析这些报告 JSON", skill_doc)
        self.assertIn("已经有现成 manifest", skill_doc)
        self.assertIn("绝对可点击路径", skill_doc)
        self.assertIn("默认执行模式是 `三 agent 执行`", skill_doc)
        self.assertIn("每个子 agent 必须 **严格只处理一个 deck**", skill_doc)
        self.assertIn("处理完 deck A 后，又在同一会话里继续处理 deck B", skill_doc)
        self.assertIn("同时活跃的子 agent", skill_doc)
        self.assertIn("同时活跃", skill_doc)
        self.assertIn("停下来让用户选择", skill_doc)
        self.assertIn("批量模式下最终的 Studio 推送仍必须 **顺序执行**", skill_doc)
        self.assertIn("最多重试 **4** 次", skill_doc)
        self.assertIn("目标 vertical 的可点击 Studio URL", skill_doc)
        self.assertIn("绝不要在同一个子 agent 会话里读取或查看两个不同 deck 的图片", skill_doc)
        self.assertIn("指的是**同时活跃**的本地生成子 agent 上限", skill_doc)
        self.assertIn("混合工作目录 / 多类 JSON 文件特别重要", skill_doc)
        self.assertNotIn("NotebookLM / `nlm-course-slides`", skill_doc)

    def test_skill_doc_mentions_paginated_markdown_preprocessing(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("分页 Markdown 预处理", skill_doc)
        self.assertIn("_cache/manuscript", skill_doc)
        self.assertIn("`source_speech` 会指向这个清洗后的 Markdown", skill_doc)
        self.assertIn("通用整稿 prompt", skill_doc)
        self.assertIn("imagesgallery-risk-report.json", skill_doc)
        self.assertIn("风险列表", skill_doc)
        self.assertIn("不阻断主流程", skill_doc)


if __name__ == "__main__":
    unittest.main()
