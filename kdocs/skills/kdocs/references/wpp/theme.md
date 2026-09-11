# 字体与配色

通过形状级工具调整文本和填充，母版及整稿主题查询使用对应 properties 工具。当前目录没有全文或单页切换预设字体/配色主题的接口。`wpp.shape.texts.font` 的 schema 仅允许查询；设置字体请查 `wpp.shape.texts.font_paragraph`。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.shape.texts.font` | 查询形状字体格式（需 slide_id、shape_id；可设 font_name/font_size）。 |
| `wpp.shape.texts.font_paragraph` | 设置形状字体格式段落格式。 |
| `wpp.shape.items.fill` | 形状：填充：支持 查询/设置（需 slide_id、shape_id；可设 fill_color）。 |
| `wpp.master.properties.theme` | 查询母版的主题。 |
| `wpp.master.properties.color_scheme` | 查询母版的配色方案。 |
| `wpp.presentation.properties.fonts` | 查询演示文稿的字体集合。 |
