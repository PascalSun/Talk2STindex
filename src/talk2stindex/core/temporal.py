"""Simple relative temporal resolver.

Resolves relative temporal expressions to absolute ISO 8601 dates
using a reference date as anchor.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def resolve_relative(
    temporal_text: str,
    temporal_reference: Optional[str] = None,
) -> Tuple[str, str]:
    """Resolve a relative temporal expression to absolute ISO 8601.

    Args:
        temporal_text: The normalized temporal string from LLM.
        temporal_reference: ISO 8601 anchor date.

    Returns:
        (resolved_value, type) — type is "date", "datetime", etc.
    """
    text_lower = temporal_text.lower().strip()

    # Already ISO 8601
    if _is_iso8601(temporal_text):
        return temporal_text, _guess_type(temporal_text)

    if not temporal_reference:
        return temporal_text, "relative"

    try:
        anchor = datetime.fromisoformat(temporal_reference[:10])
    except (ValueError, TypeError):
        return temporal_text, "relative"

    # Relative phrases first (before weekday check, since "last month" contains "mon")
    if "last week" in text_lower:
        d = anchor - timedelta(weeks=1)
        return d.strftime("%Y-%m-%d"), "date"
    if "next week" in text_lower:
        d = anchor + timedelta(weeks=1)
        return d.strftime("%Y-%m-%d"), "date"
    if "last month" in text_lower:
        m = anchor.month - 1 or 12
        y = anchor.year if anchor.month > 1 else anchor.year - 1
        return f"{y:04d}-{m:02d}", "month"
    if "next month" in text_lower:
        m = anchor.month % 12 + 1
        y = anchor.year if anchor.month < 12 else anchor.year + 1
        return f"{y:04d}-{m:02d}", "month"
    if "last year" in text_lower:
        return str(anchor.year - 1), "year"
    if "next year" in text_lower:
        return str(anchor.year + 1), "year"
    if "yesterday" in text_lower:
        d = anchor - timedelta(days=1)
        return d.strftime("%Y-%m-%d"), "date"
    if "tomorrow" in text_lower:
        d = anchor + timedelta(days=1)
        return d.strftime("%Y-%m-%d"), "date"
    if "today" in text_lower:
        return anchor.strftime("%Y-%m-%d"), "date"

    # "next quarter"
    if "next quarter" in text_lower:
        q = (anchor.month - 1) // 3 + 2  # next quarter number
        y = anchor.year
        if q > 4:
            q = 1
            y += 1
        month = (q - 1) * 3 + 1
        return f"{y:04d}-{month:02d}", "month"

    # N days/weeks/months ago
    m = re.search(r"(\d+)\s+(day|week|month|year)s?\s+ago", text_lower)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "day":
            d = anchor - timedelta(days=n)
            return d.strftime("%Y-%m-%d"), "date"
        if unit == "week":
            d = anchor - timedelta(weeks=n)
            return d.strftime("%Y-%m-%d"), "date"
        if unit == "month":
            mo = anchor.month - n
            yr = anchor.year
            while mo < 1:
                mo += 12
                yr -= 1
            return f"{yr:04d}-{mo:02d}", "month"
        if unit == "year":
            return str(anchor.year - n), "year"

    # Weekday names (after relative phrases to avoid "mon" in "last month")
    for name, day_num in WEEKDAYS.items():
        if name in text_lower:
            resolved = _next_weekday(anchor, day_num)
            return resolved.strftime("%Y-%m-%d"), "date"

    return temporal_text, _guess_type(temporal_text)


def _next_weekday(anchor: datetime, target_day: int) -> datetime:
    """Find the next occurrence of target_day on or after anchor."""
    days_ahead = target_day - anchor.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return anchor + timedelta(days=days_ahead)


def _is_iso8601(text: str) -> bool:
    """Quick check if text looks like ISO 8601."""
    return bool(re.match(r"^\d{4}-\d{2}(-\d{2})?(T\d{2}:\d{2})?", text.strip()))


def _guess_type(text: str) -> str:
    text = text.strip()
    if "T" in text:
        return "datetime"
    if text.startswith("P"):
        return "duration"
    if "/" in text:
        return "interval"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return "date"
    if re.match(r"^\d{4}-\d{2}$", text):
        return "month"
    if re.match(r"^\d{4}$", text):
        return "year"
    return "date"
