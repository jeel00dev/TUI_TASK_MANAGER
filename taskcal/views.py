"""Visual calendars and shared panels. Rendering never changes task data."""
from __future__ import annotations

import calendar
import math
import time
from datetime import date, timedelta

from .calendar import bounds, segments, span_lanes, time_blocks, workload
from .drawing import Rect, cell_width, ellipsis, wrap
from .model import midnight, schedule_text


MIN_COLUMNS, MIN_ROWS = 90, 28
MARGIN, GUTTER, CONTENT_TOP = 2, 3, 6


def tracks(start, length, count, gap=0):
    """Share all available cells; edges differ by at most one cell."""
    usable = length-gap*(count-1)
    return [(start+i*usable//count+i*gap, usable*(i+1)//count-usable*i//count)
            for i in range(count)]


def circled(day):
    """Unicode circled dates; 21–31 occupy two terminal cells."""
    return chr(0x2460+day-1) if day <= 20 else chr(0x3251+day-21)


def year_geometry(rect):
    """Fit every month, switching to summary tiles when dates would not fit."""
    columns = 4 if rect.w >= 99 else 3
    rows = 12 // columns
    gap = 1 if rect.h >= rows * 10 + rows + 1 else 0
    height = (rect.h - 2 - gap * (rows-1)) // rows
    return columns, rows, gap, height


SYMBOLS = {"pending": "○", "ongoing": "▶", "completed": "✓"}


def duration(delta):
    minutes = max(0, int(delta.total_seconds() / 60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return " ".join(value for value in (f"{days}d" if days else "", f"{hours}h" if hours else "", f"{minutes}m" if minutes else "") if value) or "0m"


def compact_time(starts, ends, width):
    """Keep complete endpoints where possible, shortening whole hours first."""
    full = starts + "–" + ends
    short = starts.replace(":00", "") + "–" + ends.replace(":00", "")
    return next((text for text in (full, short) if cell_width(text) <= width),
                ellipsis(full, width))


class Views:
    def __init__(self, app):
        self.a = app
        self.p = app.paint
        self.card_rects = []
        self.hits = []
        self.frame_size = None

    def color(self, item):
        if item.task.state == "completed":
            return "green"
        if item.overdue(self.a.at):
            return "red"
        if item.task.state == "ongoing":
            return "orange"
        if item.task.all_day or item.task.end and item.task.end - item.task.start >= timedelta(days=1):
            return "purple"
        if item.task.priority == "low":
            return "brown"
        return "blue"

    def selected(self, item):
        selected = self.a.chosen()
        return bool(selected and selected.ref == item.ref)

    def symbol(self, item):
        return "!" if item.overdue(self.a.at) else SYMBOLS[item.task.state]

    def title(self, item):
        return self.symbol(item) + " " + item.task.title + (" !" if item.task.priority == "high" else "") + (" ↻" if item.task.repeat else "")

    def hit(self, rect, action, value=None):
        self.hits.append((rect, action, value))

    def button(self, rect, label, action, value=None, active=False):
        style = "active_tab" if active else "button"
        if rect.h >= 3:
            self.p.box(rect, style="active_tab_border" if active else "button_border", fill=style)
            self.p.centered(rect.y+1, rect.inset(), label, style)
        else:
            self.p.pill(rect, style)
            self.p.centered(rect.y, rect, label, style)
        self.hit(rect, action, value)

    def usable(self):
        rows, cols = self.a.screen.getmaxyx()
        return rows >= MIN_ROWS and cols >= MIN_COLUMNS

    def small(self, flush=True, editing=False):
        a, p = self.a, self.p
        rows, cols = a.screen.getmaxyx()
        a.screen.erase()
        p.begin()
        self.hits, self.card_rects = [], []
        p.surface = p.limit = None
        p.cells.clear()
        y = max(0, rows//2-3)
        for index,(text,style) in enumerate([
            ("TASK · resize the terminal", "heading"),
            (f"At least {MIN_COLUMNS} columns × {MIN_ROWS} rows required", "accent"),
            (f"Current size: {cols} × {rows}", "muted"),
            ("Your work is preserved. Resize to continue.", "muted"),
            ("Esc cancels · Ctrl-C quits" if editing else "q quits · Esc cancels an open dialog", "muted"),
        ]):
            p.centered(y+index, Rect(0,0,max(0,cols-1),rows), text, style)
        if flush:
            p.refresh()

    def draw(self, flush=True):
        a, p = self.a, self.p
        height, width = a.screen.getmaxyx()
        self.frame_size = (height, width)
        a.screen.erase()
        p.begin()
        p.surface = p.limit = None
        p.cells.clear()
        self.card_rects, self.hits = [], []
        if not self.usable():
            self.small(flush)
            return
        self.header(width)
        area = Rect(MARGIN, CONTENT_TOP, width-2*MARGIN, height-CONTENT_TOP-3)
        sidebar = a.sidebar and width >= 132 and height >= 40
        if sidebar:
            sw = min(48, max(32, area.w // 5))
            main = Rect(area.x, area.y, area.w-sw-GUTTER, area.h)
            side = Rect(main.x+main.w+GUTTER, area.y, sw, area.h)
        else:
            main, side = area, None
        if a.view == "year" and not a.agenda and side and year_geometry(main)[3] < 10 <= year_geometry(area)[3]:
            main, side = area, None
        self.hit(main, "scroll")
        with p.within(main):
            if a.agenda or a.view in ("inbox", "history", "search"):
                self.agenda(main)
            elif a.view in ("day", "week"):
                self.timeline(main)
            elif a.view == "year":
                self.year(main)
            else:
                self.month(main)
        if side:
            with p.within(side, "panel"):
                self.sidebar(side)
        self.footer(width, height, bool(side))
        a.need_focus = False
        if flush:
            p.refresh()

    def header(self, width):
        a, p = self.a, self.p
        p.fill(Rect(0, 0, width, 3), "status")
        p.text(1, MARGIN, "TASK", "status", bold=True)
        tab_width = 13 if width >= 112 else 11
        x = 8
        for key,label,view in [("d","Day","day"),("w","Week","week"),("m","Month","month"),("y","Year","year"),("i","Inbox","inbox"),("H","History","history")]:
            text = f"{label} {key}" if width >= 112 else label
            self.button(Rect(x,0,tab_width,3),text,"key",key,a.view==view)
            x += tab_width+1
        new_width = 14 if width >= 112 else 6
        new_x = width-MARGIN-new_width
        if new_x-x >= 24:
            clock = a.at.strftime("%a %d %b  %H:%M")
            p.text(1,new_x-len(clock)-3,clock,"status_dim")
        self.button(Rect(new_x,0,new_width,3),"+ New task" if width >= 112 else "+ a","key","a")
        lo, hi = bounds(a.day, a.view)
        title = {"day": a.day.strftime("%A, %d %B %Y"), "week": f"{lo:%d %b} – {hi-timedelta(days=1):%d %b %Y}", "month": a.day.strftime("%B %Y"), "year": f"{a.day.year} · {a.day:%d %b} selected", "inbox": "Inbox · ready to schedule", "history": "Completed history", "search": "Search · " + a.query}[a.view]
        if a.view in ("day","week","month","year"):
            self.button(Rect(MARGIN,4,3,1),"‹","key","h")
            self.button(Rect(MARGIN+4,4,3,1),"›","key","l")
            self.hit(Rect(11,4,min(len(title),width-58),1),"key","g")
            p.text(4,11,ellipsis(title,width-58),"heading",width-58)
        else:
            p.text(4,MARGIN,ellipsis(title,width-49),"heading",width-49)
        for (x,w),(label,key,active) in zip(tracks(width-MARGIN-43,43,4,1),[
                ("t Today","t",False),("/ Search","/",False),
                ("f Filter","f",bool(a.filter)),("v List" if not a.agenda else "v Grid","v",a.agenda)]):
            self.button(Rect(x,4,w,1),label,"key",key,active)

    def footer(self, width, height, sidebar):
        a, p = self.a, self.p
        p.fill(Rect(0, height-2, width, 2), "status")
        if time.monotonic() < a.message_until:
            status = a.message
        elif a.filter:
            status = "Filter: " + a.filter + " · Esc clears"
        elif a.chosen() and not sidebar:
            item = a.chosen()
            status = f"{item.task.title} · {item.task.state} · {schedule_text(item.task)}"
        else:
            status = f"{len(a.items)} tasks   ○ pending   ▶ ongoing   ✓ completed   ! overdue"
        p.text(height-2,2,status,"accent" if time.monotonic()<a.message_until else "status_dim",width-23)
        p.text(height-2,width-18,"● reminders on" if a.reminders else "○ reminders off","green" if a.reminders else "muted")
        x=2
        actions=[("a Add","a"),("e Edit","e"),("s Start","s"),("x Done","x"),("r Move","r"),("u Undo","u"),("? Commands","?"),("q Quit","q")]
        for label,key in actions:
            self.button(Rect(x,height-1,len(label)+2,1),label,"key",key)
            x += len(label)+3

    def timeline(self, rect):
        a, p = self.a, self.p
        p.box(rect)
        lo, hi = bounds(a.day, a.view)
        week = a.view == "week"
        # Keep columns useful in a split terminal. Arrow keys pan the focused day.
        days = 7 if week else 1
        if week and rect.w < 105:
            days = 3 if rect.w >= 62 else 1
            offset = max(0, min(7-days, a.day.weekday() - days // 2))
            lo += timedelta(days=offset)
            hi = lo + timedelta(days=days)
        grid_x, grid_w = rect.x + 7, rect.w - 8
        edges = [grid_x + i * grid_w // days for i in range(days + 1)]
        dates = [lo.date() + timedelta(days=i) for i in range(days)]
        spans = [o for o in a.items if o.task.all_day and o.overlaps(lo, hi)]
        earlier = [o for o in a.items if o.overdue(a.at) and not o.overlaps(lo,hi)] if not week else []
        bars = span_lanes(spans, dates[0], days)
        lane_count = max((b.lane + 1 for b in bars), default=0)
        span_rows = min(lane_count, max(1, min(4, rect.h // 6)))
        selected_bar = next((b for b in bars if self.selected(b.item)), None)
        span_offset = max(0, selected_bar.lane - span_rows + 1) if selected_bar else 0
        more_spans = int(lane_count > span_rows)
        header_rows = 4 + span_rows + more_spans + bool(earlier)
        body_y = rect.y + header_rows
        rows = max(1, rect.h - header_rows - 3)
        visible_minutes = a.visible_hours * 60
        a.start_minute = max(0, min(a.start_minute, 1440 - visible_minutes))
        chosen = a.chosen()
        if a.need_focus and chosen and not chosen.task.all_day and chosen.overlaps(lo, hi):
            # Clip a multi-day task to the selected visible day before focusing it.
            focus_day = max(lo, min(midnight(a.day), hi - timedelta(days=1)))
            if not chosen.overlaps(focus_day, focus_day + timedelta(days=1)):
                focus_day = max(lo, midnight(chosen.task.start.date()))
            start = max(0, int((chosen.task.start - focus_day).total_seconds() / 60))
            end = min(1440, int((chosen.task.end - focus_day).total_seconds() / 60))
            if start >= a.start_minute + visible_minutes or end <= a.start_minute:
                a.start_minute = max(0, min(1440 - visible_minutes, (start // 60) * 60 - 60))
        start_minute = a.start_minute
        now_minute = a.at.hour * 60 + a.at.minute
        show_now = a.at.date() in dates and start_minute <= now_minute < start_minute + visible_minutes
        # Give the time rule its own row. Map the schedule around that row so
        # even compact cards keep their text when the rule passes through them.
        schedule_rows = rows - int(show_now)
        scale = visible_minutes / schedule_rows
        marker_row = math.ceil((now_minute - start_minute) / scale) if show_now else None
        marker_y = body_y + marker_row if show_now else None

        def screen_row(row, end=False):
            after = marker_row is not None and (row > marker_row if end else row >= marker_row)
            return body_y + row + int(after)

        above, below, hidden = set(), set(), set()
        for index, day in enumerate(dates):
            x, end_x = edges[index], edges[index + 1]
            cw = end_x - x
            today = day == a.at.date()
            focus = day == a.day
            column = Rect(x, rect.y + 1, cw, rect.h - 4)
            if today:
                p.fill(column, "today")
            p.vline(x, rect.y + 1, rect.h - 3, "grid")
            p.text(rect.y,x,"┬","border",1)
            self.hit(Rect(x+1,rect.y+1,cw-1,2),"date",day)
            self.hit(Rect(x+1,body_y,cw-1,rows),"date",day)
            p.centered(rect.y + 1, Rect(x+1, 0, cw-1, 1), day.strftime("%a %d %b") if not week else day.strftime("%a %d"), "selected_day" if focus else ("today" if today else "heading"))
            dl, dh = bounds(day, "day")
            relevant = [o for o in a.items if o.overlaps(dl, dh)]
            occupied, _, _ = workload(relevant, day)
            caption = f"{len(relevant)} tasks · {occupied:g}h"
            p.centered(rect.y + 2, Rect(x+1, 0, cw-1, 1), caption, "today" if today else "muted")
            for minute in range(((start_minute+59)//60)*60, min(1440,start_minute+visible_minutes),60):
                row = int((minute-start_minute)/scale)
                p.hline(screen_row(row), x + 1, cw - 1, "today_grid" if today else "grid", "┄")
                if index == 0:
                    p.text(screen_row(row), rect.x + 1, f"{minute//60:02d}:00", "muted", 5)
            for item in relevant:
                if item.task.all_day:
                    continue
                begin = max(0, (item.task.start - dl).total_seconds() / 60)
                end = min(1440, (item.task.end - dl).total_seconds() / 60)
                if end <= start_minute:
                    above.add(item.ref)
                if begin >= start_minute + visible_minutes:
                    below.add(item.ref)
            blocks = time_blocks(relevant, day, start_minute, schedule_rows, scale)
            if not week:
                for begin,end,active in segments(relevant,day):
                    first = max(start_minute,(begin-dl).total_seconds()/60)
                    last = min(start_minute+visible_minutes,(end-dl).total_seconds()/60)
                    if not active and last-first >= scale*2:
                        row = int((first-start_minute)/scale)+1
                        finish = "24:00" if end == dh else end.strftime("%H:%M")
                        p.text(screen_row(row),x+3,f"{begin:%H:%M}–{finish} · free between timed tasks", "muted",cw-5)
            for block in blocks:
                max_lanes = max(1, (cw - 2) // (9 if week else 22))
                visible_lanes = min(block.lanes, max_lanes)
                selected = next((b for b in blocks if self.selected(b.item) and b.group == block.group), None)
                lane_offset = max(0, selected.lane - visible_lanes + 1) if selected else 0
                if not lane_offset <= block.lane < lane_offset + visible_lanes:
                    hidden.add(block.item.ref)
                    continue
                lane = block.lane - lane_offset
                bx = x + 1 + lane * (cw - 2) // visible_lanes
                bw = (lane + 1) * (cw - 2) // visible_lanes - lane * (cw - 2) // visible_lanes
                top, bottom = screen_row(block.top), screen_row(block.bottom, end=True)
                self.card(Rect(bx, top, bw, bottom - top), block.item, day, marker_y)
        p.hline(rect.y + 3, rect.x + 1, rect.w - 2, "grid")
        p.text(rect.y+3,rect.x,"├","border",1)
        p.text(rect.y+3,rect.x+rect.w-1,"┤","border",1)
        for x in edges[:-1]:
            p.text(rect.y+3,x,"┼","grid",1)
        ruler = rect.y+rect.h-3
        p.hline(ruler,rect.x+1,rect.w-2,"grid")
        p.text(ruler,rect.x,"├","border",1)
        p.text(ruler,rect.x+rect.w-1,"┤","border",1)
        for x in edges[:-1]:
            p.text(ruler,x,"┴","grid",1)
        if spans:
            p.text(rect.y + 4, rect.x + 1, "SPAN", "muted", 5)
        for bar in bars:
            if span_offset <= bar.lane < span_offset + span_rows:
                x, end = edges[bar.top] + 1, edges[bar.bottom]
                self.bar(Rect(x, rect.y + 4 + bar.lane - span_offset, end - x, 1), bar.item, lo, hi)
        if more_spans:
            p.text(body_y-1-bool(earlier), grid_x+1, f"{lane_count-span_rows} more span rows · j/k selects", "muted", grid_w-2)
        if earlier:
            item = next((o for o in earlier if self.selected(o)), earlier[0])
            self.hit(Rect(grid_x+1,body_y-1,grid_w-2,1),"task",item.ref)
            p.text(body_y-1,grid_x+1,f"! {len(earlier)} earlier overdue · {item.task.title} · j/k select · v all", "red",grid_w-2)
        end_minute = min(1440,start_minute+visible_minutes)
        hint = f"{start_minute//60:02d}:{start_minute%60:02d}–{end_minute//60:02d}:{end_minute%60:02d}  PgUp/PgDn time  ± zoom"
        if hidden:
            hint = f"+{len(hidden)} overlaps · j/k reveal · v all  |  " + hint
        elif above or below:
            hint = f"↑{len(above)} earlier ↓{len(below)} later · v all  |  " + hint
        if days < 7 and week:
            hint += f" · {days}/7 days · ←/→ pans"
        p.text(rect.y + rect.h - 2, rect.x + 2, hint, "muted", rect.w-4)
        if not a.items:
            p.text(screen_row(min(2, schedule_rows-1)), grid_x + 3, "Your calendar is open.  A schedules work here.", "muted", grid_w - 6)
        if show_now:
            today_x = edges[dates.index(a.at.date())]
            today_end = edges[dates.index(a.at.date()) + 1]
            for xx in range(grid_x, edges[-1]):
                inside = next((r for r, _ in self.card_rects if r.contains(xx, marker_y)), None)
                if inside:
                    _, style = p.cells[(xx, marker_y)]
                    style = style.removesuffix("_edge") + "_now"
                else:
                    style = "today_now" if today_x < xx < today_end else "red"
                # Draw above cards and column dividers, preserving each fill.
                p.text(marker_y, xx, "●" if xx == today_x else "┄", style, 1)
            p.text(marker_y, rect.x+1, a.at.strftime("%H:%M"), "red", 5)

    def card(self, rect, item, day, marker_y=None):
        if rect.w < 3 or rect.h < 1:
            return
        p = self.p
        selected = self.selected(item)
        color = self.color(item)
        fill = color + ("_selected" if selected else "_fill")
        edge = fill + "_edge"
        dl, dh = bounds(day, "day")
        starts = item.task.start.strftime("%H:%M") if item.task.start >= dl else "←00:00"
        ends = item.task.end.strftime("%H:%M") if item.task.end < dh else "24:00→"
        with p.within(rect):
            if p.chrome:
                outer = p.background(rect)
                p.fill(rect,fill)
                p.rounded(rect,fill,edge,"task",outer,accent=color)
            elif rect.h >= 3:
                p.box(rect,style=edge,fill=fill,edge_aligned=True)
            else:
                p.fill(rect,fill)
            self.card_content(rect, item, starts, ends, fill, edge, marker_y)
        self.card_rects.append((rect,item.ref))
        self.hit(rect,"task",item.ref)

    def card_content(self, rect, item, starts, ends, fill, edge, marker_y):
        """Center one text group, with a hanging state symbol and shared inset.

        A calendar block cannot grow beyond its scheduled interval. Short blocks
        use one line; taller blocks gain wrapped titles, time and breathing room.
        The minute rule owns its row, so content never gets overwritten by it.
        """
        p = self.p
        rows = [y for y in range(rect.y,rect.y+rect.h) if y != marker_y]
        if not rows:
            return
        pad = 3 if rect.w >= 40 else 2 if rect.w >= 10 else 1
        width = rect.w-2*pad
        gutter = 2 if width >= 6 else 0
        x, width = rect.x+pad+gutter, width-gutter
        if width <= 0:
            return
        title = self.title(item)[2:]  # State has its own column on every line.
        timing = compact_time(starts, ends, width)
        selected = self.selected(item)
        if len(rows) < 4:
            y = min(rows,key=lambda row:(abs(2*row-(2*rect.y+rect.h-1)),-row))
            # Wide, shallow blocks can retain both fields on the same baseline.
            time_width = cell_width(timing)
            inline = width >= time_width+14
            title_width = width-time_width-2 if inline else width
            p.text(y,x,ellipsis(title,title_width),fill,title_width,bold=selected)
            if inline:
                p.text(y,x+width-time_width,timing,edge,time_width)
        else:
            rows = rows[1:-1]  # Equal top/bottom inset, clear of the accent.
            lines = wrap(title,width)
            count = min(3,len(lines),len(rows)-1)
            if len(lines) > count:
                lines[count-1] = ellipsis(" ".join(lines[count-1:]),width)
            gap = int(len(rows) >= count+3)
            # Center using screen coordinates, including a possible minute row.
            # On a half-cell tie, leave the extra breathing room above the text.
            offset = min(range(len(rows)-count-gap), key=lambda i:
                         (abs(rows[i]+rows[i+count+gap]-(2*rect.y+rect.h-1)),-i))
            y = rows[offset]
            for index,line in enumerate(lines[:count]):
                p.text(rows[offset+index],x,line,fill,width,bold=selected)
            p.text(rows[offset+count+gap],x,timing,edge,width)
        if gutter:
            p.text(y,x-gutter,self.symbol(item),edge,1)

    def bar(self, rect, item, lo, hi):
        color = self.color(item)
        style = color + ("_selected" if self.selected(item) else "_fill")
        self.p.fill(rect, style)
        left = "←" if item.task.start < lo else self.symbol(item)
        right = "→" if item.task.end > hi else ""
        text = left + " " + item.task.title
        self.p.text(rect.y, rect.x, ellipsis(text, rect.w-1-len(right)), style + "_edge", rect.w-1, bold=self.selected(item))
        if right:
            self.p.text(rect.y, rect.x + rect.w-1, right, style + "_edge", 1)
        self.card_rects.append((rect, item.ref))
        self.hit(rect,"task",item.ref)

    def month(self, rect):
        a,p=self.a,self.p
        p.box(rect)
        weeks=calendar.Calendar().monthdatescalendar(a.day.year,a.day.month)
        edges=[rect.x+i*(rect.w-1)//7 for i in range(8)]
        available=rect.h-5
        bottoms=[rect.y+3+i*available//len(weeks) for i in range(len(weeks)+1)]
        for col,label in enumerate(("MON","TUE","WED","THU","FRI","SAT","SUN")):
            p.centered(rect.y+1,Rect(edges[col]+1,0,edges[col+1]-edges[col]-1,1),label,"muted")
        for row,week in enumerate(weeks):
            top,bottom=bottoms[row],bottoms[row+1]
            for col,day in enumerate(week):
                x,cw=edges[col],edges[col+1]-edges[col]
                box=Rect(x+1,top,cw-1,bottom-top-1)
                if day==a.day or day==a.at.date():
                    p.fill(box,"today" if day==a.at.date() else "status")
                self.hit(box,"date",day)
                label=circled(day.day) if day==a.at.date() else str(day.day)
                style="accent" if day in (a.day,a.at.date()) else ("heading" if day.month==a.day.month else "muted")
                p.text(top,x+2,label,style,cw-3)
                lo,hi=bounds(day,"day")
                count=sum(o.overlaps(lo,hi) for o in a.items)
                if count:
                    p.text(top,edges[col+1]-6,f"{count:2} ·","muted",4)
            # Every separator connects to its verticals and the outer frame.
            p.hline(top-1,rect.x+1,rect.w-2,"grid")
            p.text(top-1,rect.x,"├","border",1)
            p.text(top-1,rect.x+rect.w-1,"┤","border",1)
            for x in edges[1:-1]:
                p.text(top-1,x,"┬" if row==0 else "┼","grid",1)
                p.vline(x,top,bottom-top-1,"grid")
        last=bottoms[-1]-1
        p.hline(last,rect.x+1,rect.w-2,"grid")
        p.text(last,rect.x,"├","border",1)
        p.text(last,rect.x+rect.w-1,"┤","border",1)
        for x in edges[1:-1]:
            p.text(last,x,"┴","grid",1)
        # Continuous bars sit above the day grid, just like calendar span events.
        for row,week in enumerate(weeks):
            top,bottom=bottoms[row],bottoms[row+1]
            bars=span_lanes(a.items,week[0])
            slots=max(0,bottom-top-2)
            max_lane=max((b.lane for b in bars),default=-1)
            overflow=max_lane>=slots
            if overflow and slots>1:
                slots-=1
            chosen=next((b for b in bars if self.selected(b.item)),None)
            offset=max(0,chosen.lane-slots+1) if chosen and slots else 0
            shown=set()
            for bar in bars:
                if offset<=bar.lane<offset+slots:
                    x,end=edges[bar.top]+1,edges[bar.bottom]
                    self.bar(Rect(x,top+1+bar.lane-offset,end-x,1),bar.item,midnight(week[0]),midnight(week[-1])+timedelta(days=1))
                    shown.add(bar.item.ref)
            if overflow:
                for col,day in enumerate(week):
                    lo,hi=bounds(day,"day")
                    more=sum(o.overlaps(lo,hi) and o.ref not in shown for o in a.items)
                    if more and bottom-top-2>slots:
                        box=Rect(edges[col]+1,bottom-2,edges[col+1]-edges[col]-1,1)
                        p.text(box.y,box.x+1,f"+{more} more","muted",box.w-2)
                        self.hit(box,"open_day",day)
        p.text(rect.y+rect.h-2,rect.x+2,"Click date · double-click opens day   j/k task   A schedule   v agenda","muted",rect.w-4)

    def year(self, rect):
        a, p = self.a, self.p
        columns, rows, gap, tile_h = year_geometry(rect)
        lo, hi = bounds(a.day, "year")
        by_day = {}
        by_month = {month: [] for month in range(1, 13)}
        for item in a.items:
            first = max(lo, item.task.start).date()
            last = (min(hi, item.task.end) - timedelta(microseconds=1)).date()
            for month in range(first.month, last.month + 1):
                by_month[month].append(item)
            day = first
            while day <= last:
                by_day.setdefault(day, []).append(item)
                day += timedelta(days=1)
        chosen = a.chosen()
        month_columns = tracks(rect.x,rect.w,columns,GUTTER)
        month_rows = tracks(rect.y,rect.h-2,rows,gap)
        for month in range(1, 13):
            row, col = divmod(month-1, columns)
            x, tile_w = month_columns[col]
            y, tile_h = month_rows[row]
            tile = Rect(x,y,tile_w,tile_h)
            focused = month == a.day.month
            first = date(a.day.year, month, 1)
            self.hit(tile, "year_month", first)
            p.box(tile, style="accent" if focused else "border")
            items = by_month[month]
            p.text(tile.y+1, tile.x+2, first.strftime("%B"), "accent" if focused else "heading", tile.w-4)
            if tile_h == 10 and tile.w >= 25 and items:
                count = str(len(items))
                p.text(tile.y+1, tile.x+tile.w-len(count)-2, count, "muted", len(count))
            busy_days = sum(day.year == first.year and day.month == month for day in by_day)
            summary = f"{len(items)} tasks · {busy_days} days" if items else "No scheduled tasks"
            if tile_h >= 10:
                dates = tracks(tile.x+2,tile.w-4,7)
                for index, label in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
                    left, cell = dates[index]
                    p.centered(tile.y+2, Rect(left,0,cell,1), label, "muted")
                weeks = calendar.Calendar().monthdayscalendar(a.day.year,month)
                week_count = max(len(calendar.Calendar().monthdayscalendar(a.day.year,m))
                                 for m in range(row*columns+1,(row+1)*columns+1))
                date_top = tile.y+3
                # Neighboring months share row baselines. Padding remains part
                # of the date target; blank final weeks are not invented dates.
                footer_rows = 3 if tile_h >= 13 else (2 if tile_h >= 11 else 1)
                date_height = tile.h-3-footer_rows
                labels = [date_top + round(i*(date_height-1)/(week_count-1)) for i in range(week_count)]
                for week_index, week in enumerate(weeks):
                    label_y = labels[week_index]
                    top = date_top if week_index == 0 else (labels[week_index-1]+label_y+1)//2
                    bottom = date_top+date_height if week_index == week_count-1 else (label_y+labels[week_index+1]+1)//2
                    for index, number in enumerate(week):
                        if not number:
                            continue
                        day = date(a.day.year,month,number)
                        left, cell = dates[index]
                        box = Rect(left,label_y,cell,1)
                        active = by_day.get(day, [])
                        if day == a.day:
                            style = "selected_day"
                        elif chosen and any(o.ref == chosen.ref for o in active):
                            style = self.color(chosen)+"_selected"
                        elif active:
                            status = next((o for o in active if o.overdue(a.at)),None)
                            status = status or next((o for o in active if o.task.state=="ongoing"),None)
                            status = status or next((o for o in active if o.task.state!="completed"),active[0])
                            style = self.color(status)+"_fill"
                        else:
                            style = "plain"
                        p.fill(box,style)
                        label = circled(number) if day == a.at.date() else f"{number:2}"
                        p.centered(box.y,box,label,style)
                        self.hit(Rect(box.x,top,cell,bottom-top),"date",day)
                if tile_h >= 11:
                    p.text(tile.y+tile.h-2,tile.x+2,summary,"muted",tile.w-4)
                if tile_h >= 13 and chosen and any(o.ref==chosen.ref for o in items):
                    p.text(tile.y+tile.h-3,tile.x+2,ellipsis(chosen.task.title,tile.w-4),self.color(chosen),tile.w-4)
            else:
                p.text(tile.y+2,tile.x+2,summary,"muted",tile.w-4)
                if tile_h >= 5 and items:
                    item = next((o for o in items if self.selected(o)),items[0])
                    box = Rect(tile.x+2,tile.y+3,tile.w-4,1)
                    p.text(box.y,box.x,ellipsis(self.title(item),box.w),self.color(item),box.w)
                    self.hit(box,"task",item.ref)
        hint = "h/l year · PgUp/PgDn month · arrows date · m open month · A schedule · v agenda"
        p.text(rect.y+rect.h-1,rect.x+1,hint,"muted",rect.w-2)

    def agenda(self, rect):
        a, p = self.a, self.p
        title = {"inbox": "UNSCHEDULED", "history": "COMPLETED", "search": "RESULTS"}.get(a.view, "AGENDA")
        p.box(rect, title)
        inner = rect.inset(2)
        if not a.items:
            text = {"inbox": "Capture something. Give it a date when you're ready.", "history": "Completed work will appear here.", "search": "No matches. Try a title, #tag, notes, or a date."}.get(a.view, "No tasks in this calendar range.")
            p.text(inner.y+1, inner.x+1, text, "muted", inner.w-2)
            p.text(inner.y+3, inner.x+1, "a quick capture   A schedule   / search", "accent", inner.w-2)
            return
        row_h = 3 if rect.h >= 24 else 2
        visible = max(1, (inner.h-1)//row_h)
        if a.need_focus:
            if a.selected < a.offset:
                a.offset = a.selected
            elif a.selected >= a.offset + visible:
                a.offset = a.selected-visible+1
        a.offset = max(0, min(a.offset, len(a.items)-visible))
        for index, item in enumerate(a.items[a.offset:a.offset+visible]):
            y = inner.y + index*row_h
            color = self.color(item)
            style = color + ("_selected" if self.selected(item) else "_fill")
            card = Rect(inner.x, y, inner.w, row_h-1)
            outer = p.background(card)
            p.fill(card, style)
            p.rounded(card,style,style+"_edge","task",outer,accent=color)
            self.hit(Rect(inner.x,y,inner.w,row_h-1),"task",item.ref)
            if not p.chrome:
                p.text(y, inner.x, "┃" if self.selected(item) else "▎", style+"_edge", 1)
            p.text(y, inner.x+2, ellipsis(self.title(item), inner.w-20), style, inner.w-20, bold=self.selected(item))
            p.text(y, inner.x+inner.w-16, item.task.state, style+"_edge", 15)
            if row_h > 2:
                details = schedule_text(item.task, full=True) + "   " + " ".join("#"+t for t in item.task.tags or [])
                p.text(y+1, inner.x+2, details, style+"_edge", inner.w-4)
        p.text(rect.y+rect.h-2, rect.x+2, f"{a.offset+1}–{min(len(a.items),a.offset+visible)} of {len(a.items)}   j/k select · Enter details · r schedule", "muted", rect.w-4)

    def sidebar(self, rect):
        p, a = self.p, self.a
        y, remaining = rect.y, rect.h
        if a.view != "year":
            self.mini_calendar(Rect(rect.x,y,rect.w,12))
            y += 13
            remaining -= 13
        show_summary = remaining >= 40
        context_h = min(15,max(8,remaining//3))
        details_h = remaining-context_h-1-(9 if show_summary else 0)
        details_h = max(12,details_h)
        with p.within(Rect(rect.x,y,rect.w,details_h)):
            self.details(Rect(rect.x,y,rect.w,details_h))
        y += details_h+1
        remaining -= details_h+1
        if show_summary:
            self.summary(Rect(rect.x,y,rect.w,8))
            y += 9
            remaining -= 9
        if remaining >= 5:
            self.context(Rect(rect.x,y,rect.w,remaining))

    def mini_calendar(self, rect):
        a,p = self.a,self.p
        p.box(rect,style="panel_border",fill="panel")
        p.centered(rect.y+1,rect,a.day.strftime("%B %Y"),"panel_title")
        self.button(Rect(rect.x+1,rect.y+1,3,1),"‹","month",-1)
        self.button(Rect(rect.x+rect.w-4,rect.y+1,3,1),"›","month",1)
        dates=tracks(rect.x+2,rect.w-4,7)
        for col,name in enumerate(("Mo","Tu","We","Th","Fr","Sa","Su")):
            left,cell=dates[col]
            p.centered(rect.y+3,Rect(left,0,cell,1),name,"panel_dim")
        for row,week in enumerate(calendar.Calendar().monthdatescalendar(a.day.year,a.day.month)):
            for col,day in enumerate(week):
                left,cell=dates[col]
                box=Rect(left,rect.y+4+row,cell,1)
                style="active_tab" if day==a.day else ("accent" if day==a.at.date() else ("panel" if day.month==a.day.month else "panel_dim"))
                p.fill(box,style)
                label=circled(day.day) if day==a.at.date() else f"{day.day:2}"
                p.centered(box.y,box,label,style)
                self.hit(box,"date",day)
        p.centered(rect.y+rect.h-2,rect.inset(),"Double-click date to open","panel_dim")

    def details(self, rect):
        a,p=self.a,self.p
        p.box(rect,"SELECTED TASK","panel_border","panel")
        item=a.chosen()
        x,y,w=rect.x+2,rect.y+3,rect.w-4
        if not item:
            p.text(y,x,"Nothing selected","panel_dim",w)
            p.text(y+2,x,"a capture · A schedule","accent",w)
            return
        # Inspection is a quiet header action; mutations share one roomy row.
        open_rect = Rect(rect.x+rect.w-10,rect.y+1,8,1)
        p.centered(open_rect.y,open_rect,"Open ↵","accent@panel")
        self.hit(open_rect,"key","\n")
        task=item.task
        color=self.color(item)
        lines=[(line,color) for line in wrap(task.title,w)[:2]]
        lines.append((f"{self.symbol(item)} {task.state.capitalize()}"+(" · overdue" if item.overdue(a.at) else ""),color))
        if task.start:
            end=task.end-timedelta(microseconds=1) if task.all_day else task.end
            lines.append((task.start.strftime("%a %d %b %Y"),"panel"))
            if task.start.date()!=end.date():
                lines.append(("→ "+end.strftime("%a %d %b %Y"),"panel"))
            timing="All day" if task.all_day else f"{task.start:%H:%M}–{task.end:%H:%M}"
            lines.append((timing+"  ("+duration(task.end-task.start)+")","panel_dim"))
        else:
            lines.append(("Inbox · no schedule","panel_dim"))
        lines.append(("Priority  "+task.priority,"orange" if task.priority=="high" else "panel_dim"))
        if task.tags:
            lines.append((" ".join("#"+t for t in task.tags),"purple"))
        if task.repeat:
            lines.append(("↻ "+task.repeat,"panel_dim"))
        if item.ref in getattr(a,"snoozes",{}):
            lines.append(("Snoozed → "+a.snoozes[item.ref][11:16],"orange"))
        if task.notes:
            lines.append(("","panel"))
            lines.extend((line,"panel_dim") for line in wrap(task.notes,w))
        available=max(0,rect.h-8)
        for index,(text,style) in enumerate(lines[:available]):
            if index==available-1 and len(lines)>available:
                text=ellipsis(text+" …",w)
            p.text(y+index,x,text,style,w,bold=index==0)
        for (left,width),(label,key) in zip(tracks(x,w,3,1),(("e Edit","e"),("x Done","x"),("r Move","r"))):
            self.button(Rect(left,rect.y+rect.h-4,width,3),label,"key",key)

    def summary(self, rect):
        a, p = self.a, self.p
        p.box(rect, "THIS " + {"day": "DAY", "week": "WEEK", "month": "MONTH", "year": "YEAR"}.get(a.view, "VIEW"),"panel_border","panel")
        items = a.items
        if a.view in ("day","week","month","year"):
            lo,hi = bounds(a.day,a.view)
            items = [o for o in items if o.overlaps(lo,hi)]
        counts = {state: sum(o.task.state == state for o in items) for state in SYMBOLS}
        for index, (state, color) in enumerate((("pending", "blue"), ("ongoing", "orange"), ("completed", "green"))):
            p.text(rect.y+2+index, rect.x+2, state.capitalize(), color, rect.w-7)
            p.text(rect.y+2+index, rect.x+rect.w-5, str(counts[state]).rjust(3), color, 3)
        overdue = sum(o.overdue(a.at) for o in items)
        p.text(rect.y+5, rect.x+2, f"{overdue} overdue" if overdue else "No overdue tasks", "red" if overdue else "muted", rect.w-4)
        # A simple distribution bar, with no score or percentage.
        x = rect.x+2
        for state, color in (("completed", "green"), ("ongoing", "orange"), ("pending", "blue")):
            length = round((rect.w-4)*counts[state]/max(1,len(items)))
            p.text(rect.y+6, x, "▄"*length, color, rect.x+rect.w-2-x)
            x += length

    def context(self, rect):
        a, p = self.a, self.p
        if a.view == "day":
            lo, hi = bounds(a.day, "day")
            older = [o for o in a.items if not o.overlaps(lo, hi) and o.overdue(a.at)]
            if older:
                p.box(rect, f"EARLIER · {len(older)} OVERDUE","panel_border","panel")
                for index, item in enumerate(older[:max(1,(rect.h-4)//2)]):
                    self.hit(Rect(rect.x+1,rect.y+2+index*2,rect.w-2,2),"task",item.ref)
                    p.text(rect.y+2+index*2, rect.x+2, ellipsis(item.task.title,rect.w-4), "red", rect.w-4)
                    p.text(rect.y+3+index*2, rect.x+2, schedule_text(item.task,full=True), "muted", rect.w-4)
                p.text(rect.y+rect.h-2,rect.x+2,"j/k selects · r reschedules", "muted", rect.w-4)
                return
            p.box(rect, "FREE TIME","panel_border","panel")
            free = [(start,end) for start,end,active in segments(a.items,a.day) if not active]
            for index,(start,end) in enumerate(free[:rect.h-4]):
                end_label = "24:00" if end == hi else end.strftime("%H:%M")
                p.text(rect.y+2+index,rect.x+2,f"{start:%H:%M}–{end_label}  {duration(end-start)}","muted",rect.w-4)
            if not free:
                p.text(rect.y+2,rect.x+2,"No free timed blocks", "muted",rect.w-4)
            return
        p.box(rect, "NEXT UP","panel_border","panel")
        upcoming = [o for o in a.upcoming if o.task.state != "completed" and o.task.start > a.at]
        if not upcoming:
            p.text(rect.y+2,rect.x+2,"No upcoming tasks in 30 days", "muted",rect.w-4)
        for index,item in enumerate(upcoming[:max(1,(rect.h-3)//3)]):
            y = rect.y+2+index*3
            self.hit(Rect(rect.x+1,y,rect.w-2,min(3,rect.y+rect.h-1-y)),"upcoming",item.ref)
            p.text(y,rect.x+2,ellipsis(item.task.title,rect.w-4),self.color(item),rect.w-4)
            p.text(y+1,rect.x+2,f"{item.task.start:%a %d %b %H:%M}","muted",rect.w-4)
            if y+2 < rect.y+rect.h-1:
                p.text(y+2,rect.x+2,"in " + duration(item.task.start-a.at),"muted",rect.w-4)
