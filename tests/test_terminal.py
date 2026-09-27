"""Real pseudo-terminal and subprocess checks; only Python's standard library."""
import curses
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from datetime import timedelta
from pathlib import Path

from taskcal.model import Task, now
from taskcal.store import Store
from taskcal.tui import App

ROOT = Path(__file__).resolve().parents[1]


class Screen:
    def __init__(self, height=30, width=110):
        self.height, self.width = height, width
        self.erase()

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.rows = [" " * self.width for _ in range(self.height)]

    def addstr(self, y, x, text, attr=0):
        assert 0 <= y < self.height and 0 <= x < self.width
        self.rows[y] = (self.rows[y][:x] + text + self.rows[y][x + len(text):])[:self.width]

    def refresh(self):
        pass

    def text(self):
        return "\n".join(row.rstrip() for row in self.rows)


class RenderTests(unittest.TestCase):
    def test_all_views_at_small_and_large_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "t.db")
            today = now().replace(hour=0, minute=0, second=0)
            for i in range(15):
                store.add(Task("Prepare project " + str(i), start=today + timedelta(hours=i), end=today + timedelta(hours=i+3), tags=["backend"]))
            store.add(Task("跨月项目 · café", start=today-timedelta(days=15), end=today+timedelta(days=45), all_day=True))
            for height, width in ((12, 50), (24, 80), (30, 110), (45, 160), (8, 30)):
                screen = Screen(height, width)
                app = App(screen, store)
                for view in ("day", "week", "month", "year", "inbox", "history", "search"):
                    app.view = view
                    app.refresh()
                    app.draw()
                    self.assertIn("TASK", screen.text())
            store.close()

    def test_day_shows_blocks_and_free_periods(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "t.db")
            today = now().replace(hour=0, minute=0, second=0)
            store.add(Task("DSA", start=today + timedelta(hours=5), end=today + timedelta(hours=10)))
            store.add(Task("SQL", start=today + timedelta(hours=9), end=today + timedelta(hours=11)))
            app = App(Screen(60,160), store)
            app.view = "day"
            app.start_minute = 0
            app.refresh()
            app.draw()
            self.assertEqual(2,len(app.views.card_rects))
            text = app.screen.text()
            self.assertIn("FREE TIME",text)
            self.assertIn("00:00–05:00", text)
            self.assertIn("11:00–24:00", text)
            store.close()


class TerminalSession(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "tasks.db"
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
        env = dict(os.environ, TERM="xterm-256color")
        self.proc = subprocess.Popen([sys.executable, "-m", "taskcal", "--db", str(self.db)], stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env, start_new_session=True)
        os.close(slave)
        self.output = b""
        self.wait_for(lambda: b"TASK" in self.output)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        os.close(self.master)
        self.temp.cleanup()

    def pump(self, delay=0.1):
        limit = time.monotonic() + delay
        while time.monotonic() < limit:
            readable, _, _ = select.select([self.master], [], [], max(0, limit - time.monotonic()))
            if readable:
                try:
                    self.output += os.read(self.master, 65536)
                except OSError:
                    break

    def send(self, value):
        os.write(self.master, value.encode())
        self.pump()

    def wait_for(self, predicate, timeout=3):
        until = time.monotonic() + timeout
        while not predicate() and time.monotonic() < until:
            self.pump()
        self.assertTrue(predicate(), self.output[-2500:].decode(errors="replace"))

    def task(self):
        s = Store(self.db)
        try:
            return s.tasks()[0]
        finally:
            s.close()

    def _tasks(self):
        store=Store(self.db)
        try:
            return store.tasks()
        finally:
            store.close()


class TerminalTests(TerminalSession):
    def test_capture_edit_state_undo_move_delete_and_resize(self):
        self.send("a")
        self.send("Read PostgreSQL docs\n")
        self.send("i")
        self.assertEqual(self.task().title, "Read PostgreSQL docs")
        self.assertEqual(self.task().state, "pending")
        self.send("s")
        self.assertEqual(self.task().state, "ongoing")
        self.send("x")
        self.assertEqual(self.task().state, "completed")
        self.send("u")
        self.assertEqual(self.task().state, "ongoing")
        self.send("e")
        self.send("\x15Read database docs\x13")
        self.wait_for(lambda: self.task().title == "Read database docs")
        self.send("r")
        self.send("\x15tomorrow\n")
        self.wait_for(lambda: self.task().start is not None)
        self.send("t")
        self.send("l")
        self.send("D")
        s = Store(self.db)
        self.assertFalse(s.tasks())
        s.close()
        self.send("u")
        self.assertEqual(self.task().title, "Read database docs")
        self.send("\n")
        self.send("\x1b")
        self.send("wm")
        self.send("?")
        self.send("inbox\n")
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 50, 0, 0))
        os.kill(self.proc.pid, signal.SIGWINCH)
        self.send("d")
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertEqual(0, self.proc.returncode)
        self.assertNotIn(b"Traceback", self.output)

    def test_form_saves_every_field_and_recurrence_stays_independent(self):
        self.send("a")
        self.send("Recurring review\t2026-10-04 17:00\t19:00\tpending")
        # Clear default fields before replacing them.
        self.send("\x15pending\t\x15high\t#college #dbms\tdaily\tRead SQL\\nReview indexes\x13")
        self.wait_for(lambda: bool(self._tasks()))
        task = self.task()
        self.assertEqual("daily",task.repeat)
        self.assertEqual("high",task.priority)
        self.assertEqual(["college","dbms"],task.tags)
        self.assertEqual("Read SQL\nReview indexes",task.notes)
        self.assertEqual(17,task.start.hour)
        self.assertEqual(19,task.end.hour)
        self.send("g")
        self.send("\x152026-10-04\n")
        self.send("x")
        def done():
            store=Store(self.db)
            try:
                return store.resolve(f"{task.id}@2026-10-04").task.state == "completed"
            finally:
                store.close()
        self.wait_for(done)
        store=Store(self.db)
        self.assertEqual("pending",store.resolve(f"{task.id}@2026-10-05").task.state)
        store.close()
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertEqual(0,self.proc.returncode)

    def test_live_external_edit_appears_without_keyboard_input(self):
        self.send("a")
        self.send("Initial capture\n")
        self.wait_for(lambda: bool(self._tasks()))
        self.send("i")
        store=Store(self.db)
        store.edit(str(self.task().id),{"title":"Live external update"})
        store.close()
        self.wait_for(lambda: b"Live external update" in self.output)
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertEqual(0,self.proc.returncode)


class BackgroundTests(unittest.TestCase):
    def test_daemon_reads_new_tasks_without_tui_and_locks_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, log = root / "tasks.db", root / "sent"
            fake = root / "notify-send"
            fake.write_text("#!/usr/bin/env python3\nimport os,sys\nwith open(os.environ['TASK_TEST_LOG'],'a') as f: f.write(repr(sys.argv)+'\\n')\n")
            fake.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"], TASK_TEST_LOG=str(log))
            command = [sys.executable, "-m", "taskcal", "--db", str(database), "reminders"]
            daemon = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            store = None
            try:
                deadline = time.monotonic() + 3
                lock = database.with_suffix(".reminders.lock")
                while not lock.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=3)
                self.assertEqual(0, second.returncode)
                store = Store(database)
                at = now()
                task = store.add(Task("Background reminder", start=at, end=at+timedelta(hours=1)), at=at)
                deadline = time.monotonic() + 12
                # notify-send writes the log before the daemon commits delivery.
                while time.monotonic() < deadline and (not log.exists() or store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0] < 1):
                    time.sleep(.05)
                self.assertTrue(log.exists(), "daemon did not deliver the new task")
                self.assertIn("Background reminder", log.read_text())
                self.assertEqual("pending", store.get(task.id).state)
                self.assertEqual(1, store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0])
            finally:
                if store:
                    store.close()
                daemon.terminate()
                daemon.communicate(timeout=3)
            self.assertEqual(0, daemon.returncode)


if __name__ == "__main__":
    unittest.main()
