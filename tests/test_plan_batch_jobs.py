import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from plan_batch_jobs import (  # noqa: E402
    PREFLIGHT_REPORT_FILENAME,
    STUDIO_TARGETS_FILENAME,
    classify_json_file,
    default_preflight_report_path,
    default_studio_targets_path,
    discover_batch_jobs,
    write_studio_targets_file,
    _normalize_batch_name,
)


def _section(
    section_id: str,
    title: str,
    page_count: int,
    page_content: list[str],
    output_name: str | None = None,
) -> dict:
    return {
        "section_id": section_id,
        "section_title": title,
        "resource_title": title,
        "output_name": output_name or f"{title}.pptx",
        "page_count": page_count,
        "page_content": page_content,
    }


class TestPlanBatchJobs(unittest.TestCase):
    def test_normalize_batch_name_keeps_section_number_prefix(self):
        self.assertEqual("1.2课程a", _normalize_batch_name("1.2 课程A_水印版"))
        self.assertEqual("1.2课程a", _normalize_batch_name("1.2 课程A.pptx"))

    def test_classify_json_file(self):
        self.assertEqual("ignored_report", classify_json_file(Path("upload-report.json")))
        self.assertEqual("ignored_report", classify_json_file(Path("create-report-retry-2026-08-14.json")))
        self.assertEqual("candidate_structure", classify_json_file(Path("course.json")))
        self.assertEqual("candidate_structure", classify_json_file(Path("fira_course-v1_FIRAx_1040045_20260807.json")))
        self.assertEqual("other_json", classify_json_file(Path("notes.json")))

    def test_discover_batch_jobs_matches_local_ppt_subset_and_orders_by_section_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.3 课程C_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.1 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "upload-report.json").write_text("{}", encoding="utf-8")
            (root / "notes.json").write_text("{}", encoding="utf-8")
            section_list = {
                "sections": [
                    _section("1.1", "1.1 课程A", 2, ["## A1\n\n第一页", "## A2\n\n第二页"]),
                    _section("1.2", "1.2 课程B", 1, ["## B1\n\n第一页"]),
                    _section("1.3", "1.3 课程C", 3, ["## C1\n\n第一页", "## C2\n\n第二页", "## C3\n\n第三页"]),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            observed_counts = {
                "1.1 课程A_水印版.pptx": 2,
                "1.3 课程C_水印版.pptx": 3,
            }
            with patch(
                "plan_batch_jobs.count_presentation_pages",
                side_effect=lambda path: observed_counts[Path(path).name],
            ):
                plan = discover_batch_jobs(root, shards=2)

        self.assertTrue(plan["admission_ready"])
        self.assertEqual("clean", plan["preflight"]["status"])
        self.assertEqual(["1.1", "1.3"], [job["section_id"] for job in plan["jobs"]])
        self.assertEqual(
            ["1.2"],
            [section["section_id"] for section in plan["ignored_upstream_sections"]],
        )
        self.assertEqual(0, len(plan["discovery_failures"]))
        self.assertEqual(0, len(plan["preflight"]["failures"]))
        self.assertEqual(2, len(plan["shards"]))
        self.assertEqual(1, len(plan["shards"][0]["jobs"]))
        self.assertEqual(1, len(plan["shards"][1]["jobs"]))
        first_job = plan["jobs"][0]
        self.assertEqual(2, first_job["page_count"])
        self.assertEqual("## A1\n\n第一页", first_job["page_content"][0])
        self.assertTrue(first_job["ppt"].endswith("1.1 课程A_水印版.pptx"))
        self.assertEqual(1, len(plan["ignored_report_json"]))
        self.assertEqual(1, len(plan["candidate_structure_json"]))
        self.assertEqual(1, len(plan["other_json"]))

    def test_discover_batch_jobs_reports_discovery_failures_and_does_not_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.1 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "未知课程_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {
                "sections": [
                    _section("1.1", "1.1 课程A", 2, ["## A1\n\n第一页", "## A2\n\n第二页"]),
                    _section("1.2", "1.2 课程B", 1, ["## B1\n\n第一页"]),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            with patch("plan_batch_jobs.count_presentation_pages", return_value=2):
                plan = discover_batch_jobs(root, shards=3)

        self.assertFalse(plan["admission_ready"])
        self.assertEqual(1, len(plan["jobs"]))
        self.assertEqual(1, len(plan["discovery_failures"]))
        self.assertEqual("section_list_match_not_found", plan["discovery_failures"][0]["code"])
        self.assertEqual([], plan["shards"])

    def test_discover_batch_jobs_does_not_match_local_ppt_by_title_or_id_without_output_name_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {
                "sections": [
                    _section(
                        "1.2",
                        "1.2 课程A",
                        2,
                        ["## A1\n\n第一页", "## A2\n\n第二页"],
                        output_name="完全不同的文件名.pptx",
                    )
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            plan = discover_batch_jobs(root)

        self.assertFalse(plan["admission_ready"])
        self.assertEqual([], plan["jobs"])
        self.assertEqual("section_list_match_not_found", plan["discovery_failures"][0]["code"])

    def test_discover_batch_jobs_uses_section_id_only_to_break_output_name_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {
                "sections": [
                    _section("1.2", "1.2 课程A", 2, ["## A1", "## A2"], output_name="1.2 课程A.pptx"),
                    _section("9.9", "9.9 课程A", 2, ["## Z1", "## Z2"], output_name="1.2 课程A_讲稿版.pptx"),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            with patch("plan_batch_jobs.count_presentation_pages", return_value=2):
                plan = discover_batch_jobs(root)

        self.assertTrue(plan["admission_ready"])
        self.assertEqual(["1.2"], [job["section_id"] for job in plan["jobs"]])

    def test_discover_batch_jobs_writes_preflight_report_and_stops_before_sharding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.1 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程B_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {
                "sections": [
                    _section("1.1", "1.1 课程A", 2, ["## A1", "## A2"]),
                    _section("1.2", "1.2 课程B", 2, ["## B1", "## B2"]),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            observed_counts = {
                "1.1 课程A_水印版.pptx": 2,
                "1.2 课程B_水印版.pptx": 3,
            }
            with patch(
                "plan_batch_jobs.count_presentation_pages",
                side_effect=lambda path: observed_counts[Path(path).name],
            ):
                plan = discover_batch_jobs(root, shards=2)

            report_path = default_preflight_report_path(root)
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertFalse(plan["admission_ready"])
        self.assertEqual("failed", plan["preflight"]["status"])
        self.assertEqual(str(report_path), plan["preflight"]["report_path"])
        self.assertEqual(PREFLIGHT_REPORT_FILENAME, report_path.name)
        self.assertEqual(1, report["failure_count"])
        self.assertEqual("page_count_mismatch", report["failures"][0]["code"])
        self.assertTrue(report["failures"][0]["ppt"].endswith("1.2 课程B_水印版.pptx"))
        self.assertEqual(2, report["failures"][0]["expected_page_count"])
        self.assertEqual(3, report["failures"][0]["observed_slide_count"])
        self.assertEqual([], plan["shards"])

    def test_discover_batch_jobs_does_not_continue_studio_planning_after_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {"sections": [_section("1.2", "1.2 课程A", 2, ["## A1", "## A2"])]}
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")
            course_structure = {
                "course_id": "course-v1:FIRAx+1040045+20260807",
                "name": "示例课程",
                "chapters": [
                    {
                        "name": "1. 第一章",
                        "block_location": "block-v1:FIRAx+1040045+20260807+type@chapter+block@chapter1",
                        "block_order": "001",
                        "sections": [
                            {
                                "name": "1.2 课程A",
                                "block_location": "block-v1:FIRAx+1040045+20260807+type@sequential+block@sectiona",
                                "block_order": "001.002",
                                "verticals": [
                                    {
                                        "name": "赋能内容",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                                        "block_order": "001.002.001",
                                        "blocks": [
                                            {
                                                "name": "有声幻灯片",
                                                "category": "imagesgallery",
                                                "block_location": "block-v1:FIRAx+1040045+20260807+type@imagesgallery+block@ga",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(
                json.dumps(course_structure, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("plan_batch_jobs.count_presentation_pages", return_value=3):
                plan = discover_batch_jobs(
                    root,
                    studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+1040045+20260807",
                )

        self.assertFalse(plan["admission_ready"])
        self.assertEqual("failed", plan["preflight"]["status"])
        self.assertEqual({}, plan["studio_publish"])
        self.assertNotIn("studio_vertical_url", plan["jobs"][0])

    def test_discover_batch_jobs_reports_structural_page_content_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.1 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程B_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {
                "sections": [
                    {
                        "section_id": "1.1",
                        "section_title": "1.1 课程A",
                        "resource_title": "1.1 课程A",
                        "output_name": "1.1 课程A.pptx",
                        "page_content": ["## A1"],
                    },
                    _section("1.2", "1.2 课程B", 2, ["   ", "## B2"]),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            with patch("plan_batch_jobs.count_presentation_pages", return_value=1):
                plan = discover_batch_jobs(root)

            report = json.loads(default_preflight_report_path(root).read_text(encoding="utf-8"))

        self.assertFalse(plan["admission_ready"])
        codes = [failure["code"] for failure in report["failures"]]
        self.assertIn("missing_page_count", codes)
        self.assertIn("blank_page_content", codes)
        self.assertEqual([], plan["shards"])

    def test_discover_batch_jobs_derives_studio_vertical_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.3 课程B_水印版.pptx").write_text("ppt", encoding="utf-8")

            section_list = {
                "sections": [
                    _section("1.2", "1.2 课程A", 2, ["## A1", "## A2"]),
                    _section("1.3", "1.3 课程B", 1, ["## B1"]),
                ]
            }
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")

            course_structure = {
                "course_id": "course-v1:FIRAx+1040045+20260807",
                "name": "示例课程",
                "chapters": [
                    {
                        "name": "1. 第一章",
                        "block_location": "block-v1:FIRAx+1040045+20260807+type@chapter+block@chapter1",
                        "block_order": "001",
                        "sections": [
                            {
                                "name": "1.2 课程A",
                                "block_location": "block-v1:FIRAx+1040045+20260807+type@sequential+block@sectiona",
                                "block_order": "001.002",
                                "verticals": [
                                    {
                                        "name": "赋能内容",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                                        "block_order": "001.002.001",
                                        "blocks": [
                                            {
                                                "name": "有声幻灯片",
                                                "category": "imagesgallery",
                                                "block_location": "block-v1:FIRAx+1040045+20260807+type@imagesgallery+block@ga",
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "name": "1.3 课程B",
                                "block_location": "block-v1:FIRAx+1040045+20260807+type@sequential+block@sectionb",
                                "block_order": "001.003",
                                "verticals": [
                                    {
                                        "name": "赋能内容",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticalb",
                                        "block_order": "001.003.001",
                                        "blocks": [
                                            {
                                                "name": "有声幻灯片",
                                                "category": "imagesgallery",
                                                "block_location": "block-v1:FIRAx+1040045+20260807+type@imagesgallery+block@gb",
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(
                json.dumps(course_structure, ensure_ascii=False),
                encoding="utf-8",
            )

            observed_counts = {
                "1.2 课程A_水印版.pptx": 2,
                "1.3 课程B_水印版.pptx": 1,
            }
            with patch(
                "plan_batch_jobs.count_presentation_pages",
                side_effect=lambda path: observed_counts[Path(path).name],
            ):
                plan = discover_batch_jobs(
                    root,
                    shards=2,
                    studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+1040045+20260807",
                )

            self.assertTrue(plan["admission_ready"])
            self.assertFalse(plan["studio_publish"]["unresolved_jobs"])
            first = next(job for job in plan["jobs"] if job["name"].startswith("1.2"))
            second = next(job for job in plan["jobs"] if job["name"].startswith("1.3"))
            self.assertEqual("1.2", first["section_id"])
            self.assertEqual(
                "https://studio.uat.firacademy.com/container/block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                first["studio_vertical_url"],
            )
            self.assertEqual("1.3", second["section_id"])
            self.assertEqual(
                "https://studio.uat.firacademy.com/container/block-v1:FIRAx+1040045+20260807+type@vertical+block@verticalb",
                second["studio_vertical_url"],
            )

            targets_path = write_studio_targets_file(plan)
            self.assertEqual(default_studio_targets_path(root), targets_path)
            payload = json.loads(targets_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["ready_for_publish"])
        self.assertEqual(STUDIO_TARGETS_FILENAME, targets_path.name)
        self.assertEqual(str(targets_path), payload["targets_file"])
        self.assertEqual(2, len(payload["targets"]))
        self.assertTrue(payload["course_id_verified"])
        self.assertFalse(payload["course_id_remapped"])
        self.assertEqual("exact_match", payload["route_mode"])

    def test_discover_batch_jobs_stops_on_studio_course_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {"sections": [_section("1.2", "1.2 课程A", 1, ["## A1"])]}
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")
            course_structure = {
                "course_id": "course-v1:FIRAx+1040045+20260807",
                "name": "示例课程",
                "chapters": [
                    {
                        "name": "1. 第一章",
                        "block_location": "block-v1:FIRAx+1040045+20260807+type@chapter+block@chapter1",
                        "block_order": "001",
                        "sections": [
                            {
                                "name": "1.2 课程A",
                                "block_location": "block-v1:FIRAx+1040045+20260807+type@sequential+block@sectiona",
                                "block_order": "001.002",
                                "verticals": [
                                    {
                                        "name": "赋能内容",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                                        "block_order": "001.002.001",
                                        "blocks": [
                                            {
                                                "name": "有声幻灯片",
                                                "category": "imagesgallery",
                                                "block_location": "block-v1:FIRAx+1040045+20260807+type@imagesgallery+block@ga",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(
                json.dumps(course_structure, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("plan_batch_jobs.count_presentation_pages", return_value=1):
                with self.assertRaisesRegex(ValueError, "Batch publish stopped because the target course appears to be wrong"):
                    discover_batch_jobs(
                        root,
                        studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122",
                    )

    def test_discover_batch_jobs_can_remap_imported_course_vertical_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            section_list = {"sections": [_section("1.2", "1.2 课程A", 1, ["## A1"])]}
            (root / "section-list.json").write_text(json.dumps(section_list, ensure_ascii=False), encoding="utf-8")
            course_structure = {
                "course_id": "course-v1:FIRAx+1040045+20260807",
                "name": "示例课程",
                "chapters": [
                    {
                        "name": "1. 第一章",
                        "block_location": "block-v1:FIRAx+1040045+20260807+type@chapter+block@chapter1",
                        "block_order": "001",
                        "sections": [
                            {
                                "name": "1.2 课程A",
                                "block_location": "block-v1:FIRAx+1040045+20260807+type@sequential+block@sectiona",
                                "block_order": "001.002",
                                "verticals": [
                                    {
                                        "name": "赋能内容",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                                        "block_order": "001.002.001",
                                        "blocks": [
                                            {
                                                "name": "有声幻灯片",
                                                "category": "imagesgallery",
                                                "block_location": "block-v1:FIRAx+1040045+20260807+type@imagesgallery+block@ga",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(
                json.dumps(course_structure, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("plan_batch_jobs.count_presentation_pages", return_value=1):
                plan = discover_batch_jobs(
                    root,
                    studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122",
                    allow_course_id_remap=True,
                )

            first = plan["jobs"][0]
            self.assertFalse(plan["studio_publish"]["course_id_verified"])
            self.assertTrue(plan["studio_publish"]["course_id_remapped"])
            self.assertEqual(
                "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                first["source_vertical_block_location"],
            )
            self.assertEqual(
                "block-v1:FIRAx+211181+20251122+type@vertical+block@verticala",
                first["target_vertical_block_location"],
            )
            self.assertEqual(
                "https://studio.uat.firacademy.com/container/block-v1:FIRAx+211181+20251122+type@vertical+block@verticala",
                first["studio_vertical_url"],
            )


if __name__ == "__main__":
    unittest.main()
