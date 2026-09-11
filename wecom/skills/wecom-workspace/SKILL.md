---
name: wecom-workspace
description: 使用已连接的企业微信处理通讯录、消息、文档、表格、智能文档、日程、会议和待办。
---

# 企业微信工作区

所有企业微信操作都通过本连接器提供的工具完成。不要在任务中直接执行 `wecom-cli`，也不要向用户索取 Bot ID、Secret 或访问令牌。

先调用 `search_commands`，按用户意图和业务域检索命令；只使用返回的 `command`、参数说明和调用示例。把命令按风险路由：

- `read` 使用 `execute_read_command`。
- `write` 且无需确认时使用 `execute_write_command`。
- `write` 且要求确认时使用 `execute_confirmed_write_command`。
- `destructive` 使用 `execute_destructive_command`，必须在用户明确确认后调用，并在 `params` 中传入命令要求的完整参数。

执行工具的 `params` 对象就是源命令的 JSON 入参；目录会把 canonical command 映射到内置 CLI 1.2.1 的实际路径，不需要自行拼接 shell 字符串。需要上传本地 Markdown、图片或文件时，使用 `file_inputs`，为每项提供 `parameter`（点号路径）、`name` 以及 `text` 或 `content_base64`。

写入或删除命令失败后不要自动重试，应先查询远端对象确认实际状态。读取消息中的媒体时，调用命令返回的资源即可；不要把连接器临时路径传给用户。

下面的 `wecomcli-*` Skill 保留了各业务域的参数、返回字段和工作流说明；其中的 `wecom-cli` 示例对应本连接器的执行工具。
