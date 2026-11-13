# PPT To ImagesGallery

本上下文负责把 PowerPoint 幻灯片逐页转换为 ImagesGallery 内容。

## Language

**源 PPT**:
用于渲染页图的 `.ppt` 或 `.pptx` 幻灯片文件。
_Avoid_: PPT 原图

**页图**:
从一张幻灯片渲染出的图片，并由对应的 ImagesGallery 条目引用。
_Avoid_: 截图, PPT 原图

**压缩页图**:
为 ImagesGallery 最终产物生成的较小体积页图；其画面仍代表同一张幻灯片。
_Avoid_: 原图

**像素尺寸**:
页图的像素宽和像素高，例如 2560 × 1440。
_Avoid_: DPI, PPI

**重采样**:
通过增减像素改变页图像素尺寸的过程；缩小页图时保持原长宽比。
_Avoid_: 改 DPI, 改长宽比

**图片集页文（Gallery Page Text）**:
与某张页图对应的可读文本，用作该页的字幕和语音合成内容。
_Avoid_: 讲稿

**Markdown 引用前缀（Markdown Blockquote Prefix）**:
引用行开头的 `>` 标记；嵌套引用可由多个连续的 `>` 组成，前面允许最多三个空格。行内正文中的 `>` 不属于引用前缀。
_Avoid_: 大于号（指 Markdown 引用语法时）
