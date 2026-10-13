"""Turn an agent-usage-report dataset into an HTML report.

Usage:
    python3 report.py items  <dataset.json.gz> <work_dir>  # -> items.md
    python3 report.py stats  <dataset.json.gz> <work_dir>  # needs classification.json -> stats.json
    python3 report.py render <work_dir>                    # needs stats.json, insights.json -> report HTML
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from render import render_html

SKILL_DIR = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((SKILL_DIR / "assets" / "taxonomy.json").read_text())
ZONE = ZoneInfo("Asia/Shanghai")
TRIGGER_NAMES = {
    "scheduled": "定时任务",
    "chat": "人工对话",
    "api": "API 集成",
    "embed": "嵌入对话",
}
PRIVATE = "private"
PRIVATE_NAME = "隐私内容（不可见）"
SUMMARY_CHARS = 100
TOP_N = 10
# A scheduled task with at least this many runs and this failure+cancel ratio is unstable.
UNSTABLE_MIN_RUNS = 3
UNSTABLE_RATIO = 0.2
PRIORITIES = ("P0", "P1", "P2")
# Layout limits for insights.json: (min items, max items, max chars per field).
HEADLINE_MAX_CHARS = 50
INSIGHT_LIMITS = {
    "summary": (2, 4, 100),
    "highlights": (2, 4, {"ref": 0, "value": 100}),
    "actions": (3, 6, {"priority": 0, "title": 24, "evidence": 90, "action": 90}),
}
CANDIDATES_PER_DOMAIN = 3
PARETO_ITEMS = 20
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
# Small plain integers stay free for dates and counting words such as "3 条" or "10 月".
FREE_INTEGER_MAX = 12
DEBUG_WORDS = re.compile(
    r"修复|排查|测试|调试|配置|修改|报错|故障|异常原因|授权|安装|认证"
)
# Stats fields holding percentages; a "%" in the insights must match one of these.
PERCENT_KEY_SUFFIXES = ("_rate", "_share", "_change")
# Runs that happen without a person starting them in the chat UI.
AUTOMATED_TRIGGERS = ("scheduled", "api")


# ---------------------------------------------------------------- data


def load_dataset(path: str) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return json.load(file)


def build_groups(dataset: dict) -> list[dict]:
    """Group visible work items that share a trigger and normalized title."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in dataset["work_items"]:
        if item["content_visible"]:
            title = re.sub(r"#\d+$", "", (item["title"] or "").strip()) or "（无标题）"
            groups[(item["trigger"], title)].append(item)

    ordered = sorted(
        groups.items(), key=lambda pair: -sum(i["cost_usd"] for i in pair[1])
    )
    result = []
    for index, ((trigger, title), items) in enumerate(ordered, 1):
        top = max(items, key=lambda i: i["cost_usd"])
        result.append(
            {
                "group_id": f"g{index:03d}",
                "trigger": trigger,
                "title": title,
                "item_ids": [i["item_id"] for i in items],
                "runs": sum(i["runs"] for i in items),
                "cost_usd": sum(i["cost_usd"] for i in items),
                "is_fork": any(i["is_fork"] for i in items),
                "description": describe(top),
            }
        )
    return result


def describe(item: dict) -> str:
    """AI session summary, or the user's first request when no summary exists yet."""
    if item["summary"]:
        return item["summary"][:SUMMARY_CHARS]
    if item["request"]:
        return "[用户提问] " + item["request"][:SUMMARY_CHARS]
    return "无描述"


def contradiction(group: dict, domain: str, deliverable: str) -> str | None:
    """Return why a deliverable obviously contradicts its title or description."""
    title = group["title"]
    text = f"{title} {group['description']}"
    if not group["is_fork"]:
        if re.search(r"ppt|演示文稿", title, re.I) and deliverable != "document":
            return "标题是 PPT 或演示文稿，产出物通常是 document"
        if (
            "推送" in title
            and group["trigger"] == "scheduled"
            and deliverable != "alert"
        ):
            return "定时推送任务，产出物通常是 alert"
        if "看板" in title and deliverable not in ("dashboard", "app"):
            return "标题是看板，产出物通常是 dashboard"
        if re.search(r"报告|日报|周报|月报|简报", title) and deliverable in (
            "app",
            "qa",
            "review",
            "debug",
        ):
            return "标题是报告，产出物通常是 report 或 document"
    # Platform setup work (test messages, skill installs, demos) is debug by definition.
    if (
        deliverable == "debug"
        and domain != "ai_platform"
        and not group["is_fork"]
        and not DEBUG_WORDS.search(text)
    ):
        return "没有分支标记，描述里也看不出修复、排查、测试或配置"
    return None


def label_items(dataset: dict, classification: dict) -> dict[str, tuple[str, str]]:
    """Map item_id to (domain, deliverable); fail loudly on gaps or bad codes."""
    groups = build_groups(dataset)
    errors = []
    labels: dict[str, tuple[str, str]] = {}
    suspicious = []
    for group in groups:
        value = classification.get(group["group_id"]) or ""
        confirmed = value.endswith("!")
        domain, _, deliverable = value.rstrip("!").partition("/")
        if domain not in TAXONOMY["domains"] or (
            deliverable not in TAXONOMY["deliverables"]
        ):
            errors.append(f"{group['group_id']}={value!r}（{group['title']}）")
            continue
        reason = None if confirmed else contradiction(group, domain, deliverable)
        if reason:
            suspicious.append(
                f"{group['group_id']}={value}（{group['title']}）：{reason}"
            )
        for item_id in group["item_ids"]:
            labels[item_id] = (domain, deliverable)
    if errors:
        raise SystemExit(
            "classification.json 缺少或包含无效分类，请补全后重试：\n"
            + "\n".join(errors)
        )
    if suspicious:
        raise SystemExit(
            "以下分类与标题或描述明显矛盾，请逐条复核。分错的直接改正；"
            '确认无误的在代码末尾加 "!"（例如 "sales/app!"），然后重新运行：\n'
            + "\n".join(suspicious)
        )
    for item in dataset["work_items"]:
        labels.setdefault(item["item_id"], (PRIVATE, PRIVATE))
    return labels


def name_of(kind: str, code: str) -> str:
    if code == PRIVATE:
        return PRIVATE_NAME
    return TAXONOMY[kind][code]["name"]


def local_date(value: str):
    """Parse an API timestamp (Python 3.10 cannot parse a trailing Z)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZONE).date()


def pct_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def ratio(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


# ---------------------------------------------------------------- items


def cmd_items(dataset_path: str, work_dir: Path) -> None:
    # Outputs from an earlier run would be silently mismatched with this dataset.
    for stale in ("classification.json", "stats.json", "insights.json"):
        (work_dir / stale).unlink(missing_ok=True)
    for report in work_dir.glob("agent_usage_report_*.html"):
        report.unlink()
    dataset = load_dataset(dataset_path)
    groups = build_groups(dataset)
    hidden = sum(not i["content_visible"] for i in dataset["work_items"])
    lines = [
        f"# 待分类工作项（{len(groups)} 组，另有 {hidden} 项隐私内容已自动归类）",
        "",
        "## 业务领域代码",
        *(f"- {k}：{v['name']}（{v['hint']}）" for k, v in TAXONOMY["domains"].items()),
        "",
        "## 产出物代码",
        *(
            f"- {k}：{v['name']}（{v['hint']}）"
            for k, v in TAXONOMY["deliverables"].items()
        ),
        "",
        "## 输出要求",
        '把结果写入同目录 classification.json，格式 {"g001": "领域代码/产出物代码", ...}，必须覆盖下面每一组。',
        "",
        "## 工作项（组号 | 触发方式 | 运行次数 | 成本 | 标题 | 描述）",
        "描述优先使用 AI 会话摘要；没有摘要时显示「[用户提问]」开头的用户首条消息。【分支】表示从已有会话分叉出的会话。",
    ]
    for g in groups:
        lines.append(
            f"{g['group_id']} | {TRIGGER_NAMES[g['trigger']]}{'【分支】' if g['is_fork'] else ''} | "
            f"{g['runs']}次 | ${g['cost_usd']:.2f} | {g['title']} | {g['description']}"
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "items.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成 {work_dir / 'items.md'}，共 {len(groups)} 组待分类")


# ---------------------------------------------------------------- stats


def summarize(items: list[dict]) -> dict:
    return {
        "items": len(items),
        "runs": sum(i["runs"] for i in items),
        "cost_usd": round(sum(i["cost_usd"] for i in items), 2),
        "users": len({i["user_id"] for i in items}),
    }


def breakdown(items: list[dict], key, names) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        buckets[key(item)].append(item)
    total_cost = sum(i["cost_usd"] for i in items)
    total_runs = sum(i["runs"] for i in items)
    rows = []
    for code, bucket in buckets.items():
        row = {"code": code, "name": names(code), **summarize(bucket)}
        row["cost_share"] = ratio(row["cost_usd"], total_cost)
        row["runs_share"] = ratio(row["runs"], total_runs)
        rows.append(row)
    return sorted(rows, key=lambda row: -row["cost_usd"])


def item_row(item: dict, users: dict) -> dict:
    user = users[item["user_id"]]
    return {
        "title": item["title"] or PRIVATE_NAME,
        "trigger": TRIGGER_NAMES[item["trigger"]],
        "domain": name_of("domains", item["domain"]),
        "deliverable": name_of("deliverables", item["deliverable"]),
        "user": user["name"],
        "department": user["department"] or "未填写部门",
        "runs": item["runs"],
        "failed_runs": item["failed_runs"],
        "canceled_runs": item["canceled_runs"],
        "cost_usd": round(item["cost_usd"], 2),
        "cost_per_run": round(item["cost_usd"] / item["runs"], 2),
    }


def compute_stats(dataset: dict, labels: dict[str, tuple[str, str]]) -> dict:
    totals, previous = dataset["totals"], dataset["previous_totals"]
    users = {u["user_id"]: u for u in dataset["users"]}
    items = [
        {**i, "domain": labels[i["item_id"]][0], "deliverable": labels[i["item_id"]][1]}
        for i in dataset["work_items"]
    ]
    start = date.fromisoformat(totals["start_date"])

    scheduled = [i for i in items if i["trigger"] == "scheduled"]
    scheduled_runs = sum(i["runs"] for i in scheduled)
    unstable = [
        i
        for i in scheduled
        if i["runs"] >= UNSTABLE_MIN_RUNS
        and (i["failed_runs"] + i["canceled_runs"]) / i["runs"] >= UNSTABLE_RATIO
    ]
    forks = [i for i in items if i["is_fork"]]

    matrix: dict[str, Counter] = defaultdict(Counter)
    for item in items:
        matrix[item["domain"]][item["deliverable"]] += 1

    departments: dict[str, list[dict]] = defaultdict(list)
    for user in dataset["users"]:
        departments[user["department"] or "未填写部门"].append(user)
    domain_by_user: dict[str, Counter] = defaultdict(Counter)
    for item in items:
        domain_by_user[item["user_id"]][item["domain"]] += item["cost_usd"]

    def top_domain(user_ids: list[str]) -> str:
        counter = Counter()
        for user_id in user_ids:
            counter.update(domain_by_user[user_id])
        return name_of("domains", counter.most_common(1)[0][0])

    new_users = [u for u in dataset["users"] if local_date(u["first_run_at"]) >= start]

    domain_rows = {
        row["code"]: row for row in breakdown(items, lambda i: i["domain"], lambda c: c)
    }
    coverage = [
        {
            "segment": segment_name,
            "domains": [
                {
                    "name": domain["name"],
                    **{
                        key: domain_rows.get(code, {}).get(key, 0)
                        for key in ("items", "runs", "cost_usd", "users")
                    },
                }
                for code, domain in TAXONOMY["domains"].items()
                if domain["segment"] == segment_code and code != "other"
            ],
        }
        for segment_code, segment_name in TAXONOMY["segments"].items()
    ]

    ranked = sorted(items, key=lambda i: -i["cost_usd"])
    total_cost = sum(i["cost_usd"] for i in items)
    cost_curve, running = [], 0.0
    for item in ranked[:PARETO_ITEMS]:
        running += item["cost_usd"]
        cost_curve.append(
            {
                "title": item["title"] or PRIVATE_NAME,
                "cost_usd": round(item["cost_usd"], 2),
                "cumulative_share": ratio(running, total_cost),
            }
        )

    candidates = []
    for row in breakdown(items, lambda i: i["domain"], lambda c: c):
        if row["code"] in (PRIVATE, "other"):
            continue
        pool = [
            i
            for i in items
            if i["domain"] == row["code"] and i["deliverable"] != "debug"
        ]
        for item in sorted(pool, key=lambda i: -i["cost_usd"])[:CANDIDATES_PER_DOMAIN]:
            candidates.append(
                {
                    "ref": f"c{len(candidates) + 1:02d}",
                    **item_row(item, users),
                    "active_days": item["active_days"],
                    "description": describe(item),
                }
            )

    return {
        "period": {
            "start_date": totals["start_date"],
            "end_date": totals["end_date"],
            "days": len(dataset["days"]),
            "previous_start_date": previous["start_date"],
            "previous_end_date": previous["end_date"],
            "generated_at": datetime.now(ZONE).strftime("%Y-%m-%d %H:%M"),
        },
        "kpis": {
            "cost_usd": round(totals["cost_usd"], 2),
            "runs": totals["runs"],
            "active_users": totals["active_users"],
            "departments": len(departments),
            "work_items": len(items),
            "automation_rate": ratio(
                sum(i["runs"] for i in items if i["trigger"] in AUTOMATED_TRIGGERS),
                totals["runs"],
            ),
            "success_rate": ratio(totals["completed_runs"], totals["runs"]),
            "failed_runs": totals["failed_runs"],
            "canceled_runs": totals["canceled_runs"],
            "new_users": len(new_users),
            "cost_change": pct_change(totals["cost_usd"], previous["cost_usd"]),
            "runs_change": pct_change(totals["runs"], previous["runs"]),
            "users_change": pct_change(
                totals["active_users"], previous["active_users"]
            ),
            "previous_success_rate": ratio(
                previous["completed_runs"], previous["runs"]
            ),
            "previous_cost_usd": round(previous["cost_usd"], 2),
            "previous_runs": previous["runs"],
            "previous_active_users": previous["active_users"],
        },
        "coverage": coverage,
        "uncovered_domains": [
            d["name"] for row in coverage for d in row["domains"] if not d["items"]
        ],
        "by_trigger": breakdown(items, lambda i: i["trigger"], TRIGGER_NAMES.get),
        "by_domain": breakdown(
            items, lambda i: i["domain"], lambda c: name_of("domains", c)
        ),
        "by_deliverable": breakdown(
            items, lambda i: i["deliverable"], lambda c: name_of("deliverables", c)
        ),
        "matrix": {
            name_of("domains", d): {
                name_of("deliverables", k): v for k, v in counts.items()
            }
            for d, counts in matrix.items()
        },
        "highlight_candidates": candidates,
        "top_items": [item_row(i, users) for i in ranked[:TOP_N]],
        "cost_curve": cost_curve,
        "scheduled": {
            "tasks": len(scheduled),
            "runs": scheduled_runs,
            "cost_usd": round(sum(i["cost_usd"] for i in scheduled), 2),
            "failed_runs": sum(i["failed_runs"] for i in scheduled),
            "canceled_runs": sum(i["canceled_runs"] for i in scheduled),
            "success_rate": ratio(
                sum(i["completed_runs"] for i in scheduled), scheduled_runs
            ),
            "top_cost": [
                item_row(i, users)
                for i in sorted(scheduled, key=lambda i: -i["cost_usd"])[:TOP_N]
            ],
            "unstable": [item_row(i, users) for i in unstable],
            "task_points": [
                {
                    "title": i["title"] or PRIVATE_NAME,
                    "runs": i["runs"],
                    "cost_usd": round(i["cost_usd"], 2),
                    "cost_per_run": round(i["cost_usd"] / i["runs"], 2),
                    "unstable": i in unstable,
                }
                for i in scheduled
            ],
            "fork_items": len(forks),
            "fork_cost_usd": round(sum(i["cost_usd"] for i in forks), 2),
        },
        "departments": sorted(
            (
                {
                    "department": name,
                    "users": len(members),
                    "new_users": sum(m in new_users for m in members),
                    "runs": sum(m["runs"] for m in members),
                    "cost_usd": round(sum(m["cost_usd"] for m in members), 2),
                    "top_domain": top_domain([m["user_id"] for m in members]),
                }
                for name, members in departments.items()
            ),
            key=lambda row: -row["cost_usd"],
        ),
        "top_users": [
            {
                "name": u["name"],
                "department": u["department"] or "未填写部门",
                "runs": u["runs"],
                "work_items": u["work_items"],
                "cost_usd": round(u["cost_usd"], 2),
                "top_domain": top_domain([u["user_id"]]),
            }
            for u in sorted(dataset["users"], key=lambda u: -u["cost_usd"])[:TOP_N]
        ],
        "new_users": [
            {"name": u["name"], "department": u["department"] or "未填写部门"}
            for u in new_users
        ],
        "days": dataset["days"],
    }


def print_digest(stats: dict) -> None:
    """Print the facts the agent needs to write insights.json."""
    print(
        json.dumps({k: v for k, v in stats.items() if k != "days"}, ensure_ascii=False)
    )


def cmd_stats(dataset_path: str, work_dir: Path) -> None:
    dataset = load_dataset(dataset_path)
    classification = json.loads((work_dir / "classification.json").read_text())
    stats = compute_stats(dataset, label_items(dataset, classification))
    (work_dir / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print_digest(stats)


# ---------------------------------------------------------------- render


def normalize_number(text: str) -> str:
    text = text.replace(",", "").rstrip("%")
    return text.rstrip("0").rstrip(".") if "." in text else text


def number_forms(value: float) -> set[str]:
    """The roundings a writer may reasonably use for a value."""
    return {normalize_number(f"{abs(value):.{digits}f}") for digits in (2, 1, 0)}


def known_numbers(value, found: dict[str, set[str]], key: str = "") -> dict:
    """Collect numbers in stats; percent fields are also tracked separately."""
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        forms = number_forms(value)
        found["all"] |= forms
        if key.endswith(PERCENT_KEY_SUFFIXES):
            found["percent"] |= forms
    elif isinstance(value, str):
        found["all"].update(normalize_number(n) for n in NUMBER.findall(value))
    elif isinstance(value, dict):
        for child_key, item in value.items():
            known_numbers(item, found, child_key)
    elif isinstance(value, list):
        for item in value:
            known_numbers(item, found, key)
    return found


def unknown_numbers(text: str, known: dict[str, set[str]]) -> list[str]:
    result = []
    for token in NUMBER.findall(text):
        number = normalize_number(token)
        if token.endswith("%"):
            verified = number in known["percent"]
        else:
            verified = number in known["all"] or (
                "." not in number and int(number) <= FREE_INTEGER_MAX
            )
        if not verified:
            result.append(token)
    return result


def insight_texts(insights: dict) -> list[tuple[str, str]]:
    texts = [("headline", insights["headline"])]
    texts += [(f"summary[{i}]", s) for i, s in enumerate(insights["summary"])]
    texts += [
        (f"highlights[{i}].value", h["value"])
        for i, h in enumerate(insights["highlights"])
    ]
    for i, action in enumerate(insights["actions"]):
        texts += [
            (f"actions[{i}].{f}", action[f]) for f in ("title", "evidence", "action")
        ]
    return texts


def validate_insights(insights: dict, stats: dict) -> None:
    candidate_refs = {c["ref"] for c in stats["highlight_candidates"]}
    errors = []
    headline = insights.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        errors.append("headline 必须是非空字符串")
    elif len(headline) > HEADLINE_MAX_CHARS:
        errors.append(
            f"headline 不超过 {HEADLINE_MAX_CHARS} 字，当前 {len(headline)} 字"
        )
    for key, (low, high, limits) in INSIGHT_LIMITS.items():
        entries = insights.get(key)
        if not isinstance(entries, list) or not low <= len(entries) <= high:
            errors.append(f"{key} 必须是 {low}~{high} 条的数组")
            continue
        for index, entry in enumerate(entries):
            where = f"{key}[{index}]"
            if key == "summary":
                fields = {where: (entry, limits)}
            elif isinstance(entry, dict):
                fields = {f"{where}.{f}": (entry.get(f), n) for f, n in limits.items()}
            else:
                errors.append(f"{where} 必须是对象")
                continue
            for name, (text, max_chars) in fields.items():
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{name} 必须是非空字符串")
                elif max_chars and len(text) > max_chars:
                    errors.append(f"{name} 不超过 {max_chars} 字，当前 {len(text)} 字")
            if key == "highlights" and entry.get("ref") not in candidate_refs:
                errors.append(
                    f"{where}.ref={entry.get('ref')!r} 不在 highlight_candidates 中"
                )
            if key == "actions" and entry.get("priority") not in PRIORITIES:
                errors.append(f"{where}.priority 必须是 P0/P1/P2")
    if errors:
        raise SystemExit("insights.json 格式错误：\n" + "\n".join(errors))

    known = known_numbers(stats, {"all": set(), "percent": set()})
    unverified = [
        f"{where}：{', '.join(numbers)}"
        for where, text in insight_texts(insights)
        if (numbers := unknown_numbers(text, known))
    ]
    if unverified:
        raise SystemExit(
            "以下数字在统计 JSON 中找不到。请删除这些数字，或改用统计 JSON 中的原始数字"
            "（不要自行计算、估算或预测）：\n" + "\n".join(unverified)
        )


def cmd_render(work_dir: Path) -> None:
    stats = json.loads((work_dir / "stats.json").read_text())
    insights = json.loads((work_dir / "insights.json").read_text())
    validate_insights(insights, stats)
    period = stats["period"]
    output = (
        work_dir
        / f"agent_usage_report_{period['start_date']}_{period['end_date']}.html"
    )
    output.write_text(render_html(stats, insights, PRIVATE_NAME), encoding="utf-8")
    print(f"报告已生成：{output}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "items":
        cmd_items(args[1], Path(args[2]))
    elif len(args) == 3 and args[0] == "stats":
        cmd_stats(args[1], Path(args[2]))
    elif len(args) == 2 and args[0] == "render":
        cmd_render(Path(args[1]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
