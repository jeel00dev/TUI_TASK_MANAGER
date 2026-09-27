# Recorded feature tour

The README links to a 1920×1080, 30 fps H.264 MP4 with embedded chapter markers.
It has captions and an original stereo instrumental soundtrack. The footage is recorded from the running application
inside Kitty and tmux, using a disposable database. No personal tasks appear.

## What the recording covers

Calendar scales, overlapping tasks, free time, multi-day spans, navigation,
Inbox capture, task editing, priorities, tags, notes, state changes, rescheduling,
delete and undo, search and filters, recurrence, history, help, snooze, terminal
resizing and draft recovery, shell capture, and independent desktop reminders.

The reminder scenes use the application's real background process and a private
D-Bus notification session. Only the demonstration clock is changed, first to
16:45 and then 17:00. Captions identify those changes. The recorded notification
window is enlarged in the edit for readability. Delivery leaves the task pending.

## Recording tools

- `tools/tour_session.py`: seeded session and controllable demonstration clock;
  requires a disposable directory marked `.task-calendar-demo`.
- `tools/record_tour.py`: real keyboard/mouse interactions captured from the
  named Kitty review window into independent clips; supports resuming a capture.
- `tools/render_tour.py`: animated titles, eased zooms in and out, fades, chapters and poster.
- `tools/tour_soundtrack.py`: original synthesized pads, plucks, bass, percussion
  and quiet transition sweeps. It uses no samples or third-party recordings.
- `tools/package_release.py`: small, reproducible source archive and SHA-256 file.

These tools are for producing documentation. They add no application dependencies.
The soundtrack generator uses NumPy only during production. The music and video
are included under the repository's MIT license. AAC audio is normalized to a
quiet listening level; the captions also support watching with sound off.
The edit uses [FFmpeg's zoompan and drawing filters](https://ffmpeg.org/ffmpeg-filters.html#zoompan).
The native notification styling follows the [Dunst configuration reference](https://dunst-project.org/documentation/).
The README's poster opens the static player on GitHub Pages. The player serves
the MP4 as video/mp4 and provides native playback, sound, seeking and fullscreen
controls. The separate download link uses the release asset. Repository blob
pages cannot preview this video at its full size.
