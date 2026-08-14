import json
import tempfile
import unittest
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from plan_batch_jobs import (  # noqa: E402
    STUDIO_TARGETS_FILENAME,
    classify_json_file,
    default_studio_targets_path,
    discover_batch_jobs,
    write_studio_targets_file,
    _normalize_batch_name,
)


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

    def test_discover_batch_jobs_ignores_reports_and_builds_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.1 课程A.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.1 课程A.md").write_text("md", encoding="utf-8")
            (root / "1.2 课程B.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程B.docx").write_text("docx", encoding="utf-8")
            (root / "1.3 只有PPT.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.4 只有讲稿.md").write_text("md", encoding="utf-8")
            (root / "upload-report.json").write_text("{}", encoding="utf-8")
            (root / "create-report-worker-daba-test.json").write_text("{}", encoding="utf-8")
            (root / "course.json").write_text("{}", encoding="utf-8")
            (root / "section-list.json").write_text("{}", encoding="utf-8")
            (root / "notes.json").write_text("{}", encoding="utf-8")

            plan = discover_batch_jobs(root, shards=2)

        self.assertEqual(2, len(plan["jobs"]))
        self.assertEqual(2, len(plan["shards"]))
        self.assertEqual(1, len(plan["shards"][0]["jobs"]))
        self.assertEqual(1, len(plan["shards"][1]["jobs"]))
        self.assertEqual(2, len(plan["ignored_report_json"]))
        self.assertEqual(2, len(plan["candidate_structure_json"]))
        self.assertEqual(1, len(plan["other_json"]))
        self.assertEqual(1, len(plan["unmatched_presentations"]))
        self.assertEqual(1, len(plan["unmatched_speeches"]))
        self.assertTrue(any(job["speech"].endswith(".docx") for job in plan["jobs"]))

    def test_discover_batch_jobs_derives_studio_vertical_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程A_水印版.md").write_text("md", encoding="utf-8")
            (root / "1.3 课程B_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.3 课程B_水印版.md").write_text("md", encoding="utf-8")

            section_list = {
                "sections": [
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "resource_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                    },
                    {
                        "section_id": "1.3",
                        "section_title": "1.3 课程B",
                        "resource_title": "1.3 课程B",
                        "output_name": "1.3 课程B.pptx",
                    },
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
                                    },
                                    {
                                        "name": "在线训战",
                                        "block_location": "block-v1:FIRAx+1040045+20260807+type@vertical+block@traina",
                                        "block_order": "001.002.002",
                                        "blocks": [{"name": "文字讲解", "category": "html"}],
                                    },
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
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(json.dumps(course_structure, ensure_ascii=False), encoding="utf-8")

            plan = discover_batch_jobs(
                root,
                shards=2,
                studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+1040045+20260807",
            )

            self.assertEqual(2, len(plan["jobs"]))
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
            self.assertFalse(payload["confirmation_required"])
            self.assertFalse(payload["execution_mode_confirmation_required"])
            self.assertTrue(payload["targets_review_optional"])
            self.assertTrue(payload["auto_continue_after_targets"])
            self.assertEqual("parallel", payload["default_execution_mode"])
            self.assertEqual(3, payload["default_agent_count"])
            self.assertEqual("parallel", payload["local_generation_execution_mode"])
            self.assertEqual(3, payload["local_generation_agent_count"])
            self.assertEqual("sequential", payload["publish_execution_mode"])
            self.assertEqual(1, payload["publish_agent_count"])
            self.assertEqual(4, payload["publish_auth_retry_max_retries"])
            self.assertEqual(3, payload["publish_auth_retry_delay_seconds"])
            self.assertEqual(3, payload["max_agent_count"])
            self.assertTrue(payload["ready_for_publish"])
            self.assertEqual(STUDIO_TARGETS_FILENAME, targets_path.name)
            self.assertEqual(str(targets_path), payload["targets_file"])
            self.assertEqual(2, len(payload["targets"]))
            self.assertEqual(["sequential", "parallel"], [mode["mode"] for mode in payload["execution_modes"]])
            self.assertEqual(2, len(payload["shards"]))
            self.assertTrue(payload["course_id_verified"])
            self.assertFalse(payload["course_id_remapped"])
            self.assertEqual("exact_match", payload["route_mode"])
            self.assertFalse(plan["studio_publish"]["confirmation_required"])
            self.assertFalse(plan["studio_publish"]["execution_mode_confirmation_required"])
            self.assertEqual("parallel", plan["studio_publish"]["default_execution_mode"])
            self.assertEqual(3, plan["studio_publish"]["default_agent_count"])
            self.assertEqual("parallel", plan["studio_publish"]["local_generation_execution_mode"])
            self.assertEqual("sequential", plan["studio_publish"]["publish_execution_mode"])
            self.assertEqual(4, plan["studio_publish"]["publish_auth_retry_max_retries"])
            self.assertEqual(3, plan["studio_publish"]["publish_auth_retry_delay_seconds"])

    def test_discover_batch_jobs_stops_on_studio_course_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程A_水印版.md").write_text("md", encoding="utf-8")
            section_list = {
                "sections": [
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "resource_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                    }
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
                            }
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(json.dumps(course_structure, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Batch publish stopped because the target course appears to be wrong"):
                discover_batch_jobs(
                    root,
                    studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122",
                )

    def test_discover_batch_jobs_can_remap_imported_course_vertical_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.2 课程A_水印版.pptx").write_text("ppt", encoding="utf-8")
            (root / "1.2 课程A_水印版.md").write_text("md", encoding="utf-8")
            section_list = {
                "sections": [
                    {
                        "section_id": "1.2",
                        "section_title": "1.2 课程A",
                        "resource_title": "1.2 课程A",
                        "output_name": "1.2 课程A.pptx",
                    }
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
                            }
                        ],
                    }
                ],
            }
            (root / "fira_course-v1_FIRAx_1040045_20260807.json").write_text(json.dumps(course_structure, ensure_ascii=False), encoding="utf-8")

            plan = discover_batch_jobs(
                root,
                studio_course_url="https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122",
                allow_course_id_remap=True,
            )

            self.assertEqual("course-v1:FIRAx+1040045+20260807", plan["studio_publish"]["source_course_key"])
            self.assertEqual("course-v1:FIRAx+211181+20251122", plan["studio_publish"]["target_course_key"])
            self.assertFalse(plan["studio_publish"]["course_id_verified"])
            self.assertTrue(plan["studio_publish"]["course_id_remapped"])
            self.assertTrue(plan["studio_publish"]["course_id_remap_confirmed"])
            self.assertEqual("course_id_remapped", plan["studio_publish"]["route_mode"])

            first = plan["jobs"][0]
            self.assertTrue(first["course_id_remapped"])
            self.assertEqual("course_id_remapped", first["route_mode"])
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

            targets_path = write_studio_targets_file(plan)
            payload = json.loads(targets_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["course_id_verified"])
            self.assertTrue(payload["course_id_remapped"])
            self.assertTrue(payload["course_id_remap_confirmed"])
            self.assertEqual("course_id_remapped", payload["route_mode"])
            self.assertFalse(payload["confirmation_required"])
            self.assertFalse(payload["execution_mode_confirmation_required"])
            self.assertEqual("parallel", payload["default_execution_mode"])
            self.assertEqual("sequential", payload["publish_execution_mode"])
            self.assertEqual(4, payload["publish_auth_retry_max_retries"])
            self.assertEqual(str(targets_path), payload["targets_file"])
            self.assertEqual(
                "block-v1:FIRAx+1040045+20260807+type@vertical+block@verticala",
                payload["targets"][0]["source_vertical_block_location"],
            )
            self.assertEqual(
                "block-v1:FIRAx+211181+20251122+type@vertical+block@verticala",
                payload["targets"][0]["target_vertical_block_location"],
            )
            self.assertTrue(payload["targets"][0]["course_id_remapped"])
            self.assertEqual("course_id_remapped", payload["targets"][0]["route_mode"])


if __name__ == "__main__":
    unittest.main()
