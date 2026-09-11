# 腾讯会议问题反馈

Poco 连接器不读取或导出本机 CLI 日志，因此源连接器的 `tshoot log` 能力不迁移。远程问题反馈通过 `tshoot_feedback` 工具完成。

调用前必须先向用户展示反馈类别、原始意图、已尝试的工具和结果，并取得明确确认。反馈内容不得包含姓名、电话、会议号、会议链接、会议主题或参会人等未脱敏隐私信息。

`tshoot_feedback` 的参数与腾讯会议 `/v1/api/feedback` 接口一致，常用字段包括：

- `category`：`tool_not_found`、`tool_error`、`tool_inadequate`、`unexpected_result` 或 `suggestion`
- `intent`：用户原始意图，最多 200 字符
- `actions_tried`：已经调用的工具，最多 500 字符
- `result`：错误或阻塞结果，最多 500 字符
- `tool_name`、`error_code`：可选的工具名和错误码

该工具属于写操作，必须在 Poco 风险确认后调用，且同一会话中同一问题只反馈一次。
