"""Inline SVG and HTML chart fragments for the usage report.

Every function takes plain data and returns markup; colors and fonts come from
CSS classes defined in assets/report.html.
"""

from __future__ import annotations

import math
from datetime import date
from html import escape

# Categorical steel palette; the last color is reserved for "其他".
PALETTE = ("#1d4f7a", "#3b7bb0", "#76a7cf", "#b4cfe5", "#8c6d4f", "#a8a29e")
DONUT_SLICES = 5


def money(value: float) -> str:
    return f"${value:,.2f}"


def nice_ceiling(value: float) -> float:
    """Round up to 1, 2 or 5 times a power of ten for readable axes."""
    if value <= 0:
        return 1
    power = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * power:
            return step * power
    return 10 * power


def axis_label(value: float, unit: str = "") -> str:
    if value >= 1000:
        text = f"{value / 1000:g}k"
    else:
        text = f"{value:g}"
    return f"{unit}{text}"


def sparkline(values: list[float]) -> str:
    """Tiny trend line with a filled area and a dot on the latest value."""
    if len(values) < 2:
        return ""
    width, height, pad = 132, 36, 3
    peak = max(values) or 1
    step = (width - pad * 2) / (len(values) - 1)
    points = [
        (pad + i * step, height - pad - v / peak * (height - pad * 2))
        for i, v in enumerate(values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{pad},{height - pad} {line} {points[-1][0]:.1f},{height - pad}"
    last_x, last_y = points[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<polygon points="{area}" class="spark-area"/>'
        f'<polyline points="{line}" class="spark-line"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.6" class="spark-dot"/></svg>'
    )


def donut(rows: list[tuple[str, float]], center_value: str, center_label: str) -> str:
    """Donut with a side legend; small slices beyond the top five merge into 其他."""
    rows = sorted((r for r in rows if r[1] > 0), key=lambda r: -r[1])
    if len(rows) > DONUT_SLICES:
        rows = rows[: DONUT_SLICES - 1] + [
            ("其他", sum(v for _, v in rows[DONUT_SLICES - 1 :]))
        ]
    total = sum(v for _, v in rows)
    if not total:
        return '<p class="empty">本期没有数据</p>'
    radius, stroke = 54, 18
    circumference = 2 * math.pi * radius
    offset = 0.0
    arcs, legend = [], []
    for index, (label, value) in enumerate(rows):
        color = PALETTE[-1] if label == "其他" else PALETTE[index]
        length = value / total * circumference
        arcs.append(
            f'<circle r="{radius}" cx="70" cy="70" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 70 70)">'
            f"<title>{escape(label)} {value / total * 100:.1f}%</title></circle>"
        )
        offset += length
        legend.append(
            f'<li><i style="background:{color}"></i><span>{escape(label)}</span>'
            f"<b>{value / total * 100:.1f}%</b></li>"
        )
    return (
        '<div class="donut"><svg viewBox="0 0 140 140" role="img">'
        + "".join(arcs)
        + f'<text x="70" y="68" class="donut-value">{escape(center_value)}</text>'
        f'<text x="70" y="86" class="donut-label">{escape(center_label)}</text></svg>'
        f'<ul class="legend-list">{"".join(legend)}</ul></div>'
    )


def bar_rows(rows: list[dict]) -> str:
    """Ranked horizontal bars. Row keys: label, value, display, note, accent."""
    if not rows:
        return '<p class="empty">本期没有数据</p>'
    peak = max(r["value"] for r in rows) or 1
    parts = []
    for index, r in enumerate(rows):
        accent = " accent" if r.get("accent") else ""
        parts.append(
            f'<div class="hbar{accent}" style="--w:{r["value"] / peak * 100:.1f}%;--i:{index}">'
            f'<span class="hbar-label">{escape(r["label"])}</span>'
            f'<span class="hbar-track"><span class="hbar-fill"></span></span>'
            f'<span class="hbar-value">{escape(r["display"])}'
            f"<small>{escape(r.get('note', ''))}</small></span></div>"
        )
    return '<div class="hbars">' + "".join(parts) + "</div>"


def daily_combo(days: list[dict]) -> str:
    """Daily cost columns with a run-count line; weekends shaded, peak day marked."""
    width, height = 760, 270
    left, right, top, bottom = 52, 52, 22, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    step = plot_w / len(days)
    cost_max = nice_ceiling(max(d["cost_usd"] for d in days))
    runs_max = nice_ceiling(max(d["runs"] for d in days))
    peak = max(days, key=lambda d: d["cost_usd"])
    parts = []
    for tick in range(5):
        y = top + plot_h - tick / 4 * plot_h
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">'
            f"{axis_label(cost_max * tick / 4, '$')}</text>"
            f'<text x="{width - right + 8}" y="{y + 4:.1f}" class="axis">'
            f"{axis_label(runs_max * tick / 4)}</text>"
        )
    label_every = max(1, math.ceil(len(days) / 12))
    points = []
    for index, d in enumerate(days):
        x = left + index * step
        day = date.fromisoformat(d["day"])
        if day.weekday() >= 5:
            parts.append(
                f'<rect x="{x:.1f}" y="{top}" width="{step:.1f}" height="{plot_h}" class="weekend"/>'
            )
        bar_h = d["cost_usd"] / cost_max * plot_h
        css = "col peak" if d is peak else "col"
        parts.append(
            f'<rect x="{x + step * 0.2:.1f}" y="{top + plot_h - bar_h:.1f}" width="{step * 0.6:.1f}" '
            f'height="{bar_h:.1f}" rx="2" class="{css}"><title>{d["day"]} 成本 {money(d["cost_usd"])}'
            f" · 运行 {d['runs']} 次 · {d['active_users']} 人</title></rect>"
        )
        points.append(
            (x + step / 2, top + plot_h - d["runs"] / runs_max * plot_h, d["runs"])
        )
        if index % label_every == 0:
            parts.append(
                f'<text x="{x + step / 2:.1f}" y="{height - 16}" class="axis" text-anchor="middle">'
                f"{day.month}/{day.day}</text>"
            )
    peak_x = left + days.index(peak) * step + step / 2
    peak_y = top + plot_h - peak["cost_usd"] / cost_max * plot_h
    parts.append(
        f'<text x="{peak_x:.1f}" y="{peak_y - 8:.1f}" class="peak-label" text-anchor="middle">'
        f"{money(peak['cost_usd'])}</text>"
    )
    parts.append(
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)}" class="line"/>'
    )
    parts += [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot"><title>运行 {v} 次</title></circle>'
        for x, y, v in points
    ]
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="每日成本与运行次数">'
        + "".join(parts)
        + "</svg>"
        '<p class="chart-legend"><i class="key col"></i>每日成本（左轴，美元）'
        '<i class="key line"></i>运行次数（右轴）<i class="key weekend"></i>周末</p>'
    )


def pareto(curve: list[dict]) -> str:
    """Cost of the top work items as columns, cumulative share of total as a line."""
    if not curve:
        return '<p class="empty">本期没有数据</p>'
    width, height = 760, 250
    left, right, top, bottom = 52, 52, 18, 36
    plot_w, plot_h = width - left - right, height - top - bottom
    step = plot_w / len(curve)
    cost_max = nice_ceiling(curve[0]["cost_usd"])
    parts = []
    for tick in range(5):
        y = top + plot_h - tick / 4 * plot_h
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">'
            f"{axis_label(cost_max * tick / 4, '$')}</text>"
            f'<text x="{width - right + 8}" y="{y + 4:.1f}" class="axis">{tick * 25}%</text>'
        )
    y80 = top + plot_h * 0.2
    parts.append(
        f'<line x1="{left}" x2="{width - right}" y1="{y80:.1f}" y2="{y80:.1f}" class="ref"/>'
        f'<text x="{width - right - 4}" y="{y80 - 6:.1f}" class="ref-label" text-anchor="end">80%</text>'
    )
    points = []
    for index, item in enumerate(curve):
        x = left + index * step
        bar_h = item["cost_usd"] / cost_max * plot_h
        parts.append(
            f'<rect x="{x + step * 0.18:.1f}" y="{top + plot_h - bar_h:.1f}" width="{step * 0.64:.1f}" '
            f'height="{bar_h:.1f}" rx="2" class="col"><title>#{index + 1} {escape(item["title"])} '
            f"{money(item['cost_usd'])}</title></rect>"
            f'<text x="{x + step / 2:.1f}" y="{height - 14}" class="axis" text-anchor="middle">{index + 1}</text>'
        )
        points.append(
            (x + step / 2, top + plot_h - item["cumulative_share"] / 100 * plot_h)
        )
    parts.append(
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" class="line"/>'
    )
    parts += [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot"><title>累计 {c["cumulative_share"]}%</title></circle>'
        for (x, y), c in zip(points, curve)
    ]
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="成本帕累托图">'
        + "".join(parts)
        + "</svg>"
        '<p class="chart-legend"><i class="key col"></i>单个工作项成本（按排名）'
        '<i class="key line"></i>累计占总成本比例（右轴）</p>'
    )


def bubble(tasks: list[dict]) -> str:
    """Scheduled tasks: runs (x, square-root scale) vs cost per run (y), size = total cost."""
    if not tasks:
        return '<p class="empty">本期没有定时任务</p>'
    width, height = 760, 330
    left, right, top, bottom = 56, 24, 20, 44
    plot_w, plot_h = width - left - right, height - top - bottom
    runs_max = nice_ceiling(max(t["runs"] for t in tasks))
    unit_max = nice_ceiling(max(t["cost_per_run"] for t in tasks))
    cost_max = max(t["cost_usd"] for t in tasks) or 1

    def x_of(runs: float) -> float:
        return left + math.sqrt(runs / runs_max) * plot_w

    def y_of(unit: float) -> float:
        return top + plot_h - unit / unit_max * plot_h

    parts = []
    for tick in range(5):
        value = unit_max * tick / 4
        y = y_of(value)
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">${value:g}</text>'
        )
    for value in sorted({1, runs_max / 16, runs_max / 4, runs_max}):
        x = x_of(value)
        parts.append(
            f'<text x="{x:.1f}" y="{height - 22}" class="axis" text-anchor="middle">{value:g}</text>'
        )
    runs_mid = sorted(t["runs"] for t in tasks)[len(tasks) // 2]
    unit_mid = sorted(t["cost_per_run"] for t in tasks)[len(tasks) // 2]
    qx, qy = x_of(runs_mid), y_of(unit_mid)
    parts.append(
        f'<rect x="{qx:.1f}" y="{top}" width="{width - right - qx:.1f}" height="{qy - top:.1f}" class="quadrant"/>'
        f'<text x="{width - right - 8}" y="{top + 16}" class="quadrant-label" text-anchor="end">高频 · 高单次成本</text>'
        f'<line x1="{qx:.1f}" x2="{qx:.1f}" y1="{top}" y2="{top + plot_h}" class="ref"/>'
        f'<line x1="{left}" x2="{width - right}" y1="{qy:.1f}" y2="{qy:.1f}" class="ref"/>'
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 4}" class="axis-title" text-anchor="middle">运行次数（平方根刻度）</text>'
        f'<text x="14" y="{top + plot_h / 2:.1f}" class="axis-title" text-anchor="middle" '
        f'transform="rotate(-90 14 {top + plot_h / 2:.1f})">单次成本</text>'
    )
    labeled = {id(t) for t in sorted(tasks, key=lambda t: -t["cost_usd"])[:5]}
    for t in sorted(tasks, key=lambda t: -t["cost_usd"]):
        x, y = x_of(t["runs"]), y_of(t["cost_per_run"])
        r = 4 + 16 * math.sqrt(t["cost_usd"] / cost_max)
        css = "bubble warn" if t["unstable"] else "bubble"
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" class="{css}"><title>{escape(t["title"])}\n'
            f"运行 {t['runs']} 次 · 单次 {money(t['cost_per_run'])} · 合计 {money(t['cost_usd'])}"
            f"</title></circle>"
        )
        if id(t) in labeled:
            name = t["title"] if len(t["title"]) <= 10 else t["title"][:10] + "…"
            anchor = "end" if x > width - 160 else "start"
            dx = -(r + 4) if anchor == "end" else r + 4
            parts.append(
                f'<text x="{x + dx:.1f}" y="{y + 4:.1f}" class="bubble-label" text-anchor="{anchor}">{escape(name)}</text>'
            )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="定时任务运行次数与单次成本">'
        + "".join(parts)
        + "</svg>"
        '<p class="chart-legend"><i class="key bubble"></i>定时任务（气泡大小表示本期总成本）'
        '<i class="key warn"></i>不稳定任务<i class="key quadrant"></i>运行次数与单次成本均高于中位数</p>'
    )
