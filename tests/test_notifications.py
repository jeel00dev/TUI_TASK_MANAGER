import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from taskcal.model import Task
from taskcal.notifier import tick
from taskcal.store import Store

AT = datetime(2026, 9, 26, 16)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "tasks.db")
        self.sent = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, at=AT, **kwargs):
        fields = dict(title="DSA", start=AT + timedelta(hours=1), end=AT + timedelta(hours=2))
        fields.update(kwargs)
        return self.store.add(Task(**fields), at=at)

    def tick(self, at):
        return tick(self.store, at, send=lambda *args: self.sent.append(args))

    def test_two_notifications_no_state_change_or_repeats(self):
        task = self.add()
        self.assertEqual(0, self.tick(AT + timedelta(minutes=44)))
        self.assertEqual(1, self.tick(AT + timedelta(minutes=45)))
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45, seconds=10)))
        self.assertEqual(1, self.tick(AT + timedelta(hours=1)))
        self.assertEqual(0, self.tick(AT + timedelta(hours=2)))
        self.assertEqual("pending", self.store.get(task.id).state)

    def test_late_creation_skips_upcoming(self):
        self.add(at=AT + timedelta(minutes=55))
        self.assertEqual(0, self.tick(AT + timedelta(minutes=55)))
        self.assertEqual(1, self.tick(AT + timedelta(hours=1)))
        self.assertIn("starting now", self.sent[0][0])

    def test_creation_one_second_after_reminder_does_not_catch_up(self):
        self.add(at=AT + timedelta(minutes=45, seconds=1))
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45, seconds=5)))

    def test_immediate_task_only_starts_once(self):
        self.add(start=AT, end=AT + timedelta(hours=1))
        self.assertEqual(1, self.tick(AT))
        self.assertEqual(0, self.tick(AT + timedelta(seconds=5)))

    def test_backdated_task_does_not_notify(self):
        self.add(at=AT + timedelta(hours=3))
        self.assertEqual(0, self.tick(AT + timedelta(hours=3)))

    def test_completed_and_deleted_tasks_suppressed(self):
        completed, deleted = self.add(), self.add(title="deleted")
        self.store.edit(str(completed.id), {"state": "completed"}, at=AT)
        self.store.delete(str(deleted.id))
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45)))
        self.assertEqual(0, self.tick(AT + timedelta(hours=1)))

    def test_reschedule_cancels_old_and_enables_new(self):
        task = self.add()
        self.store.edit(str(task.id), {"start": AT + timedelta(hours=3), "end": AT + timedelta(hours=4)}, at=AT)
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45)))
        self.assertEqual(0, self.tick(AT + timedelta(hours=1)))
        self.assertEqual(1, self.tick(AT + timedelta(hours=2, minutes=45)))
        self.assertEqual(1, self.tick(AT + timedelta(hours=3)))

    def test_restart_deduplicates(self):
        self.add()
        self.tick(AT + timedelta(minutes=45))
        path = self.store.path
        self.store.close()
        self.store = Store(path)
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45, seconds=20)))

    def test_recurring_completion_does_not_suppress_next_day(self):
        task = self.add(repeat="daily")
        self.store.edit(f"{task.id}@2026-09-26", {"state": "completed"}, at=AT)
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45)))
        self.assertEqual(1, self.tick(AT + timedelta(days=1, minutes=45)))
        self.assertEqual(1, self.tick(AT + timedelta(days=1, hours=1)))

    def test_long_task_starts_only_once(self):
        self.add(end=AT + timedelta(days=40))
        self.assertEqual(1, self.tick(AT + timedelta(hours=1)))
        self.assertEqual(0, self.tick(AT + timedelta(days=1, hours=1)))

    def test_simultaneous_tasks_group_without_dropping(self):
        for i in range(12):
            self.add(title=f"Task {i}")
        self.assertEqual(12, self.tick(AT + timedelta(minutes=45)))
        self.assertEqual(3, len(self.sent))
        self.assertEqual(12, self.store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0])
        for i in range(12):
            self.assertIn(f"Task {i}\n", "\n".join(body for _, body, _ in self.sent))

    def test_snooze_is_explicit_once_and_does_not_change_state(self):
        task = self.add()
        self.store.snooze(str(task.id), 10, at=AT + timedelta(hours=1))
        self.assertEqual(1, self.tick(AT + timedelta(hours=1, minutes=10)))
        self.assertEqual(0, self.tick(AT + timedelta(hours=1, minutes=11)))
        self.assertEqual("pending", self.store.get(task.id).state)

    def test_completion_and_move_cancel_snooze(self):
        task = self.add()
        self.store.snooze(str(task.id), 10, at=AT)
        self.store.edit(str(task.id), {"state": "completed"}, at=AT)
        self.assertEqual(0, self.tick(AT + timedelta(minutes=10)))
        self.store.undo()
        self.store.edit(str(task.id), {"start": AT + timedelta(days=1), "end": AT + timedelta(days=1, hours=1)}, at=AT)
        self.assertEqual(0, self.tick(AT + timedelta(minutes=10)))

    def test_suspend_does_not_deliver_stale_events(self):
        self.add()
        self.assertEqual(0, self.tick(AT + timedelta(hours=1, minutes=5)))

    def test_delivery_failure_retries_without_marking_sent(self):
        self.add()
        def fail(*_):
            raise OSError("test notification service unavailable")
        self.assertEqual(0, tick(self.store, AT + timedelta(minutes=45), send=fail))
        self.assertEqual(0, self.store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0])
        self.assertEqual(1, self.tick(AT + timedelta(minutes=45, seconds=10)))

    def test_undo_completion_does_not_replay_delivered_events(self):
        task = self.add()
        self.tick(AT + timedelta(minutes=45))
        self.store.edit(str(task.id), {"state": "completed"}, at=AT)
        self.store.undo()
        self.assertEqual(0, self.tick(AT + timedelta(minutes=45, seconds=10)))

    def test_title_markup_is_escaped(self):
        self.add(title="DSA <b>practice</b> & SQL")
        self.tick(AT + timedelta(minutes=45))
        self.assertIn("&lt;b&gt;", self.sent[0][1])


if __name__ == "__main__":
    unittest.main()
