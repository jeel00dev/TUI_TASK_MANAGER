import curses
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from taskcal.calendar import span_lanes, time_blocks
from taskcal.model import Task, occurrence
from taskcal.store import Store
from taskcal.tui import App
from taskcal.theme import PALETTE, Theme
from test_terminal import Screen

DAY = date(2026,9,26)
BASE = datetime(2026,9,26)


class PlacementTests(unittest.TestCase):
    def test_overlaps_have_separate_columns(self):
        items = [occurrence(Task(title,id=i+1,start=BASE+timedelta(hours=start),end=BASE+timedelta(hours=end))) for i,(title,start,end) in enumerate([("A",17,20),("B",18,19),("C",18.5,20),("D",20,21)])]
        placed = time_blocks(items,DAY,480,48,20)
        self.assertEqual(4,len(placed))
        self.assertEqual(3,placed[0].lanes)
        self.assertEqual(1,placed[-1].lanes)
        self.assertNotEqual(placed[0].group,placed[-1].group)

    def test_short_tasks_do_not_overpaint_in_same_row(self):
        tasks = [occurrence(Task(str(i),id=i,start=BASE+timedelta(hours=9,minutes=i*4),end=BASE+timedelta(hours=9,minutes=i*4+3))) for i in range(5)]
        blocks = time_blocks(tasks,DAY,480,32,30)
        self.assertEqual(5,len({b.lane for b in blocks}))

    def test_random_schedules_are_bounded_and_do_not_overlap_in_a_lane(self):
        rng = random.Random(42)
        for _ in range(20):
            items = []
            for i in range(80):
                minute = rng.randrange(-720,1500)
                items.append(occurrence(Task(str(i),id=i,start=BASE+timedelta(minutes=minute),end=BASE+timedelta(minutes=minute+rng.randrange(1,600)))))
            blocks = time_blocks(items,DAY,360,37,18.4)
            for block in blocks:
                self.assertTrue(0 <= block.top < block.bottom <= 37)
                self.assertTrue(0 <= block.lane < block.lanes)
            for i,a in enumerate(blocks):
                for b in blocks[i+1:]:
                    if a.lane == b.lane:
                        self.assertFalse(a.top < b.bottom and b.top < a.bottom)

    def test_multi_week_spans_clip_to_calendar_boundaries(self):
        first = date(2026,9,21)
        item = occurrence(Task("Project",start=datetime(2026,9,19),end=datetime(2026,10,15),all_day=True))
        bar = span_lanes([item],first)[0]
        self.assertEqual((0,7),(bar.top,bar.bottom))


class VisualFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/"tasks.sqlite3")
        self.app = App(Screen(55,190),self.store)
        self.app.day = DAY
        self.app.select_relevant = False

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self,title="Task",**kwargs):
        values=dict(start=BASE+timedelta(hours=10),end=BASE+timedelta(hours=12))
        values.update(kwargs)
        return self.store.add(Task(title,**values),at=BASE)

    def refresh(self):
        with patch("taskcal.tui.now",return_value=BASE+timedelta(hours=11)):
            self.app.refresh()
        self.app.draw()


class VisualTests(VisualFixture):
    def test_selected_task_sidebar_matches_every_view(self):
        self.add("Earlier",start=BASE-timedelta(days=1),end=BASE-timedelta(days=1,hours=-1))
        task = self.add("Selected work",notes="Focus on database internals",tags=["backend"])
        self.app.focus_ref=str(task.id)
        self.refresh()
        for key in ("m","d","w"):
            self.app.action(key)
            self.refresh()
            self.assertEqual(task.id,self.app.chosen().task.id)
            self.assertIn("Selected work",self.app.screen.text())
            self.assertIn("SELECTED TASK",self.app.screen.text())

    def test_all_overlaps_remain_reachable_even_in_a_narrow_week(self):
        tasks = [self.add(f"Concurrent {i}") for i in range(9)]
        self.app.screen = self.app.paint.screen = Screen(35,110)
        for task in tasks:
            self.app.focus_ref = str(task.id)
            self.refresh()
            self.assertIn(str(task.id),[ref for _,ref in self.app.views.card_rects])
            self.assertIn("overlap",self.app.screen.text())
        self.app.action("v")
        self.refresh()
        self.assertEqual(9,len(self.app.items))

    def test_late_task_selection_scrolls_into_view(self):
        task = self.add("Midnight work",start=BASE+timedelta(hours=1),end=BASE+timedelta(hours=2))
        self.app.focus_ref=str(task.id)
        self.refresh()
        self.assertLess(self.app.start_minute,120)
        self.assertIn(str(task.id),[ref for _,ref in self.app.views.card_rects])

    def test_month_overflow_reveals_selected_task(self):
        tasks = [self.add(f"Busy {i}") for i in range(25)]
        self.app.view="month"
        for task in tasks:
            self.app.focus_ref=str(task.id)
            self.refresh()
            self.assertIn(str(task.id),[ref for _,ref in self.app.views.card_rects])
        self.assertIn("more",self.app.screen.text())

    def test_external_cli_edits_refresh_selection_and_details(self):
        task=self.add("Original")
        self.refresh()
        version=self.app.data_version
        other=Store(self.store.path)
        other.edit(str(task.id),{"title":"Changed externally","state":"ongoing","notes":"Synced notes"})
        other.close()
        self.assertNotEqual(version,self.store.db.execute("PRAGMA data_version").fetchone()[0])
        self.refresh()
        self.assertEqual("Changed externally",self.app.chosen().task.title)
        self.assertIn("Synced notes",self.app.screen.text())

    def test_dates_arrows_select_task_on_new_date(self):
        self.add("Saturday")
        task=self.add("Sunday",start=BASE+timedelta(days=1,hours=10),end=BASE+timedelta(days=1,hours=11))
        self.refresh()
        self.app.action(curses.KEY_RIGHT)
        self.refresh()
        self.assertEqual(task.id,self.app.chosen().task.id)
        self.app.action(curses.KEY_LEFT)
        self.refresh()
        self.app.action(curses.KEY_LEFT)
        self.refresh()
        self.assertIsNone(self.app.chosen())

    def test_older_overdue_is_visible_in_today_calendar(self):
        self.add("Missed deadline",start=BASE-timedelta(days=1),end=BASE-timedelta(hours=1))
        self.app.view="day"
        self.refresh()
        self.assertIn("earlier overdue",self.app.screen.text())
        self.assertIn("Missed deadline",self.app.screen.text())

    def test_zoom_and_time_scroll(self):
        self.refresh()
        self.app.action("+")
        self.assertEqual(10,self.app.visible_hours)
        self.app.action(curses.KEY_PPAGE)
        self.assertEqual(300,self.app.start_minute)
        self.app.action("-")
        self.assertEqual(16,self.app.visible_hours)

    def test_exact_palette_and_restoration(self):
        self.assertEqual("#ff5c5c",PALETTE["red"])
        self.assertEqual("#171717",PALETTE["bg"])
        theme=Theme()
        with patch.dict("os.environ",{},clear=True), patch("curses.has_colors",return_value=True), patch("curses.start_color"), patch("curses.use_default_colors"), patch("curses.can_change_color",return_value=True), patch("curses.COLORS",256,create=True), patch("curses.COLOR_PAIRS",256,create=True), patch("curses.color_content",return_value=(0,0,0)), patch("curses.init_color") as define, patch("curses.init_pair"), patch("curses.color_pair",return_value=0):
            theme.install()
            definitions=len(theme.originals)
            self.assertGreater(definitions,20)
            self.assertTrue(any(call.args[1:] == (1000,round(92*1000/255),round(92*1000/255)) for call in define.call_args_list))
            theme.restore()
            self.assertEqual(definitions*2,define.call_count)
            self.assertFalse(theme.originals)


if __name__=="__main__":
    unittest.main()
