#!/usr/bin/env python3
"""Open a disposable visual-review calendar; never touches personal task data."""
import curses
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taskcal.model import Task
from taskcal.store import Store
import taskcal.tui as tui

AT = datetime(2026, 9, 26, 11, 20)
MONDAY = datetime(2026, 9, 21)

def seed(store):
    samples = [
        (0, 9, 10, 'DSA practice', 'completed', ['dsa']),
        (0, 14, 16, 'Project planning', 'completed', ['backend']),
        (0, 19, 20, 'Read system design', 'completed', ['personal']),
        (1, 10, 12, 'Implement caching', 'completed', ['backend']),
        (1, 15, 16, 'Code review', 'completed', ['project']),
        (2, 9.5, 11, 'Design discussion', 'pending', ['project']),
        (2, 13, 14, 'Review DBMS', 'completed', ['college']),
        (2, 16, 18, 'Write documentation', 'completed', ['backend']),
        (3, 8.5, 9.5, 'Client sync', 'completed', ['project']),
        (3, 11, 13, 'Build release', 'completed', ['backend']),
        (3, 15.5, 17, 'Interview prep', 'pending', ['interview']),
        (4, 9, 10, 'Inbox review', 'completed', ['personal']),
        (4, 11, 12, 'Schema review', 'completed', ['backend']),
        (4, 14, 16, 'SQL practice', 'completed', ['dsa']),
        (4, 17, 18, 'Plan next week', 'pending', ['personal']),
        (5, 10, 12, 'Deep work', 'ongoing', ['backend']),
        (5, 14, 15, 'Read technical book', 'pending', ['personal']),
        (5, 16, 18, 'Personal project', 'pending', ['project']),
        (6, 11, 12, 'Review DBMS', 'pending', ['college']),
        (6, 16, 18, 'Plan October', 'pending', ['personal']),
    ]
    selected = None
    for day,start,end,title,state,tags in samples:
        task = store.add(Task(title,start=MONDAY+timedelta(days=day,hours=start),end=MONDAY+timedelta(days=day,hours=end),state=state,tags=tags,priority='high' if title=='Deep work' else ('low' if title=='Read technical book' else 'normal'), notes='Focus on caching and persistence. Finish the implementation, then review the query plan.' if title=='Deep work' else ''), at=MONDAY)
        if title=='Deep work':
            selected = task.id
    store.add(Task('Backend project',start=MONDAY+timedelta(days=2),end=MONDAY+timedelta(days=12),all_day=True,tags=['project']),at=MONDAY)
    store.add(Task('Prepare for interviews',start=MONDAY+timedelta(days=5),end=MONDAY+timedelta(days=21),all_day=True,tags=['interview']),at=MONDAY)
    store.add(Task('Learn Redis persistence',tags=['backend'],notes='Read the RDB and AOF documentation.'),at=MONDAY)
    store.add(Task('Try a new Neovim workflow',tags=['personal'],priority='low'),at=MONDAY)
    return selected

def main():
    with tempfile.TemporaryDirectory(prefix='task-preview-') as directory:
        store=Store(Path(directory)/'preview.sqlite3')
        selected=seed(store)
        tui.now=lambda: AT
        def run(screen):
            app=tui.App(screen,store)
            app.day=AT.date()
            app.focus_ref=str(selected)
            app.select_relevant=False
            try:
                app.run()
            finally:
                app.paint.close()
                app.theme.restore()
        curses.wrapper(run)
        store.close()

if __name__=='__main__':
    main()
