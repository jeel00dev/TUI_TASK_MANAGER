"""Calendar intervals. Overlap is allowed and workload counts occupied time once."""
import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

from .model import midnight


def bounds(day: date, view: str):
    if view == "year":
        return midnight(date(day.year, 1, 1)), midnight(date(day.year + 1, 1, 1))
    if view == "week":
        first = day - timedelta(days=day.weekday())
        return midnight(first), midnight(first + timedelta(days=7))
    if view == "month":
        first = day.replace(day=1)
        end = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return midnight(first), midnight(end)
    return midnight(day), midnight(day + timedelta(days=1))


def move_date(day: date, view: str, step: int) -> date:
    if view == "year":
        year = day.year + step
        return date(year, day.month, min(day.day, calendar.monthrange(year, day.month)[1]))
    if view == "month":
        index = day.year * 12 + day.month - 1 + step
        year, month = divmod(index, 12)
        month += 1
        return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    return day + timedelta(days=step * (7 if view == "week" else 1))


def segments(items, day: date):
    """Exact schedule boundaries, including free time and concurrent work."""
    lo, hi = bounds(day, "day")
    timed = [o for o in items if not o.task.all_day and o.overlaps(lo, hi)]
    points = sorted({lo, hi} | {max(lo, o.task.start) for o in timed} | {min(hi, o.task.end) for o in timed})
    return [(a, b, [o for o in timed if o.task.start < b and o.task.end > a]) for a, b in zip(points, points[1:])]


def workload(items, day: date):
    parts = segments(items, day)
    occupied = sum((b - a).total_seconds() / 3600 for a, b, active in parts if active)
    concurrent = max((len(active) for _, _, active in parts), default=0)
    lo, hi = bounds(day, "day")
    spanning = sum(o.task.all_day and o.overlaps(lo, hi) for o in items)
    return occupied, concurrent, spanning


@dataclass
class Placement:
    item: object
    top: int
    bottom: int
    lane: int = 0
    lanes: int = 1
    group: int = 0


def time_blocks(items, day, start_minute, rows, minutes_per_row):
    """Partition even sub-row overlaps, so no task silently paints over another."""
    lo = midnight(day)
    end_minute = start_minute + rows * minutes_per_row
    blocks = []
    for item in items:
        if item.task.all_day or not item.overlaps(lo, lo + timedelta(days=1)):
            continue
        start = max(0, (item.task.start - lo).total_seconds() / 60)
        end = min(1440, (item.task.end - lo).total_seconds() / 60)
        if start >= end_minute or end <= start_minute:
            continue
        top = max(0, math.floor((start - start_minute) / minutes_per_row))
        bottom = min(rows, max(top + 1, math.ceil((end - start_minute) / minutes_per_row)))
        blocks.append(Placement(item, top, bottom))
    blocks.sort(key=lambda p: (p.top, -p.bottom, p.item.ref))
    group, ends, group_end, group_index = [], [], -1, -1
    for block in blocks:
        if block.top >= group_end:
            for previous in group:
                previous.lanes = len(ends)
            group, ends = [], []
            group_index += 1
        available = next((i for i, end in enumerate(ends) if end <= block.top), len(ends))
        if available == len(ends):
            ends.append(block.bottom)
        else:
            ends[available] = block.bottom
        block.lane = available
        block.group = group_index
        group.append(block)
        group_end = max(p.bottom for p in group)
    for block in group:
        block.lanes = len(ends)
    return blocks


def span_lanes(items, first, days=7):
    """Pack multi-day bars into nonoverlapping lanes in a week or month row."""
    lo, hi = midnight(first), midnight(first + timedelta(days=days))
    bars = []
    for item in items:
        if item.overlaps(lo, hi):
            start = max(0, (item.task.start.date() - first).days)
            end_day = (item.task.end - timedelta(microseconds=1)).date()
            end = min(days, (end_day - first).days + 1)
            bars.append(Placement(item, start, end))
    bars.sort(key=lambda p: (p.top, -p.bottom, p.item.ref))
    ends = []
    for bar in bars:
        lane = next((i for i, end in enumerate(ends) if end <= bar.top), len(ends))
        if lane == len(ends):
            ends.append(bar.bottom)
        else:
            ends[lane] = bar.bottom
        bar.lane = lane
        bar.lanes = len(ends)
    return bars
