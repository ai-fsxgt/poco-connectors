---
name: agent-usage-report
description: "分析 Agent 平台的使用情况并生成 HTML 报告：大家用 Agent 做了什么、成本花在哪、定时任务是否稳定、哪些部门在用、下一步建议。支持单日和最长 31 天的区间。触发关键词：Agent 使用分析、平台使用情况、使用日报、使用周报、使用月报、Agent 用了多少、成本分析、Token 消耗、哪些部门在用、定时任务运行情况。"
description_zh: "分析 Agent 平台的使用情况并生成 HTML 报告：用途分类、成本去向、定时任务健康度、部门渗透与建议。支持单日和最长 31 天的区间。"
description_en: "Analyze Agent platform usage and generate an HTML report covering what the platform is used for, cost drivers, scheduled task health, department adoption and recommendations. Supports a single day or ranges up to 31 days."
version: "1.0.0"
---

# Agent 平台使用分析

数据来自连接器工具 `get_usage_dataset`，需要使用管理员账号授权。分工如下：

- **脚本负责**：日期计算、统计、生成 HTML。
- **你负责**：判断每个工作项属于什么业务，写出结论和建议。

下文 `SKILL_DIR` 指本技能所在目录。

## 流程

严格按顺序执行，不要跳步。

### 1. 确定日期区间

把用户的说法映射成下面的参数之一，然后运行脚本：

| 用户说法 | 参数 |
|---|---|
| 今天 / 昨天 | `today` / `yesterday` |
| 本周 / 上周 | `this_week` / `last_week` |
| 本月 / 上月 | `this_month` / `last_month` |
| 最近 N 天 | `last_N_days`，例如 `last_7_days` |
| 具体起止日期 | `2026-10-01 2026-10-07` |

```bash
python3 SKILL_DIR/scripts/dates.py this_week
```

- 使用脚本输出的 `start_date` 和 `end_date`，不要自己推算星期或日期。
- 用户没说时间时，默认用 `yesterday`。
- 区间超过 31 天时，请用户缩短区间。

### 2. 获取数据

调用 `get_usage_dataset(start_date, end_date)`。工具会把数据集保存为工作区里的 `.json.gz` 文件，并返回文件路径，下文记为 `DATASET`。

- 不要直接读取或解压这个文件，后续一律交给脚本处理。
- 工作目录 `WORK_DIR` 使用 `usage-report/<start_date>_<end_date>`。

### 3. 给工作项分类

```bash
python3 SKILL_DIR/scripts/report.py items DATASET WORK_DIR
```

1. 读取 `WORK_DIR/items.md` 和 [references/classification.md](references/classification.md)。
2. 给每一组写出 `领域代码/产出物代码`。
3. 写入 `WORK_DIR/classification.json`。

必须覆盖所有组。只看摘要和标题判断业务用途，不要因为 Agent 写了代码就归为开发。

### 4. 统计并写结论

```bash
python3 SKILL_DIR/scripts/report.py stats DATASET WORK_DIR
```

脚本会先校验分类，通过后打印统计 JSON。报错时按提示修改 `classification.json` 后重新运行。

- **缺少或无效分类**：补全。
- **分类与标题或描述明显矛盾**：逐条复核。
  - 分错的直接改正。
  - 确认无误的在代码末尾加 `!`，例如 `"sales/app!"`。
  - 不要不看就全部加 `!`。

然后按 [references/writing.md](references/writing.md) 写 `WORK_DIR/insights.json`。

### 5. 生成报告

```bash
python3 SKILL_DIR/scripts/report.py render WORK_DIR
```

如果报错，按提示修改 `insights.json` 后重新运行。常见错误有三类：

- 格式错误。
- 条数或字数超限：精简文字，不要删掉数据依据。
- 文字中的数字在统计数据里找不到出处：删除这个数字，或改用统计 JSON 中的原始数字。

成功后按下面的格式回复用户，不要附加其他内容：

```
报告已生成：<报告文件路径>

<headline>

- <最重要的结论 1>
- <最重要的结论 2>
- <最重要的结论 3>
```

## 禁止事项

- 不要手写或修改 HTML，页面完全由 `render` 生成。不要另外输出 Markdown 版或其他样式的报告。
- 不要修改 `SKILL_DIR` 下的任何文件，包括脚本、模板和分类表。
- 不要编造数据。所有数字都必须来自 `stats` 的输出。
- 不要绕过脚本自行统计。
- 脚本运行时，如果出现 Python 异常（Traceback），停止并把完整错误告诉用户，不要自己修改脚本或绕过。注意区分：上文那些带修改提示的报错要按提示处理，不属于这一类。
- 工具报错时，如实告诉用户错误内容：
  - 授权失败：提示用户在连接器中用管理员账号重新授权。
  - 区间过长：请用户缩短区间。
