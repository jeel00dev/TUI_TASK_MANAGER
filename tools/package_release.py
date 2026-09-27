#!/usr/bin/env python3
"""Build a small, reproducible source download without media or personal data."""
import gzip
import hashlib
import io
import sys
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from taskcal import __version__


def main():
    name=f'task-calendar-{__version__}'
    destination=ROOT/'releases'/f'{name}.tar.gz'
    destination.parent.mkdir(exist_ok=True)
    readme=(ROOT/'README.md').read_text().split('## See it in action')[0]
    readme='\n'.join(line for line in readme.splitlines()
                     if not line.startswith(('[Download','[![Task Calendar','1. [Download')))
    readme=readme.replace('2. Extract and install:', 'From the directory containing the download:')
    entries=[('README.md',readme.encode(),0o644)]
    for path in [ROOT/'task',ROOT/'pyproject.toml',ROOT/'LICENSE',*sorted((ROOT/'taskcal').glob('*.py'))]:
        entries.append((str(path.relative_to(ROOT)),path.read_bytes(),0o755 if path.name=='task' else 0o644))
    with destination.open('wb') as file, gzip.GzipFile(filename='',fileobj=file,mode='wb',mtime=0) as zipped:
        with tarfile.open(fileobj=zipped,mode='w') as tar:
            for path,data,mode in entries:
                info=tarfile.TarInfo(f'{name}/{path}')
                info.mode,info.size,info.mtime=mode,len(data),0
                tar.addfile(info,io.BytesIO(data))
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix+'.sha256').write_text(f'{digest}  {destination.name}\n')
    print(f'{destination} ({destination.stat().st_size:,} bytes)')


if __name__=='__main__':
    main()
