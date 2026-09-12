---
name: canva
description: "Use Canva's design capabilities: create and edit designs, manage assets and brand resources, search the asset library, export designs, and add comments."
description_zh: "让AI助手无缝调用Canva可画的设计能力，包括创建设计、编辑设计、管理素材和品牌资源、搜索资源库、导出设计以及添加评论等。"
description_en: "Access Canva's design capabilities: design creation and editing, asset and brand management, search, export, commenting, and more."
version: "1.0.0"
---

# Canva可画 Skill

通过 POCO 的 `canva` 连接器访问中国区 MCP 服务 `https://mcp.canva.cn/mcp`，调用设计、素材、品牌资源、导出和评论能力。可用工具以当前任务实际发现的工具为准。

## POCO 授权

- 管理员按 [安装与授权配置](references/setup.md) 注册并配置 OAuth 客户端；每位用户在 POCO 中点击连接，通过可画官方页面登录授权。
- POCO 负责 PKCE S256、访问令牌注入及可用刷新令牌的更新。不要要求用户在对话或工具参数中提供 Client Secret、授权码或令牌。
- 本包只连接中国区服务。官方工具文档作为接口参考，不代表国际版和中国区的工具、套餐或权限完全一致。

## 功能能力

- **创建设计**：使用自然语言描述，AI 自动在 Canva可画中创建设计稿
- **编辑设计**：对已有设计进行修改和调整
- **素材与品牌管理**：上传素材、管理文件夹并读取品牌资源
- **资源搜索**：搜索 Canva可画中的设计、品牌模板和文件夹
- **导出设计**：将设计导出为图片或其他格式
- **评论管理**：为设计添加评论和反馈

## 调用原则

1. 确保 Canva可画 MCP 服务已正确配置并可访问
2. 创建设计时尽量提供详细的需求描述，包括设计类型、风格、尺寸等
3. 编辑设计时明确指定目标设计和修改内容
4. 导出设计时指定所需格式和尺寸
5. 生成、编辑、上传、导出、移动和评论等写入操作须通过 POCO 确认，禁止自动重试

## 工具范围

| 用途 | 工具 |
| --- | --- |
| 设计检索与读取 | `search-designs`、`get-design`、`get-design-pages`、`get-design-content`、`get-presenter-notes`、`get-design-thumbnail`、`resolve-shortlink` |
| 生成与创建设计 | `generate-design`、`create-design-from-candidate`、`copy-design` |
| 编辑事务 | `start-editing-transaction`、`perform-editing-operations`、`commit-editing-transaction`、`cancel-editing-transaction` |
| 品牌资源与模板 | `search-brand-templates`、`list-brand-kits`、`get-brand-template-dataset`、`create-design-from-brand-template`、`autofill-design` |
| 素材与文件夹 | `upload-asset-from-url`、`get-assets`、`create-folder`、`list-folder-items`、`search-folders`、`move-item-to-folder` |
| 导入、调整与导出 | `import-design-from-url`、`resize-design`、`get-export-formats`、`export-design` |
| 评论与回复 | `comment-on-design`、`reply-to-comment`、`list-comments`、`list-replies` |

仅使用当前发现的工具参数 Schema，不编造工具名或 API 请求补齐未开放的能力。远程导入和上传工具接收其服务可访问的 URL，不能读取 POCO 工作区或用户电脑上的本地路径。

## 典型流程

1. **设计创建**：描述需求 → `generate-design` 生成候选 → 展示候选供用户选择 → 使用返回的任务 ID 和候选 ID 调用 `create-design-from-candidate` → 提供可编辑设计链接
2. **设计编辑**：指定设计和修改内容 → `start-editing-transaction` 获取事务 ID 与可编辑元素 → `perform-editing-operations` 应用修改 → 检查结果和缩略图 → `commit-editing-transaction` 保存 → 确认返回已提交状态
3. **设计导出**：指定设计 → `get-export-formats` 确认可用格式 → `export-design` 导出 → 检查任务状态及返回链接

编辑时使用开启事务返回的 `transaction_id`、页面和元素 ID，不把 `get-design-content` 返回的文本位置当作可编辑元素 ID。事务和元素 ID 来自服务响应，后续调用应显式传入；不依赖 POCO 保留 MCP 会话。逐项检查编辑结果，草稿应用成功不代表已保存。用户决定放弃草稿时，通过 POCO 确认后调用 `cancel-editing-transaction`。

导出链接可能过期，及时向用户交付结果。只报告服务实际返回的设计、链接或已保存文件，不把远程链接或服务端路径说成本地文件。

## 错误处理

- 若连接失败，检查 MCP 服务地址是否正确
- 若无法创建设计，确认设计参数是否完整
- 若导出失败，检查设计是否已完成且格式参数是否正确
- 若授权失效，在 POCO 中重新授权；权限或套餐限制按服务实际错误说明
- Canva 官方建议生成设计允许 60 秒；POCO 当前远程调用上限为 30 秒，源配置中的 `timeout: 60000` 无法由本包沿用。生成等耗时操作可能超时，该限制需要由 POCO 平台维护方处理
- 写入超时、提交冲突或结果不确定时停止并如实说明，先使用当前可用的只读工具核对状态；不要自动重新生成、重新提交或取消事务
