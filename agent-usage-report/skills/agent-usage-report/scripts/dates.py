"""Resolve a report period to Beijing-time start and end dates.

Usage:
    python3 dates.py today | yesterday | this_week | last_week
    python3 dates.py this_month | last_month | last_7_days | last_30_days
    python3 dates.py 2026-10-01 2026-10-07
"""

import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = "一二三四五六日"
MAX_DAYS = 31


def resolve(args: list[str], today: date) -> tuple[date, date]:
    if len(args) == 2:
        return date.fromisoformat(args[0]), date.fromisoformat(args[1])
    keyword = args[0]
    monday = today - timedelta(days=today.weekday())
    first_of_month = today.replace(day=1)
    if keyword == "today":
        return today, today
    if keyword == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if keyword == "this_week":
        return monday, today
    if keyword == "last_week":
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if keyword == "this_month":
        return first_of_month, today
    if keyword == "last_month":
        last_day = first_of_month - timedelta(days=1)
        return last_day.replace(day=1), last_day
    if keyword.startswith("last_") and keyword.endswith("_days"):
        days = int(keyword[len("last_") : -len("_days")])
        return today - timedelta(days=days - 1), today
    raise SystemExit(f"Unknown period: {keyword}")


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start, end = resolve(sys.argv[1:], today)
    days = (end - start).days + 1
    if days < 1 or days > MAX_DAYS:
        raise SystemExit(f"Range must be 1-{MAX_DAYS} days, got {days}")
    print(f"today={today} 周{WEEKDAYS[today.weekday()]}")
    print(f"start_date={start} 周{WEEKDAYS[start.weekday()]}")
    print(f"end_date={end} 周{WEEKDAYS[end.weekday()]}")
    print(f"days={days}")


if __name__ == "__main__":
    main()
