# Canva 可画安装与授权配置

本包使用中国区 MCP 服务和 POCO 原生 OAuth 授权码流程，客户端认证方式固定为 `client_secret_basic`，PKCE 使用 S256。管理员配置一个客户端，每位用户分别登录可画授权。

## 1. 确定回调地址

使用当前 POCO 部署的后端对外地址：

```text
${BACKEND_URL}/api/v1/connectors/oauth/callback
```

例如后端地址为 `https://poco.example.com`，则回调地址为 `https://poco.example.com/api/v1/connectors/oauth/callback`。必须与实际发起授权时的回调地址一致。

Canva 官方接入文档要求先申请回调地址允许列表。该文档面向国际版，中国区客户端接入资格和回调审批要求需向可画确认。本包不携带其他客户端的注册信息或已获批准的回调地址。

## 2. 注册中国区 OAuth 客户端

下面的命令会创建一个 OAuth 客户端，返回客户端 ID 和密钥。完成接入准备后，由管理员将示例回调替换为真实地址再执行：

```bash
curl --fail-with-body --silent --show-error \
  'https://mcp.canva.cn/register' \
  --header 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "client_name": "POCO Canva 可画",
  "redirect_uris": [
    "https://poco.example.com/api/v1/connectors/oauth/callback"
  ],
  "response_types": ["code"],
  "grant_types": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_method": "client_secret_basic",
  "scope": "design:meta:read design:content:read design:content:write folder:read folder:write brandtemplate:content:read brandtemplate:meta:read comment:read comment:write asset:read asset:write brandkit:read"
}
JSON
```

登记地址取自中国区服务实际返回的 OAuth 元数据；注册流程依据官方手动注册说明适配。客户端注册及上述权限组合尚未在真实可画账号上验收。若注册被拒绝，应按服务返回原因联系可画处理。

保存返回的 `client_id` 和 `client_secret`，核对回调地址、授权类型及 `token_endpoint_auth_method` 与请求一致。密钥只填写到 POCO 管理员配置，不写入包、Git 或聊天记录。

## 3. 安装并配置 POCO

| 管理员字段 | 填写内容 |
| --- | --- |
| MCP 服务地址 | 保留 `https://mcp.canva.cn/mcp` |
| OAuth Client ID | 上一步返回的 `client_id` |
| OAuth Client Secret | 同一客户端返回的 `client_secret` |

本包通过 MCP OAuth 元数据发现端点，并限定授权方为 `https://mcp.canva.cn`。访问令牌使用 `Authorization: Bearer` 发送，Client Secret 用于令牌端点的 HTTP Basic 客户端认证。

授予使用者 `feature.connector.canva` 权限并发布连接器后，每位用户在 POCO 中连接自己的可画账号，完成浏览器登录和授权。POCO 在服务签发刷新令牌时管理其刷新；不要用管理员自己的访问令牌代替用户授权。

## 4. 验收与已知限制

- 先验证登录回调、授权范围和工具发现，再执行 `search-designs` 或 `get-design` 等只读查询。
- 通过用户确认后，验证所需的生成、模板填充、编辑提交、导入、导出及评论能力。编辑事务需要额外验证相同用户通过 POCO 的独立调用能否继续使用服务端事务 ID。
- 验证令牌过期后的刷新、用户撤销授权后的错误提示，以及实际账号权限和套餐限制。
- 工具白名单依据公开官方文档固定；中国区实际返回的工具、参数和可用范围仍须用真实账号核对。不要将国际版套餐说明作为中国区承诺。
- Canva 建议 `generate-design` 使用 60 秒超时；POCO 当前远程 MCP 请求和读取等待上限为 30 秒。本包无法调整平台时限，长耗时生成可能失败，应由 POCO 平台维护方处理。结果不确定时先核对状态，不自动重新提交写入。
- 本次迁移未执行真实客户端注册、OAuth、令牌刷新或工具调用，也未生成发布 ZIP。发布前再按仓库规范验证最终归档。

## 来源

- [中国区受保护资源元数据](https://mcp.canva.cn/.well-known/oauth-protected-resource/mcp)
- [中国区 OAuth 服务元数据](https://mcp.canva.cn/.well-known/oauth-authorization-server)
- [官方 MCP 接入说明](https://www.canva.dev/docs/mcp/)
- [官方手动注册与超时说明](https://www.canva.dev/docs/mcp/troubleshooting/)
- [官方工具目录](https://www.canva.dev/docs/mcp/tools/)
