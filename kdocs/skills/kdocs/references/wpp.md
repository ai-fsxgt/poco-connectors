# 在线演示文稿（.pptx）

支持幻灯片、形状、文本、备注、母版查询及导出。先列出页面获取 `slide_id`，再列出形状获取 `shape_id`。页面索引、位置与 ID 是不同参数，不能混用。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.slide.items.list` | 查询幻灯片列表（返回全部幻灯片摘要列表）。 |
| `wpp.slide.items.insert` | 插入幻灯片：插入空白页。 |
| `wpp.slide.items.delete` | 删除幻灯片（需 slide_id）。 |
| `wpp.shape.items.list` | 查询形状：形状列表。 |
| `wpp.shape.texts.text` | 形状文本内容：支持 查询/设置（需 slide_id 与 shape_id）。 |
| `wpp.shape.texts.font_paragraph` | 设置形状字体格式段落格式。 |
| `wpp.export.export.pdf` | 导出在线演示文稿为 PDF（可指定 from_slide/to_slide 页码范围）。 |
| `wpp.export.export.image` | 导出在线演示文稿为 图片（可指定 slide_id 或页码范围；image_type 为 PNG/JPG）。 |

详细说明：[调用](wpp/execute.md)、[页面](wpp/slide.md)、[页面操作](wpp/jsapi_slide.md)、[形状](wpp/jsapi_shape.md)、[字体配色](wpp/theme.md)、[导出](wpp/export.md)。
