---
name: ppt-to-imagesgallery
description: 处理本地 NLM 工作目录里的 PPT 子集，按 `section-list.json` 生成 imagesgallery 产物。
disable-model-invocation: true
---

# PPT To ImagesGallery

这个 skill 现在只教一种主路径：NLM 工作目录里的 batch-only 下游流程。

运行时的唯一语音来源是 `section-list.json` 里的 `page_content` 和 `page_count`。
本地 `.ppt` / `.pptx` 决定这次运行哪些 deck 在范围内。
工作目录里的 `.md` 可能还在，但它不再属于这个 skill 的运行时输入合同。

## 必需依赖

`studio-imagegallery-publish` 是所有 Studio 推送场景的必需配套 skill。

- 生成本地 `imagesgallery` 用这个 skill。
- 推送到 Studio 必须切换到 `studio-imagegallery-publish`。
- 不要把浏览器自动化当成 Studio 推送兜底。

## BL 前置检查

音频阶段依赖百炼 CLI `bl`。

1. 检查本机是否已安装 `bl`。

```bash
bl --version
```

2. 检查认证状态。

```bash
bl auth status
```

3. 如果缺少 `bl`，按阿里云官方文档安装。

```bash
npm install -g bailian-cli
npx skills add modelstudioai/cli --all -g
bl --version
```

4. 如果还没有配置 API Key，再向用户索取并登录。

```bash
bl auth login --api-key <USER_API_KEY>
```

如果用户明确说先跳过 API Key，就先停在音频之前；不要阻塞 preflight、图片渲染或 manifest 生成。

## 主流程

1. 先跑 batch planner。

```bash
python scripts/plan_batch_jobs.py --root <folder> --shards 3
```

2. 只以 planner 产出的 `jobs[]` 为准。
   planner 会做 4 件事:
   - 发现本地 `.ppt` / `.pptx`
   - 把本地 deck 和 `section-list.json` 做唯一匹配
   - 跑 whole-batch preflight
   - 只有 admission clean 才分 shard

3. 把 `section-list.json` 里没有本地 PPT 的 section 视为正常忽略。
4. 把任何无法唯一匹配到 `section-list` 的本地 PPT 视为 admission failure。
5. 只要 preflight 有一个失败，整批就停下。
   这时不会开始渲染图片、写 stage-A manifest、合成音频、生成 preview，或继续 Studio 后续动作。
6. 如果 preflight clean，再逐个 admitted deck 继续本地生成：
   - 用 deck 对应的 PPT
   - 用该 deck 匹配到的 `section-list` 记录
   - 直接从 `page_content` 生成 stage-A manifest

## 单 deck 构建

`scripts/build_imagesgallery.py` 现在是单 deck 的 deterministic build seam。

- 输入是一个本地 `.ppt` / `.pptx` 和一个已经解析好的单 section JSON。
- 输出是图片和 stage-A `imagesgallery.json`。
- stage-A `items[].speech` 直接来自 `page_content`。
- 旧的 manuscript-path 字段已经从 manifest 合同里移除。

命令接口:

```bash
python scripts/build_imagesgallery.py \
  --ppt <deck.pptx> \
  --section-json <resolved-section.json> \
  --out <out-base> \
  --dry-run
```

`resolved-section.json` 至少要包含:

- `page_count`
- `page_content`
- 建议保留 `section_id` / `section_title` / `output_name`

## 预检 Preflight

preflight 是 whole-batch admission gate，不是 warning pass。

它至少检查:

- `page_count` 是否存在且为正整数
- `page_content` 是否存在、是数组、长度是否等于 `page_count`
- 每个 page body 是否非空
- 真实 PPT 页数是否等于 `page_count`

失败时会写:

- `_batch/imagegallery-preflight-report.json`

如果需要解释这个报告或修复建议，读 `references/preflight_repair.md`。

## 音频与预览

stage-A manifest 就绪后，再跑音频脚本:

```bash
python scripts/synthesize_imagesgallery_audio.py \
  --manifest /path/to/imagesgallery.json \
  --voice-preset 女声 \
  --model cosyvoice-v2 \
  --rate 1.1 \
  --gap-seconds 1
```

这个脚本会:

- 逐页 TTS
- 合并 `full_speech.mp3`
- 写时间轴
- 重写成 stage-B manifest
- 生成 `preview.html`

声音配置合同统一用下面这组术语:

- `run 默认声音`
  通过命令行传 `--voice-preset 女声|男声`，或者传显式 `--voice <voice_id>`。
- `单个 PPT 声音覆盖`
  在 `imagesgallery.json` 顶层加 `voice_preset` 或显式 `voice`。
- `page 声音覆盖`
  在某个 `items[]` 上加 `voice_preset` 或显式 `voice`。

解析顺序固定是:

- `page 声音覆盖 > 单个 PPT 声音覆盖 > run 默认声音 > 默认女声`

一期只支持两个预设:

- `女声 -> longxiaochun_v2`
- `男声 -> longshu_v2`

冲突规则:

- 只在同一对象内部判定冲突
- 同一 `run 默认声音`、同一 `单个 PPT 声音覆盖` 或同一 `page 声音覆盖` 里，如果 `voice_preset` 和显式 `voice` 解析到不同 voice id，整次 run 直接停止
- 如果预设和显式 `voice` 实际解析到同一个 voice id，不算冲突
- 不同层之间的不同值属于合法覆盖，不算冲突

## 批量 Studio 规划

只有在用户明确要求批量推送到 Studio 时，才读取 `fira_course-*.json` 并继续 route planning。

命令接口:

```bash
python scripts/plan_batch_jobs.py \
  --root <folder> \
  --shards 3 \
  --studio-course-url <course_url> \
  --write-studio-targets
```

规则:

- 课程 URL 和 `fira_course-*.json` 的 course id 不匹配时，整个批量流程硬停。
- 只有用户明确确认“这是导入课程副本”时，才允许 `--allow-course-id-remap`。
- 本地生成阶段最多 3 个并行 shard。
- 最终 Studio 推送必须顺序执行。
- 收尾时始终返回目标 vertical 的可点击 Studio URL。

## References

- `references/preflight_repair.md`: 仅在 preflight failed 时读取
- `references/windows_troubleshooting.md`: 仅在 Windows 环境或工具链异常时读取
- `references/preview_template.html`: preview 生成模板，不用手改
