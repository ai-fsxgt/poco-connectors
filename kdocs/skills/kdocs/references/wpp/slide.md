# 幻灯片管理

插入空白页通过 `index` 与 `layout` 指定位置和版式；已有页面操作先查询 `slide_id`。当前目录没有将外部 PPTX 页面直接导入现有文稿的能力。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.slide.items.list` | 查询幻灯片列表（返回全部幻灯片摘要列表）。 |
| `wpp.slide.items.insert` | 插入幻灯片：插入空白页。 |
| `wpp.slide.items.batch_insert` | 插入幻灯片：batch insert。 |
| `wpp.slide.items.duplicate` | 设置幻灯片：就地复制（需 slide_id，复制到相邻位置）。 |
| `wpp.slide.items.move` | 设置幻灯片：移动位置（需 slide_id 与 to_position）。 |
| `wpp.slide.items.delete` | 删除幻灯片（需 slide_id）。 |
