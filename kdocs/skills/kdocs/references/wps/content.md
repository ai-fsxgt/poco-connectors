# 文档内容

使用 `file_id`、`link_id` 或 `url` 定位文档。读取全文可使用 `read_file` 并明确禁用附件上传；精确段落编辑先读取结构和范围。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wps.texts.info` | 查询在线文字文档文本的文档信息。 |
| `wps.texts.structure` | 批量查询在线文字文档段落结构（样式名/类型/大纲级别）。 |
| `wps.texts.count` | 查询在线文字文档段落数量。 |
| `wps.texts.range` | 查询在线文字文档段落文本范围。 |
| `wps.texts.content` | 在线文字文档文本内容：支持查询/插入/设置/删除。 |
| `wps.texts.search` | 在在线文字文档中搜索文本。 |
| `wps.texts.replace` | 在在线文字文档中查找并替换文本。 |

修改第 1 段内容，使用 `execute_destructive_tool`：

```json
{"name":"wps.texts.content","arguments":{"file_id":"file_xxx","scope":"paragraphs","verb":"update","paragraph_index":1,"content":"新的段落内容"}}
```

查找文字，使用 `execute_read_tool`：

```json
{"name":"wps.texts.search","arguments":{"file_id":"file_xxx","find_text":"关键词","is_all":true}}
```
