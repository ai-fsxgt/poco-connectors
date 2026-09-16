# Poco 适配说明

上游版本：`larksuite/cli v1.0.95`

- 官方 Linux amd64 二进制、API 目录分片和保留的产品 Skills 均未修改。
- 未收录需要常驻事件进程的 `lark-event` Skill 与 `event` 命令，也未收录仅支持应用身份的 `lark-vc-agent` Skill。
- 未暴露依赖持久化本地项目、Git 凭据或插件状态的 `apps` 命令。
- 网页 OAuth 单次最多申请 200 个权限。连接器从实际命令元数据生成恰好 200 个授权范围，并按上游批量授权策略排除 `im:message.send_as_user`；因此不暴露消息发送、消息回复和邮件分享到聊天三个依赖该权限的快捷命令。
- Poco Provider 负责注入用户 OAuth 凭据、限制文件路径、映射风险等级和转换协议响应。
