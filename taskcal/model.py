"""Local wall-clock scheduling and recurrence, independent of storage and UI."""
from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Iterator
from uuid import uuid4

STATES = ("pending", "ongoing", "completed")
PRIORITIES = ("low", "normal", "high")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min)


def parse_date(value: str, base: date | None = None) -> date:
    base = base or date.today()
    value = value.strip().lower()
    if value == "today":
        return base
    if value == "tomorrow":
        return base + timedelta(days=1)
    if value in WEEKDAYS:
        return base + timedelta(days=(WEEKDAYS.index(value) - base.weekday()) % 7)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use YYYY-MM-DD, today, tomorrow, or mon … sun.") from None


def parse_moment(value: str, base: date | None = None) -> datetime:
    value = value.strip().lower()
    if re.match(r"^\d{4}-", value):
        value = value.replace("t", " ")
    if value == "now":
        return now()
    parts = value.split()
    try:
        if len(parts) == 1 and ":" in parts[0]:
            return datetime.combine(base or date.today(), time.fromisoformat(parts[0]))
        if len(parts) not in (1, 2):
            raise ValueError
        day = parse_date(parts[0], base)
        return datetime.combine(day, time.fromisoformat(parts[1]) if len(parts) == 2 else time.min)
    except (ValueError, IndexError):
        raise ValueError("Use YYYY-MM-DD HH:MM, today 17:00, tomorrow 09:00, or HH:MM.") from None


def schedule(start: str, end: str = "", base: date | None = None) -> tuple[datetime | None, datetime | None, bool]:
    if not start.strip():
        if end.strip():
            raise ValueError("Set a start before an end, or leave both empty for Inbox.")
        return None, None, False
    begins = parse_moment(start, base)
    all_day = ":" not in start and start.strip().lower() != "now"
    if end.strip():
        finishes = parse_moment(end, begins.date())
        if all_day and ":" not in end:
            finishes += timedelta(days=1)  # Date-only end is inclusive to the user.
        elif re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", end.strip()) and finishes <= begins:
            finishes += timedelta(days=1)
    else:
        finishes = begins + timedelta(days=1 if all_day else 0, hours=0 if all_day else 1)
    if finishes <= begins:
        raise ValueError("End must be after start.")
    return begins, finishes, all_day


def normalize_repeat(value: str) -> str:
    value = value.strip().lower().replace(" ", "")
    if value in ("", "none", "off"):
        return ""
    if value in ("daily", "weekly", "monthly"):
        return value
    if value == "weekdays":
        return "mon,tue,wed,thu,fri"
    days = value.split(",")
    if all(d in WEEKDAYS for d in days):
        return ",".join(d for d in WEEKDAYS if d in days)
    raise ValueError("Repeat: daily, weekly, monthly, weekdays, or mon,wed,fri.")


def tags_from(value: str) -> list[str]:
    return list(dict.fromkeys(t.lstrip("#").lower() for t in re.split(r"[\s,]+", value.strip()) if t.lstrip("#")))


@dataclass
class Task:
    title: str
    id: int = 0
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    state: str = "pending"
    priority: str = "normal"
    tags: list[str] | None = None
    notes: str = ""
    repeat: str = ""
    created: datetime | None = None
    scheduled: datetime | None = None
    completed: datetime | None = None
    token: str = ""

    def validate(self) -> Task:
        self.title = self.title.strip()
        if not self.title or "\n" in self.title or len(self.title) > 500:
            raise ValueError("Title must be one line, between 1 and 500 characters.")
        if self.state not in STATES:
            raise ValueError("State: pending, ongoing, or completed.")
        if self.priority not in PRIORITIES:
            raise ValueError("Priority: low, normal, or high.")
        if bool(self.start) != bool(self.end) or (self.start and self.end <= self.start):
            raise ValueError("A schedule needs both start and end, with end after start.")
        if self.start and (self.start.tzinfo or self.end.tzinfo):
            raise ValueError("Use local times without a timezone offset.")
        self.repeat = normalize_repeat(self.repeat)
        if self.repeat and not self.start:
            raise ValueError("Schedule the task before setting recurrence.")
        if self.repeat and self.state != "pending":
            raise ValueError("A recurring series starts pending. Change an individual occurrence's state.")
        self.tags = tags_from(" ".join(self.tags or []))
        return self

    def record(self) -> dict:
        result = asdict(self)
        for field in ("start", "end", "created", "scheduled", "completed"):
            result[field] = result[field].isoformat() if result[field] else None
        return result

    @classmethod
    def from_record(cls, data: dict) -> Task:
        data = dict(data)
        for field in ("start", "end", "created", "scheduled", "completed"):
            if data.get(field):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)


@dataclass
class Occurrence:
    task: Task
    day: str = ""
    deleted: bool = False

    @property
    def ref(self) -> str:
        return str(self.task.id) + ("@" + self.day if self.day else "")

    def overdue(self, at: datetime) -> bool:
        return bool(self.task.end and self.task.end < at and self.task.state != "completed")

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return bool(self.task.start and self.task.start < end and self.task.end > start)

    def archived(self, at: datetime) -> bool:
        last = self.task.completed or self.task.end or self.task.created or at
        return self.task.state == "completed" and last < at - timedelta(days=30)


def recurrence_dates(task: Task, first: date, last: date) -> Iterator[date]:
    """Yield occurrences in [first, last], jumping directly to the requested range."""
    anchor = task.start.date()
    first = max(anchor, first)
    if first > last:
        return
    if task.repeat == "monthly":
        year, month = first.year, first.month
        while (year, month) <= (last.year, last.month):
            if anchor.day <= calendar.monthrange(year, month)[1]:
                candidate = date(year, month, anchor.day)
                if first <= candidate <= last:
                    yield candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return
    days = {anchor.weekday()} if task.repeat == "weekly" else ({WEEKDAYS.index(d) for d in task.repeat.split(",")} if task.repeat != "daily" else set(range(7)))
    current = first
    while current <= last:
        if current.weekday() in days:
            yield current
        current += timedelta(days=1)


def occurrence(task: Task, day: str = "", override: dict | None = None) -> Occurrence:
    result = replace(task, tags=list(task.tags or []))
    if day:
        shift = date.fromisoformat(day) - task.start.date()
        result.start += shift
        result.end += shift
    if override:
        data = result.record()
        data.update({k: v for k, v in override.items() if k != "deleted"})
        result = Task.from_record(data)
    return Occurrence(result, day, bool(override and override.get("deleted")))


def fresh_token() -> str:
    return uuid4().hex


def schedule_text(task: Task, full: bool = False) -> str:
    if not task.start:
        return "Inbox · unscheduled"
    if task.all_day:
        end = (task.end - timedelta(microseconds=1)).date()
        return str(task.start.date()) + (" → " + str(end) if end != task.start.date() else " · all day")
    if full or task.start.date() != task.end.date():
        return f"{task.start:%Y-%m-%d %H:%M} → {task.end:%Y-%m-%d %H:%M}"
    return f"{task.start:%H:%M}–{task.end:%H:%M}"


def shifted_start(value: str, task: Task, at: datetime | None = None) -> tuple[datetime, datetime]:
    at = at or now()
    value = value.strip().lower()
    match = re.fullmatch(r"\+?(\d+)\s*(m|h|d|w)", value)
    if match:
        amount, unit = int(match[1]), match[2]
        delta = timedelta(minutes=amount * {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit])
        start = (task.start or at) + delta
    elif ":" not in value and value != "now":
        start = datetime.combine(parse_date(value, at.date()), task.start.time() if task.start else time(9))
    else:
        start = parse_moment(value, at.date())
    duration = task.end - task.start if task.start else timedelta(hours=1)
    return start, start + duration
