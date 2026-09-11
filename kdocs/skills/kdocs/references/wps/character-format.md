# 字符格式

通过 `font_style` 传入字体样式。段落索引从 1 开始，字符区间从 0 开始。数值单位与属性以工具说明为准，避免把颜色索引、RGB 色值和字体枚举混用。

调用前使用 `search_tools` 获取完整参数和指定入口；参数直接放在 `arguments` 对象中。

| 工具 | 能力 |
|------|------|
| `wps.texts.font` | 在线文字文档文本的段落字体：支持 查询/设置。 |
| `wps.texts.font_batch` | 设置在线文字文档文本的批量修改段落字体。 |
| `wps.texts.font_color` | 设置在线文字文档文本的段落字体颜色。 |
| `wps.texts.highlight` | 设置在线文字文档文本的段落高亮。 |
| `wps.texts.underline_color` | 在线文字文档文本的下划线颜色：支持 设置/查询。 |
