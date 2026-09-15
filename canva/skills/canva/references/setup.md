# Canva 可画安装与授权配置

本包使用中国区 MCP 服务以及 Poco 原生 OAuth 授权码流程。OAuth 客户端必须提前注册，并登记当前 Poco 部署使用的完整回调地址。连接器不执行动态客户端注册，也不在 Provider 中实现 MCP 或 OAuth 协议。

## 1. 确认并登记回调地址

Poco 的连接器 OAuth 回调格式为：

```text
${BACKEND_URL}/api/v1/connectors/oauth/callback
```

当前部署对应的完整地址为：

```text
https://agent-api.fsxgt.cn/api/v1/connectors/oauth/callback
```

必须将这一完整 HTTPS 地址提交给可画并加入 MCP OAuth 回调地址允许列表。协议、域名、端口、路径和末尾斜杠都必须与授权请求中的 `redirect_uri` 完全一致。收到 `Invalid redirect URI` 表示上游没有接受该地址，连接器无法绕过这一校验。

## 2. 注册 OAuth 客户端

若中国区服务允许手动注册，可使用其注册端点创建固定客户端。注册前先完成上一步的回调地址允许列表申请：

```bash
curl --fail-with-body --silent --show-error \
  'https://mcp.canva.cn/register' \
  --header 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "client_name": "Poco Canva 可画",
  "redirect_uris": [
    "https://agent-api.fsxgt.cn/api/v1/connectors/oauth/callback"
  ],
  "response_types": ["code"],
  "grant_types": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_method": "client_secret_basic",
  "scope": "design:meta:read design:content:read design:content:write folder:read folder:write brandtemplate:content:read brandtemplate:meta:read comment:read comment:write asset:read asset:write brandkit:read"
}
JSON
```

保存返回的 `client_id` 和 `client_secret`。若注册端点仍返回回调地址错误，应联系可画完成中国区 MCP 接入和回调地址审批，不能改用动态注册或修改 Poco 主程序规避。

## 3. 配置 Poco

| 管理员字段 | 填写内容 |
| --- | --- |
| MCP 服务地址 | 保留 `https://mcp.canva.cn/mcp` |
| OAuth Client ID | 上一步返回的 `client_id` |
| OAuth Client Secret | 同一客户端返回的 `client_secret` |

Poco 使用 MCP OAuth 元数据发现授权和令牌端点，校验签发方为 `https://mcp.canva.cn`，并使用 PKCE S256。客户端使用 `client_secret_basic` 完成令牌端点认证，访问令牌由 Poco 以 `Authorization: Bearer` 注入远程 MCP 请求。

## 4. 验收

- 确认授权请求中的 `redirect_uri` 与登记地址逐字一致。
- 使用真实账号完成登录回调、令牌交换、刷新和重新授权。
- 先调用 `search-designs` 或 `get-design` 等只读工具验证工具发现和令牌注入。
- 写操作须通过 Poco 确认；写入超时或结果不确定时不要自动重试。
- 中国区实际工具、权限和套餐必须以真实账号返回为准。
- Canva 建议为 `generate-design` 预留 60 秒，而 Poco 当前远程调用上限为 30 秒；连接器包不能自行改变平台时限。

本地结构和协议检查不能代替真实 OAuth 与账号验收。发布前必须使用已进入允许列表的回调地址完成上述真实验证。

## 来源

- [中国区受保护资源元数据](https://mcp.canva.cn/.well-known/oauth-protected-resource/mcp)
- [中国区 OAuth 服务元数据](https://mcp.canva.cn/.well-known/oauth-authorization-server)
- [Canva MCP 接入说明](https://www.canva.dev/docs/mcp/)
- [Canva MCP 手动注册与故障排查](https://www.canva.dev/docs/mcp/troubleshooting/)
- [Canva MCP 工具目录](https://www.canva.dev/docs/mcp/tools/)
