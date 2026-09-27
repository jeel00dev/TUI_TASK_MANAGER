"""Layout boundaries and real mouse input regressions for the visual calendar."""
import curses
import fcntl
import os
import signal
import struct
import termios
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from taskcal.drawing import Rect
from test_visual_calendar import VisualFixture, BASE, DAY
from test_terminal import Screen, TerminalSession


class ResponsiveTests(VisualFixture):
    def test_header_controls_stay_aligned_and_do_not_overlap_at_breakpoints(self):
        for width in (90,103,104,110,111,112,131,132,160,230,300):
            self.app.screen=self.app.paint.screen=Screen(55,width)
            self.refresh()
            controls=[r for r,a,v in self.app.views.hits if a=='key' and r.y==0]
            self.assertEqual(7,len(controls))
            self.assertEqual({3},{r.h for r in controls})
            self.assertEqual(1,len({r.w for r in controls[:-1]}))
            for left,right in zip(controls,controls[1:]):
                self.assertLess(left.x+left.w,right.x)
            self.assertEqual(width-2,controls[-1].x+controls[-1].w)
            toolbar=[r for r,a,v in self.app.views.hits if r.y==4 and a=='key']
            self.assertTrue(all(r.h==3 for r in toolbar))
            for i,left in enumerate(toolbar):
                for right in toolbar[i+1:]:
                    self.assertTrue(left.x+left.w<=right.x or right.x+right.w<=left.x)
            footer=[(r,v) for r,a,v in self.app.views.hits if r.y==52 and a=='key']
            self.assertIn('D',[v for r,v in footer])
            self.assertIn('u',[v for r,v in footer])
            self.assertTrue(all(r.h==3 and r.x+r.w<=width-2 for r,v in footer))

    def click(self, action, value=None, double=False):
        rect=next(r for r,a,v in reversed(self.app.views.hits) if a==action and (value is None or v==value))
        self.app.mouse((rect.x+rect.w//2,rect.y+rect.h//2,"click",double))
        self.refresh()

    def test_view_controls_have_no_duplicate_today_tab(self):
        self.refresh()
        tabs=[value for rect,action,value in self.app.views.hits if rect.y==0 and action=="key" and value!="a"]
        self.assertEqual(["d","w","m","y","i","H"],tabs)
        self.click("key","m")
        self.assertEqual("month",self.app.view)
        self.click("key","d")
        self.assertEqual("day",self.app.view)

    def test_mouse_select_complete_and_undo_use_shared_store(self):
        first=self.add("First")
        second=self.add("Second",start=BASE+timedelta(hours=14),end=BASE+timedelta(hours=16))
        self.refresh()
        self.click("task",str(second.id))
        self.assertEqual(second.id,self.app.chosen().task.id)
        self.click("key","x")
        self.assertEqual("completed",self.store.get(second.id).state)
        self.assertEqual("pending",self.store.get(first.id).state)
        self.click("key","u")
        self.assertEqual("pending",self.store.get(second.id).state)
        with patch.object(self.app,"inspect") as inspect:
            self.click("task",str(second.id),double=True)
            inspect.assert_called_once()

    def test_visible_delete_action_is_undoable(self):
        task=self.add('Delete with the toolbar')
        self.refresh()
        self.click('key','D')
        self.assertFalse(self.app.items)
        self.click('key','u')
        self.assertEqual(task.id,self.app.chosen().task.id)

    def test_minimum_canvas_clears_mouse_targets_and_preserves_selection(self):
        task=self.add()
        self.refresh()
        for size in [(27,120),(35,89),(10,30),(1,1)]:
            self.app.screen=self.app.paint.screen=Screen(*size)
            self.app.draw()
            self.assertFalse(self.app.views.hits)
            self.assertFalse(self.app.views.card_rects)
            if size[1]>=89:
                self.assertIn("90 columns × 28 rows",self.app.screen.text())
            self.app.mouse((3,2,"click",False))
            self.assertEqual(task.id,self.app.chosen().task.id)
        self.app.screen=self.app.paint.screen=Screen(28,90)
        self.app.draw()
        self.assertTrue(self.app.views.hits)
        self.assertIn("TASK",self.app.screen.text())

    def test_layouts_and_card_corners_are_bounded_after_every_resize(self):
        self.add("An overlapping schedule",start=BASE+timedelta(hours=8),end=BASE+timedelta(hours=16))
        self.add("Across midnight",start=BASE-timedelta(hours=3),end=BASE+timedelta(hours=14))
        self.add("Unusually long title "*10,notes="Notes "*100,tags=["backend"])
        for rows,cols in [(28,90),(40,131),(40,132),(48,160),(60,230),(28,90)]:
            self.app.screen=self.app.paint.screen=Screen(rows,cols)
            for view in ("day","week","month","year","inbox","history","search"):
                self.app.view=view
                self.refresh()
                for rect,_,_ in self.app.views.hits:
                    self.assertTrue(rect.x>=0 and rect.y>=0 and rect.x+rect.w<cols and rect.y+rect.h<=rows,(view,rect,rows,cols))
                # Nothing can extend into the unused final terminal column.
                for x,y in self.app.paint.cells:
                    self.assertTrue(0<=x<cols-1 and 0<=y<rows)
                if view in ("day","week"):
                    for rect,ref in self.app.views.card_rects:
                        if rect.h>=3:
                            self.assertEqual("🭽",self.app.paint.cells[(rect.x,rect.y)][0])
                            self.assertEqual("🭾",self.app.paint.cells[(rect.x+rect.w-1,rect.y)][0])
                            self.assertEqual("🭼",self.app.paint.cells[(rect.x,rect.y+rect.h-1)][0])
                            self.assertEqual("🭿",self.app.paint.cells[(rect.x+rect.w-1,rect.y+rect.h-1)][0])

    def test_month_grid_junctions_connect_in_four_five_and_six_week_months(self):
        self.app.view="month"
        for day in (date(2021,2,15),date(2026,9,26),date(2026,8,15)):
            self.app.day=day
            self.refresh()
            cells=self.app.paint.cells
            crosses=[(x,y) for (x,y),(char,_) in cells.items() if char=="┼"]
            self.assertTrue(crosses)
            for x,y in crosses:
                self.assertEqual("│",cells[(x,y-1)][0])
                self.assertEqual("│",cells[(x,y+1)][0])
                self.assertEqual("─",cells[(x-1,y)][0])
                self.assertEqual("─",cells[(x+1,y)][0])

    def test_short_cards_show_title_text_when_first_word_is_long(self):
        self.add("Extraordinarily long description")
        self.refresh()
        self.app.views.card(Rect(3,10,16,4),self.app.chosen(),DAY)
        title="".join(self.app.paint.cells[(x,11)][0] for x in range(4,18))
        self.assertIn("Extraord",title)

    def test_mini_calendar_has_six_rows_and_clicks_the_actual_date(self):
        self.app.day=date(2026,8,15) # Six calendar rows.
        self.refresh()
        rect=Rect(150,4,38,19)
        self.app.views.hits=[]
        self.app.views.mini_calendar(rect)
        hits=[(r,v) for r,a,v in self.app.views.hits if a=="date" and rect.contains(r.x,r.y)]
        self.assertEqual(42,len(hits))
        self.assertTrue(all(r.y<rect.y+rect.h-2 for r,_ in hits))
        target=date(2026,9,6)
        r=next(r for r,v in hits if v==target)
        self.app.mouse((r.x+1,r.y,"click",True))
        self.refresh()
        self.assertEqual(("day",target),(self.app.view,self.app.day))

    def test_time_marker_updates_on_minute_change_and_preserves_cards(self):
        self.add()
        self.app.view="day"
        self.refresh()
        with patch("taskcal.tui.now",return_value=BASE+timedelta(hours=11,minutes=1)):
            self.assertTrue(self.app.needs_refresh())
            self.app.refresh()
        self.app.draw()
        self.assertIn("11:01",self.app.screen.text())
        dots=[(xy,style) for xy,(char,style) in self.app.paint.cells.items() if char=="┄" and (style=="red" or style.endswith("_now"))]
        self.assertGreater(len(dots),10)
        self.assertEqual("pending",self.store.tasks()[0].state)

    def test_time_marker_is_continuous_without_erasing_task_titles(self):
        monday = BASE-timedelta(days=DAY.weekday())
        for day in range(7):
            self.add(f"T{day}",start=monday+timedelta(days=day,hours=9),end=monday+timedelta(days=day,hours=13))
        for rows,cols in ((28,90),(40,132),(55,190)):
            self.app.screen=self.app.paint.screen=Screen(rows,cols)
            for view in ("day","week"):
                self.app.view=view
                self.app.start_minute=0
                self.app.visible_hours=24
                for minute in (0,680,1439):
                    with self.subTest(size=(rows,cols),view=view,minute=minute):
                        with patch("taskcal.tui.now",return_value=BASE+timedelta(minutes=minute)):
                            self.app.refresh()
                        self.app.draw()
                        cells=self.app.paint.cells
                        marker=next((xy for xy,(char,style) in cells.items() if char=="●" and style=="red"),None)
                        self.assertIsNotNone(marker)
                        main=next(rect for rect,action,_ in self.app.views.hits if action=="scroll")
                        for x in range(main.x+7,main.x+main.w-1):
                            self.assertIn(cells[(x,marker[1])][0],("┄","●"))
                        for rect,ref in self.app.views.card_rects:
                            text="".join(cells.get((x,y),(" ",""))[0] for y in range(rect.y,rect.y+rect.h) for x in range(rect.x,rect.x+rect.w))
                            self.assertIn(self.store.get(int(ref)).title,text)

    def test_time_marker_is_absent_outside_visible_date_or_time(self):
        self.add()
        self.app.view="day"
        for day,start in ((DAY,13*60),(DAY+timedelta(days=1),8*60)):
            self.app.day=day
            self.app.start_minute=start
            self.app.visible_hours=6
            self.app.need_focus=False
            self.refresh()
            self.assertFalse(any(char=="●" and style=="red" or style.endswith("_now") for char,style in self.app.paint.cells.values()))

    def test_wheel_scrolls_without_changing_task_state(self):
        self.add()
        self.refresh()
        self.app.start_minute=300
        self.app.mouse((20,20,"down",False))
        self.assertEqual(360,self.app.start_minute)
        self.app.mouse((20,20,"up",False))
        self.assertEqual(300,self.app.start_minute)
        self.assertEqual("pending",self.store.tasks()[0].state)

    def test_idle_event_loop_refreshes_on_the_next_minute(self):
        self.app.view="day"
        clock=[BASE+timedelta(hours=11,minutes=20,seconds=59)]
        calls=[None,"q"]
        def key():
            clock[0]=BASE+timedelta(hours=11,minutes=21)
            return calls.pop(0)
        with patch.object(self.app,"setup"), patch.object(self.app,"key",side_effect=key), patch("taskcal.tui.now",side_effect=lambda:clock[0]):
            self.app.run()
        self.assertIn("11:21",self.app.screen.text())

    def test_press_release_does_not_trigger_a_button_twice(self):
        with patch("curses.getmouse",return_value=(0,1,1,0,curses.BUTTON1_RELEASED)):
            self.assertIsNone(self.app.mouse_event())
        with patch("curses.getmouse",return_value=(0,1,1,0,curses.BUTTON1_PRESSED)):
            self.assertEqual("click",self.app.mouse_event()[2])

    def test_mouse_uses_new_layout_when_resize_event_is_still_pending(self):
        self.refresh()
        self.app.screen=self.app.paint.screen=Screen(40,260)
        with patch.object(self.app,"form") as form:
            self.app.mouse((250,1,"click",False))
            form.assert_called_once_with(scheduled=False)


class MouseTerminalTests(TerminalSession):
    def click(self,x,y):
        # SGR coordinates are one-based; release must not repeat the mutation.
        self.send(f"\x1b[<0;{x+1};{y+1}M\x1b[<0;{x+1};{y+1}m")

    def resize(self,rows,cols):
        fcntl.ioctl(self.master,termios.TIOCSWINSZ,struct.pack("HHHH",rows,cols,0,0))
        os.kill(self.proc.pid,signal.SIGWINCH)
        self.pump(.2)

    def test_mouse_add_form_save_complete_and_undo(self):
        self.click(104,1) # New task in the 110-column header.
        self.wait_for(lambda:b"NEW TASK" in self.output)
        self.send("Created entirely by mouse")
        self.click(16,27) # Save in the editor's footer.
        self.wait_for(lambda:bool(self._tasks()))
        self.assertEqual("Created entirely by mouse",self.task().title)
        self.click(58,1) # Inbox tab.
        self.click(31,28) # Complete selected task.
        self.wait_for(lambda:self.task().state=="completed")
        self.click(67,28) # Undo once, despite press + release.
        self.wait_for(lambda:self.task().state=="pending")
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertEqual(0,self.proc.returncode)

    def test_resize_preserves_form_draft_and_disables_hidden_controls(self):
        self.send("a")
        self.send("Keep this unsaved draft")
        self.resize(20,80)
        self.wait_for(lambda:b"90 columns" in self.output)
        self.send(" queue")  # Text, including q, belongs to the paused draft.
        self.send("\x13")
        self.click(16,17)
        self.assertFalse(self._tasks())
        self.resize(40,160)
        self.send("\x13")
        self.wait_for(lambda:bool(self._tasks()))
        self.assertEqual("Keep this unsaved draft queue",self.task().title)
        self.send("q")
        self.proc.wait(timeout=3)
        self.assertNotIn(b"Traceback",self.output)

    def test_click_editor_field_and_select_control(self):
        self.send("a")
        self.send("Mouse priority")
        self.click(35,17) # Priority input, fifth field.
        self.click(16,27)
        self.wait_for(lambda:bool(self._tasks()))
        self.assertEqual("high",self.task().priority)
        self.send("q")
        self.proc.wait(timeout=3)

    def test_mouse_coordinates_beyond_223_columns(self):
        self.resize(40,260)
        self.click(250,1)
        self.wait_for(lambda:b"NEW TASK" in self.output)
        self.send("Wide terminal capture")
        self.click(92,35)
        self.wait_for(lambda:bool(self._tasks()))
        self.assertEqual("Wide terminal capture",self.task().title)
        self.send("q")
        self.proc.wait(timeout=3)
