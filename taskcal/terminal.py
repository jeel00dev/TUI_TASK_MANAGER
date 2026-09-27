"""Pane-local transport for Kitty graphics through tmux."""
from __future__ import annotations

import os
import subprocess


def tmux(*args):
    result = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=.5)
    if result.returncode:
        raise OSError(result.stderr.strip() or "tmux did not respond")
    return result.stdout.strip()


class TmuxTransport:
    """Use native placeholder text as an anchor; tmux owns its screen position.

    No client/pane offsets, polling, global configuration, or redraw hooks are
    needed. Kitty derives image visibility and location from the anchor.
    """
    def __init__(self):
        self.pane = os.environ["TMUX_PANE"]
        self.previous = tmux("show-options", "-pqv", "-t", self.pane, "allow-passthrough")
        self.changed = self.previous != "on"
        if self.changed:
            tmux("set-option", "-p", "-t", self.pane, "allow-passthrough", "on")

    @staticmethod
    def packet(data):
        return b"\x1bPtmux;" + data.replace(b"\x1b", b"\x1b\x1b") + b"\x1b\\"

    def metrics(self):
        try:
            parts = tmux("display-message", "-p", "-t", self.pane,
                         "#{window_cell_width} #{window_cell_height}").split()
            width, height = map(int, parts)
            return (width, height) if width > 0 and height > 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    def close(self):
        if not self.changed:
            return
        try:
            # Do not override an option the user changed while the app was open.
            if tmux("show-options", "-pqv", "-t", self.pane, "allow-passthrough") == "on":
                if self.previous:
                    tmux("set-option", "-p", "-t", self.pane, "allow-passthrough", self.previous)
                else:
                    tmux("set-option", "-pu", "-t", self.pane, "allow-passthrough")
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.changed = False
