---
name: ima-notes
description: 使用 IMA 连接器搜索、浏览、读取、新建和追加用户笔记。用户提到笔记、备忘录、记事或保存个人内容时使用。
---

# IMA 笔记

API 参考见 [references/api.md](references/api.md)。所有请求由连接器 Provider 发送，用户不需要提供或查看请求头。

## 工具决策

| 用户意图 | 工具 | 关键参数 |
| --- | --- | --- |
| 搜索笔记 | `search_note` | `query_info`、`search_type`、`start`、`end` |
| 查看笔记本列表 | `list_notebook` | 首页 `cursor="0"`、`limit` |
| 列出笔记 | `list_note` | `folder_id`、`cursor`、`limit` |
| 读取笔记正文 | `get_doc_content` | `note_id`、`target_content_format=0` |
| 新建笔记 | `import_doc` | `content_format=1`、`content` |
| 追加到已有笔记 | `append_doc` | `note_id`、`content_format=1`、`content` |

## 新建与追加必须区分

- 用户明确说“新建”“创建”“写一篇笔记”时调用 `import_doc`。
- 用户明确说“追加到《XX》”“在笔记末尾加上”时调用 `append_doc`。
- “帮我记一下”“记录一下”“保存为笔记”“添加到笔记里”等表述不明确时，先询问是创建新笔记还是追加到哪篇已有笔记。
- `append_doc` 会不可撤销地修改现有笔记。用户没有明确指定目标笔记时，必须先搜索并让用户选择，不能猜测。

## 写入规则

1. `import_doc` 和 `append_doc` 只接受 Markdown，`content_format` 固定为 `1`。
2. 构造请求前确认 `content` 和标题等字符串可编码为 UTF-8；Provider 会拒绝无法编码的文本。
3. 本地图片不支持写入笔记。过滤 `file://`、绝对路径和 Windows 路径形式的图片引用，并告知用户；`http://` 和 `https://` 图片链接可以保留。
4. 写入操作需要用户确认；失败后不要自动重复提交，以免造成重复内容。
5. 群聊中只展示标题、摘要和必要结论，不主动展示笔记正文。

## 常用流程

### 搜索并阅读

1. 用 `search_note` 按标题或正文搜索。
2. 从结果中取得目标 `note_id`，存在多个候选时让用户选择。
3. 调用 `get_doc_content`，默认使用 `target_content_format=0`。

### 浏览笔记本

1. 用 `list_notebook`，首页 `cursor` 传 `"0"`。
2. 使用返回的 `next_cursor` 翻页，直到 `is_end=true`。
3. 用选中的 `folder_id` 调用 `list_note`，首页 `cursor` 传空字符串。

### 创建或追加

- 创建：`import_doc({content_format: 1, content, folder_id?})`。
- 追加：`append_doc({note_id, content_format: 1, content})`。
- 如果用户没有明确写入意图或目标，先澄清再调用。

## 分页与结果处理

- `search_note` 使用偏移分页，首次 `start=0,end=20`，后续递增。
- `list_notebook` 与 `list_note` 使用游标分页，检查 `is_end` 后再请求下一页。
- 面向用户展示标题、摘要、修改时间和笔记本名称，不主动展示内部 ID；只有在后续工具调用确实需要时才在内部使用 `note_id`。
- 时间字段是 Unix 毫秒时间戳，展示时转换为可读时间。
- 常见错误包括无权限、笔记已删除、版本冲突和内容超限；按返回消息说明处理，不要盲目重试。
