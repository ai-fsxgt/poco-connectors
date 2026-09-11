# 段落格式

通过 `scope=paragraphs` 加 `paragraph_index` 定位段落，或 `scope=ranges` 加 `begin/end` 定位字符区间。样式字段使用工具要求的 `paragraph_style`，不得传入旧命令参数。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wps.texts.alignment` | 设置在线文字文档文本的段落对齐。 |
| `wps.texts.indent` | 设置在线文字文档文本的段落缩进。 |
| `wps.texts.line_spacing` | 设置在线文字文档文本的段落行距。 |
| `wps.texts.format` | 在线文字文档文本的段落格式：支持 查询/设置。 |
| `wps.texts.format_batch` | 设置在线文字文档文本的批量修改段落格式。 |
| `wps.texts.format_copy` | 将源段落格式复制到目标段落范围（格式刷）。 |
