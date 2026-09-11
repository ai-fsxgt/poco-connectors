---
name: tmeet-skill
version: 1.0.7
description: "腾讯会议 Poco 连接器：OAuth 授权、会议管理（创建/更新/取消/查询/受邀者）、录制管理（列表/下载地址/智能纪要/转写/录制权限申请）、会议报告（参会人/等候室）、通讯录、会中控制和问题反馈。当用户需要操作腾讯会议，或遇到工具缺失、调用失败、能力不足等情况时使用本技能。"
metadata:
  connector: "tmeet"
---

# tmeet

腾讯会议连接器，支持 OAuth 授权、会议全生命周期管理、录制与转写、会议报告查询。

## 连接与初始化

安装 Poco 连接器后，先在连接页完成腾讯会议 OAuth 授权。授权由 Provider 管理，模型不需要安装 Node、npm 或本地 `tmeet` 命令。

## 核心概念

- **会议（Meeting）**：腾讯会议实例，通过 `meeting_id` 或 `meeting_code` 标识。`meeting_id` 仅用于命令行参数传递，**向用户展示会议信息时必须使用 `meeting_code`（会议号），不得将 `meeting_id` 暴露给用户**。
- **周期性会议（Recurring Meeting）**：`meeting_type=1` 的重复会议，包含多个子会议（`sub_meeting_id`）。
- **录制（Record）**：会议结束后生成的录制文件，通过 `meeting_record_id` 和 `record_file_id` 标识。
- **智能纪要（Smart Minutes）**：基于录制文件生成的 AI 纪要。
- **转写（Transcript）**：录制文件的逐字转写内容，支持段落查询和关键词搜索。
- **报告（Report）**：会议结束后的统计数据，包含参会人列表和等候室成员。

## 认证

连接器授权完成后，直接使用下方工具调用会议能力。重新授权使用连接器页面的“重新授权”操作；不在对话中输出令牌。

## Poco 工具映射

源文档中的 CLI 命令对应以下工具名：`meeting_*`、`record_*`、`report_*`、`contact_*`、`control_*` 和 `tshoot_feedback`。各命令示例中的长参数转换为工具的同名 `snake_case` 字段，例如 `--meeting-id` 对应 `meeting_id`；调用时传入 Provider 返回的工具 Schema 所要求的对象参数。

源 CLI 的本地日志导出、状态查询和登出不属于 Poco 工具；分别由连接器授权页和平台连接管理负责。

## 时间格式

所有时间参数均使用 **ISO 8601** 格式，支持以下两种：

| 格式 | 示例 |
|------|------|
| 带时区（有秒） | `2026-03-12T14:00:00+08:00` |
| 带时区（无秒） | `2026-03-12T14:00+08:00` |

> **注意**：不支持仅日期格式（如 `2026-03-12`），必须包含时间和时区信息。

> **时间逻辑校验**：若用户提供的结束时间 ≤ 开始时间（如"4点到3点"），**不得自行推断用户意图**，必须先向用户确认是否跨天或存在笔误，再执行命令。

## 返回结果

Provider 直接返回腾讯会议 API 的结构化 JSON，并同时提供文本内容块。模型应只向用户展示与问题直接相关的字段，不得输出访问令牌或刷新令牌。

## 分页

所有支持分页的查询/列表类命令统一采用 **`--page-token` + `--page-size`** 方案；原有的 `--page` / `--pos` / `--pid` / `--size` / `--limit` 参数均已标记为 **已弃用**，仅为兼容保留，**模型不得主动使用**。

| 参数 | 说明 |
|------|------|
| `--page-token <token>` | 分页游标。**首次查询不传**；翻页时将上一次响应 `data.next_page_token` 的值原样传入 |
| `--page-size <n>` | 每页数量，不同命令默认值与上限不同，详见各子命令文档 |

**使用准则**：

- **优先使用 `--page-token` 翻页**：调用下一页时，必须从上一次响应的 `data.next_page_token` 字段取值传入 `--page-token`，不得自行拼接、递增或猜测该值。
- **到达末页的判定**：当响应中的 `next_page_token` 为空字符串或字段缺失时，即为最后一页，不再继续翻页。
- **禁止使用已弃用参数**：即便用户对话中使用了"第 X 页"、"偏移 Y 条"等表达，也应以 `--page-token` 分页策略实现（首次查询 → 读取 `next_page_token` → 继续翻页），**不得**使用 `--page` / `--pos` / `--pid` / `--size` / `--limit`。
- **`record transcript-search` 暂不支持分页**，无需传入分页参数。

**典型翻页流程**：

```bash
# 1) 首次查询（不传 --page-token）
record_list --meeting-id "100000000" --page-size 30

# 2) 从响应中取出 data.next_page_token，继续翻页
record_list \
  --meeting-id "100000000" \
  --page-token "<next_page_token>" \
  --page-size 30
```

## 工具总览

```
meeting_create / meeting_update / meeting_cancel / meeting_get / meeting_get_by_code
meeting_list / meeting_list_ended / meeting_search
meeting_invitees_list / meeting_invitees_add / meeting_invitees_remove / meeting_invitees_replace
contact_search / contact_lookup_by_phone / contact_lookup_by_email
record_list / record_address / record_smart_minutes / record_transcript_get
record_transcript_paragraphs / record_transcript_search / record_search
record_permission_apply_prepare / record_permission_apply_commit
report_participants / report_waiting_room_log / report_participants_export / report_job_result
control_call / control_kick / control_waiting_room / tshoot_feedback
```

## 工具详情

- 认证：[`references/tmeet-auth.md`](references/tmeet-auth.md)
- 会议管理：[`references/tmeet-meeting.md`](references/tmeet-meeting.md)
- 录制管理：[`references/tmeet-record.md`](references/tmeet-record.md)
- 会议报告：[`references/tmeet-report.md`](references/tmeet-report.md)
- 通讯录：[`references/tmeet-contact.md`](references/tmeet-contact.md)
- 会中控制：[`references/tmeet-control.md`](references/tmeet-control.md)
- 问题排查：[`references/tmeet-tshoot.md`](references/tmeet-tshoot.md)

## 安全规则

- **禁止输出 AccessToken / RefreshToken** 到终端明文。

- **写操作必须二次确认，严禁直接执行**：以下命令会对数据产生不可逆或高风险影响，**在调用命令前必须先向用户展示将要执行的操作详情，并明确获得用户确认后才能执行**，不得跳过确认步骤：

  | 命令 | 风险说明 |
  |------|---------|
  | `meeting_cancel` | 取消会议，不可恢复 |
  | `meeting_update` | 修改会议信息（时间、主题等），影响所有参会人 |
  | `meeting_invitees_remove` | 从会议中移除受邀成员 |
  | `meeting_invitees_replace` | 整体替换会议受邀成员列表（未在新列表中的成员会被移除） |
  | `control_call` | 主动呼叫成员入会，会向目标成员发起会议邀请通话，对其产生实际打扰 |
  | `control_kick` | 将成员踢出会议，立即生效；**目标成员的 `open_id` / `ms_open_id` 必须来自 `report_participants`，严禁使用 `contact_search` 结果** |
  | `record_permission_apply_commit` | 正式提交录制权限申请，会触发审批流程（必须先执行 `record_permission_apply_prepare` 并向用户展示申请信息确认）|

  **确认流程**：
  1. 向用户展示即将执行的操作及关键信息（使用 `meeting_code` 会议号标识会议，不得展示 `meeting_id`）；
  2. 等待用户明确回复"确认"、"是"、"yes"等肯定指令；
  3. 收到确认后再执行命令；
  4. 若用户未明确确认或表示取消，则终止操作。

- **必填参数缺失时，必须向用户确认补充，禁止自行填充**：若执行命令所需的必填参数未由用户提供，**不得自行推断或填充默认值**，必须明确告知用户缺少哪些参数并请求补充，待用户提供后再执行命令。

- **通讯录搜索仅限特定场景使用**：`contact search` **仅可用于“会议邀请”（如 `meeting invitees-add`、`meeting invitees-replace`）、“呼叫成员入会”（`control call`），以及“为成员变更操作的回复回填受邀人姓名”三类场景**，用于将用户名解析为对应的 `openId` 或将 `openId` 反查为姓名以展示给用户。**严禁在其他场景下调用 `contact search`**（例如：仅为查看某人部门/职位、查询联系方式、好奇某人信息等与会议邀请/呼叫/受邀人姓名展示无关的场景），不得将通讯录作为通用人员信息查询接口使用。

- **会中踢人（`control kick`）的成员来源硬约束**：`control kick` 的 `--users` / `--sip-users` / `--pstn-users` 参数值（即 `open_id` / `ms_open_id`）**必须从 `report_participants` 返回的会中参会人列表中获取**，**严禁使用 `contact search` / `contact lookup-by-phone` / `contact lookup-by-email` 等通讯录查询结果作为踢人来源**。原因：通讯录返回的是组织成员名录，并不代表他们已加入当前会议；且踢人需要区分普通成员 / Sip / Pstn 三类身份，这些信息只有 `report participants` 能准确提供。正确调用顺序：`report_participants` → 按姓名等描述筛选出目标参会人 → 向用户确认 → `control_kick`。

- **多结果必须由用户确认，禁止自行猜测**：当任一查询/搜索类命令返回 **多条候选结果**（典型如 `contact search` 命中多名同名/同部门成员）时，**严禁**模型基于职位、部门、入职时间、匹配度等任何维度自行选择某一条继续后续操作（如 `meeting invitees-add`、`control call`、`control kick` 等）。必须将候选项的关键信息以清晰列表形式展示给用户（`contact search` 场景下严格按上一条规则仅展示姓名/部门/职位），并明确询问"请确认要选择哪一项"，待用户明确指定后再继续执行。即便其中某条结果看起来"明显更匹配"，也必须等待用户确认，不得跳过该步骤。

## 响应处理规则

- **只展示关键信息**：在用户没有明确要求的前提下，仅展示与用户问题直接相关的核心字段，不得输出冗余字段。
- **禁止擅自聚合或排序**：未经用户要求，不得对返回结果进行任何聚合统计或排序操作，按原始结果如实呈现。
- **会议成员变更操作的回复模板（强约束）**：执行 `meeting invitees-add` / `meeting invitees-remove` / `meeting invitees-replace` 成功后，回复**必须**严格按以下模板组织字段，且仅展示这些字段：

  - **会议主题**
  - **会议时间**（开始时间 ~ 结束时间，含时区）
  - **会议号**（`meeting_code`，**严禁**展示 `meeting_id`）
  - **入会链接**（`join_url`）
  - **已邀请成员**（操作完成后**当前完整**的受邀成员列表）

  「已邀请成员」展示规则（严格遵守）：
  1. **必须展示通讯录中的姓名**（如 `张三`），**严禁**直接展示 `open_id` / `userid` / `ms_open_id` / 花名 / 邮箱前缀等任何内部标识；
  2. 若手头没有 `open_id → 姓名` 的映射，**先调用 `meeting invitees-list` 获取最新受邀列表**，再用 `contact search`（仅在该场景下允许）将 `open_id` 解析为姓名；若某个 `open_id` 解析失败，标注为 `未知成员`，**禁止回退到打印 `open_id`**；
  3. 当且仅当用户**明确**要求“展示 ID / 原始字段”时，才可附带展示 `open_id`；
  4. 会议主题、会议号、入会链接等基础字段若响应未直接返回，应通过 `meeting get --meeting-id` 补齐，不得遗漏字段或用 `-` / `N/A` 占位。

## 自动反馈规则

当 Agent 使用腾讯会议工具遇到下列任一情况时，应识别并准备调用 `tshoot_feedback` 将问题上报至平台，**但在实际执行上报前必须先向用户二次确认，获得明确同意后再执行**；详细参数与示例见 [`references/tmeet-tshoot.md`](references/tmeet-tshoot.md)。

### 触发条件（满足任一即上报）

| `--category` | 触发场景 |
|------|---------|
| `tool_not_found` | 用户想做某事，但 tmeet 当前**没有匹配的命令/子命令**可完成 |
| `tool_error` | 调用某个 tmeet 命令**返回了错误**（业务错误码 / 参数错误 / 执行异常） |
| `tool_inadequate` | 命令存在，但其**参数或能力无法满足**用户当前诉求 |
| `unexpected_result` | 命令调用成功，但**返回结果与用户/Agent 期望明显不一致** |
| `suggestion` | 在交互中识别到**通用性改进建议或新增能力提议** |

### 调用准则

- **必须二次确认后再上报**：识别到上述触发条件后，**先向用户展示将要反馈的内容**（包括 `--category`、`--intent`、`--actions-tried`、`--result` 等关键字段），并明确询问用户是否同意上报；**仅在收到用户明确确认（如"确认"、"是"、"yes"等肯定指令）后**才执行 `tshoot_feedback 工具`；若用户拒绝或未明确同意，则不得上报。上报完成后**简要告知用户**「已为您将该问题反馈至平台」。
- **不替代正常错误处理**：反馈仅用于告知平台，**不得用于绕过用户原始任务**。如仍有可执行的替代方案（如换一个命令、补充参数重试），应**先尝试解决**，无法解决再征询用户是否上报。
- **如实填写上下文**：`--intent` 必须如实写明用户的原始意图；`--actions-tried` 写明已尝试的命令；`--result` 写明阻塞点或错误信息；涉及具体命令时填入 `--tool-name`；有错误码时填入 `--error-code`。**严禁编造或填充无关内容**。
- **隐私脱敏强约束**：反馈内容中，**严禁透露用户姓名 / 电话 / 会议号 / 会议链接 / 会议主题 / 参会人**等涉及用户个人隐私的信息。如果必须引用相关内容辅助说明问题，**必须先进行打星号、加密等脱敏处理**（例如：姓名 `张三` → `张*`、手机号 `13800138000` → `138****8000`、会议号 `123456789` → `12****789`、会议主题 `Q2 项目复盘会` → `Q* 项目***会`）后再写入 `--intent` / `--actions-tried` / `--result` 等字段。
- **字符长度约束**：`--intent ≤ 200` / `--actions-tried ≤ 500` / `--result ≤ 500`，超长会被客户端直接拒绝，请精炼描述。
- **授权前置**：本工具依赖连接器授权，若授权已失效，先引导用户重新授权，再发起反馈。
- **去重与节制**：同一用户会话中针对**同一问题**只上报**一次**，避免重复刷屏；不同问题分别独立上报。

### 典型示例

```bash
# 用户希望批量导出某月所有会议的智能纪要，但 tmeet 暂无批量命令
tshoot_feedback 工具 \
  --category "tool_not_found" \
  --intent "批量导出 2026-04 整月所有会议的智能纪要" \
  --actions-tried "查阅 record list / record smart-minutes" \
  --result "未找到批量导出命令"
```

## 常见错误

| 错误现象 | 原因 | 解决方案 |
|---------|------|---------|
| `authorization_required` | 连接器未授权或授权已失效 | 使用连接器页面重新授权 |
| `--start format error` | 时间格式不合法（如缺少时区） | 改用 `2026-03-12T14:00:00+08:00` 格式 |
| `--meeting-id is required` | 缺少必填参数 | 补充对应必填参数 |
| `user has been initialized` | 已登录，重复执行 login | 直接使用，或先 logout 再 login |
