---
name: feishu-workspace
description: 飞书 / Feishu 工作空间操作。用户需要查询或修改日历、任务、文档、云盘、表格、多维表格、审批、聊天、邮件、会议、通讯录等飞书数据时使用。
---

# 飞书工作空间

先调用 `search_commands`，按用户意图、产品和风险筛选官方 CLI 命令，再使用返回的 `canonical_path` 调用执行工具。不要猜测命令路径或参数名。

- 只读命令使用 `execute_read_command`。
- 普通写命令使用 `execute_write_command`，不要自动重试。
- `search_commands` 返回 `confirmation: user_required` 的普通写命令，必须先说明影响并获得明确确认，再使用 `execute_confirmed_write_command`。
- `search_commands` 返回 `destructive` 的命令必须先向用户说明影响，获得明确确认后使用 `execute_destructive_command`，并在 `flags` 中传 `yes: true`。
- 上传文件使用 `file_inputs`，不要在参数中传入本机绝对路径；下载或导出文件使用 `output` 相对路径，结果中的资源由连接器返回。
- 遇到权限不足、令牌失效或远端错误时，准确转述错误，不要重复执行写操作。

本连接器固定使用用户身份。不要传 `--as`，不要执行上游文档中的 `auth`、`config`、`update`、`event`、后台常驻进程或本地插件/项目管理命令。

详细产品语义和字段说明见 `references/upstream/skills/` 下随官方 CLI v1.0.95 发布的 Skills。里面的 `lark-cli` 示例仅用于理解流程；实际执行时必须先用 `search_commands` 找到连接器支持的命令，再把参数转换为 `flags` 和 `file_inputs`，不得直接运行示例命令。
