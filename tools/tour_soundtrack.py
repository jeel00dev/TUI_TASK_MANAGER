#!/usr/bin/env python3
"""Synthesize the tour's original instrumental bed; no downloaded samples.

Production-only dependency: NumPy. Writes stereo PCM at 44.1 kHz. The music
and this source are distributed under the repository's MIT license.
"""
import argparse
import json
import wave
from pathlib import Path
import numpy as np

RATE=44100
BEAT=60/108


def compose(duration, transitions, destination):
    rng=np.random.default_rng(2609)
    mix=np.zeros((int((duration+2)*RATE),2),dtype=np.float32)

    def add(signal, start, gain=1, pan=0):
        offset=int(start*RATE)
        if offset < 0:
            signal=signal[-offset:]
            offset=0
        size=min(len(signal),len(mix)-offset)
        if size<=0:return
        signal=signal[:size]*gain
        mix[offset:offset+size,0]+=signal*np.sqrt((1-pan)/2)
        mix[offset:offset+size,1]+=signal*np.sqrt((1+pan)/2)

    def tone(midi, length, pluck=False):
        t=np.arange(int(length*RATE))/RATE
        hz=440*2**((midi-69)/12)
        if pluck:
            waveform=np.sin(2*np.pi*hz*t)+.25*np.sin(2*np.pi*2*hz*t)*np.exp(-t*7)
            envelope=(1-np.exp(-t*150))*np.exp(-t*4)
        else:
            waveform=(np.sin(2*np.pi*hz*t)+.28*np.sin(2*np.pi*hz*1.002*t)
                      +.12*np.sin(2*np.pi*hz*2*t))/1.4
            envelope=np.minimum(t/.7,1)*np.minimum((length-t)/1.1,1)
        return (waveform*envelope).astype(np.float32)

    # D minor 9 / B-flat major 7 / F major 9 / C add 9; a restrained pulse.
    chords=((50,57,60,64,69),(46,53,57,62,65),(41,53,57,60,67),(48,55,62,64,67))
    bar=8*BEAT
    for index,start in enumerate(np.arange(0,duration,bar)):
        chord=chords[index%4]
        for voice,note in enumerate(chord):
            add(tone(note,bar+.8),start,.028,(-.65+voice*.325))
        for beat in (0,3,4,6):
            add(tone(chord[0]-12,.9,True),start+beat*BEAT,.11)
        for tick in range(16):
            note=chord[2+(tick//2)%3]+12
            at=start+tick*BEAT/2
            signal=tone(note,1.4,True)
            pan=.48 if tick%2 else -.48
            add(signal,at,.038,pan)
            add(signal,at+BEAT*.75,.014,-pan)
        for beat in range(8):
            at=start+beat*BEAT
            t=np.arange(int(.18*RATE))/RATE
            if beat%2==0:
                kick=np.sin(2*np.pi*(48*t+8*(1-np.exp(-t*35))))*np.exp(-t*28)
                add(kick,at,.085)
            noise=rng.standard_normal(int(.04*RATE)).astype(np.float32)
            noise=np.diff(noise,prepend=0)*np.exp(-np.arange(len(noise))/(RATE*.006))
            add(noise,at+BEAT/2,.012,.25)
    # Quiet airy sweeps identify chapter transitions without alarm-like sounds.
    for at in transitions:
        t=np.arange(int(.5*RATE))/RATE
        noise=rng.standard_normal(len(t))
        noise=np.convolve(noise,np.ones(18)/18,mode='same')
        add(noise*np.sin(np.pi*t/.5)**2,at-.22,.045,-.2)
    size=int(duration*RATE)
    mix=mix[:size]
    fade=np.minimum(np.arange(size)/(RATE*2.5),1)*np.minimum((size-np.arange(size))/(RATE*3),1)
    mix*=fade[:,None]
    peak=np.max(np.abs(mix))
    mix*=.65/max(peak,1e-6)
    with wave.open(str(destination),'wb') as output:
        output.setnchannels(2);output.setsampwidth(2);output.setframerate(RATE)
        output.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    scenes=json.loads((args.directory/'scenes.json').read_text())
    at=4;transitions=[]
    for scene in scenes:
        transitions.append(at);at+=scene['duration']
    destination=args.directory/'soundtrack.wav'
    compose(at+5,transitions,destination)
    print(f'Original stereo soundtrack: {destination} ({at+5:.1f}s)')


if __name__=='__main__':main()
