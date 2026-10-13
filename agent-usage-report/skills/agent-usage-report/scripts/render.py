"""Assemble the report page from stats.json and insights.json."""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from string import Template

from charts import bar_rows, bubble, daily_combo, donut, money, pareto, sparkline

TEMPLATE = Template(
    (Path(__file__).resolve().parent.parent / "assets" / "report.html").read_text()
)
PRIORITY_TITLES = {
    "P0": "本周内处理",
    "P1": "本月内处理",
    "P2": "推广与优化",
}
PRIORITY_PHRASES = {
    "P0": "项需本周内处理",
    "P1": "项需本月内处理",
    "P2": "项属于推广与优化",
}
SECTIONS = (
    ("findings", "本期结论"),
    ("decisions", "需要决策的事项"),
    ("coverage", "业务覆盖地图"),
    ("structure", "应用结构"),
    ("cost", "成本去向"),
    ("scheduled", "定时任务运行质量"),
    ("people", "部门与人员"),
)


def short_date(value: str) -> str:
    day = date.fromisoformat(value)
    return f"{day.year}.{day.month:02d}.{day.day:02d}"


def delta(value: float | None, up_is_good: bool | None) -> str:
    """Change versus the previous period; color only when direction has a meaning."""
    if value is None:
        return '<span class="delta">上期无数据</span>'
    arrow = "▲" if value > 0 else "▼" if value < 0 else "■"
    tone = ""
    if up_is_good is not None and value:
        tone = " good" if (value > 0) == up_is_good else " bad"
    return f'<span class="delta{tone}">{arrow} {abs(value):.1f}%<small>较上期</small></span>'


def table(headers: list[str], rows: list[list[str]], numeric: set[int]) -> str:
    """Plain data table; columns listed in `numeric` are right aligned."""
    head = "".join(
        f'<th class="{"num" if i in numeric else ""}">{escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if i in numeric else ""}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def item_table(rows: list[dict], empty: str, ranked: bool = False) -> str:
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    return table(
        [
            *(["#"] if ranked else []),
            "工作项",
            "业务",
            "负责人",
            "运行",
            "失败/取消",
            "单次",
            "成本",
        ],
        [
            [
                *([f'<span class="rank">{n}</span>'] if ranked else []),
                f'<span class="item-title">{escape(r["title"])}</span><small>{escape(r["trigger"])}</small>',
                f"{escape(r['domain'])}<small>{escape(r['deliverable'])}</small>",
                f"{escape(r['user'])}<small>{escape(r['department'])}</small>",
                str(r["runs"]),
                f"{r['failed_runs']} / {r['canceled_runs']}",
                money(r["cost_per_run"]),
                f"<strong>{money(r['cost_usd'])}</strong>",
            ]
            for n, r in enumerate(rows, 1)
        ],
        {4, 5, 6, 7} if ranked else {3, 4, 5, 6},
    )


def section(number: int, takeaway: str, body: str) -> str:
    key, title = SECTIONS[number - 1]
    lead = f'<p class="takeaway">{takeaway}</p>' if takeaway else ""
    return (
        f'<section id="{key}" class="section" style="--i:{number}">'
        f'<header class="section-head"><span class="section-no">{number:02d}</span>'
        f"<div><h2>{title}</h2>{lead}</div></header>{body}</section>"
    )


def masthead(stats: dict, insights: dict) -> str:
    period = stats["period"]
    single_day = period["days"] == 1
    kind = "应用日报" if single_day else "应用分析报告"
    span = (
        short_date(period["start_date"])
        if single_day
        else f"{short_date(period['start_date'])} — {short_date(period['end_date'])}"
    )
    return f"""
<header class="masthead">
  <div class="masthead-inner">
    <p class="kicker">AGENT 平台 · {kind}</p>
    <h1>{span}</h1>
    <p class="meta">统计 {period["days"]} 天（北京时间） · 对比上期 {short_date(period["previous_start_date"])} — {short_date(period["previous_end_date"])} · 生成于 {period["generated_at"]}</p>
    <p class="headline">{escape(insights["headline"])}</p>
  </div>
</header>"""


def kpi_band(stats: dict) -> str:
    kpi, days = stats["kpis"], stats["days"]
    show_trend = len(days) > 1
    primary = (
        (
            "总成本",
            money(kpi["cost_usd"]),
            delta(kpi["cost_change"], None),
            [d["cost_usd"] for d in days],
        ),
        (
            "运行次数",
            f"{kpi['runs']:,}",
            delta(kpi["runs_change"], True),
            [d["runs"] for d in days],
        ),
        (
            "活跃用户",
            f"{kpi['active_users']}",
            delta(kpi["users_change"], True),
            [d["active_users"] for d in days],
        ),
        (
            "运行成功率",
            f"{kpi['success_rate']}%",
            f'<span class="delta">上期 {kpi["previous_success_rate"]}%</span>',
            [],
        ),
    )
    cards = "".join(
        f'<div class="kpi"><span class="kpi-label">{label}</span>'
        f'<span class="kpi-value">{value}</span>{change}'
        f"{sparkline(series) if show_trend else ''}</div>"
        for label, value, change, series in primary
    )
    secondary = (
        ("自动化运行占比", f"{kpi['automation_rate']}%"),
        ("覆盖部门", f"{kpi['departments']} 个"),
        ("新用户", f"{kpi['new_users']} 人"),
        ("工作项", f"{kpi['work_items']} 个"),
        ("失败 / 取消", f"{kpi['failed_runs']} / {kpi['canceled_runs']} 次"),
    )
    strip = "".join(
        f"<div><span>{label}</span><b>{value}</b></div>" for label, value in secondary
    )
    return f'<div class="kpi-band"><div class="kpis">{cards}</div><div class="kpi-strip">{strip}</div></div>'


def findings_section(insights: dict) -> str:
    items = "".join(f"<li><p>{escape(text)}</p></li>" for text in insights["summary"])
    return section(1, "", f'<ol class="findings">{items}</ol>')


def decisions_section(insights: dict) -> str:
    """One lane per priority that has actions; empty priorities are left out."""
    lanes, phrases = [], []
    for priority, label in PRIORITY_TITLES.items():
        actions = [a for a in insights["actions"] if a["priority"] == priority]
        if not actions:
            continue
        cards = "".join(
            f'<article class="decision"><h3>{escape(a["title"])}</h3>'
            f'<p class="evidence"><span>依据</span>{escape(a["evidence"])}</p>'
            f'<p class="advice"><span>建议</span>{escape(a["action"])}</p></article>'
            for a in actions
        )
        lanes.append(
            f'<div class="lane {priority.lower()}"><header><b>{priority}</b>{label}'
            f"<em>{len(actions)}</em></header>{cards}</div>"
        )
        phrases.append(f"<b>{len(actions)}</b> {PRIORITY_PHRASES[priority]}")
    takeaway = "，".join(phrases) + "。"
    body = f'<div class="lanes" style="--lanes:{len(lanes)}">{"".join(lanes)}</div>'
    return section(2, takeaway, body)


def coverage_section(stats: dict) -> str:
    domains = [d for row in stats["coverage"] for d in row["domains"]]
    peak = max((d["cost_usd"] for d in domains), default=0) or 1
    rows = []
    for row in stats["coverage"]:
        tiles = []
        for d in row["domains"]:
            if d["items"]:
                level = 0.12 + d["cost_usd"] / peak * 0.88
                tiles.append(
                    f'<div class="tile{" dark" if level > 0.55 else ""}" style="--a:{level:.2f}">'
                    f"<strong>{escape(d['name'])}</strong><b>{money(d['cost_usd'])}</b>"
                    f"<small>{d['items']} 项 · {d['runs']} 次 · {d['users']} 人</small></div>"
                )
            else:
                tiles.append(
                    f'<div class="tile idle"><strong>{escape(d["name"])}</strong><small>本期空白</small></div>'
                )
        rows.append(
            f'<div class="segment"><div class="segment-name">{escape(row["segment"])}</div>'
            f'<div class="tiles">{"".join(tiles)}</div></div>'
        )
    covered = sum(1 for d in domains if d["items"])
    uncovered = stats["uncovered_domains"]
    takeaway = f"<b>{covered}</b> / {len(domains)} 个业务领域本期已有应用" + (
        f"，<b>{escape('、'.join(uncovered))}</b> 仍是空白。"
        if uncovered
        else "，已全面覆盖。"
    )
    legend = (
        '<p class="chart-legend"><i class="key scale"></i>颜色越深，本期投入成本越高'
        '<i class="key idle"></i>本期没有应用</p>'
    )
    return section(3, takeaway, f'<div class="coverage">{"".join(rows)}</div>{legend}')


def matrix_table(matrix: dict) -> str:
    columns = sorted(
        {c for row in matrix.values() for c in row},
        key=lambda c: -sum(r.get(c, 0) for r in matrix.values()),
    )
    peak = max((v for row in matrix.values() for v in row.values()), default=1)
    rows = []
    for domain, counts in sorted(matrix.items(), key=lambda kv: -sum(kv[1].values())):
        cells = [escape(domain)]
        for column in columns:
            value = counts.get(column, 0)
            cells.append(
                f'<span class="heat" style="--a:{value / peak:.2f}">{value or ""}</span>'
                if value
                else '<span class="heat zero">·</span>'
            )
        rows.append(cells)
    return table(["业务领域", *columns], rows, set(range(1, len(columns) + 1)))


def structure_section(stats: dict, insights: dict) -> str:
    kpi = stats["kpis"]
    top = stats["by_domain"][0] if stats["by_domain"] else None
    takeaway = f"自动化运行占比 <b>{kpi['automation_rate']}%</b>" + (
        f"；投入最多的领域是 <b>{escape(top['name'])}</b>，占总成本 <b>{top['cost_share']}%</b>。"
        if top
        else "。"
    )
    trigger_donut = donut(
        [(r["name"], r["runs"]) for r in stats["by_trigger"]],
        f"{kpi['runs']:,}",
        "次运行",
    )
    deliverable_donut = donut(
        [(r["name"], r["cost_usd"]) for r in stats["by_deliverable"]],
        money(kpi["cost_usd"]),
        "总成本",
    )
    domain_bars = bar_rows(
        [
            {
                "label": r["name"],
                "value": r["cost_usd"],
                "display": money(r["cost_usd"]),
                "note": f"{r['cost_share']}% · {r['items']} 项 · {r['runs']} 次 · {r['users']} 人",
                "accent": index == 0,
            }
            for index, r in enumerate(stats["by_domain"])
        ]
    )
    candidates = {c["ref"]: c for c in stats["highlight_candidates"]}
    cards = "".join(
        f'<article class="case"><p class="case-tag">{escape(c["domain"])} · {escape(c["deliverable"])}</p>'
        f"<h3>{escape(c['title'])}</h3><p>{escape(h['value'])}</p>"
        f"<dl><div><dt>负责人</dt><dd>{escape(c['user'])}<small>{escape(c['department'])}</small></dd></div>"
        f"<div><dt>方式</dt><dd>{escape(c['trigger'])}</dd></div>"
        f"<div><dt>运行</dt><dd>{c['runs']} 次 / {c['active_days']} 天</dd></div>"
        f"<div><dt>成本</dt><dd>{money(c['cost_usd'])}</dd></div></dl></article>"
        for h in insights["highlights"]
        for c in [candidates[h["ref"]]]
    )
    body = f"""
<div class="grid-2">
  <figure class="panel"><figcaption>运行次数构成 · 按触发方式</figcaption>{trigger_donut}</figure>
  <figure class="panel"><figcaption>成本构成 · 按产出物</figcaption>{deliverable_donut}</figure>
</div>
<figure class="panel"><figcaption>各业务领域成本排行</figcaption>{domain_bars}</figure>
<figure class="panel"><figcaption>业务领域 × 产出物 · 工作项数量</figcaption>{matrix_table(stats["matrix"])}</figure>
<h3 class="sub">代表性应用</h3>
<div class="cases">{cards}</div>"""
    return section(4, takeaway, body)


def cost_section(stats: dict) -> str:
    days, curve = stats["days"], stats["cost_curve"]
    top_n = min(10, len(curve))
    parts = []
    if top_n:
        parts.append(
            f"成本最高的 {top_n} 个工作项占总成本 <b>{curve[top_n - 1]['cumulative_share']}%</b>"
        )
    if len(days) > 1:
        peak = max(days, key=lambda d: d["cost_usd"])
        parts.append(
            f"单日成本最高为 <b>{peak['day']}</b> 的 <b>{money(peak['cost_usd'])}</b>"
        )
    takeaway = "；".join(parts) + "。" if parts else ""
    trend = (
        f'<figure class="panel"><figcaption>每日成本与运行次数</figcaption>{daily_combo(days)}</figure>'
        if len(days) > 1
        else ""
    )
    body = f"""{trend}
<figure class="panel"><figcaption>成本集中度 · 前 {len(curve)} 个工作项</figcaption>{pareto(curve)}</figure>
<h3 class="sub">成本最高的工作项</h3>
{item_table(stats["top_items"], "本期没有工作项", ranked=True)}"""
    return section(5, takeaway, body)


def scheduled_section(stats: dict) -> str:
    sched = stats["scheduled"]
    unstable = len(sched["unstable"])
    takeaway = (
        f"<b>{sched['tasks']}</b> 个定时任务运行 <b>{sched['runs']}</b> 次，成功率 <b>{sched['success_rate']}%</b>"
        + (
            f"，<b>{unstable}</b> 个任务不稳定，需要处理。"
            if unstable
            else "，没有不稳定的任务。"
        )
    )
    strip = "".join(
        f"<div><span>{label}</span><b>{value}</b></div>"
        for label, value in (
            ("任务数", f"{sched['tasks']} 个"),
            ("运行次数", f"{sched['runs']} 次"),
            ("成功率", f"{sched['success_rate']}%"),
            ("失败 / 取消", f"{sched['failed_runs']} / {sched['canceled_runs']} 次"),
            ("成本", money(sched["cost_usd"])),
            (
                "调试分支会话",
                f"{sched['fork_items']} 个 · {money(sched['fork_cost_usd'])}",
            ),
        )
    )
    body = f"""
<div class="stat-strip">{strip}</div>
<figure class="panel"><figcaption>运行次数 × 单次成本 · 右上角任务最值得优化</figcaption>{bubble(sched["task_points"])}</figure>
<h3 class="sub">不稳定任务 · 运行不少于 3 次且失败或取消不低于 20%</h3>
{item_table(sched["unstable"], "没有不稳定的定时任务")}
<h3 class="sub">成本最高的定时任务</h3>
{item_table(sched["top_cost"], "本期没有定时任务", ranked=True)}"""
    return section(6, takeaway, body)


def people_section(stats: dict) -> str:
    kpi, departments = stats["kpis"], stats["departments"]
    top = departments[0] if departments else None
    takeaway = (
        f"<b>{kpi['departments']}</b> 个部门、<b>{kpi['active_users']}</b> 人在用，新用户 <b>{kpi['new_users']}</b> 人"
        + (
            f"；成本最高的是 <b>{escape(top['department'])}</b>（{money(top['cost_usd'])}）。"
            if top
            else "。"
        )
    )
    dept_bars = bar_rows(
        [
            {
                "label": d["department"],
                "value": d["cost_usd"],
                "display": money(d["cost_usd"]),
                "note": f"{d['users']} 人"
                + (f" · 新 {d['new_users']}" if d["new_users"] else "")
                + f" · {d['top_domain']}",
                "accent": index == 0,
            }
            for index, d in enumerate(departments)
        ]
    )
    chips = (
        "".join(
            f'<span class="chip">{escape(u["name"])}<small>{escape(u["department"])}</small></span>'
            for u in stats["new_users"]
        )
        or '<p class="empty">本期没有新用户</p>'
    )
    users = table(
        ["#", "用户", "部门", "主要领域", "工作项", "运行", "成本"],
        [
            [
                f'<span class="rank">{n}</span>',
                escape(u["name"]),
                escape(u["department"]),
                escape(u["top_domain"]),
                str(u["work_items"]),
                str(u["runs"]),
                f"<strong>{money(u['cost_usd'])}</strong>",
            ]
            for n, u in enumerate(stats["top_users"], 1)
        ],
        {4, 5, 6},
    )
    body = f"""
<figure class="panel"><figcaption>各部门成本 · 人数 · 主要领域</figcaption>{dept_bars}</figure>
<h3 class="sub">本期新用户</h3>
<div class="chips">{chips}</div>
<h3 class="sub">成本最高的用户</h3>
{users}"""
    return section(7, takeaway, body)


def appendix(stats: dict, private_name: str) -> str:
    period = stats["period"]
    days = table(
        [
            "日期",
            "运行",
            "失败",
            "取消",
            "活跃用户",
            "成本",
            "输入 Token",
            "输出 Token",
        ],
        [
            [
                d["day"],
                str(d["runs"]),
                str(d["failed_runs"]),
                str(d["canceled_runs"]),
                str(d["active_users"]),
                money(d["cost_usd"]),
                f"{d['input_tokens']:,}",
                f"{d['output_tokens']:,}",
            ]
            for d in stats["days"]
        ],
        set(range(1, 8)),
    )
    return f"""
<section id="appendix" class="section appendix">
  <details><summary>附录 A · 逐日明细</summary>{days}</details>
  <details open><summary>附录 B · 口径说明</summary><dl class="method">
    <dt>数据来源</dt><dd>平台运行记录与模型用量日志，按北京时间统计 {period["start_date"]} 至 {period["end_date"]}，上期为紧邻的等长区间。</dd>
    <dt>运行</dt><dd>Agent 的一次执行；运行成功率为已完成运行占全部运行的比例。</dd>
    <dt>工作项</dt><dd>一个定时任务（本期内多次运行合并计算），或一个对话、API 会话。</dd>
    <dt>自动化运行占比</dt><dd>定时任务与 API 集成触发的运行占全部运行的比例，反映 Agent 融入日常流程的程度。</dd>
    <dt>成本</dt><dd>模型调用费用，单位美元，按平台计费口径汇总。</dd>
    <dt>业务分类</dt><dd>由 AI 根据工作项标题与会话摘要，对照公司业务架构判定业务领域和产出物；开启内容隐私的用户只计入数字，归入“{escape(private_name)}”。</dd>
    <dt>新用户</dt><dd>首次使用平台的时间落在本期内的用户。</dd>
  </dl></details>
</section>"""


def render_html(stats: dict, insights: dict, private_name: str) -> str:
    period = stats["period"]
    toc = (
        "".join(
            f'<a href="#{key}"><span>{n:02d}</span>{title}</a>'
            for n, (key, title) in enumerate(SECTIONS, 1)
        )
        + '<a href="#appendix"><span>附</span>附录</a>'
    )
    content = f"""
{masthead(stats, insights)}
{kpi_band(stats)}
<div class="layout">
  <nav class="toc">{toc}</nav>
  <main>
    {findings_section(insights)}
    {decisions_section(insights)}
    {coverage_section(stats)}
    {structure_section(stats, insights)}
    {cost_section(stats)}
    {scheduled_section(stats)}
    {people_section(stats)}
    {appendix(stats, private_name)}
    <footer class="colophon">本报告由 Agent 使用分析技能生成。数字取自平台运行记录；结论由 AI 依据统计数据撰写，并已通过数字出处校验。</footer>
  </main>
</div>"""
    title = f"Agent 平台应用分析 · {period['start_date']} 至 {period['end_date']}"
    return TEMPLATE.substitute(title=escape(title), content=content)
