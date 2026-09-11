# 演示文稿导出

使用固定 `domain=export`、`facet=export`、`verb=export`，以及目录要求的 `export_type`。页码范围使用 `from_slide`、`to_slide`；图片可按 `slide_id` 指定页面。参数未明确的取值不能猜测，应向服务提供方核实。结果格式以服务端实际返回为准，不使用未登记的查询入口。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.export.export.pdf` | 导出在线演示文稿为 PDF（可指定 from_slide/to_slide 页码范围）。 |
| `wpp.export.export.image` | 导出在线演示文稿为 图片（可指定 slide_id 或页码范围；image_type 为 PNG/JPG）。 |
| `wpp.export.export.xps` | 导出在线演示文稿为 XPS（可指定 from_slide/to_slide 页码范围）。 |
