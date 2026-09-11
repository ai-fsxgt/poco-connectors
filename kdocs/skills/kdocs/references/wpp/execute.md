# 演示文稿调用

使用具体 `wpp.*` 工具。按 schema 传入固定的 `domain`、`facet`、`verb`，仅填写该工具登记的参数，不传入脚本或命令字符串。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.slide.items.list` | 查询幻灯片列表（返回全部幻灯片摘要列表）。 |
| `wpp.slide.items.insert` | 插入幻灯片：插入空白页。 |
| `wpp.shape.items.textbox` | 插入形状：文本框（在 slide_id 指定页插入文本框）。 |
