"""SQLite storage shared by CLI, TUI, and reminders. All user edits are undoable."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from .model import Task, Occurrence, fresh_token, midnight, now, occurrence, recurrence_dates


def data_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "task-calendar/tasks.sqlite3"


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=8, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS exceptions (
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                day TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(task_id, day));
            CREATE TABLE IF NOT EXISTS undo (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, label TEXT NOT NULL, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snoozes (
                ref TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                due TEXT NOT NULL, token TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def tasks(self) -> list[Task]:
        return [Task.from_record(dict(json.loads(r["data"]), id=r["id"])) for r in self.db.execute("SELECT * FROM tasks")]

    def get(self, task_id: int) -> Task:
        row = self.db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"Task {task_id} does not exist.")
        return Task.from_record(dict(json.loads(row[0]), id=task_id))

    def overrides(self) -> dict[tuple[int, str], dict]:
        return {(r["task_id"], r["day"]): json.loads(r["data"]) for r in self.db.execute("SELECT * FROM exceptions")}

    def resolve(self, ref: str) -> Occurrence:
        parts = ref.split("@", 1)
        try:
            task = self.get(int(parts[0]))
        except (ValueError, TypeError):
            raise ValueError(f"Unknown task reference: {ref}") from None
        day = parts[1] if len(parts) > 1 else ""
        if task.repeat and not day:
            raise ValueError("Use an occurrence reference, such as 3@2026-09-26, for a recurring task.")
        if day:
            try:
                d = date.fromisoformat(day)
                valid = task.repeat and (next(recurrence_dates(task, d, d), None) or (task.id, day) in self.overrides())
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("That date is not part of this recurrence.")
        result = occurrence(task, day, self.overrides().get((task.id, day)))
        if result.deleted:
            raise ValueError("This occurrence was deleted. Use undo to restore it.")
        return result

    def _snapshot(self, task_id: int, label: str, absent: bool = False):
        snapshot = None if absent else {
            "task": self.get(task_id).record(),
            "exceptions": [dict(r) for r in self.db.execute("SELECT * FROM exceptions WHERE task_id=?", (task_id,))],
            "snoozes": [dict(r) for r in self.db.execute("SELECT * FROM snoozes WHERE task_id=?", (task_id,))],
        }
        self.db.execute("INSERT INTO undo(task_id,label,snapshot) VALUES(?,?,?)", (task_id, label, json.dumps(snapshot)))
        self.db.execute("DELETE FROM undo WHERE id NOT IN (SELECT id FROM undo ORDER BY id DESC LIMIT 100)")

    def _write(self, task: Task):
        self.db.execute("UPDATE tasks SET data=? WHERE id=?", (json.dumps(task.record()), task.id))

    def add(self, task: Task, at: datetime | None = None) -> Task:
        at = at or now()
        task = replace(task).validate()
        task.created = task.scheduled = at
        task.token = fresh_token()
        task.completed = at if task.state == "completed" else None
        with self.transaction():
            task.id = self.db.execute("INSERT INTO tasks(data) VALUES(?)", (json.dumps(task.record()),)).lastrowid
            self._snapshot(task.id, f"add {task.title}", absent=True)
            self._write(task)
        return task

    def edit(self, ref: str, changes: dict, series: bool = False, at: datetime | None = None):
        at = at or now()
        allowed = {"title", "start", "end", "all_day", "state", "priority", "tags", "notes", "repeat"}
        if set(changes) - allowed:
            raise ValueError("Unknown task field.")
        with self.transaction():
            original = self.get(int(ref.split("@")[0]))
            item = occurrence(original) if series else self.resolve(ref)
            target = replace(item.task, **changes)
            # Occurrences keep their series label, but may have any state.
            repeat = target.repeat
            if item.day:
                if "repeat" in changes and changes["repeat"] != original.repeat:
                    raise ValueError("Use E (edit series) to change recurrence.")
                if not target.start:
                    raise ValueError("Keep a schedule for a recurring occurrence. Capture an Inbox task separately.")
                target.repeat = ""
            target.validate()
            if item.day:
                target.repeat = repeat
            timing = any(getattr(target, k) != getattr(item.task, k) for k in ("start", "end", "all_day", "repeat"))
            if timing:
                target.token, target.scheduled = fresh_token(), at
            if target.state != item.task.state:
                target.completed = at if target.state == "completed" else None
            self._snapshot(original.id, f"edit {target.title}")
            if item.day:
                baseline = occurrence(original, item.day).task.record()
                changed = {k: v for k, v in target.record().items() if baseline[k] != v}
                self.db.execute("INSERT OR REPLACE INTO exceptions VALUES(?,?,?)", (original.id, item.day, json.dumps(changed)))
                if timing or target.state == "completed":
                    self.db.execute("DELETE FROM snoozes WHERE ref=?", (ref,))
            else:
                self._write(target)
                if timing:
                    # Explicitly edited occurrences retain their schedule and state.
                    detached = []
                    for (tid, day), patch in self.overrides().items():
                        if tid == original.id:
                            old = occurrence(original, day, patch)
                            if target.repeat:
                                frozen = old.task.record()
                                frozen["repeat"] = target.repeat
                                frozen["deleted"] = old.deleted
                                self.db.execute("UPDATE exceptions SET data=? WHERE task_id=? AND day=?", (json.dumps(frozen), tid, day))
                            elif not old.deleted:
                                old.task.repeat = ""
                                cursor = self.db.execute("INSERT INTO tasks(data) VALUES(?)", (json.dumps(old.task.record()),))
                                detached.append(cursor.lastrowid)
                    row = self.db.execute("SELECT id,snapshot FROM undo ORDER BY id DESC LIMIT 1").fetchone()
                    snap = json.loads(row["snapshot"])
                    snap["detached"] = detached
                    self.db.execute("UPDATE undo SET snapshot=? WHERE id=?", (json.dumps(snap), row["id"]))
                    if not target.repeat:
                        self.db.execute("DELETE FROM exceptions WHERE task_id=?", (original.id,))
                    self.db.execute("DELETE FROM snoozes WHERE task_id=?", (original.id,))
                elif target.state == "completed":
                    self.db.execute("DELETE FROM snoozes WHERE task_id=?", (original.id,))

    def delete(self, ref: str, series: bool = False):
        with self.transaction():
            tid = int(ref.split("@")[0])
            item = occurrence(self.get(tid)) if series else self.resolve(ref)
            self._snapshot(tid, f"delete {item.task.title}")
            if item.day:
                self.db.execute("INSERT OR REPLACE INTO exceptions VALUES(?,?,?)", (tid, item.day, '{"deleted":true}'))
                self.db.execute("DELETE FROM snoozes WHERE ref=?", (ref,))
            else:
                self.db.execute("DELETE FROM tasks WHERE id=?", (tid,))

    def snooze(self, ref: str, minutes: int, at: datetime | None = None):
        if minutes not in (5, 10, 15, 30, 60):
            raise ValueError("Snooze for 5, 10, 15, 30, or 60 minutes.")
        at = at or now()
        with self.transaction():
            item = self.resolve(ref)
            if item.task.state == "completed" or not item.task.start:
                raise ValueError("Only unfinished scheduled tasks can be snoozed.")
            self._snapshot(item.task.id, f"snooze {item.task.title}")
            self.db.execute("INSERT OR REPLACE INTO snoozes VALUES(?,?,?,?)", (ref, item.task.id, (at + timedelta(minutes=minutes)).isoformat(), item.task.token))

    def undo(self) -> str:
        with self.transaction():
            row = self.db.execute("SELECT * FROM undo ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                raise ValueError("Nothing to undo.")
            snap = json.loads(row["snapshot"])
            self.db.execute("DELETE FROM tasks WHERE id=?", (row["task_id"],))
            if snap:
                self.db.execute("INSERT INTO tasks(id,data) VALUES(?,?)", (row["task_id"], json.dumps(snap["task"])))
                for r in snap["exceptions"]:
                    self.db.execute("INSERT INTO exceptions VALUES(?,?,?)", (r["task_id"], r["day"], r["data"]))
                for r in snap["snoozes"]:
                    self.db.execute("INSERT INTO snoozes VALUES(?,?,?,?)", (r["ref"], r["task_id"], r["due"], r["token"]))
                for tid in snap.get("detached", []):
                    self.db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            self.db.execute("DELETE FROM undo WHERE id=?", (row["id"],))
            return row["label"]

    def between(self, start: datetime, end: datetime, history: bool = False, at: datetime | None = None) -> list[Occurrence]:
        at = at or now()
        overrides = self.overrides()
        result = {}
        for task in self.tasks():
            if not task.start:
                continue
            if not task.repeat:
                item = occurrence(task)
                if item.overlaps(start, end):
                    result[item.ref] = item
                continue
            duration = task.end - task.start
            first = max(date.min, (start - min(duration, start - datetime.min)).date())
            for day in recurrence_dates(task, first, end.date()):
                item = occurrence(task, str(day), overrides.get((task.id, str(day))))
                if not item.deleted and item.overlaps(start, end):
                    result[item.ref] = item
            # A moved occurrence may originate outside the visible range.
            for (tid, day), patch in overrides.items():
                if tid == task.id and "start" in patch:
                    item = occurrence(task, day, patch)
                    if not item.deleted and item.overlaps(start, end):
                        result[item.ref] = item
        return self.sort([o for o in result.values() if history or not o.archived(at)])

    @staticmethod
    def sort(items):
        return sorted(items, key=lambda o: (o.task.start or datetime.max, o.task.state == "completed", o.task.priority != "high", o.task.title.casefold(), o.ref))

    def inbox(self, history: bool = False) -> list[Occurrence]:
        return self.sort([occurrence(t) for t in self.tasks() if not t.start and (history or not occurrence(t).archived(now()))])

    def history(self) -> list[Occurrence]:
        result = []
        overrides = self.overrides()
        for task in self.tasks():
            if not task.repeat and task.state == "completed":
                result.append(occurrence(task))
            for (tid, day), patch in overrides.items():
                if tid == task.id:
                    item = occurrence(task, day, patch)
                    if not item.deleted and item.task.state == "completed":
                        result.append(item)
        return sorted(result, key=lambda o: o.task.completed or datetime.min, reverse=True)

    def overdue(self, at: datetime | None = None) -> list[Occurrence]:
        at = at or now()
        starts = [t.start for t in self.tasks() if t.start]
        if not starts:
            return []
        return [o for o in self.between(min(starts), at, at=at) if o.overdue(at)]

    def search_pool(self, at: datetime | None = None) -> list[Occurrence]:
        at = at or now()
        result = {o.ref: o for o in self.inbox(True) + self.history()}
        overrides = self.overrides()
        for t in self.tasks():
            if not t.repeat:
                result[str(t.id)] = occurrence(t)
            else:
                for (tid, day), patch in overrides.items():
                    if tid == t.id:
                        item = occurrence(t, day, patch)
                        if not item.deleted:
                            result[item.ref] = item
        result.update({o.ref: o for o in self.between(at - timedelta(days=366), at + timedelta(days=366), history=True, at=at)})
        return self.sort(list(result.values()))
