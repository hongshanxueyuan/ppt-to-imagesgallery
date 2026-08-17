# PPT 转有声幻灯片使用说明

这个项目给已经安装了 Codex 和相关 skill 的同学使用。  
你不需要了解代码，只需要准备好文件，然后按下面的话术告诉 Codex 要做什么即可。

如果你是维护者，技术细节请看 [SKILL.md](D:/work/codeup/ppt-to-imagesgallery/SKILL.md)。

## 安装

先让 Codex 安装这两个 skill：

- `https://github.com/hongshanxueyuan/ppt-to-imagesgallery`
- `https://github.com/hongshanxueyuan/studio-imagegallery-publish`

这两个 skill 要一起安装。  
如果你后面要推送到 Studio，`studio-imagegallery-publish` 不是可选项。
生成本地 `imagegallery` 时，也建议明确说出 `ppt-to-imagesgallery` 这个 skill 名字。

安装完成后，建议重启一次 Codex。

## 先准备什么

同一个目录下，准备好一对文件：

- 一个 PPT 文件：`.pptx`、`.ppt` 或 `.pdf`
- 一个讲稿文件：优先用 `.md` 或 `.docx`

推荐做法：

- 如果是从 NotebookLM 或类似工具导出的内容，优先直接使用配套的 Markdown 讲稿
- 如果没有 Markdown，讲稿请放到 Word 里保存成 `docx`
- 不建议只用纯文本 `txt`，因为格式容易丢

如果后面要推送到 Studio，还需要准备：

- Studio 账号和密码
- 批量推送时对应课程的课程地址

## 怎么用

### 场景一：先在本地生成，确认没问题再推送

把 PPT 和讲稿放好后，对 Codex 说：

```text
用 ppt-to-imagesgallery 把这个 PPT 转成有声幻灯片
```

处理完成后，Codex 会生成预览文件。你可以先看页面、字幕和音频是否正常。
音频合成默认会按线上当前女声配置 `cosyvoice-v2 + longxiaochun_v2`，并以 `1.1` 倍速调用百炼 CLI 生成 MP3。

确认没问题后，再对 Codex 说：

```text
用 studio-imagegallery-publish 推送到 Studio：<这里换成目标小节地址>
```

这里的小节地址通常长这样：

```text
https://studio.xxx.com/container/block-v1:ORG+COURSE+RUN+type@vertical+block@XXXX
```

### 场景二：直接生成并推送

如果你不想先本地确认，也可以直接说：

```text
用 ppt-to-imagesgallery 把这个 PPT 转成有声幻灯片，然后用 studio-imagegallery-publish 推送到 Studio：<目标小节地址>
```

## 批量操作怎么说

如果一个目录下有很多组 PPT 和讲稿，可以直接说：

```text
用 ppt-to-imagesgallery 把这个目录批量生成 imagegallery
```

如果要批量生成并推送，再说：

```text
用 ppt-to-imagesgallery 把这个目录批量生成 imagegallery，然后用 studio-imagegallery-publish 批量推送到 Studio，课程地址是：<课程地址>
```

这里的课程地址通常长这样：

```text
https://studio.xxx.com/course/course-v1:ORG+COURSE+RUN
```

批量推送时，Codex 不会直接开推，而是会先生成一份待确认清单。  
它会把这份路由文件的可点击路径发给你，你可以随手点开检查；只要课程链接没有问题，Codex 会直接继续执行，不用专门停下来等你回复确认。

## 批量时你可以重点留意什么

- 每个 PPT 是否都找到了对应讲稿
- 目标 Studio 课程地址是否正确
- 每个文件要推送到哪个小节，是否和预期一致

Codex 默认会用 `三 agent 执行`。  
这个默认只用于本地生成阶段。  
最后推送到 Studio 时，会自动改成 `顺序执行`，避免多个发布任务同时登录把会话打架。  
如果当前环境临时不能开多 agent，本地生成阶段才会自动退回 `顺序执行`。

## 关于课程 ID 不一致

有一种常见情况是：这门课后来通过课程包导入导出，被复制到了另一个平台或另一个课程里。  
这时你输入的 Studio 课程地址，可能和目录里的原始 JSON 记录不一致。

遇到这种情况时，Codex 应该先停下来问你确认，而不是直接继续。

如果你确认目标课程确实是同一门课的导入副本，就明确告诉 Codex 可以继续。  
如果你不确定，就不要继续推送。

## 常见建议

- 先小范围试一节，确认效果后再批量跑
- 批量推送前，先看一遍 Codex 生成的确认清单
- 涉及生成 `imagegallery` 时，明确说出 `ppt-to-imagesgallery` 这个 skill 名字
- 涉及推送到 Studio 时，明确说出 `studio-imagegallery-publish` 这个 skill 名字，避免 Codex 跑去加载浏览器类 skill
- 批量推送结束后，Codex 应该把每个已推送成功的小节 Studio 地址列出来，方便运营逐个点开人工微调
- 如果讲稿里有分页标记、标题或富文本格式，直接保留原文件即可，Codex 会按当前 skill 规则处理

## 这份 README 不展开的内容

下面这些实现细节，这里不展开：

- 脚本命令
- 音频合成细节
- 路由映射规则
- Windows 排障
- 开发和测试说明

如果需要看这些内容，请直接看 [SKILL.md](D:/work/codeup/ppt-to-imagesgallery/SKILL.md)。
