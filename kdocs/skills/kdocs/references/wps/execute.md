# 在线文字调用

使用目录中的具体 `wps.*` 工具。需要 `scope` 或 `verb` 的工具必须使用 schema 中列出的枚举，不能自行添加操作字段。

`wps.texts.content` 包含删除能力，整体属于破坏性工具；即使 `verb=query` 也需要指定的确认入口。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wps.texts.content` | 在线文字文档文本内容：支持查询/插入/设置/删除。 |
| `wps.texts.search` | 在在线文字文档中搜索文本。 |
| `wps.texts.replace` | 在在线文字文档中查找并替换文本。 |
