# Poco 连接器

本仓库用于维护 Poco Agent 平台的可安装连接器。根目录下的每个连接器目录都是完整、独立的安装包源码，可单独开发、校验、打包、安装和发布；仓库本身不是一个需要整体构建的应用。

## 当前连接器

| 目录 | 连接器 | Key | 版本 | 主要能力 |
| --- | --- | --- | --- | --- |
| [`agentkey/`](./agentkey/) | AgentKey | `agentkey` | `1.0.0` | 网页、社交媒体、金融、电商和企业等实时数据查询 |
| [`dingtalk/`](./dingtalk/) | 钉钉 | `dingtalk` | `1.0.1` | 日程、待办、文档、云盘、聊天、通讯录及业务数据操作 |
| [`feishu/`](./feishu/) | 飞书 | `feishu` | `1.0.0` | 日历、任务、文档、云盘、表格、审批、聊天、邮件及业务数据操作 |
| [`ima-mcp/`](./ima-mcp/) | IMA | `ima-mcp` | `1.0.0` | IMA 知识库的浏览、检索与原文读取 |
| [`kdocs/`](./kdocs/) | 金山文档 | `kdocs` | `1.4.12` | 文档、表格、PDF、演示文稿、云盘与知识库操作 |
| [`qq-mail/`](./qq-mail/) | QQ 邮箱 | `qq-mail` | `1.0.0` | 邮件读取、搜索、发送、回复、转发、删除与附件获取 |
| [`tencent-docs/`](./tencent-docs/) | 腾讯文档 | `tencent-docs` | `1.0.0` | 在线文档、表格、文件与知识库操作 |
| [`weknora/`](./weknora/) | WeKnoraX 知识库 | `knowledge-base` | `1.0.2` | 检索用户已授权知识空间中的文档与知识 |

## 连接器目录结构

```text
example/
├── manifest.json       # 包信息、授权方式、运行时及工具策略
├── provider/           # Python Provider 与可选运行资源
├── locales/            # 各语言的界面文案
├── assets/             # 图标等展示资源
└── skills/             # 随连接器安装的 Agent Skill
```

连接器可以按自身需要增加 `patches/`、`NOTICE`、`PATCHES.md` 或构建脚本，但不应依赖其他连接器目录。通用设计与开发规范统一放在 [`docs/`](./docs/) 中。

## 开发流程

1. 新建独立且不含平台标识、版本号的连接器目录。
2. 编写 `manifest.json`，使用 `package_version` 管理版本。
3. 补齐所有声明语言的文案、图标和 Skill。
4. 仅在标准远程 MCP 无法表达协议时实现 Python Provider。
5. 校验当前连接器，通过真实服务验收后再生成 ZIP 包。

以 WeKnoraX 连接器为例，可在仓库根目录执行基础检查：

```bash
connector_dir=weknora
python -m compileall "$connector_dir/provider"
for file in "$connector_dir/manifest.json" "$connector_dir"/locales/*.json; do
  python -m json.tool "$file" >/dev/null
done
```

进入连接器目录后生成安装包：

```bash
zip -X -r ../weknora-1.0.2.zip . \
  -x '*/__pycache__/*' '*.pyc' '.DS_Store'
```

更完整的结构校验、Provider 协议、OAuth、工具策略和发布步骤见：

- [连接器安装包开发手册](./docs/connector-package-development.mdx)
- [可安装连接器框架设计](./docs/connector-framework-design.mdx)

## 安装与验收

在 Poco 管理后台上传单个连接器 ZIP，填写管理员配置并安装。随后分配 `feature.connector.<key>` 权限、发布连接器，并使用普通用户完成授权、工具发现和实际调用验收。更新时必须上传相同 Key 的更高语义版本。

## 安全说明

不要提交真实密钥、令牌或用户数据。Python Provider 和随包二进制会以受信任代码运行，合入前必须审查来源与行为；修改 vendored archive 时必须同步更新校验和。真实 OAuth、远程 MCP、网络、TLS 和权限行为必须在目标环境单独验证。
