# TAPD 安装与授权配置

本包使用 TAPD 官方远程 MCP 和 Poco 原生 OAuth 授权码流程。管理员为当前 Poco 部署配置一个 OAuth 客户端，每位用户分别登录自己的 TAPD 账号授权。

## 1. 登记回调地址并注册客户端

使用当前 Poco 部署的后端对外地址，登记完整回调 URL：

```text
${BACKEND_URL}/api/v1/connectors/oauth/callback
```

例如后端地址为 `https://poco.example.com`，回调地址就是 `https://poco.example.com/api/v1/connectors/oauth/callback`，必须与实际发起授权时的地址一致。

TAPD MCP 的公开 OAuth 元数据声明了客户端注册端点 `https://websocket.tapd.cn/mcp/register`。Poco 的清单使用管理员预先提供的 Client ID 和 Client Secret，不会在连接时自动注册客户端。

以下是根据该元数据编写的标准 OAuth 客户端注册请求示例。将示例回调替换为实际地址后，由管理员执行；该请求会创建客户端。本次迁移未执行真实注册，注册资格和回调准入要求需由 TAPD 确认。

```bash
curl --fail-with-body --silent --show-error \
  'https://websocket.tapd.cn/mcp/register' \
  --header 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "client_name": "Poco TAPD",
  "redirect_uris": [
    "https://poco.example.com/api/v1/connectors/oauth/callback"
  ],
  "response_types": ["code"],
  "grant_types": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_method": "client_secret_post",
  "scope": "user"
}
JSON
```

保存返回的 `client_id` 和 `client_secret`，核对注册的回调地址、授权类型和客户端认证方式。若注册被拒绝，按服务返回原因联系 TAPD 处理。凭据仅填写到 Poco 配置中，不写入安装包或 Git。

## 2. 填写 Poco 管理员配置

| 字段 | 填写内容 |
| --- | --- |
| MCP 服务地址 | 保留 `https://websocket.tapd.cn/mcp/mcp` |
| OAuth Client ID | 为当前 Poco 部署注册的 TAPD MCP 客户端 ID |
| OAuth Client Secret | 同一客户端的密钥，认证方式必须为 `client_secret_post` |

本包通过 MCP 元数据发现 OAuth 端点，并限定授权方为 `https://websocket.tapd.cn/mcp`。申请 `user` 权限，使用 PKCE S256；访问令牌通过 `Authorization: Bearer` 发送。用户实际可访问的公司、项目和操作由 TAPD 授权范围与项目权限决定。

## 3. 用户连接

管理员分配 `feature.connector.tapd` 权限并发布连接器后，用户在 Poco 中连接 TAPD，通过官方页面登录并完成授权。TAPD 签发刷新令牌时，Poco 管理后续刷新；授权失效或刷新失败时，用户需要重新授权。

## 4. 验收范围

- 本次已通过只读请求核对受保护资源和 OAuth 元数据，包括服务地址、授权方、注册端点、权限、客户端认证方式、PKCE、刷新和撤销能力声明。
- 未带凭据的 MCP `initialize` 请求返回 HTTP 401，确认服务要求授权；尚未使用真实账号完成授权后的 `initialize`、`tools/list` 或 `tools/call`。
- 工具白名单沿用源 Skill 的 39 个工具，其中 24 个只读、15 个写入。工具参数说明保留源文档，以真实服务发现的 schema 为准。
- 部署验收先验证客户端注册、OAuth 回调、权限和工具发现，再用 `get_user_participant_projects` 查询参与的项目。核对项目后，通过 Poco 确认流程验收实际需要的写操作，并验证令牌刷新与撤销。
- 写操作禁止自动重试。需要用户确认的工具仅可在 Poco 即时交互任务中使用，定时、后台和 OpenAPI 任务会拒绝这些操作。
- 本次仅完成源码移植。真实账号验收后再生成发布 ZIP，并按仓库开发手册对最终归档执行发布校验。

## 来源

- [TAPD MCP 受保护资源元数据](https://websocket.tapd.cn/.well-known/oauth-protected-resource/mcp/mcp)
- [TAPD MCP OAuth 元数据](https://websocket.tapd.cn/.well-known/oauth-authorization-server/mcp)
- [TAPD 帮助中心](https://www.tapd.cn/help/view)
