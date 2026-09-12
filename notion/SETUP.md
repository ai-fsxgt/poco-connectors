# Notion 安装与授权配置

本包通过 Poco 原生远程 MCP 连接 `https://mcp.notion.com/mcp`，使用 OAuth 授权码、PKCE S256 和 `client_secret_basic` 客户端认证。管理员注册一个客户端并保存配置，每位用户分别登录 Notion 授权。

## 1. 注册 OAuth 客户端

Poco 回调地址为：

```text
${BACKEND_URL}/api/v1/connectors/oauth/callback
```

将下方示例回调替换为当前部署的真实后端对外地址，再由管理员执行一次注册。生产环境使用 HTTPS，登记地址须与 Poco 发起授权时的回调地址完全一致。

```bash
curl --fail-with-body --silent --show-error \
  'https://mcp.notion.com/register' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json' \
  --data-binary @- <<'JSON'
{
  "client_name": "Poco Notion",
  "redirect_uris": [
    "https://poco.example.com/api/v1/connectors/oauth/callback"
  ],
  "response_types": ["code"],
  "grant_types": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_method": "client_secret_basic",
  "scope": "default"
}
JSON
```

核对返回的客户端认证方式和回调地址，并保存 `client_id`、`client_secret`。密钥仅填写在 Poco 管理员配置中，不写入安装包、Git 或聊天记录。已有连接应继续使用原客户端，不要为每位用户或每次授权重新注册。

注册地址、权限和认证方式已通过官方公开元数据核对；上述注册请求未实际执行。注册失败时按服务错误处理，不更换授权方式或自动重复注册。

## 2. 安装和连接

| 管理员字段 | 填写内容 |
| --- | --- |
| MCP 服务地址 | 保留 `https://mcp.notion.com/mcp` |
| OAuth Client ID | 注册返回的 `client_id` |
| OAuth Client Secret | 同一客户端返回的 `client_secret` |

本包限定 OAuth issuer 为 `https://mcp.notion.com`，由 Poco 发现端点、注入访问令牌并管理刷新。Poco 当前要求预先填写客户端配置，不会根据本包自动执行动态注册。

安装后分配 `feature.connector.notion` 权限并发布连接器，用户即可通过 Poco 登录 Notion 授权。连接完成后，使用 `notion-fetch` 读取 `id: "self"`，核对实际工作区与用户。源目录没有图标，清单不声明图标资源。

## 3. 工具与 Skill

本包保留知识沉淀、会议准备、研究文档、需求实施计划 4 个工作流。允许以下 9 个工具，其他工具默认拒绝：

| 工具 | 策略 |
| --- | --- |
| `notion-search`、`notion-ai-search`、`notion-fetch`、`notion-query-data-sources`、`notion-get-async-task` | 只读，允许安全重试 |
| `notion-create-pages`、`notion-create-database`、`notion-create-comment` | 写入，需要确认，禁止重试 |
| `notion-update-page` | 可替换或删除已有页面内容，按破坏性操作处理，需要确认，禁止重试 |

调用使用 Poco 实际发现的工具及参数 Schema。页面创建或更新返回异步任务时，先查询任务状态再报告结果；查到失败不代表可以自动重新提交。需要确认的操作只能在 Poco 即时交互任务中执行。

文档中的数据库结构、页面链接和 ID 均为业务示例，使用前读取真实页面及数据源。不得将普通 REST API 请求结构直接当作 MCP 参数，也不得通过其他接口绕过白名单。

## 4. 验收

- 验证真实客户端注册、用户登录回调、工具发现，以及 `notion-fetch` 和工作区搜索。
- 在用户指定的页面中，确认后验证页面创建、更新、数据库和评论；如返回异步任务，核对最终状态和页面链接。
- 验证访问令牌刷新、刷新令牌轮换、撤销授权和权限错误。`invalid_grant` 需要重新授权，不反复刷新。
- 检查真实账号可用的搜索、筛选和数据源查询范围，不把套餐受限误报成“没有数据”。

本次移植已完成源码、JSON、文件引用、多语言、工具策略和源文件摘要检查；通过启用 TLS 证书校验的系统 curl 核对了公开 OAuth 元数据及无凭据请求返回的 401。本地 Python 网络检查因证书信任链缺失未通过，不代表目标 Poco 环境的 TLS 行为已验证。未完成上述账号验收，也未生成发布 ZIP。正式发布时再校验最终归档和 Poco Backend Loader。

## 来源

- [官方客户端接入文档](https://developers.notion.com/guides/mcp/build-mcp-client)
- [官方工具目录](https://developers.notion.com/guides/mcp/mcp-supported-tools)
- [受保护资源元数据](https://mcp.notion.com/.well-known/oauth-protected-resource/mcp)
- [OAuth 服务元数据](https://mcp.notion.com/.well-known/oauth-authorization-server)

核对日期：2026-09-12。源材料复用与许可情况见包内 `NOTICE`。
