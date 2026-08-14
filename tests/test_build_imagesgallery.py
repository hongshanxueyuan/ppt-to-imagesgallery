import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_imagesgallery import (  # noqa: E402
    _extract_json_text,
    load_full_speech_session_prompt,
    parse_bl_omni_stdout,
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

    def test_read_manuscript_strips_duplicate_document_title_before_page_one(self):
        raw = """# 2.4 从AI给建议转向建议执行监督闭环

- 第 1 页

# 从AI给建议转向建议执行监督闭环

本节介绍的内容
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "2.4 从AI给建议转向建议执行监督闭环_水印版.md"
            md_path.write_text(raw, encoding="utf-8")
            manuscript = read_manuscript(md_path)

        self.assertFalse(manuscript.startswith("# 2.4 从AI给建议转向建议执行监督闭环"))
        self.assertIn("- 第 1 页", manuscript)
        self.assertIn("# 从AI给建议转向建议执行监督闭环", manuscript)

    def test_read_manuscript_keeps_distinct_preface_before_page_one(self):
        raw = """# 课程前言

- 第 1 页

# 正式标题

本节介绍的内容
"""
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "课程前言.md"
            md_path.write_text(raw, encoding="utf-8")
            manuscript = read_manuscript(md_path)

        self.assertTrue(manuscript.startswith("# 课程前言"))
        self.assertIn("# 正式标题", manuscript)

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

    def test_canonical_prompt_includes_pre_paginated_branch(self):
        canonical_prompt = load_full_speech_session_prompt()
        self.assertIn("A 类：已分页稿", canonical_prompt)
        self.assertIn("页码标记仅是**顺序锚点**", canonical_prompt)
        self.assertIn("相邻页码段", canonical_prompt)
        self.assertIn("自然段 / 列表项 / 小节边界", canonical_prompt)

    def test_skill_doc_mentions_studio_publish_dependency(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("studio-imagegallery-publish", skill_doc)
        self.assertIn("https://github.com/hongshanxueyuan/studio-imagegallery-publish", skill_doc)
        self.assertIn("推送到 Studio", skill_doc)
        self.assertIn("required companion skill", skill_doc)
        self.assertIn("must also install `studio-imagegallery-publish`", skill_doc)
        self.assertIn("Browser automation is not an allowed fallback for publish", skill_doc)
        self.assertIn("Do **not** read or preload browser-use/browser/chrome skill instructions", skill_doc)
        self.assertIn("do not continue any later batch actions after a course-id mismatch", skill_doc)

    def test_skill_doc_mentions_batch_planner_and_json_hygiene(self):
        skill_doc = (SCRIPT_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("plan_batch_jobs.py", skill_doc)
        self.assertIn("upload-report.json", skill_doc)
        self.assertIn("absolute paths", skill_doc)
        self.assertIn("imagegallery-push-studio-targets.json", skill_doc)
        self.assertIn("course-id mismatch", skill_doc.lower().replace("_", "-"))
        self.assertIn("do **not** open or analyze those report json files at all", skill_doc.lower())
        self.assertIn("已经有现成 manifest", skill_doc)
        self.assertIn("absolute clickable path", skill_doc)
        self.assertIn("Default execution mode is `三 agent 执行`", skill_doc)
        self.assertIn("do **not** stop to ask the user to choose", skill_doc)
        self.assertIn("Final Studio publish in batch mode must still run **sequentially**", skill_doc)
        self.assertIn("retry at most **4** times", skill_doc)
        self.assertIn("always list the final clickable Studio URLs", skill_doc)


if __name__ == "__main__":
    unittest.main()
