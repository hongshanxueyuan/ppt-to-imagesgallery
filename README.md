# PPT 转有声幻灯片使用说明

这个 skill 现在面向 NLM 工作目录里的 batch-only 下游流程。
如果你是维护者，细节请看 [SKILL.md](./SKILL.md)。

## 安装

先让 Codex 安装这两个 skill：

- `https://github.com/hongshanxueyuan/ppt-to-imagesgallery`
- `https://github.com/hongshanxueyuan/studio-imagegallery-publish`

如果后面要推送到 Studio，`studio-imagegallery-publish` 不是可选项。

## 先准备什么

同一个目录下，准备这些内容：

- 本地 `.pptx` / `.ppt` 文件
- 上游生成好的 `section-list.json`
- 如果后面要推送到 Studio，再准备课程地址和账号

这里最重要的变化是：

- 本地 PPT 子集决定这次 run 的 scope
- `section-list.json` 决定顺序、`page_count` 和 `page_content`
- `.md` 不再是这个 skill 的运行时输入合同

## 怎么说给 Codex

### 场景一：先做本地生成

```text
用 ppt-to-imagesgallery 处理这个 NLM 工作目录，先做 preflight，再生成本地 imagegallery
```

Codex 会先跑整批 preflight。
如果 preflight 失败，它会停在 `_batch/imagegallery-preflight-report.json`，不会继续渲染、音频或 preview。
如果 preflight 通过，才会继续生成图片、manifest、音频和 preview。

### 场景二：批量生成并准备 Studio 路由

```text
用 ppt-to-imagesgallery 处理这个 NLM 工作目录，并为 Studio 批量推送准备目标路由
```

如果需要批量推送，再额外提供课程地址：

```text
课程地址是：https://studio.xxx.com/course/course-v1:ORG+COURSE+RUN
```

Codex 会先生成路由目标文件，再继续后续流程。

## 你会看到什么

- planner 结果
- 如有失败时的 `_batch/imagegallery-preflight-report.json`
- 每个 deck 的 `imagesgallery/imagesgallery.json`
- 音频目录和 `preview.html`
- 如果做 Studio 规划，还会有 `_batch/imagegallery-push-studio-targets.json`

## 批量时重点留意

- 本地每个 PPT 是否都唯一匹配到了一个 `section-list` 记录
- `page_count` 和真实 PPT 页数是否一致
- 课程地址是否正确
- 生成的 Studio 目标 vertical 是否符合预期

## 音频阶段怎么配声音

音频脚本统一用这些术语：

- `run 默认声音`
  用命令行传 `--voice-preset 女声|男声`，或显式 `--voice <voice_id>`。
- `单个 PPT 声音覆盖`
  在当前 `imagesgallery.json` 顶层写 `voice_preset` 或显式 `voice`。
- `page 声音覆盖`
  在某个 `items[]` 里写 `voice_preset` 或显式 `voice`。

解析顺序固定是 `page 声音覆盖 > 单个 PPT 声音覆盖 > run 默认声音 > 默认女声`。
一期只支持 `男声` / `女声` 两个预设；显式 `voice` 会直接透传给 TTS。
如果同一层里预设和显式 `voice` 解析到不同 voice id，整次 run 会直接停止。

## 常见建议

- 先拿一两个 section 小范围试跑
- preflight fail 时先修 `section-list` 或本地 PPT，再整批重跑
- 涉及本地生成时，明确说出 `ppt-to-imagesgallery`
- 涉及推送到 Studio 时，明确说出 `studio-imagegallery-publish`
- 批量推送结束后，保留 Codex 给出的目标 vertical URL 方便人工复核
