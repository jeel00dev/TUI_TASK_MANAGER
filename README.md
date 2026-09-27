# Task Calendar

A visual calendar inside your terminal: time blocks, day columns, continuous span
bars, and a live details sidebar. Built for Kitty, i3, keyboard navigation, and mouse input.

A small, local task calendar for the terminal. Python + curses + SQLite, with no
third-party Python dependencies. Independent desktop reminders run while the TUI
is closed. Nothing connects to the internet.

## Run

```sh
./task                 # run from this checkout
./task install         # install `task` and enable session reminders
task                   # launch from any directory
```

Requires Python 3.10+ with curses and SQLite. Installation copies the application
to `~/.local/share/task-calendar/app` and creates `~/.local/bin/task`. Keep
`~/.local/bin` in your PATH. Run `./task install` again after editing the source.
It refuses to overwrite another program's `~/.local/bin/task`.

No package manager or network access is needed to install the application.
`pip install .` is also supported if you already use a Python environment.

### Desktop reminders on Void + i3

Desktop reminders require `notify-send` (libnotify), a notification daemon, and
your normal desktop D-Bus session. For example:

```sh
sudo xbps-install -S libnotify dunst
task install --with-dunst
task doctor
task reminders --test
```

`task install` starts the reminder process now and writes
`~/.config/autostart/task-calendar-reminders.desktop`. An i3 configuration with
`exec --no-startup-id dex --autostart --environment i3` loads this at login.
If the i3 config exists but `dex` is missing, installation instead adds one
`include` for `~/.config/task-calendar/i3-startup.conf`, which starts the same
services directly. This is the setup used on this machine.

For an i3 setup without XDG autostart, add this line instead:

```i3
exec --no-startup-id ~/.local/bin/task reminders
```

If Dunst is not activated automatically by D-Bus, start `dunst` in your desktop
session, and add `exec --no-startup-id dunst` to i3. Reminders inherit the session's
display and D-Bus environment. Do not run them as root or as a system service.
They work independently of Kitty, tmux, or the task TUI. No systemd dependency.

`--with-dunst` also adds a small Dunst autostart entry and starts it now.
Use this when D-Bus activation lacks the session's display environment. Omit the
flag if you already run a different notification daemon.

`task reminders --start` starts a detached process; `task reminders` stays in the
foreground for a session supervisor such as runit. A process lock prevents two
reminder processes using the same database. `task doctor` reports its status.
Detached logs are in `~/.local/state/task-calendar/reminders.log`.

## Everyday keys

| Key | Action |
| --- | --- |
| `d` / `w` / `m` / `y` | Day / week / month / year |
| `t` | Today, including overdue work from earlier dates |
| `h` / `l` | Previous / next calendar range; in Year, previous / next year |
| `[` / `]` or ← / → | Previous / next date; `d` opens that date |
| ↑ / ↓ | Select a task; in month/year view, move by a week |
| `g` | Go to a date |
| `j` / `k` | Select tasks |
| Page Up / Page Down | Scroll time or the agenda; in Year, previous / next month |
| `+` / `-` | Zoom the time grid: 6, 10, 16, or 24 hours |
| `v` | Toggle the full agenda for the visible calendar range |
| `b` | Show or hide the sidebar |
| `a` | Quick capture: type a title and Enter to save to Inbox |
| `A` | Add a scheduled task on the selected date |
| `e` / `E` | Edit this task or occurrence / edit its recurring series |
| `s` / `x` / `p` | Ongoing / completed / pending |
| `r` | Reschedule while keeping the duration |
| `z` | Snooze once: 5, 10, 15, 30, or 60 minutes |
| Enter | Inspect schedule, notes, recurrence, and state |
| `i` / `H` | Inbox / completed history |
| `/` / `f` | Search all tasks / filter the current view |
| `D` / `u` | Delete this task or occurrence / undo |
| `X` | Delete the entire recurring series; `u` restores it |
| `?` or `:` | Searchable command menu; Enter runs the selected action |
| Esc / `q` | Clear filter or return / quit |

In a form, Tab or arrows change fields and **Ctrl-S saves**. Enter on the title
of a new `a` capture saves immediately; elsewhere Enter advances through the form.
Ctrl-U clears a field. Space cycles state, priority, and recurrence presets; you
can also type a value directly. Esc cancels without saving. Notes accept `\n` for
line breaks. The selected-task inspector also offers edit, state, reschedule, and
snooze actions.

## Calendar behavior

- **Week:** seven day columns with timed task blocks. The default viewport is
  08:00–24:00; Page Up/Down moves through time, and `+`/`-` changes the scale.
  The current day has a subtle charcoal background. A red dotted time rule
  refreshes on each minute, including while the application is idle.
  It has a reserved row across the entire grid, passing over task blocks and
  column dividers without covering task titles or times.
  Exact times remain in each block and the details panel.
- **Day:** a larger time grid, concurrent tasks in adjacent columns, and exact
  free periods in the gaps. All-day spans occupy a separate strip. Earlier
  overdue work is called out above the grid and in the sidebar.
- **Month:** a full calendar grid. Long tasks use continuous bars across dates
  and continuation arrows across weeks/months. Small task counts show busy dates.
  Arrows select dates; `d` opens the focused day and `A` schedules work there.
- **Year (`y`):** all 12 months in one view. Scheduled dates use task colors;
  selecting a long task highlights its dates across months. `h`/`l` changes years,
  Page Up/Down changes months, and arrows select dates. Click a month heading to
  select its first day; double-click opens Month. Click a date to select it;
  double-click opens Day. `A` schedules work on the selected date, including tasks
  lasting several months or crossing years. Set date-only Start and End fields
  for an inclusive range. `v` opens the year's full task list, with the same
  editing, filtering, completion and undo actions as other views. Smaller windows
  show 12 compact month cards; `m` opens the selected month for its dates.
- **Sidebar:** mini calendar, selected task, simple state counts, and upcoming
  work. Day view uses the final panel for older overdue tasks or free time.
  All panels reflect the same data and selection. Enter opens complete details.
- **Inbox, history, and search:** use the same colors and panels, with task rows
  and their schedules. `/` searches all tasks; `f` filters the current view.
- Completed work remains visible with a checkmark and quieter text. Overdue is
  derived from the end time of an unfinished task, never stored as a state.
- Completed tasks move out of ordinary calendars 30 days after completion. `H`
  and search retain the full history. Archiving never deletes records.

**Crowded schedules:** overlapping time blocks occupy separate columns. When
there are too many for the available width, a visible overflow count appears;
`j`/`k` brings each selected task into view. `v` always shows the full agenda.
Month cells similarly reveal selected tasks hidden by an overflow count. Long
spans remain one task in storage, regardless of how many dates they touch.

**Terminal sizes:** at least **90 columns × 28 rows**. Below this, the app shows
required and current dimensions, suspends hidden controls, and preserves editor
drafts. At 132 columns and 40 rows the sidebar becomes available; at about
160×48 the full week and sidebar fit comfortably. Narrow calendars show three
days around the focused date, with arrow keys to pan. `b` toggles the sidebar.
Year view aligns date rows across neighboring month cards, including clickable space
around the dates. It hides the sidebar when that makes room for 12 complete mini calendars,
then switches to compact month cards if needed. Month view reduces the number of
visible task rows as space decreases. `v` shows
the full agenda and Enter opens complete details at every supported size.

The theme follows the supplied **ZCode** screenshot: #171717 workspace,
#262626 panels, #313131 selections, subtle gray borders, and blue active controls.
In Kitty, including inside tmux, panels and task cards have smooth circular corners;
tabs have equal widths and rounded rectangles; small buttons have capsule ends.
Radii scale with the terminal's cell
size: about 18 pixels for panels, 14 for tasks and 12 for fields at a 17-pixel
cell height. Fills meet the thin outlines, and tasks have a thicker colored base.
Kitty draws these locally generated borders behind ordinary terminal text; mouse
input, text selection, and the live time rule stay native. No font or graphics
packages are required. Other terminals retain character-based borders. Inside tmux
the app enables
graphics passthrough for its own pane while running, then restores that pane
option on exit. A native text anchor keeps the graphics attached to the pane
when switching windows, moving splits, and zooming. Run `task` normally; no
separate Kitty window or tmux configuration change is needed.
Task fills are saturated, with lighter outlines and labels for contrast.
Tasks use blue pending work, orange
ongoing work, quieter green completed work, and red overdue work. Long pending
spans use purple; low-priority work uses a warm neutral. Exact RGB values are
used and restored on programmable-color terminals, with a nearest-color fallback.
`NO_COLOR=1 task` uses symbols and monochrome selection instead.

Previews: [week](docs/week.png), [day](docs/day.png), [month](docs/month.png),
[year](docs/year.png), [compact year](docs/year-compact.png),
[editor](docs/editor.png), [compact window](docs/compact.png), and
[minimum-size message](docs/minimum-size.png).

The [design research](docs/design-research.md) records primary sources, measured
colors, layout decisions, and terminal limits. ZCode's site uses Geist Sans and
Geist Mono. A TUI inherits its terminal's fixed-width font: it cannot render the
proportional Sans UI. Smooth radii use Kitty graphics, with a character fallback
elsewhere. The app uses the font of your existing Kitty window, including in
tmux. You can choose Geist Mono in Kitty's font settings if it is installed;
the application does not change your terminal configuration.

### Mouse

- Click view tabs, previous/next range controls, Today, Search, Filter, and actions.
  Today is a jump to the current Day, not a separate view.
- Click a task to select it; double-click to open full details.
- Click a calendar date to focus it; double-click to open its Day.
- Use the mini-calendar arrows to change months. Today's date is circled; the
  selected date has its own background highlight.
- Scroll the wheel over a timeline to move by an hour; over a month to move by a
  week; over Year to move by a month; over a list to scroll tasks. Editors and
  inspectors scroll independently.
- Click editor fields to focus them. Clicking State, Priority, or Repeat cycles
  the available choices. Save, Cancel, dialog close, and command entries are clickable.

For mouse input inside tmux, enable forwarding in `~/.tmux.conf`:

```tmux
set -g mouse on
```

Kitty's Shift-selection remains available for copying terminal text. Keyboard
shortcuts continue to work without mouse support.

Changes made through another terminal are detected while the TUI is idle, usually
within half a second. Forms retain your draft until you save or cancel.

To review the interface without adding fake tasks to your personal database:

The CLI supports `task list --view year --date 2028-01-01`.

```sh
python3 tools/preview.py
```

That developer preview uses a disposable database and a fixed date. It does not
start reminder delivery or alter your real tasks.

Screenshots captured in Kitty with that disposable calendar:
[week](docs/week.png), [day](docs/day.png), [month](docs/month.png),
[task editor](docs/editor.png).

## Dates, durations, and recurrence

Times are **local wall-clock times**, in 24-hour format:

```text
today 17:00
tomorrow 09:00
2026-10-04 17:00
17:00                  # uses the selected day in the TUI
2026-10-04             # all-day task
```

End is optional: timed tasks default to one hour; date-only tasks to one day.
Date-only end dates are inclusive: October 4 → October 10 includes all of October
10. Internally intervals are half-open, so a task ending at midnight does not
occupy the following day. A time-only end earlier than the start crosses midnight.
Blank start and end keep a task in Inbox. Overlap is always allowed.

Reschedule accepts `tomorrow`, `+1h`, `+1d`, `+1w`, or a new date/time. Relative
offsets shift the existing start. A date keeps the existing time and duration.
Scheduling an Inbox item this way defaults to 09:00 and one hour.

Recurrence supports `daily`, `weekly`, `monthly`, `weekdays`, and selected weekdays
such as `mon,wed,fri`. Weekly uses the original start's weekday. Monthly keeps the
day of the month and skips months without that day. Each occurrence preserves the
original wall-clock start and duration across local timezone/DST changes.

`e`, `s`, `x`, `p`, `r`, and `D` affect **one occurrence**. `E` edits the series.
Explicitly edited/completed/moved occurrences keep their schedule and state when
the series schedule changes. Removing recurrence preserves these exceptions as
standalone tasks, including completed history. All these edits can be undone.
The CLI uses `ID@YYYY-MM-DD` for a recurring occurrence; the date stays tied to
the original occurrence even after it is moved.

## Search and filters

Search matches titles, notes, tags, and scheduled dates. Titles also support
subsequence matching. Filters can be combined with ordinary text:

```text
postgres
#backend
state:ongoing
state:overdue priority:high
#interview from:2026-10-01 to:2026-10-15
on:2026-10-04
```

Search includes every standalone task and every saved occurrence exception,
including archived history. Unmodified recurring occurrences are expanded from
one year ago to one year ahead for general search. `on:`, or a `from:` / `to:` pair,
can search recurrence in any year. A single `from:` or `to:` expands a year on
either side of that date. Calendar navigation has no such search horizon.

## CLI examples

```sh
task add "Learn Redis persistence"
task add "Do 5 DSA questions" --start "today 17:00" --end "19:00" \
  --priority high --tags "dsa interview" --repeat daily
task add "Prepare backend project" --start "2026-10-04" --end "2026-10-10"
task list --view week
task list --view inbox
task list --search "#backend"
task list --filter "state:overdue"
task show 3
task start 3
task done 2@2026-09-26
task move 3 tomorrow
task edit 3 --notes "Focus on SQL and operating systems."
task edit 2 --series --repeat mon,wed,fri
task snooze 3 10
task delete 3
task undo
```

`task --help` lists commands. `task --db /path/to/tasks.sqlite3 …` uses an isolated
database, useful during development. There is no import/export interface.

## Reminder behavior

- One reminder 15 minutes before a task, and one at its start.
- Creating or rescheduling inside the 15-minute window skips the old upcoming
  reminder. Immediate starts may notify within a 90-second grace period.
- Completion, deletion, and rescheduling are read from the same SQLite database
  each tick. No copied schedules. Notifications never change task state.
- Every recurrence has its own reminders. A long task only notifies at its
  actual beginning, not every day it remains active.
- Simultaneous reminders are grouped in batches of up to five, including every
  title. Snooze is explicit and sends one extra reminder.
- Checks run every 10 seconds. A start reminder can therefore arrive up to about
  10 seconds after its scheduled time under normal conditions.
- Successful deliveries are recorded across restarts. Failed deliveries retry
  during the 90-second grace window. Older missed events are skipped after sleep
  or a stopped daemon, avoiding a burst of stale notifications on resume.
- Desktop notification actions are intentionally omitted; use the TUI or CLI
  for Start, Complete, and Snooze. Presentation and timeout follow your desktop
  notification daemon's rules.

The process must be running in a logged-in desktop session. It cannot display
notifications while the machine is off or suspended. SQLite cannot atomically
commit with a desktop notification service: a crash between sending a bubble and
recording delivery can cause that event to repeat once within the grace window.

## Storage and maintenance

The database lives at `~/.local/share/task-calendar/tasks.sqlite3`. Standard
`XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME` overrides are respected.
The database is user-readable only. WAL mode and transactions allow the CLI,
TUI, and reminder process to share it safely. The last 100 user changes can be
undone, including after restarting the app. Notification delivery history is
separate, so undo does not replay already delivered reminders.

Source modules separate calendar rules, storage, search, reminders, terminal UI,
and CLI integration. There are no accounts, web services, telemetry, subtasks,
projects, plugins, or background network requests.

```sh
python3 -m unittest discover -s tests -v
```

Desktop integration follows the [freedesktop notification protocol](https://specifications.freedesktop.org/notification/latest/protocol.html)
and [i3 startup behavior](https://i3wm.org/docs/userguide.html#_automatically_starting_applications_on_i3_startup).
