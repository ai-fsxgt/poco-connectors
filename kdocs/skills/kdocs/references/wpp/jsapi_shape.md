# 形状与文本

先取得页面及形状 ID，再更新对应对象。插入形状时以目录规定的类型和尺寸参数为准。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.shape.items.list` | 查询形状：形状列表。 |
| `wpp.shape.items.shape` | 插入形状：shape。 |
| `wpp.shape.items.textbox` | 插入形状：文本框（在 slide_id 指定页插入文本框）。 |
| `wpp.shape.items.picture` | 插入形状：图片（在 slide_id 指定页插入图片）。 |
| `wpp.shape.items.table` | 插入形状：表格（在 slide_id 指定页插入表格）。 |
| `wpp.shape.texts.text` | 形状文本内容：支持 查询/设置（需 slide_id 与 shape_id）。 |
| `wpp.shape.items.delete` | 删除形状（需 slide_id 与 shape_id）。 |
