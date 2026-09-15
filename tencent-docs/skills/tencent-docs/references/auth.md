# 腾讯文档授权

腾讯文档连接器使用官方页面生成的自定义 Token。四个 MCP 服务共用同一份 Token，Poco 会把原始值直接写入每个请求的 `Authorization` 请求头。

## 连接步骤

1. 在浏览器打开[腾讯文档官方接入页](https://docs.qq.com/scenario/open-claw.html?nlc=1)。
2. 使用需要连接的 QQ 或微信账号登录并完成授权。
3. 复制页面显示的 Token。
4. 在 Poco 的腾讯文档连接器授权表单中粘贴 Token。不要添加 `Bearer` 前缀。
5. 提交后，Poco 会对以下四个服务执行 MCP 初始化和工具发现；全部服务验证成功后才会保存连接：
   - `https://docs.qq.com/openapi/mcp`
   - `https://docs.qq.com/api/v6/slide/mcp`
   - `https://docs.qq.com/api/v6/doc/mcp`
   - `https://docs.qq.com/api/v6/sheet/mcp`

Token 只应填写在 Poco 的密钥表单中。不要把 Token 发到对话、写入脚本、环境变量、日志或工作区文件。

## 失败处理

- Token 无效、过期或返回 HTTP 401/403：重新打开官方接入页获取 Token，然后在 Poco 中选择“重新授权”。
- 任一 MCP 服务连接失败：Poco 会拒绝整组连接。确认网络可访问四个固定地址，并重新提交同一份有效 Token。
- 权限不足：确认授权账号可以查看或编辑目标文档；如需调整共享权限，由用户在腾讯文档中处理或明确授权后使用权限工具。
- VIP 或积分不足：按服务返回的信息处理，不自动购买、升级或重复调用。

Poco 负责 MCP 初始化、会话、工具发现、调用和 Token 注入。不要使用 `mcporter`、自定义 HTTP 脚本或其他本地配置重复注册服务。

