# 在线文字文档（Word / .docx）

支持段落、字符区间、样式、表格、图片、批注等操作。段落索引从 1 开始，字符区间从 0 开始。先读取目标位置再编辑，写入后独立读取核验。

新建正文使用 `create_file_with_content`；下载原文件使用 `download_file`。当前目录没有在线文字导出 PDF、图片或智能文档的工具。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wps.texts.info` | 查询在线文字文档文本的文档信息。 |
| `wps.texts.content` | 在线文字文档文本内容：支持查询/插入/设置/删除。 |
| `wps.texts.search` | 在在线文字文档中搜索文本。 |
| `wps.texts.replace` | 在在线文字文档中查找并替换文本。 |
| `wps.texts.font` | 在线文字文档文本的段落字体：支持 查询/设置。 |
| `wps.texts.format` | 在线文字文档文本的段落格式：支持 查询/设置。 |
| `wps.tables.create` | 在在线文字文档末尾新建指定行列数的空表格（新建后可用 wps.tables.cell_content 逐格填入内容）。 |
| `wps.tables.cell_content` | 在线文字文档表格的单元格内容：支持 删除/查询/设置。 |
| `wps.images.insert` | 在文档、段落或区间插入图片（file_path 为图片 URL）。 |
| `wps.comments.add` | 在在线文字文档中插入批注。 |

详细说明：[调用](wps/execute.md)、[内容](wps/content.md)、[段落格式](wps/paragraph-format.md)、[字符格式](wps/character-format.md)、[通用枚举](wps/enums.md)。
