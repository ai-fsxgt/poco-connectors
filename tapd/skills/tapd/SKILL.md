---
name: tapd-skill
description: TAPD 敏捷项目管理技能 - 管理需求、缺陷、任务、迭代、测试用例、Wiki、工时、评论和工作流
version: "1.0.0"
author: "TAPD"
---

# TAPD Skill

TAPD 是腾讯敏捷研发管理平台，覆盖需求、计划、研发、测试、发布研发全生命周期。本 Skill 支持用自然语言与 TAPD 对话，与 TAPD API 无缝集成，提升开发效率。

## Poco 调用约定

- 本 Skill 通过 Poco 的 TAPD 连接器调用官方远程 MCP。管理员先按[安装与授权配置](references/setup.md)配置 OAuth 客户端，用户再在 Poco 中授权自己的 TAPD 账号。
- 下方工具名对应 MCP 上游名称。仅使用 Poco 当前实际暴露的工具，参数以工具发现返回的 schema 为准；本包白名单之外的工具默认拒绝。
- 创建、更新、状态流转、关联关系、评论和工时填写均为写操作。调用前确认目标项目、对象和完整参数，通过 Poco 的确认流程执行；发生超时或结果不确定时，先查询实际状态，不自动重复提交。
- 每次调用独立建立 MCP 会话，需要项目 ID 的工具应显式传入 `workspace_id`，不要依赖上一次调用保留项目上下文。

## 支持的功能

- **待办**：获取需求、缺陷、任务的待办
- **项目**：查询项目信息和配置、获取用户参与的项目
- **需求**：查询/创建/更新需求、查询字段配置/工作流/附件
- **缺陷**：查询/创建/更新缺陷、查询字段配置
- **任务**：查询/创建/更新任务、查询字段配置
- **源码关键字**：获取需求/缺陷/任务的源码提交关键字，将 commit 与工作项关联
- **迭代**：查询/创建/更新迭代
- **评论**：添加/更新/获取评论
- **关联关系**：获取和创建需求与缺陷的关联关系
- **工时花费**：填写/更新/查询工时
- **Wiki**：创建/更新/获取 Wiki
- **测试用例**：创建/更新/获取测试用例（支持批量创建）
- **发布计划**：根据发布计划查询需求、查询指定日期发布的需求

## 重要约定

- 大部分工具需要 `workspace_id`（项目 ID）。如果用户没有指定，先调用 `get_user_participant_projects` 获取项目列表，过滤掉 `category` 为 `organization` 的记录。
- 使用自定义字段（`custom_field_*`）查询前，**必须先调用 `get_entity_custom_fields`** 获取字段配置。
- 流转需求状态前，先调用 `get_workflows_all_transitions` 查询当前状态可流转的目标状态。
- 返回给用户的数据中包含链接时，链接要可点击。

---

## 可用工具

### 项目与用户

#### get_user_participant_projects - 获取用户参与的项目

获取当前用户或指定用户参与的所有项目列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| nick | string | - | 用户昵称，不传则从 Token 自动获取 |

**使用场景**：用户未指定 workspace_id 时，先调此接口让用户选择项目。注意过滤掉 `category` 为 `organization` 的记录。

#### get_workspace_info - 获取项目信息

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |

---

### 需求 / 任务（Story / Task）

#### get_stories_or_tasks - 查询需求或任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entity_type | string | ✅ | `stories`（需求）或 `tasks`（任务） |
| options.name | string | - | 标题，支持模糊匹配 `%关键词%` |
| options.v_status | string | - | 状态别名（支持中文） |
| options.owner | string | - | 处理人 |
| options.iteration_id | string | - | 迭代 ID |
| options.iteration_name | string | - | 迭代名称（自动解析为 ID） |
| options.priority_label | string | - | 优先级：High/Middle/Low/Nice To Have |
| options.limit | int | - | 返回数量，默认 10 |
| options.page | int | - | 页码，默认 1 |
| options.fields | string | - | 指定字段，逗号分隔。获取详细描述需包含 `description` |

**注意**：如果未传 limit，需提醒用户剩余数量。任务状态只有 `open`/`progressing`/`done`。

#### get_story_or_task_count - 获取需求或任务数量

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entity_type | string | ✅ | `stories` 或 `tasks` |

#### create_story_or_task - 创建需求或任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| name | string | ✅ | 标题 |
| options.entity_type | string | ✅ | `stories` 或 `tasks` |
| options.description | string | - | 描述（支持 Markdown） |
| options.owner | string | - | 处理人 |
| options.priority_label | string | - | 优先级 |
| options.iteration_id | string | - | 迭代 ID |

#### update_story_or_task - 更新需求或任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entity_type | string | ✅ | `stories` 或 `tasks` |
| options.id | string | ✅ | 需求或任务 ID |
| options.v_status | string | - | 状态（中文名） |
| options.name | string | - | 新标题 |

**注意**：流转需求状态前先调 `get_workflows_all_transitions` 查可流转状态。

#### get_stories_fields_info - 获取需求字段及候选值

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |

#### get_stories_fields_lable - 获取需求字段中英文映射

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |

#### get_entity_custom_fields - 获取自定义字段配置

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entity_type | string | ✅ | `stories`/`tasks`/`iterations`/`tcases`/`bugs` |

#### get_workitem_types - 获取需求类别

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |

---

### 缺陷（Bug）

#### get_bug - 查询缺陷

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.title | string | - | 标题 |
| options.status | string | - | 状态，支持枚举 `s1|s2|s3` |
| options.priority_label | string | - | 优先级：urgent/high/medium/low/insignificant |
| options.severity | string | - | 严重程度：fatal/serious/normal/prompt/advice |
| options.limit | int | - | 返回数量，默认 10 |

#### get_bug_count - 获取缺陷数量

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |

#### create_bug - 创建缺陷

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| title | string | ✅ | 缺陷标题 |
| options.description | string | - | 描述（Markdown） |
| options.priority_label | string | - | 优先级 |
| options.severity | string | - | 严重程度 |
| options.current_owner | string | - | 处理人 |

#### update_bug - 更新缺陷

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.id | string | ✅ | 缺陷 ID |
| options.v_status | string | - | 状态（中文名） |

#### get_related_bugs - 获取需求关联的缺陷

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.story_id | string | ✅ | 需求 ID，支持多 ID |

---

### 迭代（Iteration）

#### get_iterations - 查询迭代

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | - | 迭代名称 |
| options.status | string | - | 状态：`open`/`done` |

#### create_iteration - 创建迭代

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | ✅ | 迭代名称 |
| options.startdate | string | ✅ | 开始日期 |
| options.enddate | string | ✅ | 结束日期 |
| options.creator | string | ✅ | 创建人 |

#### update_iteration - 更新迭代

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.id | string | ✅ | 迭代 ID |
| options.current_user | string | ✅ | 变更人 |

---

### 评论（Comment）

#### get_comments - 查询评论

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entry_id | string | - | 业务对象 ID |
| options.entry_type | string | - | 类型：`bug`/`stories`/`tasks` |

#### create_comments - 添加评论

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entry_id | string | ✅ | 业务对象 ID |
| options.entry_type | string | ✅ | 类型：`bug`/`stories`/`tasks` |
| options.author | string | ✅ | 评论人 |
| options.description | string | ✅ | 评论内容 |

#### update_comments - 更新评论

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.id | string | ✅ | 评论 ID |
| options.description | string | ✅ | 新内容 |
| options.change_creator | string | ✅ | 变更人 |

---

### 测试用例（TCase）

#### get_tcases - 查询测试用例

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | - | 用例名称 |
| options.status | string | - | 状态：`updating`/`abandon`/`normal` |
| options.limit | int | - | 返回数量，默认 30 |

#### create_or_update_tcases - 创建/更新测试用例

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | - | 用例名称 |
| options.steps | string | - | 用例步骤 |
| options.expectation | string | - | 预期结果 |
| options.precondition | string | - | 前置条件 |

#### create_tcases_batch - 批量创建测试用例

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.tcases | list | ✅ | 用例列表，每个元素含 name 等字段，最多 200 条 |

---

### Wiki

#### get_wiki - 查询 Wiki

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | - | 标题 |
| options.limit | int | - | 返回数量，默认 30 |

#### create_wiki - 新建 Wiki

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | ✅ | 标题 |
| options.markdown_description | string | - | Markdown 内容 |
| options.creator | string | ✅ | 创建人 |

#### update_wiki - 更新 Wiki

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.id | string | ✅ | Wiki ID |
| options.markdown_description | string | - | 新内容（Markdown） |

---

### 工作流（Workflow）

#### get_workflows_all_transitions - 获取工作流流转规则

查询当前状态可以流转到哪些目标状态。流转需求/缺陷状态前**必须先调用此工具**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.system | string | ✅ | `story`（需求）或 `bug`（缺陷） |
| options.workitem_type_id | string | ✅ | 需求类别 ID |

#### get_workflows_status_map - 获取状态中英文映射

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.system | string | ✅ | `story` 或 `bug` |
| options.workitem_type_id | string | ✅ | 需求类别 ID |

#### get_workflows_last_steps - 获取工作流结束状态

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.system | string | ✅ | `story` 或 `bug` |

---

### 工时（Timesheet）

#### get_timesheets - 查询工时

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.owner | string | - | 工时创建人 |
| options.spentdate | string | - | 花费日期 YYYY-MM-DD |
| options.entity_type | string | - | 对象类型：`story`/`task`/`bug` |

#### add_timesheets - 填写工时

填写前建议先调 `get_timesheets` 查看该日期是否已有记录，已有则用 `update_timesheets` 更新。

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entity_type | string | ✅ | `story`/`task`/`bug` |
| options.entity_id | string | ✅ | 对象 ID |
| options.timespent | string | ✅ | 花费工时 |
| options.spentdate | string | - | 花费日期 YYYY-MM-DD |

#### update_timesheets - 更新工时

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.id | string | ✅ | 工时记录 ID |
| options.timespent | string | ✅ | 新花费工时 |

---

### 附件与图片

#### get_image - 获取图片下载链接

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.image_path | string | ✅ | 图片路径或完整 URL |

**注意**：每次只能获取一张图片，下载链接有效期 300 秒。

#### get_entity_attachments - 获取附件下载链接

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.entry_id | string | ✅ | 业务对象 ID |
| options.type | string | ✅ | `story` 或 `bug` |

---

### 其他工具

#### get_todo - 获取待办

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | - | 项目 ID |
| entity_type | string | ✅ | `story`/`bug`/`task` |
| limit | int | - | 返回数量，默认 10 |

#### entity_relations - 创建关联关系

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.source_type | string | ✅ | `story` 或 `bug` |
| options.target_type | string | ✅ | `story` 或 `bug` |
| options.source_id | string | ✅ | 源对象 ID |
| options.target_id | string | ✅ | 目标对象 ID |

#### get_release_info - 获取发布计划

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.name | string | - | 名称，模糊匹配 |
| options.status | string | - | `open` 或 `done` |

#### get_commit_msg - 获取源码提交关键字

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| workspace_id | int | ✅ | 项目 ID |
| options.object_id | string | ✅ | 对象 ID |
| options.type | string | ✅ | `story`/`task`/`bug` |

---

## 常见使用流程

### 查询项目下的需求

1. 调用 `get_user_participant_projects` 获取项目列表
2. 用户选择项目后，调用 `get_stories_or_tasks`（entity_type=stories）

### 按自定义字段查询

1. 调用 `get_entity_custom_fields` 获取自定义字段配置
2. 使用返回的 `custom_field_*` 作为查询参数

### 流转需求状态

1. 调用 `get_workitem_types` 获取需求类别 ID
2. 调用 `get_workflows_all_transitions` 查询可流转状态
3. 调用 `update_story_or_task` 更新状态

### 填写工时

1. 调用 `get_timesheets` 查看指定日期是否已有记录
2. 如无记录，调用 `add_timesheets`；如有记录，调用 `update_timesheets`

## 注意事项

- 首次使用需在 Poco 完成 TAPD OAuth 授权，可访问的数据取决于用户的授权范围和项目权限
- TAPD 签发刷新令牌时由 Poco 管理刷新；授权失效或刷新失败时提示用户在 Poco 重新授权，不自行获取或处理用户令牌
- 描述字段支持 Markdown 格式，会自动转换为 HTML
- 单次查询默认返回 10-30 条，可通过 `limit` 和 `page` 参数分页
