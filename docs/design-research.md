# Calendar UI redesign: ZCode reference

Research checked 27 September 2026. The supplied screenshot is the dark desktop
interface also shown on the [official ZCode site](https://zcode.z.ai/en).
The application remains a local curses program; these sources were consulted
while developing it, and are not runtime dependencies.

## Visual evidence

The screenshot itself provides the target surface colors. Sampling flat interior
areas gives workspace **#171717**, left navigation **#1a1a1a**, raised panels
**#262626**, selected navigation **#313131**, borders **#3b3b3b**, and primary
text **#e5e5e5**. These are opaque colors in the terminal.

[ZCode's published CSS](https://github.com/zai-org/ZCode/blob/main/packages/ui/src/styles.css)
distinguishes workspace, panel, card, input, border and selected surfaces. The
current Zai Dark variant differs slightly from the screenshot: #161616 workspace,
#202020 panels and #2b2b2b cards. Its semantic colors are #4099ff blue,
#46bf72 success, #ff5c5c destructive, and #ff8a30 warning. This implementation uses
the screenshot's measured neutral surfaces, the site's sky-blue active accent,
and those explicit semantic colors. Calendar task fills are opaque blends over
the card surface, with brighter selected edges. Completed tasks have quieter text.
This is a deliberate terminal adaptation, not a claim that every theme version
uses identical tokens.

[The design system](https://github.com/zai-org/ZCode/blob/main/DESIGN.md) describes
a compact workspace, repeated spacing, rounded containers, visible input focus,
and depth through surfaces and borders. Calendar equivalents are a segmented view
selector, a large calendar frame, an optional details pane, compact action buttons,
and one shared editor. Color identifies state; IDs and secondary metadata do not
compete with task titles. The right pane holds dates, selection and upcoming work;
there is no IDE activity feed, chat box, or decorative window controls.

The site's [font stylesheet](https://zcode.z.ai/_next/static/css/6ad9841b43ad2bc9.css)
loads Geist Sans and Geist Mono. Proportional Geist Sans, arbitrary pixel sizes,
CSS radius and antialiasing cannot be duplicated by character glyphs alone.
Version 1.4 adds optional Kitty graphics for those shapes, described below.
Kitty controls font rendering through its [font settings](https://sw.kovidgoyal.net/kitty/conf/#fonts).
Use Geist Mono in a dedicated Kitty profile if installed; the application does
not change the user's terminal font. Unicode grid borders, edge-aligned filled
containers and circled dates provide cell-aligned equivalents. Theme colors use programmable RGB slots where
supported, restore the original slots on exit, and have a limited-color fallback.

## Layout and interaction decisions

- Minimum usable canvas: **90 columns × 28 rows**. Smaller windows show actual and
  required dimensions. Edits survive shrink/expand, and invisible controls cannot
  receive mouse events.
- At 132 columns with adequate height, show the right pane. Below that, full details
  remain one Enter or double-click away. Week columns change from seven to three
  when the calendar itself is too narrow. Navigation stays attached to the selected
  date. Large windows gain space, rather than oversized fixed padding.
- Full-height cards get four closed corners. One- or two-cell-high tasks use compact
  filled chips instead of incomplete box outlines. Grid separators use explicit
  junctions. Every component writes within its rectangle.
- A six-row mini-calendar has a fixed seven-column layout, with a circled current
  date and an independent selected-date highlight. Weekday labels align with dates.
- One Day tab; `t` jumps to today's day. A red dotted rule marks current time and
  refreshes on each local minute transition, even without input.
- Click tabs, dates, tasks, buttons and fields. Double-click tasks to inspect them;
  double-click a date to open Day. The wheel scrolls time, agenda or dialog content.
  Mouse and keyboard invoke the same actions and use the same database.

[Python curses](https://docs.python.org/3/library/curses.html) supplies resize and
mouse events, clipping and color pairs. Mouse coordinates are resolved against the
latest frame's rectangles. Press/release handling avoids accidental duplicate
mutations; a modal owns its own targets. The [xterm protocol](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html)
defines extended mouse reporting, including coordinates beyond 223 columns.
In tmux, enable [mouse forwarding](https://github.com/tmux/tmux/wiki/Getting-Started#using-the-mouse)
with `set -g mouse on`. Keyboard operation remains available throughout.

## Verification

Check wide, medium, minimum and undersized canvases; four-, five- and six-week
months; crossing-midnight and overlapping tasks; closed card/grid edges; current
minute transitions; and resize while an editor contains unsaved text. Exercise
mouse navigation and mutations through a real pseudo-terminal. Re-run storage,
recurrence, undo, CLI and notification tests, then visually inspect real Kitty
and tmux renders. Preview data lives in a disposable database.

### Review results

The full 81-test regression suite passed. After the final narrow-card and click
corrections, all 15 UI regression tests passed, including the newly added long-title
case. Real Kitty screenshots are linked from the README. A separate temporary tmux
session passed mouse capture, form save, Inbox selection and task completion checks.
Installed version 1.2.0 matches the source. `task doctor` reports SQLite integrity
ok, the reminder process running, Dunst responding and the i3 autostart entry present.
No personal task data was used for screenshots or input tests.

## Filled task edges and annual planning (1.3.0)

Task outlines now use edge-aligned eighth-block characters, including the joined
corner blocks U+1FB7C–U+1FB7F from the
[Unicode Symbols for Legacy Computing chart](https://www.unicode.org/charts/PDF/U1FB00.pdf).
Their strokes sit on cell boundaries, allowing the same task tint behind the edge
and its interior. This removes both the exterior halo of center-stroke borders
and the interior gap caused by giving border cells the calendar background.
Task corners are square. Verified in the real Kitty renderer.

Year uses a 4×3 or 3×4 month layout. At smaller heights it keeps all twelve months
as summary cards. Dates, filters, recurrence, completion and scheduling use the
same underlying occurrences as the other calendar views. Scheduling through A
keeps the existing task model, including spans across months and years.

Validation for 1.3.0: all 91 regression tests passed. Kitty previews verified the
filled card edges and both year layouts. An isolated tmux session rendered the
new edge glyphs and all twelve months; mouse capture, save and completion also
passed through tmux. Installation matches the source, and `task doctor` reports
the database and desktop reminder services healthy.

## Consistent filled components (1.3.1)

Every filled box now uses the same edge-aligned strokes: view tabs, sidebar panels,
dialogs, editor fields and task cards. Border cells use the same background as the
interior, including focused inputs and selected tabs. Unfilled calendar grids keep
their existing connected junctions. This prevents both exterior color halos and
interior gaps throughout the interface.

Task fills use a stronger blend of the semantic hue (38%, or 50% for selection).
Colored outlines and labels are lightened to remain legible on those stronger
fills; selected titles use the brightest text color. Completed titles retain a
quieter green tint. Neutral workspace and panel colors are unchanged.

Validation for 1.3.1: all 91 regression tests passed, including resize and mouse
interaction through a pseudo-terminal. All 17 border/fill style pairs have matching
backgrounds. Real Kitty previews covered the four calendar views, compact layouts,
the editor, rescheduling, task inspection and the command menu. README screenshots
were refreshed using the disposable preview database.

## Continuous current-time rule (1.3.2)

The previous rule skipped task labels and vertical borders, leaving long gaps.
The timeline now reserves one row for the red dotted rule and places task text
around it. The rule draws over every calendar column and task fill, including
selected and compact cards. Calendar scaling accounts for the reserved row;
times and task durations are unchanged. The clock still refreshes each minute.

Validation: all 93 tests passed. The new checks cover an uninterrupted rule and
intact task titles in Day and Week at three terminal sizes, including midnight
and 23:59, plus hiding the rule outside the visible date/time. Real Kitty captures
verified the full week, day and compact layouts.


## Rounded surfaces (1.4.0)

The supplied close-ups show circular panel corners with substantial radii and
capsule controls. Single-cell corner characters cannot describe those curves:
their radius is tied to a small fraction of one terminal cell. The previous
small-corner prototype did not meet this reference.

The [CSS corner-shaping rules](https://drafts.csswg.org/css-backgrounds/#corner-shaping)
define circular/elliptical outer corners and the inset inner edge. The
[non-overlap rule](https://drafts.csswg.org/css-backgrounds/#corner-overlap)
limits adjacent radii. For this app's uniform circular corners, the limit is half
the smaller dimension. At a 17-pixel cell height, panels use about 18 pixels,
tasks 14 pixels and fields 12 pixels. Capsules use half their height. These are
chosen proportions based on the supplied images, not extracted CSS values.

[Kitty's graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
allows pixel images behind terminal text. The renderer produces PNG edge masks
using only Python's standard library. Quarter-circle distance calculations give
antialiased strokes; the outside is masked to the parent surface. The interior
is transparent so native date highlights and cell backgrounds remain visible.
Task accents are about four pixels thick, clipped by the same curve.

The renderer reads the actual cell dimensions from the terminal, reuses generated
shapes, and removes its own placements when a view disappears. A dialog clips the
borders underneath it. Each frame re-transmits cached images because a terminal
clear during resize can evict them. Synchronized output presents the text and
edges together. Exiting frees the app's images and restores the terminal palette.
There are no runtime downloads, external images, or font changes.

In version 1.4.0, direct Kitty sessions enabled this automatically. Actual tmux panes, other
terminals, and NO_COLOR use the character renderer: passing graphics around a
multiplexer risks leaving shapes behind when changing panes or windows. An
inherited TMUX environment variable does not disable graphics in a fresh Kitty
window. The fallback preserved every keyboard and mouse action. Version 1.5.0
below replaces that tmux limitation; a separate Kitty window is no longer needed.

Year date rows now share the available month height, with click targets extending
through the spacing. The footer retains task context. Compact cards still show
all twelve months when individual dates cannot fit.

Validation: all 103 tests passed, including pixel geometry, antialiasing, capsule
scaling, image cleanup, dialog occlusion, continuous minute rules, mouse input and
expanded year date targets. Real Kitty checks covered every calendar scale,
mouse tab switching, font resizing, and an unsaved editor draft through the
minimum-size screen. A disposable tmux session passed mouse capture, save,
Inbox selection and completion. The summary distribution bar now uses a half-cell
stroke instead of a thin rule. Screenshots use disposable preview data.


## tmux rendering and layout consistency (1.5.0)

### Existing-window workflow

The previous release deliberately disabled graphics in tmux. That did not meet
the intended `Kitty → tmux → task` workflow. This release keeps the same command
and renders inside the current pane.

Kitty documents [relative placements](https://sw.kovidgoyal.net/kitty/graphics-protocol/#relative-placements)
whose parent can be a transparent Unicode placeholder. The placeholder is normal
text in tmux's screen buffer; graphics attached to it follow its location and
visibility. This avoids absolute client coordinates and redraw hooks. Image
commands travel through [tmux's pane-local passthrough](https://man.openbsd.org/tmux.1#allow-passthrough).
The app temporarily enables the option for its own pane, restoring the previous
value on exit. No global tmux options or configuration files are changed.

All image commands suppress replies, avoiding accidental keyboard input from
terminal protocol responses. The renderer uses actual tmux cell metrics, clips
modal occlusion, and keeps task text and mouse hit targets in the native cell
layout. A newly launched Kitty window with inherited TMUX variables is detected
as a direct terminal by comparing its TTY with the named pane's TTY.

### Layout research and decisions

IBM Carbon's [grid guidance](https://carbondesignsystem.com/elements/2x-grid/overview/)
uses consistent alignment lines, fixed spacing and fluid content areas. Its
[spacing guidance](https://carbondesignsystem.com/elements/spacing/overview/)
connects repeated spacing with visual grouping. The [button guidance](https://carbondesignsystem.com/components/button/usage/)
recommends matching sizes within a group. These principles inform the layout;
the app retains the supplied ZCode colors and terminal typography.

- The calendar and sidebar share their top and bottom edges. The sidebar uses
  roughly one fifth of the width, bounded to keep both notes and dates readable.
- A three-column horizontal gutter and a one-row vertical gutter have similar
  physical size after border insets in a typical 8×17-pixel terminal cell.
- Six view tabs have equal widths. New task matches their height and baseline.
  The date toolbar occupies a separate row with equal-width action controls.
- Panel borders share the calendar's insets. Inputs have a small vertical inset,
  producing a consistent gap without reducing the number of visible fields.
- Task titles and times share a left inset. Pixel borders allow short cards to
  show both lines without spending two full text rows on border characters.
- Month cards use all available grid height; adjacent months share date-row
  baselines. Empty calendar weeks remain blank rather than inventing dates.
- Details actions divide the complete width evenly. Sidebar sections fit the
  available height, keeping full inspection and keyboard actions accessible.

These are explicit terminal layout choices, not a claim that a single visual
ratio establishes product quality. Tests cover layout bounds, interaction and
renderer cleanup, with visual review at several sizes in actual Kitty/tmux.

Validation: 111 tests passed. In Kitty 0.48.2 with tmux 3.7b, the installed
`task` command was checked with disposable task data. SGR mouse events sent
through the tmux client exercised capture, save, selection, completion and undo.
Visual checks covered window switching, moving the app into a right-hand split,
the status bar above the pane, font changes, and minimum-size recovery with an
unsaved draft. The pane's passthrough option was restored after exit. The eight
preview images now show the application running inside tmux.

## Task content and selected-task actions (1.5.1)

The previous cards placed the title on their first row and the time near their
last row. This gave wrapped titles uneven margins and separated related text.
Cards now center a single title/time group vertically. Side padding grows from
two to three columns on wider blocks; the state symbol has a separate column,
so wrapped text and time labels share the same left edge. Normal cards reserve
a blank row above and below their content. Short blocks use a single centered
line, with an inline time range when wide enough. Larger blocks show up to three
title lines. They retain their scheduled height rather than expanding into
neighboring tasks. The current-time rule retains its own uninterrupted row.

The details panel replaces the stacked, single-row capsules with an Open action
in the header and three equal, three-row controls at the bottom. Content stops
before the controls, and every action remains reachable by keyboard or mouse.
The complete task title and schedule remain accessible through inspection.

Validation: all 115 tests passed, including balanced card insets, wrapped-title
alignment, compact time labels, and sidebar action bounds. The installed 1.5.1
launcher passed mouse-event checks through Kitty/tmux for capture, save,
selection, Open, Edit, Move, completion and undo. Visual review covered all
calendar scales, compact windows, font resizing, and an unsaved draft through
the minimum-size screen. Preview images use disposable task data.
