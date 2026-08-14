---
name: ppt-to-imagesgallery
description: Convert a PPT file and its full manuscript into an imagesgallery output. Slide image rendering and validation use scripts; AI speech slicing/matching must be done directly in the current Codex session (not via script model calls).
---

# PPT To ImagesGallery

Use bundled scripts for deterministic file generation and validation.  
Do AI slicing/matching in the current session directly.

## Required Skill Dependency

`studio-imagegallery-publish` is a **required companion skill** for any Studio workflow.

- Installing `ppt-to-imagesgallery` for real use means you must also install `studio-imagegallery-publish`.
- `ppt-to-imagesgallery` is responsible for generating local `imagesgallery` outputs.
- `studio-imagegallery-publish` is responsible for pushing those outputs to Studio.
- Do **not** present `studio-imagegallery-publish` as an optional add-on when the user wants any Studio push/publish capability.
- Do **not** tell the user that `ppt-to-imagesgallery` alone can finish a Studio publish flow.

## BL Prerequisite Check (Required Before Workflow)

This skill uses Bailian CLI (`bl`) for TTS synthesis in the audio stage.
Before running the workflow, always do this pre-flight:

1. Check whether `bl` is available:

```bash
bl --version
```

2. If `bl` is missing, install it by following Aliyun official doc:
   `https://bailian.aliyun.com/cli/install.md`
   Use the documented install commands:

```bash
npm install -g bailian-cli
npx skills add modelstudioai/cli --all -g
bl --version
```

3. Check auth status:

```bash
bl auth status
```

4. If API key auth is not configured, ask user for Bailian API key, then login:

```bash
bl auth login --api-key <USER_API_KEY>
```

5. If user explicitly says to skip API key for now:
- Respect that choice.
- Continue all non-BL steps first (render images, in-session slicing, manifest validation).
- When reaching BL-dependent audio synthesis, pause and ask for API key again before running TTS.

## Quick Start

```bash
python3 scripts/build_imagesgallery.py \
  --ppt /path/to/slides.pptx \
  --speech /path/to/manuscript.docx \
  --out /path/to/output \
  --dry-run
```

Output directory:

- `/path/to/output/<ppt_name>/imagesgallery/images/page-001.png` ...
- `/path/to/output/<ppt_name>/imagesgallery/imagesgallery.json` (dry-run placeholder speech; overwrite in-session)

## Workflow

1. Run BL pre-flight check: install (if missing) and verify auth status.
2. Convert PPT to page images.
3. In current Codex session, match/slice manuscript to per-page speech in order.
4. Write final `imagesgallery.json` with real speech content.
5. Validate JSON shape and manuscript continuity.
6. Synthesize per-page speech to MP3, merge into one full MP3 with 1s gap between segments, and export continuous timestamps.
7. Generate `preview.html` in output for voiced PPT playback preview (auto page switch + subtitle sync).
8. `studio-imagegallery-publish` is a hard dependency for Studio push/publish. If the user has not installed it yet, install it from `https://github.com/hongshanxueyuan/studio-imagegallery-publish` first, then use that skill for the publish flow.
9. If running on Windows, check `references/windows_troubleshooting.md` first when any environment/tool issue appears.

Hard boundary for Studio publish:

- When publish/push to Studio is requested, do **not** say you will "connect browser automation", "open browser and click through", or use any browser/chrome automation as the publish implementation.
- Studio publish in this workflow must go strictly through the `studio-imagegallery-publish` skill and its scripts/API flow.
- Browser automation is not an allowed fallback for publish in this skill, even if browser tools are available in the session.
- Do **not** read or preload browser-use/browser/chrome skill instructions for this workflow. Those browser skills are irrelevant here and can bias the plan away from the required publish skill.

## Input Discovery Rules (Important for NotebookLM / nlm-course-slides folders)

When the user points this skill at a folder exported by NotebookLM / `nlm-course-slides`, do **not** broadly treat every adjacent JSON file as workflow state or proof that processing is already done.

Always apply this discovery order first:

1. Find real content inputs by pairing same-stem files:
   - presentation: `.pptx` / `.ppt` / `.pdf`
   - manuscript: `.docx` / `.md` / `.markdown` / `.txt`
2. Ignore report/status JSON during content discovery:
   - `course-json-report.json`
   - `create-report*.json`
   - `finalize-report*.json`
   - `upload-report.json`
3. Treat `course.json`, `section-list.json`, `fira_course-*.json` as **optional structure files only**:
   - do not use them to decide whether PPT processing is already complete
   - only read them when the user explicitly wants Studio target resolution / batch publish mapping
4. Prefer deterministic planning via:

```bash
python scripts/plan_batch_jobs.py --root <folder>
```

This prevents Codex from being distracted by unrelated report JSON files in the same directory.

Extra guardrails for mixed folders:

- Treat `course-json-report.json`, `create-report*.json`, `finalize-report*.json`, and `upload-report.json` as upstream audit/report artifacts only.
- They are **not** `imagesgallery` manifests, **not** current-run temporary files, **not** publish plans, and **not** evidence that this folder already contains reusable voiced PPT outputs.
- In normal `批量生成imagegallery` / `批量生成并推送` flow, do **not** open or analyze those report JSON files at all unless the user explicitly asks to investigate those reports.
- Do **not** infer conclusions such as "已经有现成 manifest", "这些材料之前被批量上传过", or "可以直接复用已有 imagegallery 产物链路" from those report JSON files.
- For normal batch flow, the only JSON files worth reading are:
  - `section-list.json`
  - `fira_course-*.json`
  and only after the user has asked for Studio target mapping / batch publish planning.

## Command Interface

```bash
python3 scripts/build_imagesgallery.py \
  --ppt <file.ppt|file.pptx> \
  --speech <file.docx|file.md|file.txt> \
  --out <dir> \
  --dry-run
```

Arguments:

- `--ppt`: input slide deck.
- `--speech`: full manuscript that matches the PPT; supports `.docx`/`.md`/`.txt` (recommended: `.docx` from Word, including table content).
- `--out`: output base directory; script writes to `<out>/<ppt_name>/imagesgallery`.
- `--dry-run`: compatibility flag; script always generates images + manifest skeleton only.

## Ops Input Standard (Recommended)

For operation teams, use this stable workflow:

1. Prepare one PPT file and one full-script Word file (`.docx`) in the same folder.
2. Keep rich text in Word (headings, bold, bullet lists); do not export to plain `.txt`.
3. Run the skill with `--speech` pointing to the `.docx`.

Why:

- Plain `.txt` drops formatting.
- `.docx` preserves structure better, and the script converts major formatting to Markdown-like text for later subtitle rendering (headings, bold/italic, lists, and tables).

## Manuscript Hygiene

- `read_manuscript()` now strips a **duplicate document-level title** that appears **before** the first pagination marker when page 1 repeats the same title.
- This is common in NotebookLM-generated paginated Markdown such as:
  - line 1: file-level heading like `# 2.4 ...`
  - line 3: `- 第 1 页`
  - page 1 heading: `# ...`
- Treat the pre-pagination duplicate as file metadata, not as narration content for cover/page 1.
- Only strip it when the pre-page block is a single heading and it clearly matches the page-1 heading; otherwise preserve the original preface text.

## Session Matching Rules

- Do not call `bl omni` for slicing.
- Use the current Codex session model to assign manuscript segments to each page.
- **Mandatory:** read `references/prompt_full_speech_session.md` verbatim and use it as the single source of slicing constraints.
- **Forbidden:** do not invent, rewrite, summarize, or "optimize" another slicing prompt in place of `references/prompt_full_speech_session.md`.
- This skill is atomic and self-contained: do not depend on any external repo paths or files at runtime.
- `references/prompt_full_speech_session.md` is the in-skill canonical prompt snapshot for full-manuscript page slicing.
- If slicing behavior needs to change, update this skill's own prompt file first, then update this SKILL.md accordingly.
- If the manuscript already contains page markers, treat them as **soft ordering anchors** only: final slicing must still follow the actual PPT screenshots, allowing local merge/split when NotebookLM or another LLM has re-grouped content across slides.
- Preserve manuscript Markdown structure when writing page `speech`: keep headings, blank-line paragraph boundaries, and list markers from the source manuscript. Do not run page output through alignment-only normalization before saving it back to `imagesgallery.json`.
- Run as full-deck one-shot slicing (all page images + full manuscript in one request).
- Model output must be strict JSON only:
  - `pages: [{page_number, speech}]`
- `page_number` must be continuous from `1..N`.

## Session Prompt Usage

Recommended process for better slicing accuracy:

1. Read `references/prompt_full_speech_session.md` in full and paste/follow its constraints directly.
2. Attach all page images in order (`page-001.png ... page-NNN.png`).
3. Provide the full manuscript in one request (not remaining-tail batches).
4. Ask model to return strict JSON only (no prose/code fence):
   - `pages: [{page_number, speech}]`
5. Post-check with `scripts/align_manuscript.py` and then write final manifest.

## Batch Mode

When the user says things like `批量生成imagegallery` / `批量生成并推送` / `batch generate` / `batch publish`, switch to batch workflow instead of handling the folder as one large mixed context.

Recommended process:

1. Run the batch planner first:

```bash
python scripts/plan_batch_jobs.py --root <folder> --shards 3
```

2. Use only the returned `jobs[]` as the source of truth for batch work.
3. Do not let agents rediscover files by rescanning the whole folder once the plan is fixed.
4. For plain batch generation, ignore `candidate_structure_json`.
5. For batch Studio publish, the user must provide a **Studio course URL** like:

```text
https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122
```

6. Before any batch publish action, generate a confirmation file first:

```bash
python scripts/plan_batch_jobs.py \
  --root <folder> \
  --shards 3 \
  --studio-course-url <course_url> \
  --write-studio-targets
```

This writes:

- `<out_base>/_batch/imagegallery-push-studio-targets.json`

If the planner reports that the `studio-course-url` course id does not match `fira_course-*.json`, stop and ask the user whether the target course is an imported copy of the same source course.

In a combined `批量生成并推送` / `batch generate and publish` request, this mismatch is a **hard stop for the entire batch workflow**, not only for the final publish step:

- do **not** continue to generate local `imagesgallery` outputs
- do **not** continue to synthesize audio
- do **not** continue to prepare or execute publish requests
- wait for explicit user confirmation first, then restart the batch workflow from planning

Only after the user explicitly confirms that scenario may you rerun the planner with:

```bash
python scripts/plan_batch_jobs.py \
  --root <folder> \
  --shards 3 \
  --studio-course-url <course_url> \
  --allow-course-id-remap \
  --write-studio-targets
```

7. If the planner succeeds without a course-id mismatch stop, do **not** interrupt the user just to confirm that file:
   - print the generated file's **absolute clickable path** so the user can open it anytime
   - treat that file as a visibility / spot-check artifact, not as a blocking approval gate
   - continue the workflow automatically in the same task
8. Default execution mode is `三 agent 执行`:
   - this default applies to the **local generation / slicing / validation / TTS** stage only
   - if multi-agent tools are available, split work into **at most 3 agents** using the planner's shard list
   - if multi-agent tools are unavailable in the current session, automatically fall back to sequential processing
   - do **not** stop to ask the user to choose `顺序执行` vs `三 agent 执行` during the normal success path
9. Final Studio publish in batch mode must still run **sequentially**, even when local generation used 3 agents:
   - publish one deck at a time
   - do **not** publish multiple decks to Studio concurrently with the same operator account/session
   - if a publish step fails with an auth/session error such as `401`, `Not Login yet`, csrf/session invalidation, or similar login errors, retry that publish step with session refresh
   - retry at most **4** times with a short delay of a few seconds between attempts
10. For batch Studio publish, consult `candidate_structure_json` only **after** jobs are fixed, and only to resolve course section / Studio target mapping.

Batch planning boundaries:

- Before the plan is fixed, only inspect:
  - same-stem PPT/manuscript pairs
  - optional `section-list.json`
  - optional `fira_course-*.json`
- Do **not** open `upload-report.json`, `course-json-report.json`, `create-report*.json`, or `finalize-report*.json` as part of normal batch planning.
- Do **not** load browser/chrome skill docs while planning batch generate/publish; they are unrelated to the required flow and can cause the session to drift.

Batch context isolation rules:

- Each agent/job must receive explicit **absolute paths** for:
  - `ppt`
  - `speech`
  - output base directory
  - generated `manifest`
  - current deck image directory
- Never reason about two decks' slide images in the same slicing request.
- When attaching or reading images, use full absolute paths like `...\\deck-a\\imagesgallery\\images\\page-001.png`, not only `page-001.png`.
- Before starting the next deck, restate the current deck's absolute paths so the session context is reset around the new pair.

Batch Studio route rules:

- Use `section-list.json` to map file names / section ids such as `1.2`, `1.3`, `4.2` to course sections.
- Use `fira_course-*.json` to resolve the real source section/vertical structure and the exact vertical `block_location`.
- The planner must choose the primary publish target vertical by preferring the vertical that contains:
  - `imagesgallery` block category
  - or block name like `有声幻灯片`
  - or vertical name like `赋能内容`
- If the user explicitly confirms an imported-course remap, rewrite only the course-id prefix in the chosen vertical locator using the `--studio-course-url` course key, and preserve the original `+type@vertical+block@...` suffix.
- The generated targets file must surface both `source_vertical_block_location` and `target_vertical_block_location`, plus a route mode/remap flag, so the user can verify the rewritten route before publish.
- Do **not** guess Studio targets from filename alone once the structure JSONs are available.
- The generated targets file is for human visibility and optional spot-checking; in the normal non-mismatch path it should not block auto-execution.
- After the publish task finishes, always list the final clickable Studio URLs for the created `imagesgallery` blocks in the closing response so operators can open them for manual inspection and fine-tuning.

## Validation Rules

Use two-stage schema checks:

- Stage A (after session slicing): `imagesgallery.json` should contain
  - `version`,
  - `source_ppt`,
  - `source_speech`,
  - `items[{page_number,image,speech}]`.
- Stage B (after audio synthesis script rewrite): `imagesgallery.json` should contain
  - `version`,
  - `source_ppt`,
  - `source_speech`,
  - `audio`,
  - `items[{page,image,subtitle,start,end}]` where `start/end` are milliseconds.
- Continuity check must pass with `scripts/align_manuscript.py` (`strict_consume_pages`).
- Final manuscript tail must not contain substantive unconsumed text.

## Studio Publish Dependency

When the user explicitly says `推送到studio` / `推送到 Studio` / `发布到 Studio` / `publish to Studio`, treat that as a dependency handoff:

1. Treat `studio-imagegallery-publish` as required, not optional.
2. Check whether `studio-imagegallery-publish` is already installed under `$CODEX_HOME/skills/studio-imagegallery-publish`.
3. If it is missing, use the `skill-installer` skill and install it from:
   - `https://github.com/hongshanxueyuan/studio-imagegallery-publish`
4. After install succeeds, read that skill's own `SKILL.md` and follow it for the actual Studio publish work.
5. Do not reimplement Studio publish logic inside `ppt-to-imagesgallery`; reuse `studio-imagegallery-publish`.
6. When explaining the workflow to the user, say it clearly as:
   - use `ppt-to-imagesgallery` to generate local `imagesgallery`
   - use `studio-imagegallery-publish` to push to Studio

Notes:

- When the user asks how to install this workflow, explicitly tell them to install **both** skills together:
  - `https://github.com/hongshanxueyuan/ppt-to-imagesgallery`
  - `https://github.com/hongshanxueyuan/studio-imagegallery-publish`
- Only trigger this dependency flow when the user explicitly asks to publish/push to Studio.
- Prefer checking/installing before asking the user for Studio credentials, so the publish workflow can continue cleanly in one pass.
- Do not use browser automation, Chrome automation, or manual click-through as a substitute publish path. If `studio-imagegallery-publish` is unavailable or blocked, stop and report that publish cannot continue yet.
- Studio publish expects finalized stage-B `imagesgallery.json` with `audio` and per-page `subtitle/start/end`.
- In batch flows, "三 agent" only applies to local generation. The final Studio publish stage must hand off to `studio-imagegallery-publish` and run sequentially to avoid login/session conflicts.
- For **batch** Studio publish, the `studio-course-url` must normally match the course id recorded in `fira_course-*.json` (`course-v1:ORG+COURSE+RUN`); if `ORG`, `COURSE`, or `RUN` differs, stop immediately and tell the user the course URL may be wrong.
- Exception: if the user explicitly confirms that the target Studio course is a package-imported copy of the source course, rerun the planner with `--allow-course-id-remap`, which rewrites only the course-id prefix in vertical locators while preserving the original `+type@vertical+block@...` suffix.
- Without that explicit confirmation, do not continue any later batch actions after a course-id mismatch, including local generation, audio synthesis, or publish requests, because batch push to the wrong course is high-risk.

## Validation Snippet

Run after writing final JSON:

```bash
python3 - <<'PY'
import json
from pathlib import Path
import sys

root = Path(".codex/skills/ppt-to-imagesgallery/scripts").resolve()
sys.path.insert(0, str(root))
from align_manuscript import normalize_for_alignment, strict_consume_pages, is_substantive_gap
from build_imagesgallery import read_manuscript

manifest = Path("/path/to/output/<ppt_name>/imagesgallery/imagesgallery.json")
data = json.loads(manifest.read_text(encoding="utf-8"))
speech_path = Path(data["source_speech"])
manuscript = normalize_for_alignment(read_manuscript(speech_path))
# Supports both stage schemas:
pages = [
    item.get("speech", item.get("subtitle", ""))
    for item in data["items"]
]
res = strict_consume_pages(manuscript, pages, start_cursor=0)
tail = manuscript[res.cursor:]
if is_substantive_gap(tail):
    raise SystemExit("validation failed: unconsumed substantive tail")
print("OK: continuity validated")
PY
```

## Resources

- `scripts/build_imagesgallery.py`: rendering + manifest skeleton generation.
- `scripts/plan_batch_jobs.py`: deterministic batch planning for mixed folders containing deck/manuscript pairs plus report JSON files.
- `scripts/align_manuscript.py`: manuscript normalization and continuity checks.
- `scripts/synthesize_imagesgallery_audio.py`: per-segment TTS, merged MP3, and timeline timestamps.
- `references/prompt_full_speech_session.md`: default full-deck session slicing prompt.
- `references/windows_troubleshooting.md`: Windows known issues and fixes for ops runs.

## Windows Notes (Important)

To reduce repeated operator failures on Windows:

- If `soffice` is missing, `build_imagesgallery.py` now auto-falls back to PowerPoint COM export for `.ppt/.pptx`.
- TTS synthesis now uses `bl ... --text-file` per page instead of `--text`.
- Subprocess output decoding is forced to UTF-8 to avoid common GBK decode crashes.

For full troubleshooting and command-level checks, use:

- `references/windows_troubleshooting.md`

## Audio Synthesis

After `imagesgallery.json` is finalized:

```bash
python3 scripts/synthesize_imagesgallery_audio.py \
  --manifest /path/to/output/<ppt_name>/imagesgallery/imagesgallery.json \
  --voice longxiaochun_v3 \
  --rate 1.1 \
  --gap-seconds 1 \
  --final-name full_speech.mp3 \
  --timeline-name speech_timestamps.json
```

Outputs:

- `/path/to/output/<ppt_name>/imagesgallery/audio/segments/page-001.mp3` ...
- `/path/to/output/<ppt_name>/imagesgallery/audio/full_speech.mp3`
- `/path/to/output/<ppt_name>/imagesgallery/audio/speech_timestamps.json`
- `/path/to/output/<ppt_name>/imagesgallery/preview.html`

Timestamp rule:

- Final manifest uses `items[i].start` / `end` in milliseconds.
- `end` includes trailing inter-segment gap for all non-last segments.
- Therefore adjacent items satisfy: `items[i].end == items[i+1].start`.

Preview behavior:

- Click play to start narration.
- Slide auto-switches by `items[].start/end` timestamps.
- Left thumbnail list supports click-to-seek.
- Subtitle panel shows current page `subtitle`.
