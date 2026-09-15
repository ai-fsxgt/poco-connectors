---
name: tencent-docs
description: 使用已连接的腾讯文档账号创建、读取、编辑和管理在线文档、Word、表格、幻灯片、智能文档、智能表格、思维导图、流程图、文件目录与知识库空间。用户提到腾讯文档、docs.qq.com、云文档或要求把内容保存到腾讯文档时使用。
metadata:
  homepage: https://docs.qq.com/home
  source_version: "1.0.41"
  author: tencent-docs
---

# 腾讯文档

通过 Poco 的 `tencent-docs` 连接器访问腾讯文档官方 MCP。连接器使用同一份 Token 注册四个独立服务：

| 服务 | 负责能力 |
| --- | --- |
| `tencent-docs` | 通用读取、文件管理、知识库、智能文档、智能表格、图形文档、OCR、网页剪藏与导入导出 |
| `slide-mcp` | 幻灯片内部结构与 `slide_*` 工具 |
| `doc-mcp` | Word 文档内部结构与 `doc.*` 工具 |
| `sheet-mcp` | Excel 表格内部结构与 `sheet.*` 工具 |

Token 由 Poco 连接器管理。不要要求用户在对话、工具参数、脚本或文件中提供 Token，也不要直接请求四个 MCP 端点。授权失效时，引导用户在 Poco 中重新连接；获取 Token 的官方说明见 [授权说明](references/auth.md)。

只调用 Poco 当前发现且允许的工具。参考文档用于选择工具和理解字段；若参考文档与当前工具 Schema 不一致，以 Schema 为准，不猜测工具名、参数、文件 ID、页面索引或版本号。

## 文档类型

| 类型 | `doc_type` | 主要服务 |
| --- | --- | --- |
| 智能文档 | `smartcanvas` | `tencent-docs` |
| Excel | `sheet` / `tencentsheet` | `sheet-mcp` |
| PPT | `slide` / `tencentslide` | `slide-mcp` |
| 思维导图 | `mind` | `tencent-docs` |
| 流程图 | `flowchart` | `tencent-docs` |
| Word | `doc` / `tencentdoc` | `doc-mcp` |
| 收集表 | `form` / `tencentform` | `tencent-docs` |
| 智能表格 | `smartsheet` | `tencent-docs` |
| HTML 演示文稿 | `smartpage` | `tencent-docs` |

## 场景路由

先判断用户是在创建内容、编辑内容、管理文件，还是转换已有材料。混合任务按实际依赖顺序分步处理。

### 创建

| 用户意图 | 首选工具或流程 | 必读参考 |
| --- | --- | --- |
| PPT、幻灯片、演示文稿 | Slide 工作流；空白文件先用 `manage.create_file` 创建 | [slide/entry.md](slide/entry.md) |
| 思维导图 | `create_mind_by_markdown` | [references/diagram_references.md](references/diagram_references.md) |
| 流程图 | `create_flowchart_by_mermaid` | [references/diagram_references.md](references/diagram_references.md) |
| 报告、笔记、文章、总结、会议纪要 | `create_smartcanvas_by_mdx` | [smartcanvas/entry.md](smartcanvas/entry.md) |
| 论文、公文、合同等 Word 文档 | `doc.create_with_markdown` 或 Doc 工作流 | [doc/entry.md](doc/entry.md) |
| 数据表格、计算、统计 | Sheet 工作流 | [sheet/entry.md](sheet/entry.md) |
| 结构化数据、多视图表格 | `manage.create_file` + `smartsheet.*` | [references/smartsheet_references.md](references/smartsheet_references.md) |
| 收集表或空白文件 | `manage.create_file` | [references/manage_references.md](references/manage_references.md) |

### 读取与编辑

先从链接前缀判断类型；不能确定时调用 `manage.query_file_info`。不得用一种品类的内部编辑工具修改另一种文档。

| 文档类型 | 工具集 | 必读参考 |
| --- | --- | --- |
| 智能文档 | `smartcanvas.*` | [smartcanvas/entry.md](smartcanvas/entry.md) |
| PPT | `slide_*`（`slide-mcp`） | [slide/entry.md](slide/entry.md)、[references/slideengine_references.md](references/slideengine_references.md) |
| Word | `doc.*`（`doc-mcp`） | [references/docengine_references.md](references/docengine_references.md) |
| Excel | `sheet.*`（`sheet-mcp`） | [sheet/entry.md](sheet/entry.md) |
| 智能表格 | `smartsheet.*` | [references/smartsheet_references.md](references/smartsheet_references.md) |

通用读取、图片上传与网页剪藏见 [references/workflows.md](references/workflows.md)。文件夹、搜索、权限、移动、复制、删除和导入导出见 [references/manage_references.md](references/manage_references.md)。知识库空间与节点见 [references/space_references.md](references/space_references.md)。OCR 见 [references/ocr_references.md](references/ocr_references.md)。

## 核心规则

- 编辑前先读取目标对象及当前版本；文件、工作表、页面、形状、字段、视图和记录 ID 必须来自用户输入或工具返回。
- 同一文档连续三次及以上写入时，优先使用批量工具，例如 `smartsheet.add_records`、`smartsheet.update_records`、`sheet.set_range_value`、`slide_add_shapes` 和 `slide_add_texts`。
- 写入、上传、创建、导入、导出和异步任务提交均禁止自动重试。超时或结果不确定时先用只读工具核对，再由用户决定是否重试。
- 删除文件、页面、形状、表格、字段、记录、空间节点或内容块前，明确核对目标和范围；递归删除空间节点尤其要确认 `remove_type`。
- Poco 会执行清单中的风险确认。不要改用其他工具、直接 HTTP 或脚本绕过确认。
- 异步操作只在进度工具返回完成状态后报告成功；尚未完成时如实报告任务 ID 和当前状态。
- 用户要求把当前对话内容保存、归档、整理成报告或会议纪要时，优先用 `create_smartcanvas_by_mdx`。
- 用户给出网页 URL 并要求保存内容时，使用 `scrape_url`，随后通过 `scrape_progress` 查询结果。
- `create_smartcanvas_by_mdx` 不支持 `parent_id`；其他创建工具是否支持父目录，以当前 Schema 为准。
- 空间节点的 `node_id` 可作为对应文档的 `file_id` 使用。
- 如果当前发现的工具无法完成用户要求，直接说明能力边界，不调用遥测或静默上报工具。

## 本地文件与图片

导入普通本地文件时，按 [references/aipage_references.md](references/aipage_references.md) 和 [references/manage_references.md](references/manage_references.md) 执行：调用 `manage.pre_import` 获取签名上传地址，使用该地址上传文件，再调用 `manage.async_import`，最后查询 `manage.import_progress`。签名上传地址只用于本次文件上传，不等同于 MCP 端点。

导入 HTML 时，可先运行包内零依赖脚本：

```bash
node aipage_pack.js --html "<html_path>" --title "<title>"
```

脚本只负责把 HTML 和资源打成 `.aipage`，不会读取凭据或调用 MCP。

本地图片用于 OCR、Word、PPT 或智能文档时，可读取文件并按当前工具 Schema 传入 base64，或先用 `upload_image` 获取 `image_id`。不要把 base64 或临时签名 URL展示在最终回复中；大图片超过工具限制时如实说明，不要求用户把开放平台凭据发到对话中。

## 结果交付

创建或修改成功后，返回服务实际给出的 `file_url`；用户只提供 `file_id` 时，只在文档类型已确认的情况下使用对应的腾讯文档 URL 前缀。不要编造链接，也不要把导出产生的临时 URL 当作在线文档链接。

## 错误处理

- HTTP 401/403、错误码 400006 或 Token 失效：提示用户在 Poco 中重新连接腾讯文档。
- 权限不足：说明缺少查看或编辑权限，提示用户调整共享权限；不要擅自修改权限。
- VIP 或积分不足：转述服务返回的限制，不自动购买、升级或重复调用。
- 文档类型不匹配（如 400016）：重新确认文档类型并切换到对应服务。
- 版本冲突：重新读取当前版本和目标内容，禁止用旧版本参数盲目重试。
- 文件、工作表、页面或对象不存在：重新查询，不猜测替代 ID。

上游包版本与迁移取舍见 [references/upstream.md](references/upstream.md)。
