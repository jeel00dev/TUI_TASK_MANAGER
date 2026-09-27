import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from taskcal.calendar import bounds, move_date, segments, workload
from taskcal.model import Task, normalize_repeat, occurrence, parse_moment, recurrence_dates, schedule, shifted_start
from taskcal.query import search
from taskcal.store import Store

AT = datetime(2026, 9, 26, 12)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "tasks.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, **changes):
        values = dict(title="Practice DSA", start=AT + timedelta(hours=5), end=AT + timedelta(hours=7))
        values.update(changes)
        return self.store.add(Task(**values), at=AT)

    def test_inbox_and_default_pending(self):
        t = self.add(start=None, end=None)
        self.assertEqual(t.state, "pending")
        self.assertEqual([str(t.id)], [o.ref for o in self.store.inbox()])
        self.assertEqual([], self.store.between(AT, AT + timedelta(days=1)))

    def test_half_open_intervals_and_multi_month_spans(self):
        t = self.add(start=datetime(2026, 10, 10), end=datetime(2026, 11, 16), all_day=True)
        for day in (date(2026, 10, 10), date(2026, 10, 31), date(2026, 11, 15)):
            self.assertEqual([str(t.id)], [o.ref for o in self.store.between(*bounds(day, "day"))])
        self.assertFalse(self.store.between(*bounds(date(2026, 11, 16), "day")))
        self.assertFalse(self.store.between(*bounds(date(2026, 10, 9), "day")))

    def test_overnight_and_overlap_allowed(self):
        self.add(start=datetime(2026, 9, 26, 23), end=datetime(2026, 9, 27, 2))
        self.add(start=datetime(2026, 9, 27, 1), end=datetime(2026, 9, 27, 3))
        items = self.store.between(*bounds(date(2026, 9, 27), "day"))
        occupied, concurrent, spans = workload(items, date(2026, 9, 27))
        self.assertEqual((occupied, concurrent, spans), (3, 2, 0))
        free = [(a.hour, b.hour) for a, b, active in segments(items, date(2026, 9, 27)) if not active]
        self.assertEqual(free, [(3, 0)])

    def test_overdue_is_derived(self):
        task = self.add(end=AT + timedelta(hours=6))
        item = self.store.resolve(str(task.id))
        self.assertFalse(item.overdue(AT))
        self.assertTrue(item.overdue(AT + timedelta(days=1)))
        self.store.edit(str(task.id), {"state": "completed"}, at=AT)
        self.assertFalse(self.store.resolve(str(task.id)).overdue(AT + timedelta(days=1)))
        with self.assertRaises(ValueError):
            self.store.edit(str(task.id), {"state": "overdue"})

    def test_recurring_completion_independent(self):
        task = self.add(repeat="daily")
        ref = f"{task.id}@2026-09-26"
        self.store.edit(ref, {"state": "completed"}, at=AT)
        items = self.store.between(AT, AT + timedelta(days=3), history=True)
        self.assertEqual([o.task.state for o in items], ["completed", "pending", "pending"])
        self.assertEqual(len(self.store.history()), 1)

    def test_recurring_reschedule_outside_visible_origin(self):
        task = self.add(repeat="weekly")
        ref = f"{task.id}@2026-09-26"
        self.store.edit(ref, {"start": AT + timedelta(days=20), "end": AT + timedelta(days=20, hours=1)}, at=AT)
        self.assertEqual([], self.store.between(*bounds(AT.date(), "day")))
        items = self.store.between(*bounds(date(2026, 10, 16), "day"))
        self.assertEqual([o.ref for o in items], [ref])
        self.assertEqual(self.store.resolve(ref).task.start, AT + timedelta(days=20))

    def test_recurrence_deletion_only_one_occurrence(self):
        task = self.add(repeat="daily")
        ref = f"{task.id}@2026-09-26"
        self.store.delete(ref)
        self.assertEqual(2, len(self.store.between(AT, AT + timedelta(days=3))))
        self.store.undo()
        self.assertEqual(3, len(self.store.between(AT, AT + timedelta(days=3))))

    def test_undo_survives_restart_and_deletion(self):
        task = self.add(notes="local notes", tags=["backend"])
        self.store.delete(str(task.id))
        path = self.store.path
        self.store.close()
        self.store = Store(path)
        self.store.undo()
        self.assertEqual(self.store.get(task.id).notes, "local notes")
        self.store.undo()
        self.assertFalse(self.store.tasks())

    def test_undo_chain(self):
        task = self.add()
        ref = str(task.id)
        self.store.edit(ref, {"state": "ongoing"}, at=AT)
        self.store.edit(ref, {"start": AT + timedelta(days=1), "end": AT + timedelta(days=1, hours=1)}, at=AT)
        self.store.edit(ref, {"state": "completed"}, at=AT)
        self.store.undo()
        self.assertEqual("ongoing", self.store.get(task.id).state)
        self.store.undo()
        self.assertEqual(task.start, self.store.get(task.id).start)
        self.store.undo()
        self.assertEqual("pending", self.store.get(task.id).state)

    def test_series_edits_keep_realized_occurrences(self):
        task = self.add(repeat="daily")
        ref = f"{task.id}@2026-09-26"
        self.store.edit(ref, {"state": "completed"}, at=AT)
        self.store.edit(str(task.id), {"repeat": "weekdays"}, series=True, at=AT)
        self.assertEqual("mon,tue,wed,thu,fri", self.store.get(task.id).repeat)
        self.assertEqual("completed", self.store.resolve(ref).task.state)
        self.assertEqual(1, len(self.store.between(*bounds(AT.date(), "day"), history=True)))
        self.store.undo()
        self.assertEqual("daily", self.store.get(task.id).repeat)

    def test_removing_recurrence_preserves_history_and_undo(self):
        task = self.add(repeat="daily")
        ref = f"{task.id}@2026-09-26"
        self.store.edit(ref, {"state": "completed"}, at=AT)
        self.store.edit(str(task.id), {"repeat": ""}, series=True, at=AT)
        self.assertEqual(2, len(self.store.tasks()))
        self.assertEqual(1, len(self.store.history()))
        self.store.undo()
        self.assertEqual(1, len(self.store.tasks()))
        self.assertEqual("completed", self.store.resolve(ref).task.state)

    def test_search_notes_tags_history_and_dates(self):
        task = self.add(notes="Learn postgres persistence", tags=["backend"])
        self.store.edit(str(task.id), {"state": "completed"}, at=AT - timedelta(days=100))
        self.assertEqual(1, len(search(self.store, "postgres #backend state:completed", AT)))
        self.assertEqual(1, len(search(self.store, "PrctcDSA", AT)))
        self.assertEqual(1, len(search(self.store, "on:2026-09-26", AT)))
        self.assertEqual(0, len(search(self.store, "on:2026-09-27", AT)))

    def test_search_recurring_arbitrary_year(self):
        self.add(repeat="daily")
        results = search(self.store, "on:2030-01-01", AT)
        self.assertEqual(1, len(results))
        self.assertEqual("2030-01-01", results[0].day)

    def test_archive_hides_only_old_completed(self):
        task = self.add()
        self.store.edit(str(task.id), {"state": "completed"}, at=AT)
        self.assertEqual(1, len(self.store.between(AT, AT + timedelta(days=1), at=AT + timedelta(days=10))))
        self.assertEqual(0, len(self.store.between(AT, AT + timedelta(days=1), at=AT + timedelta(days=31))))
        self.assertEqual(1, len(self.store.history()))

    def test_invalid_edit_is_atomic(self):
        task = self.add()
        count = self.store.db.execute("SELECT count(*) FROM undo").fetchone()[0]
        with self.assertRaises(ValueError):
            self.store.edit(str(task.id), {"end": AT})
        self.assertEqual(task.end, self.store.get(task.id).end)
        self.assertEqual(count, self.store.db.execute("SELECT count(*) FROM undo").fetchone()[0])


class ModelTests(unittest.TestCase):
    def test_date_only_inclusive_end(self):
        start, end, all_day = schedule("2026-10-04", "2026-10-10")
        self.assertEqual(end, datetime(2026, 10, 11))
        self.assertTrue(all_day)

    def test_overnight_short_end(self):
        start, end, all_day = schedule("2026-10-04 23:00", "02:00")
        self.assertEqual(end - start, timedelta(hours=3))
        self.assertFalse(all_day)

    def test_parse_defaults_and_bad_input(self):
        self.assertEqual(schedule("", ""), (None, None, False))
        start, end, _ = schedule("09:00", base=date(2026, 9, 26))
        self.assertEqual(end - start, timedelta(hours=1))
        for start, end in (("", "15:00"), ("nonsense", ""), ("2026-09-26", "2026-09-25"), ("2026-09-26 05:00 extra", "")):
            with self.assertRaises(ValueError):
                schedule(start, end)

    def test_iso_and_relative_times(self):
        self.assertEqual(parse_moment("2026-09-26T17:00"), datetime(2026, 9, 26, 17))
        self.assertEqual(parse_moment("tomorrow 09:00", date(2026, 9, 26)), datetime(2026, 9, 27, 9))

    def test_reschedule_preserves_duration(self):
        task = Task("span", start=AT, end=AT + timedelta(days=3, hours=4))
        start, end = shifted_start("tomorrow", task, at=AT)
        self.assertEqual(start, AT + timedelta(days=1))
        self.assertEqual(end - start, task.end - task.start)
        self.assertEqual(shifted_start("+1w", task, at=AT)[0], AT + timedelta(days=7))

    def test_month_navigation_clamps(self):
        self.assertEqual(move_date(date(2028, 1, 31), "month", 1), date(2028, 2, 29))
        self.assertEqual(move_date(date(2026, 12, 31), "month", 1), date(2027, 1, 31))

    def test_week_boundaries(self):
        self.assertEqual(bounds(date(2026, 10, 1), "week"), (datetime(2026, 9, 28), datetime(2026, 10, 5)))

    def test_recurrence_patterns_and_missing_monthdays(self):
        task = Task("monthly", start=datetime(2026, 1, 31, 17), end=datetime(2026, 1, 31, 18), repeat="monthly")
        self.assertEqual(list(recurrence_dates(task, date(2026, 1, 1), date(2026, 4, 30))), [date(2026, 1, 31), date(2026, 3, 31)])
        task.repeat = normalize_repeat("mon,wed,fri")
        self.assertEqual([d.weekday() for d in recurrence_dates(task, date(2026, 2, 2), date(2026, 2, 8))], [0, 2, 4])

    def test_local_wall_clock_recurrence_across_dst(self):
        task = Task("daily", start=datetime(2026, 3, 7, 9), end=datetime(2026, 3, 7, 10), repeat="daily")
        self.assertEqual(occurrence(task, "2026-03-08").task.start.hour, 9)


if __name__ == "__main__":
    unittest.main()
