"""Keyboard controller and dialogs for the visual task calendar."""
from __future__ import annotations

import curses
import sqlite3
import time
from datetime import date, timedelta

from .calendar import bounds, move_date
from .model import Task, midnight, now, parse_date, schedule, schedule_text, shifted_start, tags_from
from .notifier import running
from .query import match, search
from .drawing import Painter, Rect, cell_width, wrap
from .theme import Theme
from .views import Views, duration


HELP = [
    ("d", "Day calendar"), ("w", "Week calendar"), ("m", "Month calendar"), ("y", "Year calendar · all 12 months"),
    ("t", "Jump to today in Day, including unfinished overdue tasks"), ("i", "Inbox · unscheduled tasks"),
    ("H", "Completed history · includes archived tasks"),
    ("h / l", "Previous / next day, week, month, or year"),
    ("[ / ]", "Previous / next date within a calendar"), ("g", "Go to a date"),
    ("j / k", "Next / previous task"), ("PgUp / PgDn", "Scroll time / agenda; year: previous / next month"),
    ("← / →", "Select previous / next date"), ("↑ / ↓", "Select task; month/year: previous / next week"),
    ("+ / -", "Zoom in / out on the time grid"), ("v", "Toggle complete agenda / calendar"),
    ("b", "Toggle details sidebar"),
    ("Enter", "Inspect task · notes and full schedule"),
    ("a", "Quick capture · enter a title, then Enter to save to Inbox"),
    ("A", "Add scheduled task on selected date"),
    ("e", "Edit task / this occurrence"), ("E", "Edit recurring series · existing exceptions are retained"),
    ("s", "Start task · set ongoing"), ("x", "Complete task"), ("p", "Move task back to pending"),
    ("r", "Reschedule · tomorrow, +1h, +1w, or a date/time"),
    ("z", "Snooze once · 5, 10, 15, 30, or 60 minutes"),
    ("D", "Delete task / this occurrence · undo with u"), ("u", "Undo last change · persists across restarts"),
    ("X", "Delete the entire recurring series · undo with u"),
    ("/", "Search title, notes, tags and dates; includes history"),
    ("f", "Filter current view · text, #tag, state:pending, priority:high"),
    ("Esc", "Clear filter / return from search / cancel"),
    ("? or :", "Searchable shortcuts / command menu"), ("q", "Quit"),
]


class App:
    def __init__(self, screen, store):
        self.screen, self.store = screen, store
        self.view, self.day = "week", date.today()
        self.filter, self.query = "", ""
        self.selected, self.offset = 0, 0
        self.items = []
        self.message, self.message_until = "", 0
        self.quit = False
        self.previous_view = "day"
        self.theme = Theme()
        self.paint = Painter(screen, self.theme)
        self.views = Views(self)
        self.sidebar, self.agenda = True, False
        self.start_minute, self.visible_hours = 480, 16
        self.upcoming = []
        self.focus_ref = None
        self.focus_date = False
        self.data_version = None
        self.detail_offset = 0
        self.refresh_at = 0
        self.need_focus = True
        self.select_relevant = True
        self.reminders = running(store)
        self.last_click = None
        self.modal_hits = []

    def setup(self):
        curses.raw()  # Ctrl-S belongs to the form, not terminal XON/XOFF.
        curses.set_escdelay(25)
        self.screen.keypad(True)
        self.screen.timeout(500)
        curses.mouseinterval(0)
        curses.mousemask(curses.BUTTON1_PRESSED | curses.BUTTON4_PRESSED | getattr(curses,"BUTTON5_PRESSED",0))
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.theme.install()
        self.screen.bkgd(" ", self.theme.attr("plain"))
        self.paint.setup()

    def notice(self, text):
        self.message, self.message_until = text, time.monotonic() + 6

    def chosen(self):
        return self.items[self.selected] if self.items and 0 <= self.selected < len(self.items) else None

    def refresh(self):
        old_ref = self.chosen().ref if self.chosen() else None
        self.at = now()
        lo, hi = bounds(self.day, self.view)
        if self.view == "inbox":
            items = self.store.inbox()
        elif self.view == "history":
            items = self.store.history()
        elif self.view == "search":
            items = search(self.store, self.query, self.at)
        else:
            items = self.store.between(lo, hi, at=self.at)
            if self.view == "day" and self.day == self.at.date():
                refs = {o.ref for o in items}
                items += [o for o in self.store.overdue(self.at) if o.ref not in refs]
        if self.filter:
            items = [o for o in items if match(o, self.filter, self.at)]
        self.items = items
        if self.focus_date and self.view in ("day", "week", "month", "year"):
            day_start, day_end = bounds(self.day,"day")
            indices = [i for i,o in enumerate(items) if o.overlaps(day_start,day_end)]
            active = [i for i in indices if items[i].task.state == "ongoing"]
            self.selected = (active or indices or [-1])[0]
            self.need_focus = True
        elif self.focus_ref and self.focus_ref in [o.ref for o in items]:
            self.selected = next(i for i, o in enumerate(items) if o.ref == self.focus_ref)
            self.need_focus = True
        elif self.select_relevant and self.view in ("day", "week") and self.day == self.at.date() and items:
            current = [i for i, o in enumerate(items) if not o.task.all_day and o.task.state != "completed" and o.task.start <= self.at < o.task.end]
            upcoming = [i for i, o in enumerate(items) if o.task.state != "completed" and o.task.start > self.at]
            self.selected = (current or upcoming or [0])[0]
            self.need_focus = True
        elif old_ref in [o.ref for o in items]:
            self.selected = next(i for i, o in enumerate(items) if o.ref == old_ref)
        else:
            self.selected = min(self.selected, max(0, len(items) - 1))
        self.select_relevant = False
        self.focus_ref = None
        self.focus_date = False
        self.snoozes = {r["ref"]: r["due"] for r in self.store.db.execute("SELECT ref,due FROM snoozes")}
        self.upcoming = self.store.between(self.at, self.at + timedelta(days=30), at=self.at)
        if self.filter:
            self.upcoming = [o for o in self.upcoming if match(o, self.filter, self.at)]
        self.data_version = self.store.db.execute("PRAGMA data_version").fetchone()[0]
        self.refresh_at = time.monotonic()

    def draw(self, flush=True):
        self.modal_signature = None
        self.paint.track = True
        self.views.draw(flush)

    def modal(self, title, width, height, subtitle=""):
        rows, cols = self.screen.getmaxyx()
        signature = (title,rows,cols)
        if getattr(self,"modal_signature",None)!=signature or self.needs_refresh():
            self.refresh()
            self.draw(flush=False)
            self.modal_signature=signature
            if self.paint.chrome:
                self.modal_chrome = self.paint.chrome.surfaces[:]
        self.modal_hits = []
        self.paint.track = False
        width, height = min(width, cols - 4), min(height, rows - 2)
        rect = Rect(max(1, (cols-width)//2), max(1, (rows-height)//2), width, height)
        self.paint.surface = "panel"
        self.paint.limit = rect
        if self.paint.chrome:
            self.paint.chrome.surfaces = self.modal_chrome[:]
        self.paint.box(rect, title, "panel_border", "panel", parent="plain")
        if subtitle:
            self.paint.text(rect.y+2, rect.x+2, subtitle, "panel_dim", rect.w-4)
        self.paint.text(rect.y+1,rect.x+rect.w-5," × ","panel_dim",3)
        self.modal_hits.append((Rect(rect.x+rect.w-5,rect.y+1,3,1),"key","\x1b"))
        return rect

    def canvas_ready(self, on_text=None):
        """Suspend dialogs without discarding their local draft on a small canvas."""
        while not self.views.usable():
            self.modal_signature = None
            self.cursor(False)
            self.views.small(editing=on_text is not None)
            key=self.key()
            if key=="\x03" or key=="q" and on_text is None:
                self.quit=True
                return False
            if key=="\x1b":
                return False
            if key==curses.KEY_MOUSE:
                self.mouse_event()  # Discard hidden clicks, including their event data.
            elif on_text is not None:
                # Typed characters may already be queued when SIGWINCH arrives.
                # Preserve text edits while Save and navigation stay suspended.
                on_text(key)
        return True

    def modal_button(self, rect, label, key, primary=False):
        style="primary" if primary else "button"
        self.paint.pill(rect,style,parent="panel")
        self.paint.centered(rect.y,rect,label,style)
        self.modal_hits.append((rect,"key",key))

    def mouse_event(self):
        try:
            _,x,y,_,state=curses.getmouse()
        except curses.error:
            return None
        if state & curses.BUTTON4_PRESSED:
            return x,y,"up",False
        if state & getattr(curses,"BUTTON5_PRESSED",0):
            return x,y,"down",False
        if state & curses.BUTTON1_PRESSED:
            at=time.monotonic()
            double=bool(self.last_click and self.last_click[:2]==(x,y) and at-self.last_click[2]<.4)
            self.last_click=None if double else (x,y,at)
            return x,y,"click",double
        return None

    def modal_mouse(self, event):
        if event and event[2]=="click":
            return next(((action,value) for rect,action,value in reversed(self.modal_hits) if rect.contains(event[0],event[1])),None)
        return None

    def mouse(self, event):
        if not event or not self.views.usable():
            return
        if self.views.frame_size != self.screen.getmaxyx():
            # Mouse input may arrive before curses reports KEY_RESIZE.
            self.draw(flush=False)
        x,y,kind,double=event
        if kind in ("up","down"):
            if not any(r.contains(x,y) and action=="scroll" for r,action,_ in self.views.hits):
                return
            step=1 if kind=="down" else -1
            if self.view in ("day","week") and not self.agenda:
                self.start_minute=max(0,min(1440-self.visible_hours*60,self.start_minute+step*60))
                self.need_focus=False
            elif self.view=="year" and not self.agenda:
                self.day=move_date(self.day,"month",step)
                self.focus_date=True
            elif self.view=="month" and not self.agenda:
                self.day+=timedelta(days=step*7)
                self.focus_date=True
            else:
                self.offset=max(0,self.offset+step*3)
                self.need_focus=False
            return
        target=next(((action,value) for rect,action,value in reversed(self.views.hits) if rect.contains(x,y)),None)
        if not target:
            return
        action,value=target
        if action=="key":
            self.action(value)
        elif action == "year_month":
            self.day=value
            self.focus_date=True
            if double:
                self.view="month"
                self.agenda=False
        elif action in ("date","open_day","month"):
            self.day=move_date(self.day,"month",value) if action=="month" else value
            if action=="open_day" or double or self.view not in ("day","week","month","year"):
                self.view="day"
                self.agenda=False
            self.focus_date=True
        elif action in ("task","upcoming"):
            if action=="upcoming":
                item=self.store.resolve(value)
                self.day,self.view,self.agenda=item.task.start.date(),"day",False
                self.focus_ref=value
                self.refresh()
            self.selected=next((i for i,item in enumerate(self.items) if item.ref==value),self.selected)
            self.need_focus=True
            if double and self.chosen():
                self.inspect(self.chosen())

    def cursor(self, visible):
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def key(self):
        try:
            return self.screen.get_wch()
        except curses.error:
            return None

    def prompt(self, label, initial="", hint=""):
        value, cursor = initial, len(initial)
        def preserve_text(key):
            nonlocal value, cursor
            value, cursor = self.edit_text(value, cursor, key)
        self.cursor(True)
        try:
            while True:
                if not self.canvas_ready(preserve_text):
                    return None
                self.cursor(True)
                rect = self.modal(label.upper(), 78, 10, hint)
                field = Rect(rect.x+2, rect.y+3, rect.w-4, 3)
                self.paint.box(field, style="field_active", fill="field_focus", parent="panel")
                available = max(1, field.w-4)
                start = max(0, cursor-available+1)
                self.paint.text(field.y+1, field.x+2, value[start:], "field_focus", available)
                self.modal_hits.append((field,"input",None))
                self.modal_button(Rect(rect.x+2,rect.y+rect.h-2,15,1),"Enter Apply","\n",True)
                self.modal_button(Rect(rect.x+19,rect.y+rect.h-2,13,1),"Esc Cancel","\x1b")
                self.paint.text(rect.y+rect.h-2,rect.x+35,"Ctrl-U clear","panel_dim",rect.w-37)
                try:
                    self.screen.move(field.y+1, field.x+2+min(available-1, cell_width(value[start:cursor])))
                except curses.error:
                    pass
                self.paint.refresh()
                key = self.key()
                if key == curses.KEY_MOUSE:
                    event=self.mouse_event()
                    hit=self.modal_mouse(event)
                    if hit and hit[0]=="key":
                        key=hit[1]
                    elif hit and hit[0]=="input":
                        cursor=self.cursor_at(value,start,max(0,event[0]-field.x-2))
                if key in ("\n", "\r", curses.KEY_ENTER):
                    return value.strip()
                if key in ("\x1b", "\x03"):
                    return None
                value, cursor = self.edit_text(value, cursor, key)
        finally:
            self.cursor(False)

    @staticmethod
    def cursor_at(value, start, column):
        cursor=start
        while cursor<len(value) and cell_width(value[start:cursor+1])<=column:
            cursor+=1
        return cursor

    @staticmethod
    def edit_text(value, cursor, key):
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            if cursor:
                value, cursor = value[:cursor-1] + value[cursor:], cursor - 1
        elif key == curses.KEY_DC:
            value = value[:cursor] + value[cursor + 1:]
        elif key in (curses.KEY_LEFT, "\x02"):
            cursor = max(0, cursor - 1)
        elif key in (curses.KEY_RIGHT, "\x06"):
            cursor = min(len(value), cursor + 1)
        elif key in (curses.KEY_HOME, "\x01"):
            cursor = 0
        elif key in (curses.KEY_END, "\x05"):
            cursor = len(value)
        elif key == "\x15":
            value, cursor = "", 0
        elif key == "\x0b":
            value = value[:cursor]
        elif isinstance(key, str) and key.isprintable():
            value, cursor = value[:cursor] + key + value[cursor:], cursor + len(key)
        return value, cursor

    def form(self, item=None, scheduled=False, series=False):
        task = (self.store.get(item.task.id) if series else item.task) if item else Task("")
        start = task.start.strftime("%Y-%m-%d" + ("" if task.all_day else " %H:%M")) if task.start else (str(self.day) + " 09:00" if scheduled else "")
        end = ((task.end - timedelta(days=1)).strftime("%Y-%m-%d") if task.all_day else task.end.strftime("%Y-%m-%d %H:%M")) if task.end else ""
        fields = [
            ["Title", task.title, "Enter saves a new Inbox task; Tab adds details"],
            ["Start", start, "Blank = Inbox · today 17:00 · YYYY-MM-DD · HH:MM"],
            ["End", end, "Blank = +1h / one day · date-only end is inclusive"],
            ["State", task.state, "Space cycles: pending / ongoing / completed"],
            ["Priority", task.priority, "Space cycles: low / normal / high"],
            ["Tags", " ".join("#"+t for t in task.tags or []), "Space or comma separated"],
            ["Repeat", task.repeat, "Space cycles presets · or type mon,wed,fri"],
            ["Notes", task.notes.replace("\n", "\\n"), "Optional · type \\n for a line break"],
        ]
        if item and item.day and not series:
            fields[6][2] = "To change recurrence, cancel and use E (edit series)"
        if item:
            fields[0][2] = "Ctrl-S saves your changes · Enter moves to the next field"
        focus, cursor, error = 0, len(fields[0][1]), ""
        def preserve_text(key):
            nonlocal cursor
            fields[focus][1], cursor = self.edit_text(fields[focus][1], cursor, key)
        self.cursor(True)
        try:
            while True:
                if not self.canvas_ready(preserve_text):
                    return
                self.cursor(True)
                rows, cols = self.screen.getmaxyx()
                heading = "EDIT SERIES" if series else ("EDIT OCCURRENCE" if item and item.day else ("EDIT TASK" if item else "NEW TASK"))
                rect = self.modal(heading, 92, 34, "Tab / ↑↓ fields   Ctrl-S save   Esc cancel")
                available_rows = max(1, rect.h-9)
                visible = max(1, available_rows//3)
                first = max(0, min(focus-visible+1, len(fields)-visible))
                input_x = rect.x+14
                input_w = max(8, rect.w-17)
                cursor_y, cursor_x = rect.y+4, input_x+2
                for index in range(first, min(len(fields), first+visible)):
                    label, value, hint = fields[index]
                    row = rect.y+3+(index-first)*3
                    active = index == focus
                    self.paint.text(row+1, rect.x+3, label, "accent" if active else "panel_dim", 10)
                    field=Rect(input_x,row,input_w,3)
                    self.paint.box(field, style="field_active" if active else "field_border", fill="field_focus" if active else "field", parent="panel")
                    self.modal_hits.append((field,"field",index))
                    offset = max(0,cursor-max(1,input_w-5)) if active else 0
                    placeholder = {"Start":"Unscheduled · Inbox", "End":"Automatic duration", "Tags":"#backend #personal", "Repeat":"none", "Notes":"Optional notes"}.get(label, "Task title")
                    self.paint.text(row+1,input_x+2,(value[offset:] if value else placeholder),"field_focus" if active else "field",input_w-4)
                    if active:
                        cursor_y, cursor_x = row+1, input_x+2+min(input_w-5,cell_width(value[offset:cursor]))
                self.paint.text(rect.y+rect.h-5,rect.x+3,fields[focus][2],"panel_dim",rect.w-6)
                self.paint.text(rect.y+rect.h-4,rect.x+3,error or "Blank dates keep a task in Inbox. All times are local.","overdue" if error else "panel_dim",rect.w-6)
                self.modal_button(Rect(rect.x+3,rect.y+rect.h-2,15,1),"Ctrl-S Save","\x13",True)
                self.modal_button(Rect(rect.x+20,rect.y+rect.h-2,13,1),"Esc Cancel","\x1b")
                self.paint.text(rect.y+rect.h-2,rect.x+36,"Ctrl-U clear · Enter next","panel_dim",rect.w-39)
                try:
                    self.screen.move(cursor_y,cursor_x)
                except curses.error:
                    pass
                self.paint.refresh()
                key = self.key()
                if key == curses.KEY_MOUSE:
                    event=self.mouse_event()
                    hit=self.modal_mouse(event)
                    if hit and hit[0]=="key":
                        key=hit[1]
                    elif hit and hit[0]=="field":
                        focus=hit[1]
                        cursor=len(fields[focus][1])
                        if fields[focus][0] in ("State","Priority","Repeat"):
                            key=" "
                        else:
                            start=max(0,cursor-max(1,input_w-5))
                            cursor=self.cursor_at(fields[focus][1],start,max(0,event[0]-input_x-2))
                    elif event and event[2] in ("up","down"):
                        key=curses.KEY_UP if event[2]=="up" else curses.KEY_DOWN
                if key in ("\x1b", "\x03"):
                    return
                presets = {"State":["pending","ongoing","completed"],"Priority":["low","normal","high"],"Repeat":["","daily","weekly","monthly","weekdays"]}
                if key == " " and fields[focus][0] in presets:
                    choices = presets[fields[focus][0]]
                    current = fields[focus][1]
                    fields[focus][1] = choices[(choices.index(current)+1)%len(choices)] if current in choices else choices[0]
                    cursor = len(fields[focus][1])
                    continue
                quick = key in ("\n", "\r") and focus == 0 and item is None and not scheduled
                if key == "\x13" or quick or (key in ("\n", "\r") and focus == len(fields) - 1):
                    try:
                        values = {label: value for label, value, _ in fields}
                        begins, finishes, all_day = schedule(values["Start"], values["End"], self.day)
                        changes = dict(title=values["Title"], start=begins, end=finishes, all_day=all_day, state=values["State"].strip().lower(), priority=values["Priority"].strip().lower(), tags=tags_from(values["Tags"]), repeat=values["Repeat"], notes=values["Notes"].replace("\\n", "\n"))
                        if item:
                            self.store.edit(item.ref, changes, series=series)
                        else:
                            added = self.store.add(Task(**changes))
                            self.focus_ref = str(added.id) + ("@" + str(added.start.date()) if added.repeat else "")
                        self.notice("Saved · u undoes" + (" · in Inbox" if not begins else ""))
                        return
                    except ValueError as exc:
                        error = str(exc)
                elif key in ("\t", curses.KEY_DOWN, "\n", "\r"):
                    focus = (focus + 1) % len(fields)
                    cursor = len(fields[focus][1])
                elif key in (curses.KEY_BTAB, curses.KEY_UP):
                    focus = (focus - 1) % len(fields)
                    cursor = len(fields[focus][1])
                else:
                    fields[focus][1], cursor = self.edit_text(fields[focus][1], cursor, key)
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def inspect(self, item):
        self.detail_offset = 0
        while True:
            if not self.canvas_ready():
                return
            if self.needs_refresh():
                self.refresh()
                try:
                    item=self.store.resolve(item.ref)
                except ValueError:
                    return
            task = item.task
            rect = self.modal("TASK DETAILS", 88, 29, f"#{item.ref} · {task.state}" + (" · overdue" if item.overdue(self.at) else ""))
            lines = [(task.title, self.views.color(item)), ("", "panel")]
            lines += [("Schedule   " + schedule_text(task, full=True), "panel")]
            if task.start:
                lines += [("Duration   " + duration(task.end-task.start), "panel")]
            lines += [("Priority   " + task.priority, "panel"), ("Tags       " + (" ".join("#"+t for t in task.tags or []) or "—"), "span"), ("Recurrence " + (task.repeat or "none"), "panel")]
            if item.day:
                lines.append(("Occurrence " + item.day + " · E edits the series", "panel_dim"))
            lines += [("", "panel"), ("NOTES", "panel_dim"), (task.notes or "No notes.", "panel")]
            wrapped = [(part,style) for text,style in lines for part in wrap(text,max(1,rect.w-6))]
            count = rect.h-6
            self.detail_offset = min(self.detail_offset,max(0,len(wrapped)-count))
            for row,(text,style) in enumerate(wrapped[self.detail_offset:self.detail_offset+count]):
                self.paint.text(rect.y+3+row,rect.x+3,text,style,rect.w-6)
            x=rect.x+3
            for label,key in (("e Edit","e"),("s Start","s"),("x Done","x"),("r Move","r"),("z Snooze","z"),("Esc Close","\x1b")):
                self.modal_button(Rect(x,rect.y+rect.h-2,len(label)+2,1),label,key)
                x+=len(label)+3
            self.paint.refresh()
            key = self.key()
            if key==curses.KEY_MOUSE:
                event=self.mouse_event()
                hit=self.modal_mouse(event)
                if hit and hit[0]=="key":
                    key=hit[1]
                elif event and event[2] in ("up","down"):
                    key="k" if event[2]=="up" else "j"
            if key in ("\n","\r","\x1b","q"):
                return
            if key in ("e","E","s","x","p","r","z","D","X"):
                self.action(key)
                self.refresh()
                try:
                    item = self.store.resolve(item.ref)
                except ValueError:
                    return
            elif key in ("j",curses.KEY_DOWN,curses.KEY_NPAGE):
                self.detail_offset += count if key == curses.KEY_NPAGE else 1
            elif key in ("k",curses.KEY_UP,curses.KEY_PPAGE):
                self.detail_offset = max(0,self.detail_offset-(count if key == curses.KEY_PPAGE else 1))

    def commands(self):
        query, selected = "", 0
        while True:
            if not self.canvas_ready():
                return
            rect = self.modal("COMMANDS", 88, 27, "Type to search · ↑↓ select · Enter runs · Esc closes")
            self.paint.fill(Rect(rect.x+2,rect.y+3,rect.w-4,1),"field_focus")
            self.paint.text(rect.y+3,rect.x+3,"/ " + query,"field_focus",rect.w-6)
            matches = [(key,desc) for key,desc in HELP if query.lower() in (key+" "+desc).lower()]
            selected = min(selected,max(0,len(matches)-1))
            count = max(1,rect.h-7)
            start = max(0,selected-count+1)
            for row,(key,desc) in enumerate(matches[start:start+count]):
                chosen = row+start == selected
                style = "selected" if chosen else "panel"
                self.paint.fill(Rect(rect.x+2,rect.y+5+row,rect.w-4,1),style)
                self.paint.text(rect.y+5+row,rect.x+3,f"{key:<13}{desc}",style,rect.w-6)
                self.modal_hits.append((Rect(rect.x+2,rect.y+5+row,rect.w-4,1),"command",row+start))
            if not matches:
                self.paint.text(rect.y+6,rect.x+3,"No matching commands", "panel_dim",rect.w-6)
            self.paint.text(rect.y+rect.h-2,rect.x+3,"Mouse: click controls · double-click tasks · wheel scrolls","panel_dim",rect.w-6)
            self.paint.refresh()
            key = self.key()
            if key==curses.KEY_MOUSE:
                event=self.mouse_event()
                hit=self.modal_mouse(event)
                if hit and hit[0]=="key":
                    key=hit[1]
                elif hit and hit[0]=="command":
                    selected=hit[1]
                    key="\n"
                elif event and event[2] in ("up","down"):
                    key=curses.KEY_UP if event[2]=="up" else curses.KEY_DOWN
            if key in ("\x1b","\x03"):
                return
            if key == curses.KEY_DOWN:
                selected = min(len(matches)-1,selected+1)
            elif key == curses.KEY_UP:
                selected = max(0,selected-1)
            elif key in ("\n","\r") and matches:
                command = matches[selected][0].split()[0]
                if command not in ("?", ":"):
                    self.action({"Enter":"\n","Esc":"\x1b","PgUp":curses.KEY_PPAGE,"←":curses.KEY_LEFT,"↑":curses.KEY_UP}.get(command,command))
                return
            elif key in (curses.KEY_BACKSPACE,"\x7f","\b"):
                query,selected = query[:-1],0
            elif isinstance(key,str) and key.isprintable():
                query,selected = query+key,0

    def action(self, key):
        item = self.chosen()
        if key in ("q", "\x03"):
            self.quit = True
        elif key in ("d", "w", "m", "y", "i", "H", "t"):
            self.view = {"d": "day", "w": "week", "m": "month", "y": "year", "i": "inbox", "H": "history", "t": "day"}[key]
            if key == "t":
                self.day, self.filter = date.today(), ""
                self.select_relevant = True
            self.selected, self.offset, self.need_focus = 0, 0, key == "t"
            self.focus_ref = item.ref if item and key != "t" else None
            self.agenda = False
        elif key in ("h", "l", curses.KEY_LEFT, curses.KEY_RIGHT, "[", "]"):
            step = -1 if key in ("h", "[", curses.KEY_LEFT) else 1
            self.day = move_date(self.day, "day" if key in ("[", "]", curses.KEY_LEFT, curses.KEY_RIGHT) else self.view, step)
            if self.view not in ("day", "week", "month", "year"):
                self.view = "day"
            self.selected, self.offset, self.need_focus = 0, 0, False
            self.focus_date = True
        elif key in (curses.KEY_UP, curses.KEY_DOWN) and self.view in ("month", "year") and not self.agenda:
            self.day += timedelta(days=7 if key == curses.KEY_DOWN else -7)
            self.select_relevant = False
            self.focus_date = True
        elif key in ("j", "k", curses.KEY_DOWN, curses.KEY_UP):
            self.selected = min(max(0, len(self.items) - 1), max(0, self.selected + (1 if key in ("j", curses.KEY_DOWN) else -1)))
            self.need_focus = True
            chosen = self.chosen()
            if chosen and chosen.task.start and self.view in ("week", "month", "year"):
                lo,hi = bounds(self.day,self.view)
                if chosen.overlaps(lo,hi):
                    self.day = max(lo.date(), min(chosen.task.start.date(), (hi-timedelta(days=1)).date()))
        elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE):
            step = 1 if key == curses.KEY_NPAGE else -1
            if self.view in ("day", "week") and not self.agenda:
                self.start_minute = max(0,min(1380,self.start_minute+step*180))
            elif self.view == "year" and not self.agenda:
                self.day=move_date(self.day,"month",step)
                self.focus_date=True
            else:
                self.offset = max(0,self.offset+step*max(1,(self.screen.getmaxyx()[0]-12)//3))
            self.need_focus = False
        elif key in ("+", "=", "-"):
            levels = [6,10,16,24]
            index = levels.index(self.visible_hours)
            self.visible_hours = levels[max(0,min(3,index+(-1 if key in ("+","=") else 1)))]
            self.need_focus = True
        elif key == "b":
            self.sidebar = not self.sidebar
        elif key == "v":
            self.agenda = not self.agenda
            self.offset = 0
            self.need_focus = True
        elif key == "g":
            value = self.prompt("Go to date", str(self.day), "YYYY-MM-DD / today / tomorrow / mon … sun")
            if value:
                self.day, self.offset = parse_date(value), 0
                self.focus_date = True
                if self.view not in ("day", "week", "month", "year"):
                    self.view = "day"
        elif key in ("a", "A"):
            self.form(scheduled=key == "A")
            self.need_focus = True
        elif key == "u":
            self.notice("Undid " + self.store.undo())
        elif key in ("?", ":"):
            self.commands()
        elif key == "/":
            value = self.prompt("Search", self.query, 'Text / #tag / state:overdue / priority:high / on:YYYY-MM-DD')
            if value is not None:
                if self.view != "search":
                    self.previous_view = self.view
                self.query, self.view, self.offset, self.selected = value, "search", 0, 0
        elif key == "f":
            value = self.prompt("Filter", self.filter, 'e.g. #backend state:pending · from:2026-10-01 to:2026-10-15')
            if value is not None:
                # Validate before accepting an invalid date filter.
                if self.items:
                    match(self.items[0], value, self.at)
                self.filter, self.selected, self.offset = value, 0, 0
        elif key == "\x1b":
            self.filter = ""
            if self.view == "search":
                self.view = self.previous_view
            self.offset, self.selected = 0, 0
        elif item:
            if key in ("\n", "\r", curses.KEY_ENTER):
                self.inspect(item)
            elif key in ("e", "E"):
                self.form(item, series=key == "E")
            elif key in ("s", "x", "p"):
                state = {"s": "ongoing", "x": "completed", "p": "pending"}[key]
                self.store.edit(item.ref, {"state": state})
                self.notice(f"{state.capitalize()} · u undoes")
            elif key in ("D","X"):
                self.store.delete(item.ref, series=key == "X")
                self.notice("Deleted series · u restores" if key == "X" and item.task.repeat else "Deleted · u restores")
            elif key == "r":
                value = self.prompt("Reschedule", "tomorrow", "Preserves duration · +1h / +1d / +1w / tomorrow / YYYY-MM-DD HH:MM")
                if value:
                    start, end = shifted_start(value, item.task)
                    self.store.edit(item.ref, {"start": start, "end": end, "all_day": item.task.all_day and start.time() == midnight(start.date()).time()})
                    self.notice("Rescheduled · u undoes")
            elif key == "z":
                value = self.prompt("Snooze minutes", "10", "5 / 10 / 15 / 30 / 60 · one explicit reminder")
                if value:
                    self.store.snooze(item.ref, int(value))
                    self.notice(f"Snoozed for {value} minutes · u undoes")

    def needs_refresh(self):
        minute=now().replace(second=0,microsecond=0)
        return (minute!=self.at.replace(second=0,microsecond=0)
                or self.data_version!=self.store.db.execute("PRAGMA data_version").fetchone()[0]
                or time.monotonic()-self.refresh_at>10)

    def run(self):
        self.setup()
        self.refresh()
        self.draw()
        while not self.quit:
            key = self.key()
            try:
                if key==curses.KEY_MOUSE:
                    self.mouse(self.mouse_event())
                elif key is not None and (self.views.usable() or key in ("q","\x03")):
                    self.action(key)
                expired = self.message and time.monotonic() > self.message_until
                if expired:
                    self.message = ""
                if key is not None or expired or self.needs_refresh():
                    self.reminders = running(self.store)
                    self.refresh()
                    if not self.quit:
                        self.draw()
            except (ValueError, OverflowError, sqlite3.Error) as exc:
                self.notice(str(exc))
                if self.view == "search":
                    self.view = self.previous_view
                self.filter = ""
                self.draw()


def launch(store):
    def session(screen):
        app = App(screen, store)
        try:
            app.run()
        finally:
            app.paint.close()
            app.theme.restore()
    curses.wrapper(session)
