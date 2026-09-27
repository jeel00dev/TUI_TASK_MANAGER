"""User-local installation and desktop session integration."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .notifier import running


def app_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "task-calendar"


def start_reminders(store) -> bool:
    if running(store):
        return False
    logdir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "task-calendar"
    logdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    logpath = logdir / "reminders.log"
    if logpath.exists() and logpath.stat().st_size > 1_000_000:
        logpath.replace(logdir / "reminders.log.1")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    with logpath.open("a") as log:
        subprocess.Popen([sys.executable, "-m", "taskcal", "--db", str(store.path.resolve()), "reminders"], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=env, cwd="/")
    return True


def install(no_autostart: bool = False, with_dunst: bool = False) -> list[str]:
    if with_dunst and not shutil.which("dunst"):
        raise ValueError("Dunst is not installed. Install it with sudo xbps-install -S dunst.")
    source = Path(__file__).resolve().parent
    destination = app_home() / "app/taskcal"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if source != destination.resolve():
        for path in source.glob("*.py"):
            shutil.copy2(path, destination / path.name)
    bindir = Path.home() / ".local/bin"
    bindir.mkdir(parents=True, exist_ok=True)
    launcher = bindir / "task"
    marker = "# Task Calendar launcher"
    if launcher.exists() and marker not in launcher.read_text(errors="replace"):
        raise ValueError(f"{launcher} already exists and belongs to another program; it was left unchanged.")
    launcher.write_text(f"#!/usr/bin/env python3\n{marker}\nimport sys\nsys.path.insert(0, {str(destination.parent)!r})\nfrom taskcal.cli import main\nsys.exit(main())\n")
    launcher.chmod(0o755)
    messages = [f"Installed {launcher}"]
    if not no_autostart:
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
        config.mkdir(parents=True, exist_ok=True)
        desktop = config / "task-calendar-reminders.desktop"
        escaped = str(launcher).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Task Calendar reminders\nComment=Local task reminders, independent of the terminal UI\nExec="' + escaped + '" reminders\nTerminal=false\nStartupNotify=false\n')
        messages.append(f"Autostart: {desktop}")
        if with_dunst:
            dunst = config / "task-calendar-dunst.desktop"
            dunst.write_text('[Desktop Entry]\nType=Application\nName=Dunst notification daemon\nComment=Desktop notifications for the session\nExec=dunst\nTryExec=dunst\nTerminal=false\nStartupNotify=false\n')
            messages.append(f"Notification daemon autostart: {dunst}")
        # Minimal i3 installations often retain a default dex line without dex.
        # In that case, launch directly through one managed include file.
        config_root = config.parent
        i3_config = config_root / "i3/config"
        if not i3_config.exists():
            i3_config = Path.home() / ".i3/config"
        if i3_config.exists() and not shutil.which("dex"):
            startup = config_root / "task-calendar/i3-startup.conf"
            startup.parent.mkdir(parents=True, exist_ok=True)
            text = "# Local task calendar session services\n"
            if (config / "task-calendar-dunst.desktop").exists():
                text += "exec --no-startup-id dunst\n"
            text += f"exec --no-startup-id {shlex.quote(str(launcher))} reminders\n"
            startup.write_text(text)
            include = 'include "' + str(startup).replace('"', '\\"') + '"'
            existing = i3_config.read_text()
            if include not in existing.splitlines():
                i3_config.write_text(existing.rstrip() + "\n\n# Task Calendar: local reminders at login\n" + include + "\n")
            messages.append(f"i3 startup: {startup}")
    if str(bindir) not in os.environ.get("PATH", "").split(os.pathsep):
        messages.append('Add ~/.local/bin to PATH: export PATH="$HOME/.local/bin:$PATH"')
    return messages


def start_dunst():
    """Start in the desktop environment, where DISPLAY is available."""
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "task-calendar"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "notification-daemon.log").open("a") as log:
        subprocess.Popen(["dunst"], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def doctor(store) -> list[str]:
    result = [f"Database: {store.path}", f"SQLite integrity: {store.db.execute('PRAGMA quick_check').fetchone()[0]}", "Reminder process: " + ("running" if running(store) else "stopped"), "notify-send: " + (shutil.which("notify-send") or "missing; install libnotify")]
    command = shutil.which("gdbus")
    if command:
        try:
            output = subprocess.run([command, "call", "--session", "--dest", "org.freedesktop.Notifications", "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.GetServerInformation"], capture_output=True, text=True, timeout=5, check=True)
            result.append("Notification server: " + output.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            result.append("Notification server: unavailable in this session; start a desktop notification daemon (for example dunst).")
    else:
        result.append("Notification server: not probed (gdbus unavailable). Use task reminders --test.")
    autostart = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/task-calendar-reminders.desktop"
    startup = autostart.parent.parent / "task-calendar/i3-startup.conf"
    result.append("Session autostart: " + (str(startup) if startup.exists() else (str(autostart) if autostart.exists() else "not installed; task install enables it")))
    return result
