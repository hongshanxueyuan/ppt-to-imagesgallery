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

- `/path/to/output/<ppt_name>/imagesgallery/images/<deck-prefix>__page-001__<timestamp>.png` ...
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

- 对 NotebookLM 风格的 `.md` / `.markdown`，**进入任何页级推理、切稿、对齐、校验之前的第一步，必须先删除分页锚点 / 页码行**；这是硬前置动作，不是可选预处理。
- 对 NotebookLM 风格的 `.md` / `.markdown`，要先做**分页 Markdown 预处理**，再进入会话切稿；不要为了适配这种稿子去修改 canonical prompt。
- 这个预处理会移除独立页码行，例如 `- 第 1 页`、`第 1 页`、`Page 1`、`Slide 1`。
- **硬规则：**Markdown 里的页码、页码锚点、`第 N 页`、`Page N`、`Slide N` 这类文本，一律只当噪声 / 元数据处理，删除后再做后续工作；它们**绝不能**作为逐页切稿的主要分割依据，也不能作为“页数校验通过”的解释依据；即使它们看起来和 PPT 页数“对得上”，也不能直接按它们切。
- **禁止级规则：**后续任何 agent / 子 agent / 人工补救流程，只要再次拿 Markdown 页码锚点去解释、切分、映射、验证 PPT 页面，或把这件事单独上升为用户风险提示，都视为**违反本 skill**。这不是“可参考但不能过度依赖”，而是**完全不能作为页级切分依据或默认风险来源**。
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
- 风险列表只应突出**在分页锚点删除之后仍然存在、且会实质影响最终字幕 / 音频 / 发布正确性**的问题，例如：重复尾稿、连续性校验失败、明显串页、末尾页异常、资源缺失、需要人工整理稿等。
- **不要**把“原始 Markdown 页码锚点数量和 PPT 页数不一致”单独作为默认用户风险；这类锚点本来就不可信，删除后如果连续性校验通过，就不需要再把它作为结论强调给用户。
- 如果风险里提到了重复尾稿、连续性失败、末尾页异常、明显结构失配之类的问题，要提醒用户：必要时先修正原始讲稿或整理稿，再重跑该 deck。
- 不要因为存在风险报告就自动停掉整条链路；只有真正的硬错误（例如连续性校验失败、资源缺失、course id 不匹配）才中断。

## 会话切稿规则

- 切稿时不要调用 `bl omni`。
- 必须使用当前 Codex 会话模型来完成逐页切稿。
- 如果输入是 Markdown，开始切稿前必须先确认分页锚点 / 页码行已经从工作底稿中删除，不能边保留边切。
- **强制要求：**逐字读取 `references/prompt_full_speech_session.md`，并把它作为切稿约束的唯一来源。
- **禁止：**不要另起炉灶编写、改写、总结或“优化”一个新的切稿 prompt 来替代 `references/prompt_full_speech_session.md`。
- 这个 skill 是原子、自洽的：运行时不要依赖外部仓库路径或外部文件。
- `references/prompt_full_speech_session.md` 是 skill 内部固化的**通用整稿 prompt**快照。
- 如果切稿行为需要变更，先更新这个 skill 自己的 prompt 文件，再同步更新本 `SKILL.md`。
- **不要**把 prompt 再拆成一个“分页 Markdown 专用分支”。如果输入讲稿是分页 Markdown，先清洗，再走同一套通用整稿 prompt 流程。
- 写回每页 `speech` 时，要保留原稿中的 Markdown 结构：标题、段落空行、列表标记都要尽量保留；不要在保存回 `imagesgallery.json` 之前先做对齐专用的归一化。
- **硬规则：**页码文本本身不能出现在最终 `speech` / `subtitle` / TTS 音频里；如果某页切稿结果里混入了 `第 N 页`、`Page N`、`Slide N` 这类标记，必须在写回 manifest 前清掉并重新校验。
- 逐页切稿的唯一允许依据是：
  - 当前 PPT 页面可见内容
  - 整篇讲稿的语义连续性
  - 切稿后逐页连续性与去重校验
- 明确禁止把下面这些内容当成页级映射锚点：
  - Markdown 页码
  - `第 N 页` / `Page N` / `Slide N`
  - “原稿第几段刚好像是下一页”的机械顺延
- 一次性整 deck 切稿：同一请求里提供全套页面图片 + 整篇讲稿。
- 模型输出必须是严格 JSON：
  - `pages: [{page_number, speech}]`
- `page_number` 必须从 `1..N` 严格连续。
- 切稿完成后，必须逐页做一次“重新切割后的人工/程序联合校验”：
  - 不能漏讲
  - 不能重复讲
  - 顺序不能倒退
  - 每页内容要尽量和当前页面视觉内容对应
  - 只要发现明显错位，必须先重切或手工修正，再进入音频合成和发布

发现错位后的强制补救规则：

- 如果用户指出“某几页内容与页面不对应”，不要再回头引用 Markdown 页码锚点解释原因。
- 正确动作是：
  - 只看该 deck 的 PPT 页面图
  - 回到整篇讲稿做语义重切
  - 修正 manifest
  - 重新校验“不漏、不重、不串页”
  - 如该 deck 已合成音频或已推送 Studio，则必须同步重做音频，并按需要重新发布
- 对同一批次的其他 deck，不能假设“只有用户指出的那一节有问题”；必须做同批次复查，必要时批量返工。

阶段标题页防串页规则（新增硬约束）：

- 当某一页 PPT 的视觉主标题明显是**新阶段 / 新章节 / 新小节**的起始页（例如页面大标题直接出现 `## ...`、`第三阶段`、`第四阶段`、`行动清单` 一类新段落标题），该标题及其紧随导语必须**从这一页开始分配**。
- 上一页即使正文较短，也**不得**为了追求“讲稿连续”而提前吃进下一阶段标题。
- 特别是“避坑指南页 → 下一阶段总览页”这类相邻组合，上一页只允许保留本页对应的避坑正文；下一阶段标题必须留给下一页。
- 这条规则优先级高于“尽量让每页多吃一点连续原文”的经验做法。
- 即使下一页的视觉主标题与讲稿中的阶段标题不是逐字同文，只要页面结构已经明显进入新阶段（例如从上一页的表格/避坑页切到下一页的总览箭头图、闭环图、路线图、行动框架图），也要把该阶段标题和导语留在下一页，**不能**因为“下一页没命中同词关键词”而回塞到上一页。
- 典型反例：若上一页仍是 `二、...` 的收束表格页，而讲稿下一行已经进入 `三、把公开实践再往前推一步...`，则 `三、...` 必须从下一页开始；上一页宁可在 `二、...` 收束句结束，也不能提前朗读 `三、...`。

封面页 / 导入页边界规则（新增硬约束）：

- 如果第 1 页视觉上明显是**封面页 / 标题页 / 章节首页**，第一页 `speech/subtitle` 只能承载该页标题、必要副标题和与封面直接对应的开场导语。
- 不得因为封面页文字较少，就把第 2 页的正文主体、案例、定义、列表、图解说明提前塞进第 1 页。
- 如果原始 Markdown 在第 1 页前存在文档级总标题、封面重复标题、自动生成的前置标题块，先按“讲稿清洗”规则处理；清洗后仍保留下来的前言内容，只有在视觉上能被第 1 页合理承载时，才允许放到第 1 页朗读。
- 如果第 2 页视觉上已经进入“课程目标 / 场景导入 / 核心问题 / 目录 / 总览”，则这些内容必须从第 2 页开始，不得被封面页偷吃。
- 同理，如果某一页视觉上是“章节封面 / 阶段起始页”，也要按封面页同样的边界处理：该页负责开场定题，后续展开内容从下一页开始。

阶段边界复核清单（进入 TTS / 发布前必须执行）：

- 先逐页识别页面在结构上属于哪一类：封面/章节首页、导入页、阶段标题页、总览页、正文展开页、沟通/避坑页、图表解释页、行动清单页、总结页。
- 每页首句必须属于当前页，而不是明显应该属于前一页或后一页；如果首句已经在讲后一页的标题、定义、图解、清单，视为边界错位。
- 每页末段必须在当前页自然收束；如果末段已经偷带后一页的标题行、导语句、编号起始句、案例开头，视为边界错位。
- 相邻 2-4 页连读时，主题推进必须自然，不能出现“后一页还在补讲前一页主题”或“前一页提前讲完后一页主题”的整体早一页/晚一页现象。
- 对所有 `##` / 关键 `###` 标题，确认**标题首次出现的页面**与页面视觉主标题或视觉结构切换位置一致。
- 对封面页、阶段标题页、总览页、避坑页、行动清单页、总结页，复核时必须额外看页面截图，不得只看 manifest 文本。

阶段切换专项清单（阶段标题切换时必须执行）：

- 逐页检查所有 `##` / 关键 `###` 标题的落点，确认**标题首次出现的页面**与页面视觉主标题一致。
- 如果某页视觉上还是上一阶段内容，但 `speech/subtitle` 已经出现下一阶段标题，视为**硬错误**，必须重切。
- 如果某页视觉上已经是新阶段标题页，但 `speech/subtitle` 还没有进入该标题，视为**硬错误**，必须重切。
- 对“阶段避坑页”“阶段总览页”“行动清单/总结页”这三类最容易串页的页面，复核时必须额外看页面截图，不得只看 manifest 文本。
- 对“上一页无明显剩余正文 + 下一页是新阶段结构图”的组合，复核时要额外执行一次反向检查：确认上一页末尾没有偷带下一阶段的任何标题行、导语句或编号起始句。

阶段收束页 / 避坑页专项规则（新增硬约束）：

- 如果某页视觉标题仍属于当前阶段，但版式已经明显是该阶段的**沟通页 / 避坑页 / 三个不要页 / 五问页 / 总结卡片页**，则该页应视为**当前阶段的最后承载页**。
- 这类页面上的正文、避坑条目、三条原则、五个问题、关键提醒等，必须尽量在**本页内部讲完**；不能只留一句过渡，再把这一页的实质内容拖到下一页。
- 如果下一页视觉上已经切到新的阶段标题页、框架图、原则图、关键少数图、行动清单页，那么新阶段标题必须从下一页开始；上一页不得继续占用下一页的主标题位置。
- 典型反例：上一页还是“短期激励沟通/避坑指南”，下一页已经是“长期激励的五个问题/核心原则”；此时短期激励的避坑条目必须留在上一页，不能拖到下一页，导致长期激励整体晚一页。
- 进入 TTS 前，对这类“阶段正文页 -> 避坑/沟通页 -> 下一阶段标题页”的三连页，必须额外复核一次：
  - 当前页是否已经吃完本阶段的避坑/沟通内容
  - 下一页首行是否已经进入新阶段标题
  - 是否出现“上一页视觉还没结束、下一页字幕却仍在讲上一阶段”的一页滞后错误

总览页 / 图解页 / 行动页专项规则（新增硬约束）：

- 如果某页视觉上是总览图、流程图、闭环图、路线图、框架图、对比图，这一页的 `speech/subtitle` 应优先完成“这张图在讲什么”的解释，不得被前一页残留正文大量挤占。
- 如果某页视觉上已经切到“行动清单 / 三件事 / 五个动作 / 总结 / 你可以立刻做什么”，这些动作项和收束语必须从本页开始，不得整体晚到下一页。
- 如果某页只是上一页主题的图解展开，允许承接同一主题继续讲；但如果视觉结构已经从“展开说明”切到“收束动作/总结提炼”，则必须把边界切干净，不能继续机械顺延正文。
- 对“总览页 -> 分点展开页”这类组合，上一页应讲清总览框架，下一页再进入具体展开；不要把下一页的第一个分点解释提前塞进总览页。

已发布 deck 返修规则（新增硬约束）：

- 如果某个 deck 已经发布到 Studio，后来又发现页文不对应、阶段串页、标题落点错误等实质问题，修复时不能只停留在本地 manifest。
- 必须完整执行：
  - 修正 manifest
  - 重新做连续性校验
  - 重新生成音频 / 时间轴 / preview
  - 重新发布到原 target vertical
  - 将 Studio 中旧的错误 imagesgallery block 删除，避免一个小节里同时残留新旧两个版本
- 批量任务里，用户一旦指出某一节有这类错位，必须把同批次已发布 deck 视为待复核对象，优先检查所有阶段切换页、避坑页、总结页、行动清单页，必要时批量返修。

## 会话 prompt 使用方式

为了提高切稿准确率，推荐按这个流程执行：

1. 先完整阅读 `references/prompt_full_speech_session.md`，严格按其中约束发起请求。
2. 如果 `imagesgallery.json` 的 `source_speech` 指向 `_cache/manuscript` 下的清洗后 Markdown，就使用这份清洗后文件，而不是原始分页稿。
3. 按顺序附上所有页面图片（文件名通常形如 `<deck-prefix>__page-001__<timestamp>.png`）。
4. 在同一个请求中提供整篇讲稿，不要分批喂“剩余尾稿”。
5. 要求模型只返回严格 JSON（不要解释文字，不要代码块）：
   - `pages: [{page_number, speech}]`
6. 返回结果后，用 `scripts/align_manuscript.py` 做后验校验，再写回最终 manifest。

图片命名规则：

- `imagesgallery/images/*.png` 不再使用通用的 `page-001.png` / `page-002.png`。
- 默认命名为：`<deck-prefix>__page-001__<timestamp>.png`
- 其中 `deck-prefix` 来自当前 PPT 文件名的稳定前缀，`timestamp` 来自本次构建时间。
- 这样即使多个 deck 连续生成并推送到同一门课里，Studio 侧拿到的上传文件名也不会互相覆盖。

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
   - **提速经验：**优先把 3 个同时活跃的子 agent 用在“本地生成 / 会话切稿 / Stage-A 校验 / TTS”上；不要把 agent 槽位浪费在最终 Studio 推送，因为发布阶段必须顺序执行
   - **调度经验：**当一批 3 个 deck 完成 Stage-A 后，主任务应立即为下一批待处理 deck 启动新的 agent，同时让已完成的 deck 尽快进入 TTS；不要等整批 deck 全部切稿完成后才统一开始合成音频
9. 批量模式下最终的 Studio 推送仍必须 **顺序执行**，即使本地生成阶段用了 3 个 agent：
   - 每次只推一个 deck
   - **不要**在同一个运营账号 / 会话里并发向 Studio 推多个 deck
   - 如果推送步骤因为认证 / 会话问题失败，例如 `401`、`Not Login yet`、csrf/session 失效等登录错误，可以做会话刷新后重试
   - 每个推送步骤最多重试 **4** 次，重试间隔为几秒钟
   - **不要**因为单个 deck 的临时失败、旧状态文件里的历史失败记录、或一次异常返回，就把整批任务停在“还剩几个没做完”的状态
   - 正确做法是：锁定当前失败 deck -> 单独排查 -> 修复/重试 -> 回填状态 -> 继续剩余 deck，直到全部目标完成或遇到真正的硬阻塞
10. 对批量 Studio 推送，只有在 `jobs` 固定之后，才允许读取 `candidate_structure_json`，而且也只能用于课程 section / Studio 目标映射。

批量收尾硬规则：

- 对 `批量生成并推送` 请求，结束前必须拿 `imagegallery-push-studio-targets.json` 做一次最终对账：
  - 哪些 target 已生成
  - 哪些 target 已发布
  - 哪些只是历史失败但后来已修复
- **不要**把状态文件里的 `failures[]` 直接当成当前未完成列表；历史失败可能已经被后续手工重试修复。
- 只有当 targets 对账后确认 `generated == target_count` 且 `published == target_count`，才能把任务视为真正完成；否则必须继续执行剩余项，而不是提前收尾。

批量恢复 / 续跑规则（重要）：

- 如果任务中途中断、切换会话或用户要求“继续”，**第一步不要重做整批扫描和整批切稿**；先做一次**状态审计**。
- 状态审计至少要输出每个 target 的以下状态：
  - `manifest` 是否存在
  - 是否仍是 Stage A，还是已经是 Stage B
  - 是否已有 `audio/full_speech.mp3`
  - 是否已有 `audio/speech_timestamps.json`
  - 是否已有 `preview.html`
  - 是否已发布到 Studio
- 恢复时必须优先利用：
  - `<out_base>/_batch/imagegallery-push-studio-targets.json`
  - 本地已存在的 `imagesgallery.json`
  - 本地 `audio/` 与 `preview.html`
  - 本地维护的发布结果日志（如 `codex-publish-results.jsonl` / `codex-final-publish-summary.json`）
- 如果本地产物已经是可复用的正确阶段，就从缺失步骤继续；**不要**因为会话断了就把整节 deck 从头重做。

dry-run skeleton 识别规则（新增硬约束）：

- `build_imagesgallery.py --dry-run` 产出的 manifest 只代表图片和 skeleton 就绪，**绝不代表切稿完成**。
- 恢复或审计时，必须检查 `items[].speech` 是否仍包含占位内容，例如：
  - `[DRY_RUN] page 1`
  - `[DRY_RUN] page N`
- 只要发现任何一页还是这类占位 `speech`，就必须把该 deck 视为**未完成 Stage A**：
  - 不能进入 TTS
  - 不能进入 Studio 推送
  - 必须先回到会话切稿 / manifest 改写 / 连续性校验
- **不要**因为 `imagesgallery.json` 文件存在、图片已渲染、或 deck-summary 里有 manifest 路径，就误判该 deck “已经生成完成”。

切稿后最低质检规则（新增提速护栏）：

- 完成 Stage A 后，主任务应立即做一次程序化快检，而不是等到整批收尾时再发现问题：
  - 连续性校验是否通过
  - 是否混入 `第 N 页` / `Page N` / `Slide N`
  - 是否仍存在明显的重复尾稿 / 重复段落
- 如果某 deck 在这一轮快检失败，应立刻在本轮修掉，不要把问题带进 TTS 和 Studio，再在后面返工整条链路。

源稿去重经验（新增）：

- 如果连续性校验失败，或某些页面出现明显的尾段重复，不要第一时间怀疑图片顺序；先检查 `_cache/manuscript/*.cleaned.md` 是否仍残留：
  - 重复标题块
  - 重复表格
  - 重复尾稿
- 对确认属于源稿清洗问题的内容，应先修复清洗稿，再重写 manifest，并重新做连续性校验；这样通常比硬在最终 manifest 上逐页切补更稳。

结构失配 outlier deck 处理规则（新增硬约束）：

- 如果某个 deck 的原始分页 Markdown 与真实 PPT 结构明显失配，不要继续强行沿用原分页稿做页级切分。
- 下面这些现象可以直接视为“结构失配”信号：
  - 原稿里的 `第 N 页` / `Page N` 数明显多于真实 PPT 页数
  - 某个阶段标题页后，原稿把同一组正文拆成多页重复展开，但 PPT 只给了 1-2 页承载
  - 原稿后段把同一节正文先完整写一遍，随后又把其中几个子点按页重复展开
  - 如果继续沿用原分页稿，会导致“行动清单 / 总结页 / 阶段标题页”被前页吃掉，或出现明显串页
- 一旦识别为这类 outlier deck，正确动作是：
  - 停止把原始分页 Markdown 当作任何页级锚点
  - 在当前 deck 的 `_cache/manuscript/` 下创建一份人工整理稿，例如：
    - `<deck-stem>.curated.md`
  - 这份整理稿应只保留**语义连续、无重复、与 PPT 实际结构一致**的正文顺序
  - manifest 的 `source_speech` 必须切换到这份 `*.curated.md`
- 人工整理稿的整理原则：
  - 删除页码锚点、重复分页、重复尾稿、重复表格块
  - 保留原稿 Markdown 结构，不做同义改写
  - 把被原稿错误拆散的连续段落重新并回正确页面范围
  - 保证“阶段标题页 / 避坑指南页 / 行动清单页 / 总结页”落点与 PPT 视觉结构一致
- 对这类 outlier deck，优先选择“先整理 source_speech，再重写 manifest”，不要试图只靠调 OCR 阈值、只改校验器、或在最终页文本上零碎打补丁来硬撑过关。
- 典型经验：
  - 如果原稿把“避坑指南 + 三个坑”先汇总写一遍，后面又按坑 1/2/3 再拆开重复分页，而 PPT 实际只给一个“避坑指南”页和一个“收束/过渡”页，那么应把重复分页压回一段连续正文，而不是让它们分别占据多个实际页面。
- 进入 TTS / 发布前，必须再次确认：
  - `strict_consume_pages` 已通过
  - 最终实质尾稿为空
  - `source_speech` 已指向 `*.curated.md`
  - 如有需要，补写 `imagesgallery-risk-report.seed.json`，并在报告中显式标注该 deck 属于 `manual_curated` 路径

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
- 附图或读取图片时，必须使用完整绝对路径，例如 `...\\deck-a\\imagesgallery\\images\\deck-a-abc12345__page-001__20260817-163045-123.png`，不要只写文件尾名
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
  --voice longxiaochun_v2 \
  --model cosyvoice-v2 \
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
