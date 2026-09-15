# Canva 可画安装与授权配置

本包使用中国区 MCP 服务和 OAuth 动态客户端注册（DCR）。管理员不需要手动创建或填写 OAuth Client ID、Client Secret；连接器会在用户发起连接时，使用 Poco 当前的真实回调地址注册独立客户端。

## 1. 确定并登记回调地址

回调地址由 Poco 后端的公开 HTTPS 地址决定：

```text
${BACKEND_URL}/api/v1/connectors/oauth/callback
```

例如后端地址为 `https://poco.example.com`，完整回调地址就是：

```text
https://poco.example.com/api/v1/connectors/oauth/callback
```

必须将完整地址提交给可画并加入 OAuth 回调地址允许列表。协议、域名、端口、路径和末尾斜杠都必须与实际授权请求完全一致；连接器不能绕过可画的允许列表校验。

## 2. 配置 Poco

管理员只需保留以下配置：

| 管理员字段 | 填写内容 |
| --- | --- |
| MCP 服务地址 | `https://mcp.canva.cn/mcp` |

连接器固定校验中国区服务地址，防止 OAuth 客户端凭据或用户令牌发送到其他服务。

## 3. 用户授权流程

1. 用户在 Poco 中点击连接可画。
2. Provider 使用本次授权的真实 `redirect_uri` 向 `https://mcp.canva.cn/register` 注册 OAuth 客户端。
3. Provider 使用注册结果、PKCE S256 和所需权限生成官方授权地址。
4. 用户登录并同意授权后，可画携带授权码返回 Poco。
5. Provider 在服务端换取访问令牌和刷新令牌；客户端密钥和令牌均由 Poco 加密保存。
6. 访问令牌过期后，Poco 使用该连接自己的客户端凭据和刷新令牌续期。

每次连接使用独立的动态客户端，避免管理员手动注册的回调地址与当前部署地址不一致。不要在聊天、日志、包文件或 Git 中记录客户端密钥、授权码和令牌。

## 4. 验收与已知限制

- 先验证登录回调、授权范围和工具发现，再执行 `search-designs` 或 `get-design` 等只读查询。
- 通过用户确认后，验证所需的生成、模板填充、编辑提交、导入、导出及评论能力。
- 验证令牌过期后的刷新、用户撤销授权后的错误提示，以及实际账号权限和套餐限制。
- 可用工具以中国区服务实际返回且被本包允许的工具为准，不把国际版套餐说明作为中国区承诺。
- Canva 当前推荐 CIMD，并将 DCR 标记为兼容能力。Poco 尚未支持 CIMD，因此本包使用中国区服务当前仍公开支持的 DCR；如果服务停止提供 DCR，需要先为 Poco 增加 CIMD 支持。
- Canva 建议 `generate-design` 使用 60 秒超时，Poco 当前远程调用上限为 30 秒。结果不确定时先核对状态，不自动重复提交写入。
- 发布前需使用已进入允许列表的真实回调地址完成 OAuth、刷新、撤销和工具调用验收。

## 来源

- [中国区受保护资源元数据](https://mcp.canva.cn/.well-known/oauth-protected-resource/mcp)
- [中国区 OAuth 服务元数据](https://mcp.canva.cn/.well-known/oauth-authorization-server)
- [官方 MCP 接入说明](https://www.canva.dev/docs/mcp/)
- [官方手动注册与超时说明](https://www.canva.dev/docs/mcp/troubleshooting/)
- [官方工具目录](https://www.canva.dev/docs/mcp/tools/)
