#!/usr/bin/env python3
"""Edit captured tour clips into a captioned 1080p MP4 with eased zooms.

Requires FFmpeg with libx264, drawtext and zoompan. Sources:
https://ffmpeg.org/ffmpeg-filters.html#zoompan
https://ffmpeg.org/ffmpeg-filters.html#drawtext
"""
import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--reuse-scenes',action='store_true',help='Reuse rendered feature clips when changing only titles or audio')
    args=parser.parse_args()
    root=args.directory
    scenes=json.loads((root/'scenes.json').read_text())
    output=root/'edited'
    output.mkdir(exist_ok=True)
    font=subprocess.check_output(['fc-match','-f','%{file}','DejaVu Sans'],text=True)
    bold=subprocess.check_output(['fc-match','-f','%{file}','DejaVu Sans:style=Bold'],text=True)

    def render(pair):
        index,scene=pair
        target=output/f'{index:02d}.mp4'
        if args.reuse_scenes and target.exists():
            return target
        duration=scene['duration']
        frames=round(duration*30)
        title=output/f'{index:02d}-title.txt'
        caption=output/f'{index:02d}-caption.txt'
        label=output/f'{index:02d}-label.txt'
        title.write_text(scene['title'])
        caption.write_text(scene['caption'])
        label.write_text(f'TASK CALENDAR    /    {index+1:02d} — {len(scenes):02d}')
        zoom=scene.get('zoom',1.06)
        fx,fy=scene.get('focus',[.5,.5])
        # Return to the full frame before each cut: both zoom in and zoom out
        # have zero velocity at their endpoints.
        ease=f'pow(sin(PI*on/{max(1,frames-1)}),2)'
        z=f'1+{zoom-1}*{ease}'
        graph=(f"[0:v]fps=30,zoompan=z='{z}':x='max(0,min(iw-iw/zoom,iw*{fx}-iw/zoom/2))':"
               f"y='max(0,min(ih-ih/zoom,ih*{fy}-ih/zoom/2))':d=1:s=1760x918:fps=30,"
               "pad=1920:1080:80:44:color=0x111111[screen];")
        extra=[]
        if scene.get('notification'):
            extra=['-loop','1','-i',scene['notification']]
            graph+="[1:v]scale=800:-1[bubble];[screen][bubble]overlay=x=1020:y=180[composed];"
            source='composed'
        else:
            source='screen'
        graph+=(f'[{source}]drawbox=x=80:y=34:w=1760:h=1:color=0x353535:t=fill,'
                f'drawbox=x=80:y=34:w={int(1760*(index+1)/len(scenes))}:h=2:color=0x4099ff:t=fill,'
                f'drawtext=fontfile={font}:textfile={label}:fontsize=14:fontcolor=0x999999:x=80:y=10,'
                f"drawtext=fontfile={bold}:textfile={title}:fontsize=29:fontcolor=0xf8f8f8:x='80+18*pow(max(0,1-t/0.5),2)':y=982,"
                f"drawtext=fontfile={font}:textfile={caption}:fontsize=20:fontcolor=0xbebfb8:x='80+12*pow(max(0,1-t/0.6),2)':y=1025,"
                f'fade=t=in:st=0:d=0.25,fade=t=out:st={max(.3,duration-.25)}:d=0.25,format=yuv420p[v]')
        command=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',scene['file'],*extra,
                 '-filter_complex_threads','1','-filter_complex',graph,'-map','[v]',
                 '-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','21',
                 '-threads','2','-movflags','+faststart',str(target)]
        subprocess.run(command,check=True)
        print(f'Rendered {index+1}/{len(scenes)}: {scene["title"]}',flush=True)
        return target

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        clips=list(pool.map(render,enumerate(scenes)))

    def title_card(name, title, subtitle, footer, seconds):
        files=[]
        for field,text in (('title',title),('subtitle',subtitle),('footer',footer)):
            path=output/f'{name}-{field}.txt';path.write_text(text);files.append(path)
        graph=(f"drawtext=fontfile={bold}:textfile={files[0]}:fontsize=76:fontcolor=0xf8f8f8:"
               "x=(w-text_w)/2:y='420+24*pow(max(0,1-t/1.2),2)',"
               "drawbox=x=900:y=534:w=120:h=3:color=0x4099ff:t=fill,"
               f"drawtext=fontfile={font}:textfile={files[1]}:fontsize=29:fontcolor=0xbebfb8:x=(w-text_w)/2:y=577,"
               f"drawtext=fontfile={font}:textfile={files[2]}:fontsize=22:fontcolor=0x999999:x=(w-text_w)/2:y=940,"
               f"fade=t=in:st=0:d=0.6,fade=t=out:st={seconds-.5}:d=0.5,format=yuv420p")
        path=output/f'{name}.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
                        f'color=c=0x151515:s=1920x1080:r=30:d={seconds}','-vf',graph,
                        '-an','-c:v','libx264','-preset','fast','-crf','21','-threads','2',str(path)],check=True)
        return path

    intro=title_card('intro','Task Calendar','Make room for the work that matters.',
                     'DAY   /   WEEK   /   MONTH   /   YEAR',4)
    outro=title_card('outro','Your time. Your terminal.','Free, open source and completely local.',
                     'github.com/jeel00dev/TUI_TASK_MANAGER',5)
    clips=[intro,*clips,outro]
    scenes=[dict(title='Task Calendar',caption='A local calendar for your terminal.',duration=4),
            *scenes,dict(title='Get Task Calendar',caption='Free under the MIT license.',duration=5)]
    listing=output/'concat.txt'
    listing.write_text(''.join(f"file '{path}'\n" for path in clips))
    chapters=output/'chapters.txt'
    text=';FFMETADATA1\ntitle=Task Calendar — a local terminal workflow\n'
    at=0
    for scene in scenes:
        end=at+round(scene['duration']*1000)
        text+=f'[CHAPTER]\nTIMEBASE=1/1000\nSTART={at}\nEND={end}\ntitle={scene["title"]}\n'
        at=end
    chapters.write_text(text)
    soundtrack=root/'soundtrack.wav'
    if not soundtrack.exists():
        raise SystemExit('Generate the original soundtrack with tools/tour_soundtrack.py first.')
    destination=ROOT/'docs/task-calendar-tour.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),
                    '-i',str(chapters),'-i',str(soundtrack),'-map','0:v:0','-map','2:a:0',
                    '-map_metadata','1','-map_chapters','1','-c:v','copy','-c:a','aac','-b:a','160k','-ar','48000',
                    '-af','loudnorm=I=-20:TP=-2:LRA=8','-shortest','-movflags','+faststart',str(destination)],check=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss','7','-i',str(destination),
                    '-frames:v','1',str(ROOT/'docs/tour-poster.png')],check=True)
    at=0;manifest=[]
    for scene in scenes:
        manifest.append(dict(start_seconds=round(at,3),title=scene['title'],caption=scene['caption']))
        at+=scene['duration']
    (ROOT/'docs/tour/chapters.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Created {destination} ({destination.stat().st_size/1024**2:.1f} MiB)',flush=True)


if __name__=='__main__':
    main()
