#!/usr/bin/env python3
"""Record a disposable tour already running in Kitty's named review window.

Developer-only: requires Kitty remote control, tmux, X11 and FFmpeg. Captures
only the named window; never the desktop or another application's contents.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    root = args.directory
    if not (root/'.task-calendar-demo').exists():
        parser.error('A disposable tour session is required')
    raw = root/'raw'
    raw.mkdir(exist_ok=True)
    remote = ['kitty','@','--to','unix:/tmp/taskcal-showcase.sock']
    tmux = ['tmux','-L','taskcal-showcase']
    info = json.loads(run(*remote,'ls'))[0]
    window = str(info['platform_window_id'])
    pane = run(*tmux,'display-message','-p','#{pane_id}')
    rows = int(run(*tmux,'display-message','-p','#{pane_height}'))
    scenes = json.loads((root/'scenes.json').read_text()) if args.resume else []
    next_scene = 0

    def send(keys, pause=.35):
        run(*remote,'send-text',keys)
        time.sleep(pause)

    def type_text(text):
        for part in (text[i:i+3] for i in range(0,len(text),3)):
            send(part,.04)

    def wait(text):
        end = time.monotonic()+5
        while time.monotonic()<end:
            if text in run(*tmux,'capture-pane','-p','-t',pane):
                return
            time.sleep(.1)
        raise RuntimeError('Expected screen: '+text)

    def search(text):
        send('/')
        send('\x15'+text+'\n',.6)
        wait('Search ·')

    def click(x,y):
        send(f'\x1b[<0;{x+1};{y+1}M\x1b[<0;{x+1};{y+1}m')

    def scene(title, caption, actions, seconds=5, zoom=1.0, focus=(.5,.5)):
        nonlocal next_scene
        index = next_scene
        next_scene += 1
        if index < len(scenes):
            return
        path = raw/f'{index:02d}.mp4'
        log = (raw/f'{index:02d}.log').open('w')
        process = subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y',
            '-f','x11grab','-window_id',window,'-draw_mouse','0','-framerate','30',
            '-i',os.environ.get('DISPLAY',':0'),'-an','-c:v','libx264','-preset','ultrafast',
            '-crf','18','-pix_fmt','yuv420p',str(path)],stdin=subprocess.PIPE,stderr=log)
        began = time.monotonic()
        time.sleep(.3)
        try:
            actions()
            time.sleep(max(.4,seconds-(time.monotonic()-began)))
        finally:
            process.communicate(b'q',timeout=10)
            log.close()
        if process.returncode:
            raise RuntimeError((raw/f'{index:02d}.log').read_text())
        duration = float(run('ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(path)))
        scenes.append(dict(file=str(path),title=title,caption=caption,duration=duration,zoom=zoom,focus=focus))
        (root/'scenes.json').write_text(json.dumps(scenes,indent=2))
        print(f'{index+1:02d} {title}: {duration:.1f}s',flush=True)

    scene('A calendar for your terminal', 'Local. Keyboard driven. Ready inside Kitty and tmux.', lambda:send('w'),6)
    scene('Make room for focused work', 'Day view shows overlaps, free time and the current-time line.',lambda:(send('d'),send('+'),time.sleep(2),send('-')),7,1.16,(.40,.40))
    scene('Your week, at a glance', 'h / l navigate ranges. Multi-day tasks stay one continuous task.',lambda:(send('w'),send('l'),time.sleep(1),send('h')),6)
    scene('A longer perspective', 'Month view keeps spanning work connected across weeks.',lambda:click(42,1),5,1.0)
    scene('All twelve months', 'y opens Year. Schedule work across months and even across years.',lambda:(send('y'),time.sleep(2),send('l'),time.sleep(1),send('h')),7)

    def capture():
        send('ia');wait('NEW TASK');type_text('Redis persistence notes');send('\n');wait('Redis persistence notes')
    scene('Capture first. Plan later.', 'a + a title + Enter. Unscheduled work belongs in Inbox.',capture,7,1.25,(.45,.40))

    def edit():
        send('e');wait('EDIT TASK')
        values=['Redis persistence notes','2026-09-26 15:00','2026-09-26 17:00','pending','high','#backend','',
                'Read RDB and AOF. Compare recovery and durability.']
        for index,value in enumerate(values):
            send('\x15'+value+('\t' if index<7 else ''),.3)
        time.sleep(1.5);send('\x13');search('Redis persistence notes')
    scene('Give the task its details', 'Dates, priority, tags, notes and recurrence. Ctrl-S saves.',edit,10,1.20,(.5,.45))
    scene('Everything in one place', 'Enter opens the full schedule and notes. Esc returns to your calendar.',lambda:(send('\n'),wait('TASK DETAILS'),time.sleep(3),send('\x1b')),6,1.32,(.5,.47))
    scene('Your actions set the state', 's starts. x completes. p returns to pending. Notifications never change state.',lambda:(send('s'),time.sleep(1.5),send('x'),time.sleep(1.5),send('p')),7,1.12,(.72,.5))
    scene('Move the plan, keep the duration', 'r accepts +1h, +1d, +1w, tomorrow, or a new date.',lambda:(send('r'),wait('RESCHEDULE'),send('\x15+1d'),time.sleep(2),send('\n')),6,1.20,(.5,.5))
    scene('Delete is easy to recover', 'Click Delete or press D. Press u to bring the task back.',lambda:(click(67,rows-2),time.sleep(2),send('u')),6,1.10,(.4,.85))

    def filtering():
        search('#backend');time.sleep(1)
        send('\x1b');send('w');send('f');send('\x15state:pending');time.sleep(1);send('\n');time.sleep(1.5);send('\x1b')
    scene('Find the work that matters', '/ searches titles, notes, tags and dates. f filters the visible calendar.',filtering,8,1.10,(.5,.4))

    def recurring():
        search('Daily DSA practice on:2026-09-26');send('E');wait('EDIT SERIES');time.sleep(2);send('\x1b')
        send('x');time.sleep(1.2);search('Daily DSA practice on:2026-09-27');time.sleep(1.5)
    scene('A routine, without the re-entry', 'Complete one occurrence. Tomorrow remains pending. E edits the series.',recurring,9,1.18,(.60,.42))
    scene('Keep the history', 'H keeps completed work searchable, including older archived tasks.',lambda:send('H'),5)
    scene('Help is always close', '? opens searchable commands. Type an action to find its shortcut.',lambda:(send('?'),type_text('snooze'),time.sleep(2),send('\x1b')),5,1.25,(.5,.44))
    scene('One more reminder, when you choose', 'z snoozes once for 5, 10, 15, 30 or 60 minutes.',lambda:(search('Daily DSA practice on:2026-09-27'),send('z'),send('\x1510'),time.sleep(1.5),send('\n')),6,1.20,(.5,.48))

    def resize():
        send('wa');type_text('This draft survives resize')
        other=run(*tmux,'split-window','-h','-l','150','-P','-F','#{pane_id}','-t',pane,'sleep 20')
        time.sleep(2)
        run(*tmux,'kill-pane','-t',other);time.sleep(2);wait('This draft survives resize');send('\x1b')
    scene('At home in tmux', 'Resize or split the terminal. Your selection and unsaved draft are preserved.',resize,9)

    def cli():
        send('q');time.sleep(.5);send('clear\n')
        type_text('task add "Read the PostgreSQL manual"');send('\n')
        type_text('task list --view inbox');send('\n');time.sleep(1.5)
    scene('Quick capture from the shell', 'The CLI, calendar and reminder process share the same local database.',cli,8,1.22,(.30,.25))
    print('Recorded interactive scenes. Add reminder footage, then render.',flush=True)


if __name__ == '__main__':
    main()
