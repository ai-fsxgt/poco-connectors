# 认证详情

POCO 通过连接器授权表单保存金山文档用户 Token，并由随包 Provider 以 Bearer Token 调用官方 MCP 服务。

## 获取 Token

1. 在浏览器打开 [金山文档](https://www.kdocs.cn/latest)，登录 WPS 账号。
2. 打开页面右上角个人菜单中的「龙虾专属入口」。
3. 复制 Token，并粘贴到 POCO 的金山文档连接授权表单。

提交时 Provider 会调用只读的最近文件接口验证 Token，并检查业务状态码；连接成功或工具目录可见不代表授权有效。验证结果不保存文件内容。

Token 由 POCO 加密保存，不要写入 Skill、脚本、环境变量或普通文件。

## 服务请求

Provider 固定调用 `https://mcp-center.wps.cn/skill_hub/mcp`，并发送以下请求头：

- `Authorization: Bearer <Token>`
- `X-Skill-Version: 1.4.12`
- `X-Request-Source: poco`

如果工具调用返回鉴权失败，请在 POCO 连接器详情页重新授权并提交新的 Token。
