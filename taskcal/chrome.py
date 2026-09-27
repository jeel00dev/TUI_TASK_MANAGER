"""Rounded terminal chrome using Kitty images behind ordinary curses text.

Only borders and corner masks are rasterized. Centers stay transparent so cell
highlights, the current-time rule, text selection, and input remain native.
tmux panes use a native, transparent placeholder to position the graphics.
"""
from __future__ import annotations

import base64
import fcntl
import math
import os
import secrets
import struct
import subprocess
import sys
import termios
import zlib
from collections import OrderedDict
from dataclasses import dataclass


def cell_size(fd=1):
    try:
        rows, cols, width, height = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if rows and cols and width >= cols and height >= rows:
            return width // cols, height // rows
    except OSError:
        pass
    return None


def inside_tmux():
    # A new Kitty window can inherit TMUX from its launcher without being a pane.
    if not os.environ.get("TMUX"):
        return False
    try:
        target = ["-t", os.environ["TMUX_PANE"]] if os.environ.get("TMUX_PANE") else []
        result = subprocess.run(["tmux", "display-message", "-p", *target, "#{pane_tty}"],
                                capture_output=True, text=True, timeout=.3)
        return result.returncode != 0 or result.stdout.strip() == os.ttyname(1)
    except (OSError, subprocess.TimeoutExpired):
        return True


def supported():
    return (os.isatty(1) and bool(os.environ.get("KITTY_WINDOW_ID"))
            and not os.environ.get("NO_COLOR")
            and (inside_tmux() or os.environ.get("TERM", "").startswith("xterm-kitty") and bool(cell_size())))


def radius_for(kind, width, height, cell_height):
    """Circular radii use the same non-overlap clamp as CSS border-radius."""
    desired = height / 2 if kind == "pill" else cell_height * {
        "panel": 1.05, "task": .85, "field": .7, "frame": 1.05, "tab": .75,
    }.get(kind, 1.05)
    return min(desired, width / 2, height / 2)


def _chunk(kind, data):
    return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))


def contour(width, height, radius, fill, outer, stroke, weight=1, accent=None,
            accent_height=0, insets=(0, 0)):
    """Return RGBA scanlines: opaque outside masks, AA edges, clear centers.

    Only the narrow edge bands need distance calculations. Interior pixels are
    transparent runs, so large panels cost roughly their perimeter to generate.
    """
    ix, iy = insets
    half_w, half_h = (width-2*ix)/2, (height-2*iy)/2
    radius = max(0, min(radius, half_w, half_h))
    cap = min(width//2, math.ceil(radius + ix + weight + 1))
    transparent = b"\0\0\0\0"

    def pixel(x, y, bottom):
        qx = abs(x+.5-width/2) - (half_w-radius)
        qy = abs(y+.5-height/2) - (half_h-radius)
        distance = math.hypot(max(0, qx), max(0, qy)) + min(max(qx, qy), 0) - radius
        if distance < -weight-.5 and not bottom:
            return transparent
        coverage = max(0., min(1., .5-distance))
        inside = 0 if bottom else max(0., min(1., .5-distance-weight))
        edge = accent if bottom else stroke
        return bytes(round(out*(1-coverage) + ink*(coverage-inside) + bg*inside)
                     for out, ink, bg in zip(outer, edge, fill)) + b"\xff"

    rows, patterns = [], {}
    for y in range(height):
        bottom = accent is not None and y >= height-iy-accent_height
        # The straight middle and both symmetric sides need just one sample.
        # Reuse identical rows but copy them so later occlusion cannot alias.
        key = (min(y, height-1-y, math.ceil(radius+iy+weight+1)), bottom)
        if key not in patterns:
            left = [pixel(x,y,bottom) for x in range(cap)]
            middle = pixel(cap,y,bottom) * (width-2*cap)
            patterns[key] = b"".join(left) + middle + b"".join(reversed(left))
        rows.append(bytearray(patterns[key]))
    return rows


def encode_png(width, height, rows):
    raw = b"".join(b"\0" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 3)) + _chunk(b"IEND", b""))


def command(params, payload=b""):
    return b"\x1b_G" + params.encode("ascii") + b";" + payload + b"\x1b\\"


@dataclass(frozen=True)
class Surface:
    rect: object
    fill: tuple
    outer: tuple
    stroke: tuple
    kind: str
    accent: tuple | None = None
    opaque: bool = True


class Chrome:
    def __init__(self, write=None, metrics=None, transport=None):
        self.write = write or self._write
        self.transport = transport
        self.metrics = metrics or (transport.metrics if transport else cell_size)
        self.size = self.metrics()
        self.surfaces = []
        self.cache = OrderedDict()
        self.placements = set()
        self.next_id = 100000 + (os.getpid() % 100000) * 1024
        self.anchor = secrets.randbelow(0xffffff-1)+1 if transport else None
        self.anchor_bg = (26,26,26)

    def packet(self, data):
        return self.transport.packet(data) if self.transport else data

    @staticmethod
    def _write(data):
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def begin(self):
        size = self.metrics()
        if size and size != self.size:
            self.clear()
            self.size = size
        self.surfaces.clear()

    def add(self, rect, fill, outer, stroke, kind="panel", accent=None, opaque=True):
        self.surfaces.append(Surface(rect, fill, outer, stroke, kind, accent, opaque))

    def _texture(self, surface, following):
        cw, ch = self.size
        rect = surface.rect
        width, height = rect.w*cw, rect.h*ch
        clips = []
        # A dialog or later filled control must cover chrome beneath it, just as
        # it covers the underlying text. Retain the visible parts of that chrome.
        for other in following:
            if not other.opaque:
                continue
            r = other.rect
            x1, y1 = max(rect.x,r.x), max(rect.y,r.y)
            x2, y2 = min(rect.x+rect.w,r.x+r.w), min(rect.y+rect.h,r.y+r.h)
            if x1 < x2 and y1 < y2:
                clips.append(((x1-rect.x)*cw,(y1-rect.y)*ch,(x2-rect.x)*cw,(y2-rect.y)*ch))
        key = (width, height, surface.fill, surface.outer, surface.stroke,
               surface.kind, surface.accent, tuple(clips), cw, ch)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if surface.kind in ("frame", "panel"):
            insets = (cw/2-.5, ch/2-.5)
        elif surface.kind == "tab":
            insets = (0,round(ch*.3))
        elif surface.kind == "field":
            insets = (0,max(2,round(ch*.15)))
        else:
            insets = (0,0)
        radius = radius_for(surface.kind, width-2*insets[0], height-2*insets[1], ch)
        rows = contour(width, height, radius, surface.fill, surface.outer,
                       surface.stroke, max(1, round(ch/20)), surface.accent,
                       max(3, round(ch*.24)) if surface.accent else 0, insets)
        for x1, y1, x2, y2 in clips:
            clear = b"\0" * ((x2-x1)*4)
            for y in range(y1, y2):
                rows[y][x1*4:x2*4] = clear
        payload = base64.b64encode(encode_png(width, height, rows))
        self.next_id += 1
        image_id = self.next_id
        output = bytearray()
        for offset in range(0, len(payload), 4096):
            chunk = payload[offset:offset+4096]
            more = int(offset+4096 < len(payload))
            params = f"a=t,f=100,i={image_id},q=2,m={more}" if not offset else f"m={more},q=2"
            output.extend(command(params, chunk))
        self.cache[key] = (image_id, bytes(output))
        return self.cache[key]

    def render(self):
        if not self.size:
            return
        output = bytearray(b"\x1b7")  # Save the cursor used by native text input.
        if self.anchor:
            # This transparent 1-cell image is ordinary text in tmux's buffer.
            # All chrome is relative to it: hiding/moving the pane hides/moves
            # the graphics as well, without coordinates in the outer terminal.
            output.extend(self.packet(command(f"a=t,f=32,s=1,v=1,i={self.anchor},q=2", b"AAAAAA==")))
            output.extend(self.packet(command(f"a=p,U=1,i={self.anchor},p=1,c=1,r=1,q=2")))
            red, green, blue = (self.anchor >> 16) & 255, (self.anchor >> 8) & 255, self.anchor & 255
            bg = ";".join(map(str,self.anchor_bg))
            output.extend(f"\x1b[1;1H\x1b[38;2;{red};{green};{blue};48;2;{bg}m\U0010eeee\u0305\u0305\x1b[0m".encode())
        # Curses may erase stored images when it clears a screen on resize.
        # Re-send each cached PNG once per frame; shared shapes reuse that upload.
        placements, uploaded = set(), set()
        for index, surface in enumerate(self.surfaces, 1):
            image_id, transmission = self._texture(surface, self.surfaces[index:])
            if image_id not in uploaded:
                output.extend(self.packet(transmission))
                uploaded.add(image_id)
            rect = surface.rect
            if self.anchor:
                position = f",P={self.anchor},Q=1,H={rect.x},V={rect.y}"
            else:
                output.extend(f"\x1b[{rect.y+1};{rect.x+1}H".encode("ascii"))
                position = ""
            output.extend(self.packet(command(f"a=p,i={image_id},p={index},q=2,C=1,z=-1{position}")))
            placements.add((image_id,index))
        for image_id, placement in self.placements-placements:
            output.extend(self.packet(command(f"a=d,d=i,i={image_id},p={placement},q=2")))
        self.placements = placements
        # Bound terminal image memory during long sessions / repeated resizing.
        used = {image_id for image_id,_ in placements}
        for key, (image_id, _) in list(self.cache.items()):
            if len(self.cache) <= 128:
                break
            if image_id not in used:
                output.extend(self.packet(command(f"a=d,d=I,i={image_id},q=2")))
                del self.cache[key]
        output.extend(b"\x1b8")
        self.write(bytes(output))

    def clear(self):
        if self.cache:
            self.write(self.packet(b"".join(command(f"a=d,d=I,i={image_id},q=2") for image_id, _ in self.cache.values())))
        self.cache.clear()
        self.placements.clear()
        self.surfaces.clear()

    def close(self):
        self.clear()
        if self.transport:
            self.write(self.packet(command(f"a=d,d=I,i={self.anchor},q=2")))
            self.transport.close()
