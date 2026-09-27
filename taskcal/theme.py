"""ZCode-inspired dark surfaces, with exact RGB on programmable-color terminals."""
from __future__ import annotations

import curses
import os

# Neutral surfaces measured from the supplied ZCode screenshot. Semantic hues
# follow ZCode's published dark theme; see docs/design-research.md.
PALETTE = {
    "red": "#ff5c5c", "green": "#46bf72", "blue": "#4099ff",
    "orange": "#ff8a30", "white": "#e5e5e5", "brown": "#d5b387",
    "purple": "#a888f2", "cyan": "#0ea5e9", "bg": "#171717",
    "bg2": "#1a1a1a", "bg3": "#313131", "bg4": "#363636",
    "bg5": "#404040", "quartz": "#f8f8f8", "comment": "#999999",
    "line_nr": "#303030", "selection": "#313131", "match": "#542500",
    "cursor_line": "#202020", "visual": "#202020", "border": "#3b3b3b",
    "float_bg": "#262626", "statusline_bg": "#1a1a1a",
}


def rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def tint(value, amount, base="#262626"):
    return "#" + "".join(f"{round(b + (c-b)*amount):02x}" for c,b in zip(rgb(value),rgb(base)))


class Theme:
    def __init__(self):
        self.styles = {}
        self.originals = {}
        self.colors = {}

    def install(self):
        if not curses.has_colors() or os.environ.get("NO_COLOR"):
            return
        curses.start_color()
        curses.use_default_colors()
        values = dict(PALETTE)
        for name in ("blue", "orange", "green", "red", "purple", "brown"):
            values[name + "_fill"] = tint(values[name], .38)
            values[name + "_selected"] = tint(values[name], .50)
            # Stronger fills need lighter colored labels and outlines to keep
            # times, span titles, and selection readable on every task hue.
            values[name + "_ink"] = tint(values[name], .50, PALETTE["quartz"])
            values[name + "_selected_ink"] = tint(values[name], .30, PALETTE["quartz"])
        values["completed_text"] = tint(PALETTE["green"], .18, PALETTE["white"])
        mapped = {}
        for value in dict.fromkeys(values.values()):
            components = rgb(value)
            if curses.can_change_color() and curses.COLORS >= 256:
                index = 64 + len(mapped)
                self.originals[index] = curses.color_content(index)
                curses.init_color(index, *(round(c * 1000 / 255) for c in components))
            else:
                candidates = range(16, curses.COLORS) if curses.COLORS >= 256 else range(curses.COLORS)
                index = min(candidates, key=lambda n: sum((a - b * 255 / 1000) ** 2 for a, b in zip(components, curses.color_content(n))))
            mapped[value] = index
        specs = {
            "plain": ("white", "bg"), "heading": ("quartz", "bg"),
            "muted": ("comment", "bg"), "dim": ("comment", "bg"),
            "border": ("border", "bg"), "grid": ("line_nr", "bg"),
            "accent": ("cyan", "bg"), "pending": ("blue", "bg"),
            "ongoing": ("orange", "bg"), "completed": ("green", "bg"),
            "overdue": ("red", "bg"), "span": ("purple", "bg"),
            "tab": ("comment", "statusline_bg"), "active_tab": ("quartz", "selection"),
            "active_tab_border": ("cyan", "selection"),
            "status": ("white", "statusline_bg"), "status_dim": ("comment", "statusline_bg"),
            "selected": ("quartz", "selection"), "selected_day": ("blue", "blue_fill"),
            "today_grid": ("line_nr", "cursor_line"), "today": ("cyan", "cursor_line"),
            "today_now": ("red", "cursor_line"),
            "field": ("white", "float_bg"), "field_focus": ("quartz", "bg3"),
            "field_border": ("line_nr", "float_bg"), "field_active": ("cyan", "bg3"),
            "panel": ("white", "float_bg"), "panel_dim": ("comment", "float_bg"),
            "panel_border": ("border", "float_bg"), "panel_title": ("quartz", "float_bg"),
            "button": ("white", "bg3"), "primary": ("quartz", "blue_selected"),
            "button_border": ("border", "bg3"),
        }
        for name in ("blue", "orange", "green", "red", "purple", "brown"):
            specs[name] = (name, "bg")
            for suffix in ("fill", "selected"):
                specs[f"{name}_{suffix}"] = ("quartz" if suffix == "selected" else "white", f"{name}_{suffix}")
                ink = name + ("_selected_ink" if suffix == "selected" else "_ink")
                specs[f"{name}_{suffix}_edge"] = (ink, f"{name}_{suffix}")
                specs[f"{name}_{suffix}_now"] = ("red", f"{name}_{suffix}")
        specs["green_fill"] = ("completed_text", "green_fill")
        for name,(fg,bg) in list(specs.items()):
            if bg == "bg":
                specs[name + "@panel"] = (fg, "float_bg")
        for index, (name, (fg, bg)) in enumerate(specs.items(), 1):
            if index >= curses.COLOR_PAIRS:
                break
            curses.init_pair(index, mapped[values[fg]], mapped[values[bg]])
            self.styles[name] = curses.color_pair(index)
            self.colors[name] = (rgb(values[fg]), rgb(values[bg]))

    def attr(self, name="plain", bold=False):
        attr = self.styles.get(name, 0)
        if bold or name in ("heading", "panel_title", "active_tab"):
            attr |= curses.A_BOLD
        if not self.styles:
            if name in ("dim", "muted", "grid", "panel_dim", "status_dim"):
                attr |= curses.A_DIM
            elif name in ("selected", "active_tab", "active_tab_border", "field_focus", "field_active") or name.endswith(("_selected", "_selected_edge", "_selected_now")):
                attr |= curses.A_REVERSE
        return attr

    def restore(self):
        for index, value in self.originals.items():
            curses.init_color(index, *value)
        self.originals.clear()
