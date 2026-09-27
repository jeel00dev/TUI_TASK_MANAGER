"""Year navigation and scheduling use the same task records as other scales."""
import calendar
import curses
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from taskcal.calendar import bounds, move_date
from test_terminal import Screen, TerminalSession
from test_visual_calendar import VisualFixture, BASE, DAY


class YearTests(VisualFixture):
    def year(self, day=DAY):
        self.app.day = day
        self.app.action("y")
        self.refresh()

    def test_year_bounds_and_leap_day_navigation(self):
        self.assertEqual((datetime(2028,1,1),datetime(2029,1,1)),bounds(date(2028,2,29),"year"))
        self.assertEqual(date(2029,2,28),move_date(date(2028,2,29),"year",1))
        self.assertEqual(date(2024,2,29),move_date(date(2028,2,29),"year",-4))
        self.year(date(2028,2,29))
        self.app.action("l")
        self.refresh()
        self.assertEqual(("year",date(2029,2,28)),(self.app.view,self.app.day))
        self.app.action(curses.KEY_NPAGE)
        self.refresh()
        self.assertEqual(date(2029,3,28),self.app.day)

    def test_every_month_remains_visible_across_resizes(self):
        self.year()
        for rows,cols in ((28,90),(38,110),(40,132),(48,160),(55,230),(28,90)):
            self.app.screen = self.app.paint.screen = Screen(rows,cols)
            self.app.draw()
            months = [(r,v) for r,a,v in self.app.views.hits if a=="year_month"]
            self.assertEqual(list(range(1,13)),[v.month for r,v in months])
            for rect,day in months:
                self.assertGreaterEqual(rect.h,4)
                self.assertLessEqual(rect.y+rect.h,rows-3)
                self.assertLess(rect.x+rect.w,cols)
                self.assertIn(calendar.month_name[day.month],self.app.screen.text())
            # No date or task hit target can cover a month title or footer.
            for rect,action,value in self.app.views.hits:
                self.assertLess(rect.x+rect.w,cols)
                self.assertLessEqual(rect.y+rect.h,rows)

    def test_full_year_grid_has_every_leap_year_date_once(self):
        self.year(date(2028,2,29))
        days = [value for _,action,value in self.app.views.hits if action=="date"]
        self.assertEqual(366,len(days))
        self.assertEqual(366,len(set(days)))
        self.assertIn(date(2028,2,29),days)
        self.assertIn(date(2028,12,31),days)

    def test_date_rows_fill_tall_months_and_spacing_is_clickable(self):
        self.app.screen = self.app.paint.screen = Screen(85,230)
        self.year(date(2021,2,1)) # February has four weeks; August has six.
        for month in (2,3,8):
            tile = next(r for r,a,v in self.app.views.hits if a=='year_month' and v.month==month)
            dates = [(r,v) for r,a,v in self.app.views.hits if a=='date' and v.month==month]
            rows = sorted(set(r.y for r,_ in dates))
            self.assertEqual(len(calendar.Calendar().monthdayscalendar(2021,month)),len(rows))
            self.assertEqual(tile.y+3,rows[0])
            self.assertLessEqual(max(r.y+r.h for r,_ in dates),tile.y+tile.h-3)
            self.assertGreaterEqual(max(r.y+r.h for r,_ in dates),tile.y+tile.h//2)
            heights = [r.h for r,_ in dates]
            self.assertGreater(min(heights),1)
            # The padding around a number selects that date, not its month tile.
            target,day = dates[-1]
            self.app.mouse((target.x+1,target.y+target.h-1,'click',False))
            self.refresh()
            self.assertEqual(('year',day),(self.app.view,self.app.day))

    def test_mouse_month_and_date_selection_keeps_year_until_opened(self):
        self.year()
        rect,value = next((r,v) for r,a,v in self.app.views.hits if a=="year_month" and v.month==12)
        self.app.mouse((rect.x+2,rect.y+1,"click",False))
        self.refresh()
        self.assertEqual(("year",12),(self.app.view,self.app.day.month))
        rect = next(r for r,a,v in self.app.views.hits if a=="date" and v==date(2026,12,31))
        self.app.mouse((rect.x,rect.y,"click",False))
        self.refresh()
        self.assertEqual(("year",date(2026,12,31)),(self.app.view,self.app.day))
        with patch.object(self.app,"form") as form:
            self.app.action("A")
            form.assert_called_once_with(scheduled=True)
        self.app.mouse((rect.x,rect.y,"click",True))
        self.refresh()
        self.assertEqual(("day",date(2026,12,31)),(self.app.view,self.app.day))
        self.year()
        rect = next(r for r,a,v in self.app.views.hits if a=="year_month" and v.month==7)
        self.app.mouse((rect.x+2,rect.y+1,"click",True))
        self.refresh()
        self.assertEqual(("month",7),(self.app.view,self.app.day.month))

    def test_neighboring_months_share_date_rows_and_bottom_edge(self):
        self.app.screen=self.app.paint.screen=Screen(62,230)
        self.year(date(2026,9,26))
        tiles=[(r,v.month) for r,a,v in self.app.views.hits if a=='year_month']
        for top in {r.y for r,_ in tiles}:
            group=[(r,m) for r,m in tiles if r.y==top]
            self.assertEqual(1,len({r.h for r,_ in group}))
            rows=[]
            for _,month in group:
                rows.append(sorted({r.y for r,a,v in self.app.views.hits if a=='date' and v.month==month}))
            first_rows=min(map(len,rows))
            self.assertEqual(1,len({tuple(r[:first_rows]) for r in rows}))
        main=next(r for r,a,v in self.app.views.hits if a=='scroll')
        self.assertEqual(main.y+main.h-2,max(r.y+r.h for r,_ in tiles))

    def test_tasks_cross_years_and_changes_stay_shared_with_other_views(self):
        carry = self.add("Year-long project",start=datetime(2025,12,20),end=datetime(2027,2,1),all_day=True)
        december = self.add("December review",start=datetime(2026,12,15,9),end=datetime(2026,12,15,10),tags=["review"])
        outside = self.add("Next year",start=datetime(2027,2,2),end=datetime(2027,2,3))
        self.year()
        self.assertEqual({carry.id,december.id},{o.task.id for o in self.app.items})
        self.assertNotIn(outside.id,[o.task.id for o in self.app.items])
        self.app.filter = "#review"
        self.refresh()
        self.assertEqual([december.id],[o.task.id for o in self.app.items])
        self.app.action("x")
        self.refresh()
        self.app.day=date(2026,12,15)
        self.app.action("m")
        self.refresh()
        self.assertEqual("completed",self.app.chosen().task.state)
        self.app.action("u")
        self.refresh()
        self.app.action("y")
        self.refresh()
        self.assertEqual("pending",self.app.chosen().task.state)
        self.assertEqual(1,len([o for o in self.app.items if o.task.id==december.id]))

    def test_recurrence_completion_remains_per_occurrence_in_year(self):
        task=self.add("Annual planning reviews",start=datetime(2026,1,1,9),end=datetime(2026,1,1,10),repeat="monthly")
        self.year()
        self.assertEqual(12,len(self.app.items))
        self.app.focus_ref=f"{task.id}@2026-09-01"
        self.refresh()
        self.app.action("x")
        self.refresh()
        self.assertEqual("completed",self.store.resolve(f"{task.id}@2026-09-01").task.state)
        self.assertEqual("pending",self.store.resolve(f"{task.id}@2026-10-01").task.state)


class YearTerminalTests(TerminalSession):
    def test_schedule_a_multi_month_task_from_year(self):
        self.send("yg")
        self.send("\x152032-02-29\n")
        self.send("A")
        self.send("Long-range project\t\x152032-02-29\t2032-12-31\x13")
        self.wait_for(lambda:bool(self._tasks()))
        task=self.task()
        self.assertEqual(datetime(2032,2,29),task.start)
        self.assertEqual(datetime(2033,1,1),task.end)
        self.assertTrue(task.all_day)
        self.send("x")
        self.wait_for(lambda:self.task().state=="completed")
        self.send("u")
        self.wait_for(lambda:self.task().state=="pending")
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertEqual(0,self.proc.returncode)
        self.assertNotIn(b"Traceback",self.output)
