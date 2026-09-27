#!/usr/bin/env python3
"""Disposable, clock-controlled sessions for the recorded product tour."""
import argparse
import curses
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.preview import seed, AT, MONDAY
from taskcal.model import Task
from taskcal.store import Store
import taskcal.store as storage
import taskcal.tui as tui
import taskcal.notifier as notifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('mode', choices=('ui', 'reminders'))
    args = parser.parse_args()
    # Never open a personal database when running recording helpers.
    if not (args.directory / '.task-calendar-demo').exists():
        parser.error('Use a disposable directory with a .task-calendar-demo marker')
    clock = args.directory / 'clock.txt'
    def now():
        return datetime.fromisoformat(clock.read_text().strip())
    db = args.directory / 'data/task-calendar/tasks.sqlite3'
    fresh = not db.exists()
    store = Store(db)
    selected = None
    if fresh:
        selected = seed(store)
        store.add(Task('Pair on query tuning', start=AT.replace(hour=10, minute=45),
                       end=AT.replace(hour=11, minute=45), tags=['backend']), at=MONDAY)
        store.add(Task('Daily DSA practice', start=AT.replace(hour=18, minute=0),
                       end=AT.replace(hour=19, minute=0), repeat='daily',
                       priority='high', tags=['dsa'], notes='Five questions. Review the difficult solutions.'), at=MONDAY)
        store.add(Task('Ship the database project', start=datetime(2026,10,10),
                       end=datetime(2027,1,16), all_day=True, tags=['project']), at=MONDAY)
        store.add(Task('Finish the first prototype', state='completed',
                       start=datetime(2026,6,1,9), end=datetime(2026,6,1,11)), at=datetime(2026,6,1,11))
        store.add(Task('Prepare the interview', start=datetime(2026,10,12,17),
                       end=datetime(2026,10,12,19), priority='high'), at=MONDAY)
    else:
        selected = next((t.id for t in store.tasks() if t.title == 'Deep work'), None)
    storage.now = tui.now = notifier.now = now
    try:
        if args.mode == 'reminders':
            notifier.run(store)
        else:
            def run(screen):
                app = tui.App(screen, store)
                app.day = now().date()
                app.focus_ref = str(selected) if selected else None
                app.select_relevant = False
                try:
                    app.run()
                finally:
                    app.paint.close()
                    app.theme.restore()
            curses.wrapper(run)
    finally:
        store.close()


if __name__ == '__main__':
    main()
