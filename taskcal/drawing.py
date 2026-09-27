"""Clipped cell drawing used by every calendar, panel, and dialog."""
from __future__ import annotations

import curses
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass


def clean(text):
    return "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(text))


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in "WF" else 1) for c in text)


def clip(text, width):
    result, used = [], 0
    for char in clean(text):
        size = cell_width(char)
        if used + size > width:
            break
        result.append(char)
        used += size
    return "".join(result)


def ellipsis(text, width):
    text = clean(text)
    return text if cell_width(text) <= width else clip(text, max(0, width - 1)) + ("…" if width else "")


def wrap(text, width):
    width = max(1, width)
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in clean(paragraph).split():
            if line and cell_width(line + " " + word) > width:
                lines.append(line)
                line = ""
            while cell_width(word) > width:
                if line:
                    lines.append(line)
                    line = ""
                part = clip(word, width)
                if not part:
                    part = word[0]
                lines.append(part)
                word = word[len(part):]
            line = (line + " " + word).strip()
        lines.append(line)
    return lines


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def inset(self, amount=1):
        return Rect(self.x + amount, self.y + amount, max(0, self.w - 2 * amount), max(0, self.h - 2 * amount))

    def contains(self, x, y):
        return self.x <= x < self.x+self.w and self.y <= y < self.y+self.h


class Painter:
    def __init__(self, screen, theme):
        self.screen, self.theme = screen, theme
        self.surface = None
        self.limit = None
        self.cells = {}
        self.track = True
        self.chrome = None

    def setup(self):
        from .chrome import Chrome, supported
        if self.theme.colors and supported():
            self.chrome = Chrome()

    def begin(self):
        if self.chrome:
            self.chrome.begin()

    def refresh(self):
        if self.chrome:
            self.chrome.write(b"\x1b[?2026h")
        try:
            self.screen.refresh()
            if self.chrome:
                self.chrome.render()
        finally:
            if self.chrome:
                self.chrome.write(b"\x1b[?2026l")

    def close(self):
        if self.chrome:
            self.chrome.close()

    def background(self, rect):
        style = self.cells.get((rect.x, rect.y), (" ", "plain"))[1]
        return self.theme.colors.get(style, ((229,229,229), (23,23,23)))[1]

    def rounded(self, rect, fill, style, kind="panel", outer=None, accent=None, opaque=True):
        if not self.chrome:
            return
        colors = self.theme.colors
        parent = outer if outer is not None else self.background(rect)
        self.chrome.add(rect, colors[fill][1], parent, colors[style][0], kind,
                        colors[accent][0] if accent else None, opaque)

    def pill(self, rect, style="button", parent=None):
        outer = self.background(rect) if parent is None else self.theme.colors.get(parent, (None,None))[1]
        self.fill(rect, style)
        edge = "active_tab_border" if style == "active_tab" else "button_border"
        self.rounded(rect, style, edge, "pill", outer)

    @contextmanager
    def within(self, rect, surface=None):
        previous, old_surface = self.limit, self.surface
        if previous:
            x, y = max(rect.x,previous.x), max(rect.y,previous.y)
            rect = Rect(x,y,max(0,min(rect.x+rect.w,previous.x+previous.w)-x),max(0,min(rect.y+rect.h,previous.y+previous.h)-y))
        self.limit = rect
        if surface:
            self.surface = surface
        try:
            yield
        finally:
            self.limit, self.surface = previous, old_surface

    def text(self, y, x, text, style="plain", width=None, bold=False):
        height, columns = self.screen.getmaxyx()
        if self.limit and not self.limit.contains(x, y):
            return
        if not 0 <= y < height or not 0 <= x < columns - 1:
            return
        size = min(columns - x - 1, width if width is not None else columns)
        if self.limit:
            size = min(size, self.limit.x+self.limit.w-x)
        if size <= 0:
            return
        try:
            if self.surface == "panel" and style+"@panel" in self.theme.styles:
                style += "@panel"
            value = clip(text, size)
            self.screen.addstr(y, x, value, self.theme.attr(style, bold))
            if self.track:
                column = x
                for char in value:
                    for offset in range(cell_width(char)):
                        self.cells[(column+offset,y)] = (char,style)
                    column += cell_width(char)
        except curses.error:
            pass

    def fill(self, rect, style="plain", char=" "):
        for y in range(rect.y, rect.y + rect.h):
            self.text(y, rect.x, char * max(0, rect.w), style, rect.w)

    def hline(self, y, x, width, style="grid", char="─"):
        self.text(y, x, char * max(0, width), style, width)

    def vline(self, x, y, height, style="grid", char="│"):
        for row in range(y, y + height):
            self.text(row, x, char, style, 1)

    def box(self, rect, title="", style="border", fill=None, edge_aligned=None, parent=None):
        if rect.w < 2 or rect.h < 2:
            return
        if edge_aligned is None:
            edge_aligned = fill is not None
        if self.chrome:
            outer = self.background(rect) if parent is None else self.theme.colors[parent][1]
            kind = ("task" if style.endswith("_edge") else "field" if style.startswith("field")
                    else "pill" if fill in ("button", "active_tab") else "panel" if fill else "frame")
            self.fill(rect, fill or "plain")
            accent = style.split("_",1)[0] if kind == "task" else None
            self.rounded(rect, fill or "plain", style, kind, outer, accent, bool(fill))
            if title:
                self.text(rect.y+1, rect.x+2, ellipsis(title,rect.w-4), "panel_title" if fill == "panel" else "heading",rect.w-4)
            return
        if fill:
            self.fill(rect.inset(), fill)
        # Eighth-block borders sit at the outside of their cells, allowing a
        # colored background to meet the stroke without spilling past it.
        # Use them for every filled control; unfilled grids keep their shared
        # center-stroke junctions. Border and fill styles must share a background.
        top, bottom, left, right = ("▔", "▂" if style.endswith("_edge") else "▁", "▏", "▕") if edge_aligned else ("─", "─", "│", "│")
        corners = ("🭽", "🭾", "🭼", "🭿") if edge_aligned else ("╭", "╮", "╰", "╯")
        self.hline(rect.y, rect.x + 1, rect.w - 2, style, top)
        self.hline(rect.y + rect.h - 1, rect.x + 1, rect.w - 2, style, bottom)
        self.vline(rect.x, rect.y + 1, rect.h - 2, style, left)
        self.vline(rect.x + rect.w - 1, rect.y + 1, rect.h - 2, style, right)
        for y, x, char in ((rect.y, rect.x, corners[0]), (rect.y, rect.x + rect.w-1, corners[1]), (rect.y+rect.h-1, rect.x, corners[2]), (rect.y+rect.h-1, rect.x+rect.w-1, corners[3])):
            self.text(y, x, char, style, 1)
        if title:
            self.text(rect.y+1, rect.x + 2, ellipsis(title, rect.w - 4), "panel_title" if fill == "panel" else "heading", rect.w - 4)

    def centered(self, y, rect, text, style="plain"):
        text = clip(text, rect.w)
        self.text(y, rect.x + max(0, (rect.w - cell_width(text)) // 2), text, style, rect.w)
