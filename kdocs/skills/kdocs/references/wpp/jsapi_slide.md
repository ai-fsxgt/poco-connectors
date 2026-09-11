# 页面操作

复制、移动和删除前先列出页面，核对目标页面 ID；删除必须确认。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wpp.slide.items.count` | 查询幻灯片总数（返回演示文稿幻灯片页数）。 |
| `wpp.slide.items.list` | 查询幻灯片列表（返回全部幻灯片摘要列表）。 |
| `wpp.slide.items.layout` | 幻灯片：版式：支持 查询/设置（需 slide_id 与 layout 版式索引）。 |
| `wpp.slide.items.duplicate` | 设置幻灯片：就地复制（需 slide_id，复制到相邻位置）。 |
| `wpp.slide.items.move` | 设置幻灯片：移动位置（需 slide_id 与 to_position）。 |
| `wpp.slide.items.delete` | 删除幻灯片（需 slide_id）。 |
