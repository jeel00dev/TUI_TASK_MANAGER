"""Independent local reminder process. No UI, network, or systemd dependency."""
from __future__ import annotations

import fcntl
import html
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .model import Occurrence, now, schedule_text

GRACE = timedelta(seconds=90)


@dataclass
class Reminder:
    item: Occurrence
    kind: str
    due: datetime

    @property
    def key(self):
        return f"{self.item.ref}:{self.item.task.token}:{self.kind}:{self.due.isoformat()}"


def pending(store, at: datetime) -> list[Reminder]:
    """Recent due events only: no avalanche after suspend or an offline session."""
    items = store.between(at - GRACE, at + timedelta(minutes=16), history=True, at=at)
    result = []
    for item in items:
        task = item.task
        if task.state == "completed":
            continue
        for kind, due in (("upcoming", task.start - timedelta(minutes=15)), ("start", task.start)):
            if not at - GRACE <= due <= at:
                continue
            if kind == "upcoming" and task.scheduled > due:
                continue
            # Immediate tasks get a start event only within the short grace window.
            if kind == "start" and task.scheduled > due + GRACE:
                continue
            reminder = Reminder(item, kind, due)
            if not store.db.execute("SELECT 1 FROM deliveries WHERE key=?", (reminder.key,)).fetchone():
                result.append(reminder)
    for row in store.db.execute("SELECT * FROM snoozes WHERE due<=? AND due>=?", (at.isoformat(), (at - GRACE).isoformat())):
        try:
            item = store.resolve(row["ref"])
        except ValueError:
            continue
        if item.task.state == "completed" or item.task.token != row["token"]:
            continue
        reminder = Reminder(item, "snooze", datetime.fromisoformat(row["due"]))
        if not store.db.execute("SELECT 1 FROM deliveries WHERE key=?", (reminder.key,)).fetchone():
            result.append(reminder)
    return result


def send_desktop(summary: str, body: str, urgency: str):
    subprocess.run(
        ["notify-send", "--app-name=Task Calendar", f"--urgency={urgency}", "--expire-time=10000", "--hint=boolean:suppress-sound:true", "--", summary, body],
        check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def tick(store, at: datetime | None = None, send=send_desktop) -> int:
    at = at or now()
    delivered = 0
    # Hold a short write transaction through delivery: a simultaneous edit either
    # happens before this check or after this delivery, never from a stale copy.
    with store.transaction():
        groups = defaultdict(list)
        for event in pending(store, at):
            groups[(event.kind, event.due)].append(event)
        for (kind, due), events in groups.items():
            heading = {"upcoming": "Upcoming task", "start": "Task starting now", "snooze": "Task reminder"}[kind]
            if len(events) > 1:
                heading = {"upcoming": "Upcoming tasks", "start": "Tasks starting now", "snooze": "Task reminders"}[kind]
                heading += f" · {len(events)}"
            # Bound each desktop bubble while still including every task.
            for offset in range(0, len(events), 5):
                batch = events[offset:offset + 5]
                lines = []
                for event in batch:
                    task = event.item.task
                    text = f"{task.title}\n{schedule_text(task, full=True)}"
                    if kind == "upcoming":
                        remaining = max(1, round((task.start - at).total_seconds() / 60))
                        text += f" · starts in {remaining} minutes"
                    lines.append(html.escape(text))
                try:
                    send(heading, "\n\n".join(lines), "normal")
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"task reminders: delivery failed: {exc}", file=sys.stderr)
                    continue  # Retry on next tick until grace expires.
                for event in batch:
                    store.db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?)", (event.key, at.isoformat()))
                    if event.kind == "snooze":
                        store.db.execute("DELETE FROM snoozes WHERE ref=?", (event.item.ref,))
                delivered += len(batch)
        store.db.execute("DELETE FROM snoozes WHERE due<?", ((at - GRACE).isoformat(),))
    return delivered


def lock_path(store) -> Path:
    return store.path.with_suffix(".reminders.lock")


def running(store) -> bool:
    with lock_path(store).open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def run(store, once: bool = False) -> int:
    with lock_path(store).open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if once:
                print("Reminder process is already running.", file=sys.stderr)
            return 0
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        if once:
            tick(store)
            return 0
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            try:
                tick(store)
            except (sqlite3.Error, OSError) as exc:
                print(f"task reminders: {exc}", file=sys.stderr)
            stop.wait(10)
        return 0
