---
name: github
description: "Use the GitHub connector in POCO to search repositories and code, manage files and issues, work with pull requests, and query users and teams."
description_zh: "通过 POCO 的 GitHub 连接器搜索仓库和代码、管理文件与 Issue、处理 PR，并查询用户和团队。"
description_en: "Use the GitHub connector in POCO to search repositories and code, manage files and issues, work with pull requests, and query users and teams."
version: 1.0.0
---

该 Skill 需要调用 POCO 中 `github` 连接器实际发现的工具。

## 授权

- 用户在 POCO 的 GitHub 授权表单中填写个人访问令牌（PAT）。POCO 加密保存令牌并注入 `Authorization: Bearer <token>`；不要要求用户在对话或工具参数中提供令牌。
- 使用 `get_me` 确认当前账号。仓库可见范围和可执行操作由 PAT 权限、用户权限与组织策略决定。
- 认证失败时提示用户在 POCO 中重新授权。权限不足时说明缺少的访问权限，不要求扩大与当前操作无关的权限。

## 工具范围

工具白名单依据 GitHub 官方 MCP Server v1.12.1 文档中的 `context`、`repos`、`issues`、`pull_requests`、`users` 工具集。远程服务会独立更新，调用时以当前任务发现的工具名称和参数 Schema 为准；文档中出现的工具不代表当前账号一定可用。

| 用途 | 工具 |
| --- | --- |
| 账号与团队 | `get_me`、`get_teams`、`get_team_members`、`search_users` |
| 仓库和代码搜索 | `search_repositories`、`search_code`、`search_commits` |
| 文件、提交与分支读取 | `get_file_contents`、`get_commit`、`list_commits`、`list_branches`、`list_repository_collaborators` |
| 标签与发布版本读取 | `list_tags`、`get_tag`、`list_releases`、`get_latest_release`、`get_release_by_tag` |
| 仓库与文件写入 | `create_repository`、`fork_repository`、`create_branch`、`create_or_update_file`、`push_files`、`delete_file`、`delete_repository` |
| Issue 查询 | `issue_read`、`list_issues`、`search_issues`、`get_label`、`list_issue_types`、`list_issue_fields` |
| Issue 和评论写入 | `issue_write`、`add_issue_comment`、`sub_issue_write` |
| PR 查询 | `pull_request_read`、`list_pull_requests`、`search_pull_requests` |
| PR 写入与评审 | `create_pull_request`、`update_pull_request`、`update_pull_request_branch`、`merge_pull_request`、`pull_request_review_write`、`add_comment_to_pending_review`、`add_reply_to_pull_request_comment` |

`get_label` 查询仓库标签定义；Issue 的标签和字段通过 `issue_write` 管理。工具集不包含 GitHub Actions 工作流触发或日志工具；PR 检查结果通过 `pull_request_read` 查询。

## 操作流程

### 查询仓库与代码

1. 从用户提供的链接确定 `owner`、`repo`、分支或提交；不明确时先搜索仓库。
2. 搜索时用 `repo:owner/repo` 限定范围。使用 `get_file_contents` 读取相关文件，需要固定版本时传入工具支持的 `ref` 或 `sha`。
3. 按工具 Schema 使用页码或游标继续获取结果，不将第一页当作完整结果。返回结论时附上仓库、文件或提交链接。

### 修改文件

1. 确定目标仓库、分支、路径与修改内容，先读取该分支当前文件。
2. `create_or_update_file` 更新已有文件时需要当前文件的 blob SHA，不能拿提交 SHA 代替。在此文档对应的官方版本中，`content` 接收原文，不需要 Base64 编码；实际调用遵循当前工具 Schema。
3. 多文件提交使用 `push_files`。提交前展示目标分支、变更内容及提交信息，通过 POCO 确认后执行。
4. 写入后查询目标分支或提交确认结果；不要把远程工具中的文件路径当作 POCO 本地文件路径。

### 处理 Issue 与 PR

1. 先通过查询工具读取目标 Issue 或 PR；区分 Issue 编号、PR 编号、评论 ID 和子 Issue ID。
2. 创建或更新 Issue 使用 `issue_write`，维护父子关系使用 `sub_issue_write`。`issue_read` 和 `pull_request_read` 的 `method` 应按查询内容选择。
3. 代码审查时先读取差异、检查结果及现有评论，整理意见。发布评论、评审、批准或请求修改前取得用户确认。
4. 待提交评审保存在 GitHub。添加行内评审意见前先确认存在当前用户的待提交评审，再用 `add_comment_to_pending_review`；提交使用 `pull_request_review_write` 的 `submit_pending`。
5. 合并或更新 PR 分支前重新读取 PR 状态，并在当前 Schema 支持时传入刚读取的 `expectedHeadSha`；目标分支、合并方式和完整参数须通过 POCO 确认。

## 操作确认与错误处理

- 文件提交、仓库创建、评论、评审、Issue 更新和 PR 合并等写入操作均需通过 POCO 确认，禁止自动重试。
- `delete_file`、`delete_repository` 为破坏性操作。`sub_issue_write` 包含移除或替换父子关系，`pull_request_review_write` 包含删除待提交评审，POCO 按工具最高风险统一要求破坏性操作确认。
- POCO 每次工具调用新建 MCP 会话，不能依赖上一次会话中的动态工具集开关。只调用当前任务已发现且获准的工具，不通过 CLI 或自构造 API 请求绕过工具策略。
- 调用超时、网络错误或 GitHub 返回错误时如实说明。写入结果不确定时，先通过只读工具核对是否已经生效；不要再次提交写入来确认结果。
- 调用时限由 POCO 管理，不能沿用源客户端的 `timeout: 600` 设置。认证校验和工具发现成功也不代表所有仓库写入权限均已验证。
