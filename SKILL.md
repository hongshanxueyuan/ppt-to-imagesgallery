---
name: ppt-to-imagesgallery
description: 将 PPT 与整篇讲稿转换为 imagesgallery 产物。页面图片渲染与校验使用脚本；AI 口播切分/匹配必须直接在当前 Codex 会话中完成，不能通过脚本调用模型。
---

# PPT 转 ImagesGallery

使用仓库内置脚本完成可复现的文件生成与校验。  
AI 切稿/匹配必须直接在当前会话里完成。

## 必需技能依赖

`studio-imagegallery-publish` 是所有 Studio 工作流的**必需配套 skill**。

- 实际安装 `ppt-to-imagesgallery` 时，必须同时安装 `studio-imagegallery-publish`。
- `ppt-to-imagesgallery` 负责生成本地 `imagesgallery` 产物。
- `studio-imagegallery-publish` 负责把这些产物推送到 Studio。
- 当用户要做 Studio 推送/发布时，**不要**把 `studio-imagegallery-publish` 说成可选附加项。
- **不要**告诉用户仅靠 `ppt-to-imagesgallery` 就能完成 Studio 发布全流程。

## BL 前置检查（开始工作前必须执行）

这个 skill 在音频阶段依赖百炼 CLI（`bl`）进行 TTS 合成。  
开始流程前，必须先完成以下检查：

1. 检查本机是否已安装 `bl`：

```bash
bl --version
```

2. 如果缺少 `bl`，按阿里云官方文档安装：  
   `https://bailian.aliyun.com/cli/install.md`  
   使用文档里的安装命令：

```bash
npm install -g bailian-cli
npx skills add modelstudioai/cli --all -g
bl --version
```

3. 检查认证状态：

```bash
bl auth status
```

4. 如果还没有配置 API Key 认证，向用户索取百炼 API Key，然后登录：

```bash
bl auth login --api-key <USER_API_KEY>
```

5. 如果用户明确表示暂时跳过 API Key：
- 尊重用户这个选择。
- 先继续执行所有不依赖 BL 的步骤（渲染图片、会话内切稿、manifest 校验）。
- 到了依赖 BL 的音频合成阶段，再暂停并重新向用户索取 API Key。

## 快速开始

```bash
python3 scripts/build_imagesgallery.py \
  --ppt /path/to/slides.pptx \
  --speech /path/to/manuscript.docx \
  --out /path/to/output \
  --dry-run
```

输出目录：

- `/path/to/output/<ppt_name>/imagesgallery/images/page-001.png` ...
- `/path/to/output/<ppt_name>/imagesgallery/imagesgallery.json`（dry-run 阶段是占位 `speech`，后续要在会话里覆写）

## 工作流

1. 先完成 BL 前置检查：必要时安装，并确认认证状态。
2. 把 PPT 转成页面图片。
3. 在当前 Codex 会话里，按顺序把整稿匹配/切分为逐页 `speech`。
4. 写入最终版 `imagesgallery.json`。
5. 校验 JSON 结构与讲稿连续性。
6. 逐页合成 MP3，再按 1 秒间隔拼成完整 MP3，并导出连续时间轴。
7. 在输出目录里生成 `preview.html`，用于预览有声幻灯片（自动翻页 + 字幕同步）。
8. `studio-imagegallery-publish` 是 Studio 推送/发布的硬依赖。如果用户还没安装，先从 `https://github.com/hongshanxueyuan/studio-imagegallery-publish` 安装，再把推送工作交给那个 skill。
9. 如果运行环境是 Windows，遇到任何环境/工具问题，先查 `references/windows_troubleshooting.md`。

Studio 推送硬边界：

- 当用户要求推送/发布到 Studio 时，**不要**说“接浏览器自动化”“打开浏览器点一遍”，也**不要**用任何 browser/chrome 自动化来代替真正的推送实现。
- Studio 推送必须严格通过 `studio-imagegallery-publish` skill 及其脚本/API 流程完成。
- 浏览器自动化不是这个 skill 允许的推送兜底方案，即使当前会话里有浏览器工具也不行。
- **不要**预加载或阅读 `browser-use` / `browser` / `chrome` 这些 skill 的说明；它们和本工作流无关，容易把规划带偏。

## 输入发现规则（混合工作目录 / 多类 JSON 文件特别重要）

当工作目录中同时存在 PPT/讲稿文件和多类 JSON 文件时，**不要**把目录里所有相邻 JSON 都当成当前工作流状态，更不要据此判断“已经处理过了”。

必须先按下面这个顺序发现输入：

1. 先按同 stem 文件配对真正的内容输入：
   - 演示文件：`.pptx` / `.ppt` / `.pdf`
   - 讲稿文件：`.docx` / `.md` / `.markdown` / `.txt`
2. 在内容发现阶段忽略各种报告/状态 JSON：
   - `course-json-report.json`
   - `create-report*.json`
   - `finalize-report*.json`
   - `upload-report.json`
3. 把 `course.json`、`section-list.json`、`fira_course-*.json` 仅视为**可选结构文件**：
   - 不要用它们判断 PPT 是否已经处理完成
   - 只有当用户明确要做 Studio 目标映射 / 批量推送规划时，才去读取这些文件
4. 优先使用确定性的批量规划脚本：

```bash
python scripts/plan_batch_jobs.py --root <folder>
```

这样可以避免 Codex 被同目录里无关的报告 JSON 干扰。

针对混合目录的额外护栏：

- 把 `course-json-report.json`、`create-report*.json`、`finalize-report*.json`、`upload-report.json` 都视为上游审计/报告产物。
- 它们**不是** `imagesgallery` manifest，**不是**本次运行的临时文件，**不是**发布计划，也**不是**“这个目录里已经有可复用有声 PPT 产物”的证据。
- 在正常的 `批量生成imagegallery` / `批量生成并推送` 流程里，除非用户明确要求排查这些报告，否则**完全不要**打开或分析这些报告 JSON。
- **不要**从这些报告 JSON 推断出诸如“已经有现成 manifest”“这些材料之前被批量上传过”“可以直接复用已有 imagegallery 产物链路”之类的结论。
- 在正常批量流程里，真正值得读取的 JSON 只有：
  - `section-list.json`
  - `fira_course-*.json`
  而且也必须是在用户明确提出要做 Studio 目标映射 / 批量发布规划之后。

## 命令接口

```bash
python3 scripts/build_imagesgallery.py \
  --ppt <file.ppt|file.pptx> \
  --speech <file.docx|file.md|file.txt> \
  --out <dir> \
  --dry-run
```

参数说明：

- `--ppt`：输入的幻灯片文件。
- `--speech`：与 PPT 对应的整篇讲稿；支持 `.docx` / `.md` / `.txt`（推荐使用 Word 导出的 `.docx`，可保留表格内容）。
- `--out`：输出根目录；脚本会写入 `<out>/<ppt_name>/imagesgallery`。
- `--dry-run`：兼容保留参数；脚本始终只负责生成图片和 skeleton manifest。

## 运营输入标准（推荐）

对运营同学，推荐使用下面这个稳定流程：

1. 同一目录里准备一份 PPT 文件和一份整稿 Word 文件（`.docx`）。
2. 讲稿尽量保留 Word 里的富文本结构（标题、加粗、列表），不要导出成纯 `.txt`。
3. 运行 skill 时让 `--speech` 指向这份 `.docx`。

原因：

- 纯 `.txt` 会丢掉格式。
- `.docx` 更能保留结构，脚本会把主要格式转成类似 Markdown 的文本，便于后续字幕展示（标题、粗斜体、列表、表格）。

## 讲稿清洗

- 对 NotebookLM 风格的 `.md` / `.markdown`，要先做**分页 Markdown 预处理**，再进入会话切稿；不要为了适配这种稿子去修改 canonical prompt。
- 这个预处理会移除独立页码行，例如 `- 第 1 页`、`第 1 页`、`Page 1`、`Slide 1`。
- 它还会去掉第 1 页之前重复出现、且与第 1 页标题相同的文档级标题。
- 如果检测到原始 Markdown 在后段又重新冒出“一级标题 + 开场正文”的重复尾稿，预处理会自动裁掉这段重复内容。
- 这种页码前的重复标题应视为文件元数据，不应视为封面/第一页要朗读的内容。
- 只有当前置块确实只是一个标题，且它与第一页标题明确匹配时，才去掉；否则保留原来的前言内容。
- 清洗后的文件会缓存到 `<out>/<ppt_name>/_cache/manuscript/`，只要缓存文件比原始 Markdown 更新，就优先复用。
- 当预处理生效时，manifest 里的 `source_speech` 会指向这个清洗后的 Markdown，这样后续的对齐、字幕生成和 TTS 都会读取同一份干净文本。
- 如果检测到这类可疑源稿问题，脚本会在 deck 根目录额外生成 `imagesgallery-risk-report.json`。
- 这个风险报告只用于提醒人工复核，**不阻断主流程**；只要清洗稿和后续校验都能通过，流程仍然继续执行。
- `.docx` 和 `.txt` **不**走这个分页 Markdown 预处理路径。

风险报告使用规则：

- 当 deck 根目录存在 `imagesgallery-risk-report.json` 时，收尾时必须主动读取并向用户输出一份简明的**风险列表**。
- 风险列表要明确说明：这通常意味着原始讲稿本身可能有问题，建议关注 PPT 页数、讲稿分页锚点、最终字幕和音频是否一致。
- 如果风险里提到了重复尾稿、页数不匹配、末尾页异常之类的问题，要提醒用户：必要时先修正原始讲稿，再重跑该 deck。
- 不要因为存在风险报告就自动停掉整条链路；只有真正的硬错误（例如连续性校验失败、资源缺失、course id 不匹配）才中断。

## 会话切稿规则

- 切稿时不要调用 `bl omni`。
- 必须使用当前 Codex 会话模型来完成逐页切稿。
- **强制要求：**逐字读取 `references/prompt_full_speech_session.md`，并把它作为切稿约束的唯一来源。
- **禁止：**不要另起炉灶编写、改写、总结或“优化”一个新的切稿 prompt 来替代 `references/prompt_full_speech_session.md`。
- 这个 skill 是原子、自洽的：运行时不要依赖外部仓库路径或外部文件。
- `references/prompt_full_speech_session.md` 是 skill 内部固化的**通用整稿 prompt**快照。
- 如果切稿行为需要变更，先更新这个 skill 自己的 prompt 文件，再同步更新本 `SKILL.md`。
- **不要**把 prompt 再拆成一个“分页 Markdown 专用分支”。如果输入讲稿是分页 Markdown，先清洗，再走同一套通用整稿 prompt 流程。
- 写回每页 `speech` 时，要保留原稿中的 Markdown 结构：标题、段落空行、列表标记都要尽量保留；不要在保存回 `imagesgallery.json` 之前先做对齐专用的归一化。
- 一次性整 deck 切稿：同一请求里提供全套页面图片 + 整篇讲稿。
- 模型输出必须是严格 JSON：
  - `pages: [{page_number, speech}]`
- `page_number` 必须从 `1..N` 严格连续。

## 会话 prompt 使用方式

为了提高切稿准确率，推荐按这个流程执行：

1. 先完整阅读 `references/prompt_full_speech_session.md`，严格按其中约束发起请求。
2. 如果 `imagesgallery.json` 的 `source_speech` 指向 `_cache/manuscript` 下的清洗后 Markdown，就使用这份清洗后文件，而不是原始分页稿。
3. 按顺序附上所有页面图片（`page-001.png ... page-NNN.png`）。
4. 在同一个请求中提供整篇讲稿，不要分批喂“剩余尾稿”。
5. 要求模型只返回严格 JSON（不要解释文字，不要代码块）：
   - `pages: [{page_number, speech}]`
6. 返回结果后，用 `scripts/align_manuscript.py` 做后验校验，再写回最终 manifest。

## 批量模式

当用户说出 `批量生成imagegallery` / `批量生成并推送` / `batch generate` / `batch publish` 这类需求时，要切换到批量工作流，而不是把整个目录当成一个大上下文去处理。

推荐流程：

1. 先跑批量规划器：

```bash
python scripts/plan_batch_jobs.py --root <folder> --shards 3
```

2. 后续批量工作只能以规划器返回的 `jobs[]` 为准。
3. 计划一旦固定，就不要让 agent 再去重新扫描整个目录发现文件。
4. 对单纯的批量生成，忽略 `candidate_structure_json`。
5. 对批量 Studio 推送，用户必须提供一个 **Studio 课程 URL**，例如：

```text
https://studio.uat.firacademy.com/course/course-v1:FIRAx+211181+20251122
```

6. 真正开始批量推送前，必须先生成一份确认文件：

```bash
python scripts/plan_batch_jobs.py \
  --root <folder> \
  --shards 3 \
  --studio-course-url <course_url> \
  --write-studio-targets
```

这会输出：

- `<out_base>/_batch/imagegallery-push-studio-targets.json`

如果规划器发现 `studio-course-url` 里的 course id 与 `fira_course-*.json` 不匹配，必须停下，并询问用户目标课程是否是由原课程导入出来的副本。

对组合型请求 `批量生成并推送` / `batch generate and publish`，这种不匹配是**整个批量流程的硬停止条件**，不只是最终推送阶段要停：

- **不要**继续生成本地 `imagesgallery` 输出
- **不要**继续合成音频
- **不要**继续准备或执行推送请求
- 必须等用户明确确认之后，再从规划阶段重新开始

只有在用户明确确认“这是导入课程副本”的情况下，才可以用下面的命令重新规划：

```bash
python scripts/plan_batch_jobs.py \
  --root <folder> \
  --shards 3 \
  --studio-course-url <course_url> \
  --allow-course-id-remap \
  --write-studio-targets
```

7. 如果规划器成功，而且不存在 course id 不匹配导致的硬停，不要仅仅为了确认这个文件而中断用户：
   - 直接打印生成文件的**绝对可点击路径**
   - 把这份文件视为可见性 / spot-check 产物，而不是阻塞审批点
   - 在同一任务里继续自动往下执行
8. 默认执行模式是 `三 agent 执行`：
   - 这个默认只适用于**本地生成 / 切稿 / 校验 / TTS**阶段
   - 如果当前会话支持 multi-agent，就让本地生成阶段以**最多 3 个同时活跃的子 agent**运行
   - 每个子 agent 必须 **严格只处理一个 deck**（`1 agent = 1 PPT/deck`）
   - **不要**让同一个子 agent 处理完 deck A 后，又在同一会话里继续处理 deck B
   - 一个 deck 结束后，要把结果交回主任务，并把该子 agent 视为生命周期结束
   - 如果后面还有 deck 在排队，主任务可以再为下一个 deck 启动一个**全新的**子 agent，但**同时活跃**的子 agent 数量始终不能超过 3
   - 如果当前会话不支持 multi-agent，就自动退回顺序执行
   - 正常成功路径里，**不要**停下来让用户选择 `顺序执行` 还是 `三 agent 执行`
9. 批量模式下最终的 Studio 推送仍必须 **顺序执行**，即使本地生成阶段用了 3 个 agent：
   - 每次只推一个 deck
   - **不要**在同一个运营账号 / 会话里并发向 Studio 推多个 deck
   - 如果推送步骤因为认证 / 会话问题失败，例如 `401`、`Not Login yet`、csrf/session 失效等登录错误，可以做会话刷新后重试
   - 每个推送步骤最多重试 **4** 次，重试间隔为几秒钟
10. 对批量 Studio 推送，只有在 `jobs` 固定之后，才允许读取 `candidate_structure_json`，而且也只能用于课程 section / Studio 目标映射。

批量规划边界：

- 在计划固定之前，只允许检查：
  - 同 stem 的 PPT / 讲稿配对
  - 可选的 `section-list.json`
  - 可选的 `fira_course-*.json`
- 在正常批量规划中，**不要**打开 `upload-report.json`、`course-json-report.json`、`create-report*.json`、`finalize-report*.json`
- 做批量生成/推送规划时，**不要**加载 browser/chrome skill 文档；这些和当前流程无关，容易导致会话跑偏

批量上下文隔离规则：

- 每个 agent/job 都必须拿到明确的**绝对路径**：
  - `ppt`
  - `speech`
  - 输出根目录
  - 生成后的 `manifest`
  - 当前 deck 的图片目录
- 一个子 agent 在自己的生命周期内，只能读取 **一个 deck** 的图片/文本。它可以在这个 deck 内完成 dry-run 渲染、清洗稿选择、切稿、校验、音频合成、manifest 改写，但所有工作都必须限定在这个 deck 内。
- 在一次切稿请求里，绝不能同时推理两个 deck 的页面图片。
- 绝不要在同一个子 agent 会话里读取或查看两个不同 deck 的图片，即使它们只是顺序处理也不行。
- 一个子 agent 只要已经看过某个 deck 的截图/讲稿，就**不要**把它复用到另一个 deck；要重新启动一个新的子 agent，确保多模态上下文是干净的。
- `最多 3 agent` 指的是**同时活跃**的本地生成子 agent 上限，不是整批任务总共最多只能处理 3 个 deck。
- 附图或读取图片时，必须使用完整绝对路径，例如 `...\\deck-a\\imagesgallery\\images\\page-001.png`，不要只写 `page-001.png`
- 开始下一个 deck 之前，要再次明确重述当前 deck 的绝对路径，让会话上下文围绕这个 deck 重新聚焦

批量 Studio 路由规则：

- 用 `section-list.json` 将文件名 / section id（例如 `1.2`、`1.3`、`4.2`）映射到课程 section。
- 用 `fira_course-*.json` 解析真实的来源 section / vertical 结构，以及精确的 vertical `block_location`。
- 规划器在选择主推送目标 vertical 时，必须优先选择包含以下特征的 vertical：
  - `imagesgallery` block category
  - 或 block 名称类似 `有声幻灯片`
  - 或 vertical 名称类似 `赋能内容`
- 如果用户明确确认这是导入课程 remap 场景，只重写选中 vertical locator 的 course-id 前缀，使用 `--studio-course-url` 里的课程 key；后面的 `+type@vertical+block@...` 后缀必须原样保留。
- 生成的目标文件里，必须同时暴露 `source_vertical_block_location` 和 `target_vertical_block_location`，以及 route mode/remap 标记，方便用户核对改写后的路由。
- 一旦有结构 JSON 可用，就**不要**仅凭文件名去猜 Studio 目标位置。
- 这份 targets 文件的作用是让人可见、可 spot-check；在正常非 mismatch 路径里，它不应该阻塞自动执行。
- 推送任务结束后，收尾回复里必须**始终列出目标 vertical 的可点击 Studio URL**，方便运营再进入对应小节做人工复核和细调。
- 新建出来的 `imagesgallery` block URL 只作为附加调试信息；不要把它当成默认主链接返回给用户。

## 校验规则

使用两阶段 schema 校验：

- Stage A（会话切稿之后）：`imagesgallery.json` 应包含
  - `version`
  - `source_ppt`
  - `source_speech`
  - `items[{page_number,image,speech}]`
- Stage B（音频合成脚本改写之后）：`imagesgallery.json` 应包含
  - `version`
  - `source_ppt`
  - `source_speech`
  - `audio`
  - `items[{page,image,subtitle,start,end}]`，其中 `start/end` 单位为毫秒
- 连续性检查必须通过 `scripts/align_manuscript.py`（`strict_consume_pages`）
- 最终剩余尾稿里不能还有实质性未消费内容

## Studio 推送依赖

当用户明确说出 `推送到studio` / `推送到 Studio` / `发布到 Studio` / `publish to Studio` 时，把这理解成一个依赖切换动作：

1. 把 `studio-imagegallery-publish` 当成必需依赖，而不是可选项。
2. 检查 `$CODEX_HOME/skills/studio-imagegallery-publish` 下是否已经安装该 skill。
3. 如果没有安装，使用 `skill-installer` skill 从下面这个地址安装：
   - `https://github.com/hongshanxueyuan/studio-imagegallery-publish`
4. 安装完成后，读取那个 skill 自己的 `SKILL.md`，并按它的规则完成实际 Studio 推送。
5. 不要在 `ppt-to-imagesgallery` 内部重新实现 Studio 推送逻辑；应复用 `studio-imagegallery-publish`。
6. 向用户解释工作流时，要明确表述为：
   - 用 `ppt-to-imagesgallery` 生成本地 `imagesgallery`
   - 用 `studio-imagegallery-publish` 推送到 Studio

补充说明：

- 当用户询问如何安装整套工作流时，要明确告诉他必须一起安装这两个 skill：
  - `https://github.com/hongshanxueyuan/ppt-to-imagesgallery`
  - `https://github.com/hongshanxueyuan/studio-imagegallery-publish`
- 只有在用户明确要求推送/发布到 Studio 时，才触发这个依赖检查/安装流程。
- 最好先检查/安装依赖，再向用户索取 Studio 凭据，这样整段推送流程更顺。
- 不要把浏览器自动化、Chrome 自动化、人工点击流程拿来当推送替代方案。如果 `studio-imagegallery-publish` 不可用或被阻塞，就必须停下并告知用户当前还无法继续推送。
- Studio 推送要求输入是最终 Stage-B 版 `imagesgallery.json`，即带有 `audio` 和逐页 `subtitle/start/end` 的版本。
- 在批量流程里，`三 agent` 只适用于本地生成阶段。最终的 Studio 推送阶段必须交给 `studio-imagegallery-publish`，并顺序执行，以避免登录/会话打架。
- 对**批量** Studio 推送，`studio-course-url` 通常必须与 `fira_course-*.json` 中记录的课程 id 保持一致（`course-v1:ORG+COURSE+RUN`）；只要 `ORG`、`COURSE`、`RUN` 中任何一个不一致，就要立刻停下，并告知用户课程 URL 可能贴错了。
- 唯一例外是：用户明确确认目标 Studio 课程是由原课程导入得到的副本。这种情况下，才可以使用 `--allow-course-id-remap` 重新规划，只重写 vertical locator 的 course-id 前缀，保留原始 `+type@vertical+block@...` 后缀。
- 如果没有这层明确确认，那么一旦发生 course id 不匹配，就不要继续任何后续批量动作，包括本地生成、音频合成、推送请求，因为批量推错课程的风险非常大。

## 校验代码片段

最终 JSON 写回后，可执行：

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
# `source_speech` 可能已经指向 `_cache/manuscript` 下的清洗后 Markdown。
manuscript = normalize_for_alignment(read_manuscript(speech_path))
# 兼容两个阶段的 schema：
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

## 资源

- `scripts/build_imagesgallery.py`：渲染图片并生成 skeleton manifest
- `scripts/plan_batch_jobs.py`：对混合目录做确定性批量规划（包含 deck/讲稿配对与结构 JSON）
- `scripts/align_manuscript.py`：讲稿归一化与连续性检查
- `scripts/synthesize_imagesgallery_audio.py`：逐段 TTS、完整 MP3 合并与时间轴输出
- `references/prompt_full_speech_session.md`：会话切稿使用的通用整稿 prompt
- `references/windows_troubleshooting.md`：Windows 常见问题与修复方法

## Windows 说明（重要）

为了减少 Windows 环境下重复踩坑：

- 如果缺少 `soffice`，`build_imagesgallery.py` 会自动回退到 PowerPoint COM 导出 `.ppt/.pptx`
- TTS 合成现在改为对每页使用 `bl ... --text-file`，不再直接用 `--text`
- 子进程输出统一按 UTF-8 解码，避免常见的 GBK 解码报错

如果要看完整排障说明，请查：

- `references/windows_troubleshooting.md`

## 音频合成

当 `imagesgallery.json` 已经定稿后，可执行：

```bash
python3 scripts/synthesize_imagesgallery_audio.py \
  --manifest /path/to/output/<ppt_name>/imagesgallery/imagesgallery.json \
  --voice longxiaochun_v3 \
  --rate 1.1 \
  --gap-seconds 1 \
  --final-name full_speech.mp3 \
  --timeline-name speech_timestamps.json
```

输出内容：

- `/path/to/output/<ppt_name>/imagesgallery/audio/segments/page-001.mp3` ...
- `/path/to/output/<ppt_name>/imagesgallery/audio/full_speech.mp3`
- `/path/to/output/<ppt_name>/imagesgallery/audio/speech_timestamps.json`
- `/path/to/output/<ppt_name>/imagesgallery/preview.html`

时间戳规则：

- 最终 manifest 中 `items[i].start` / `end` 的单位都是毫秒
- 对非最后一段，`end` 会包含后续的段间静音
- 因此相邻片段满足：`items[i].end == items[i+1].start`

预览行为：

- 点击播放后开始整段旁白
- 页面会按 `items[].start/end` 自动切换
- 左侧缩略图列表支持点击跳转
- 字幕区域展示当前页 `subtitle`
