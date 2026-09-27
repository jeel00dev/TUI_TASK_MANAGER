"""A small search vocabulary shared by the TUI and CLI."""
import re
import shlex
from datetime import datetime, timedelta

from .model import Occurrence, midnight, parse_date


def match(item: Occurrence, query: str, at: datetime) -> bool:
    task = item.task
    haystack = " ".join([task.title, task.notes, " ".join(task.tags or []), str(task.start or ""), str(task.end or "")]).casefold()
    try:
        words = shlex.split(query.casefold())
    except ValueError:
        words = query.casefold().split()
    for word in words:
        if word.startswith("#"):
            if word[1:] not in (task.tags or []):
                return False
        elif word.startswith("state:"):
            value = word[6:]
            if not (item.overdue(at) if value == "overdue" else task.state == value):
                return False
        elif word.startswith("priority:"):
            if task.priority != word[9:]:
                return False
        elif word.startswith("tag:"):
            if word[4:].lstrip("#") not in (task.tags or []):
                return False
        elif word.startswith(("from:", "to:", "on:")):
            kind, value = word.split(":", 1)
            bound = midnight(parse_date(value, at.date()))
            if not task.start:
                return False
            if kind == "from" and task.end <= bound:
                return False
            if kind == "to" and task.start >= bound + timedelta(days=1):
                return False
            if kind == "on" and not item.overlaps(bound, bound + timedelta(days=1)):
                return False
        elif word not in haystack:
            # Subsequence matching tolerates omitted letters without a dependency.
            letters = iter(task.title.casefold())
            if not all(any(c == wanted for c in letters) for wanted in word):
                return False
    return True


def search(store, query: str, at: datetime) -> list[Occurrence]:
    items = {o.ref: o for o in store.search_pool(at)}
    # Explicit date queries can reach recurring occurrences in any year.
    dates = []
    for value in re.findall(r"(?:from|to|on):([^\s]+)", query):
        dates.append(parse_date(value, at.date()))
    if dates:
        first, last = min(dates), max(dates)
        if len(dates) == 1 and "on:" not in query:
            first, last = first - timedelta(days=366), last + timedelta(days=366)
        items.update({o.ref: o for o in store.between(midnight(first), midnight(last) + timedelta(days=1), history=True, at=at)})
    return store.sort([o for o in items.values() if match(o, query, at)])
