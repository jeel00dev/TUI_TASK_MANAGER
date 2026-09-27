"""Unix entry point: no arguments launches curses; subcommands are scriptable."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

from . import __version__
from .calendar import bounds
from .model import Task, now, parse_date, schedule, schedule_text, shifted_start, tags_from
from .query import match, search
from .store import Store


def fields(parser, creating=False):
    if creating:
        parser.add_argument("title")
    else:
        parser.add_argument("--title")
    parser.add_argument("--start", help="Local YYYY-MM-DD HH:MM, today 17:00, or a date")
    parser.add_argument("--end", help="Date-only end is inclusive; default +1 hour / one day")
    parser.add_argument("--state", choices=("pending", "ongoing", "completed"), default="pending" if creating else None)
    parser.add_argument("--priority", choices=("low", "normal", "high"), default="normal" if creating else None)
    parser.add_argument("--tags", help="Space/comma separated tags")
    parser.add_argument("--notes")
    parser.add_argument("--repeat", help="daily, weekly, monthly, weekdays, or mon,wed,fri")


def parser():
    root = argparse.ArgumentParser(prog="task", description="Local task calendar. Run without arguments to open the terminal UI.")
    root.add_argument("--version", action="version", version=f"Task Calendar {__version__}")
    root.add_argument("--db", help="Use an alternative SQLite database")
    commands = root.add_subparsers(dest="command")
    add = commands.add_parser("add", help="Quick capture to Inbox, optionally scheduled")
    fields(add, creating=True)
    edit = commands.add_parser("edit", help="Edit a task or occurrence")
    edit.add_argument("ref")
    edit.add_argument("--series", action="store_true")
    fields(edit)
    listing = commands.add_parser("list", help="Print tasks, with optional search/filter")
    listing.add_argument("--view", choices=("day", "week", "month", "year", "inbox", "history", "all"), default="day")
    listing.add_argument("--date", default="today")
    listing.add_argument("--search")
    listing.add_argument("--filter", default="")
    show = commands.add_parser("show", help="Inspect full task details")
    show.add_argument("ref")
    for command, help_text in (("start", "Set ongoing"), ("done", "Set completed"), ("pending", "Set pending")):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("ref")
    move = commands.add_parser("move", help="Reschedule, preserving duration")
    move.add_argument("ref")
    move.add_argument("when", help="tomorrow, +1h, +1d, +1w, or date/time")
    delete = commands.add_parser("delete", help="Delete a task/occurrence; recover with undo")
    delete.add_argument("ref")
    delete.add_argument("--series", action="store_true")
    snooze = commands.add_parser("snooze", help="Request one additional reminder")
    snooze.add_argument("ref")
    snooze.add_argument("minutes", type=int, choices=(5, 10, 15, 30, 60))
    commands.add_parser("undo", help="Undo the last edit, including deletion")
    reminders = commands.add_parser("reminders", help="Run the independent reminder process")
    group = reminders.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="Check due reminders once")
    group.add_argument("--start", action="store_true", help="Start a detached reminder process")
    group.add_argument("--test", action="store_true", help="Show a test desktop notification")
    commands.add_parser("doctor", help="Check local storage and notification setup")
    setup = commands.add_parser("install", help="Install task in ~/.local/bin and enable session autostart")
    setup.add_argument("--no-autostart", action="store_true")
    setup.add_argument("--with-dunst", action="store_true", help="Also start installed Dunst and enable its i3 session autostart")
    return root


def safe(value):
    # Prevent task text from injecting terminal escape/control sequences.
    import unicodedata
    return "".join(c if c == "\n" or not unicodedata.category(c).startswith("C") else " " for c in str(value))


def print_item(item):
    state = "overdue/" + item.task.state if item.overdue(now()) else item.task.state
    tags = " ".join("#" + t for t in item.task.tags or [])
    print(safe(f"{item.ref:<15} {state:<16} {schedule_text(item.task, full=True):<36} {item.task.title}  {tags}"))


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    store = None
    try:
        store = Store(args.db)
        command = args.command
        if command is None:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("The TUI needs an interactive terminal. Use task list or task --help.")
            from .tui import launch
            launch(store)
        elif command in ("add", "edit"):
            changes = {field: getattr(args, field) for field in ("title", "state", "priority", "notes", "repeat") if getattr(args, field) is not None}
            if args.tags is not None:
                changes["tags"] = tags_from(args.tags)
            if command == "add" or args.start is not None or args.end is not None:
                start, end = args.start or "", args.end or ""
                if command == "edit":
                    old = store.get(int(args.ref.split("@")[0])) if args.series else store.resolve(args.ref).task
                    if args.start is None:
                        start = old.start.strftime("%Y-%m-%d" + ("" if old.all_day else " %H:%M")) if old.start else ""
                    if args.end is None and args.start is None:
                        end = old.end.isoformat(" ") if old.end else ""
                begins, finishes, all_day = schedule(start, end)
                changes.update(start=begins, end=finishes, all_day=all_day)
            if command == "add":
                result = store.add(Task(**changes))
                print(f"Added {result.id}" + (" to Inbox" if not result.start else ""))
            else:
                if not changes:
                    raise ValueError("Provide fields to edit, for example --title or --priority.")
                store.edit(args.ref, changes, series=args.series)
                print(f"Updated {args.ref}")
        elif command == "list":
            at = now()
            if args.search is not None:
                items = search(store, args.search, at)
            elif args.view == "inbox":
                items = store.inbox()
            elif args.view == "history":
                items = store.history()
            elif args.view == "all":
                items = store.search_pool(at)
            else:
                day = parse_date(args.date)
                lo, hi = bounds(day, args.view)
                items = store.between(lo, hi)
                if day == at.date() and args.view == "day":
                    seen = {o.ref for o in items}
                    items += [o for o in store.overdue(at) if o.ref not in seen]
            for item in items:
                if match(item, args.filter, at):
                    print_item(item)
        elif command == "show":
            item = store.resolve(args.ref)
            print_item(item)
            task = item.task
            print(safe(f"Priority: {task.priority}\nRepeat: {task.repeat or 'none'}\nDuration: {task.end - task.start if task.start else 'unscheduled'}\n\n{task.notes}"))
        elif command in ("start", "done", "pending"):
            state = {"start": "ongoing", "done": "completed", "pending": "pending"}[command]
            store.edit(args.ref, {"state": state})
            print(f"{args.ref}: {state}")
        elif command == "move":
            task = store.resolve(args.ref).task
            start, end = shifted_start(args.when, task)
            store.edit(args.ref, {"start": start, "end": end, "all_day": task.all_day and start.hour == start.minute == start.second == 0})
            print(f"Moved {args.ref} to {start:%Y-%m-%d %H:%M}")
        elif command == "delete":
            store.delete(args.ref, series=args.series)
            print(f"Deleted {args.ref}; task undo restores it")
        elif command == "snooze":
            store.snooze(args.ref, args.minutes)
            print(f"Snoozed {args.ref} for {args.minutes} minutes")
        elif command == "undo":
            print("Undid " + store.undo())
        elif command == "reminders":
            from .notifier import run, send_desktop
            if args.test:
                send_desktop("Task Calendar", "Local desktop reminders are working.", "normal")
                print("Sent test notification")
            elif args.start:
                from .integration import start_reminders
                print("Started reminders" if start_reminders(store) else "Reminders already running")
            else:
                return run(store, once=args.once)
        elif command == "doctor":
            from .integration import doctor
            print("\n".join(doctor(store)))
        elif command == "install":
            from .integration import install, start_dunst
            print("\n".join(install(args.no_autostart, args.with_dunst)), flush=True)
            if args.with_dunst:
                start_dunst()
            if not args.no_autostart:
                # Use the installed module so deleting the source tree is safe.
                launcher = os.path.expanduser("~/.local/bin/task")
                subprocess.run([launcher, "reminders", "--start"], check=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"task: {exc}", file=sys.stderr)
        return 1
    finally:
        if store:
            store.close()
