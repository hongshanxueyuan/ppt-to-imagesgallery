# Preflight Repair

只在 `_batch/imagegallery-preflight-report.json` 存在时读取这个文档。

## 你要先做什么

1. 先告诉用户 preflight 已经完整扫完。
2. 明确说明 batch 已经停止，后续没有开始渲染、音频、preview 或 Studio 动作。
3. 用报告里的 `failures[]` 给出精炼修复列表。

## 常见 failure code

- `section_list_match_not_found`
  本地 PPT 没有匹配到任何 `section-list` 记录。优先检查文件名、`output_name`、`section_id`。

- `section_list_match_ambiguous`
  本地 PPT 同时匹配到多个 `section-list` 记录。优先消除命名歧义，再重跑。

- `missing_page_count`
  该 section 记录缺少 `page_count`。

- `invalid_page_count`
  `page_count` 不是正整数。

- `missing_page_content`
  该 section 记录缺少 `page_content`。

- `invalid_page_content`
  `page_content` 不是数组，或者数组项不是字符串。

- `page_content_length_mismatch`
  `len(page_content)` 和 `page_count` 不一致。

- `blank_page_content`
  某一页的 `page_content` 实际是空白或只剩页码噪声。

- `slide_count_unavailable`
  下游使用的 PPT 处理后端无法得到真实页数。常见原因是 PPT 损坏、PowerPoint/LibreOffice 环境异常，或转换工具不可用。

- `page_count_mismatch`
  真实 PPT 页数和 `page_count` 不一致。

## 回复原则

- 优先按 deck 聚合，不要一条 failure 一条 failure 地碎着报。
- 始终带上绝对路径里的 PPT。
- 如果同一个 deck 有多条 failure，一次说完，避免用户修一个再踩一个。
- 不要建议带着失败 deck 继续往下跑。这个 batch 合同要求整批先修完再重跑。
