# !/usr/bin/python
# -*- coding: utf-8 -*-

import os.path
import argparse
import numpy as np
from moviepy.editor import VideoFileClip, CompositeVideoClip
from moviepy.video.VideoClip import TextClip
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from mido import MidiFile, MetaMessage

"""
Script written by jaflo

Install:

* MoviePy for video editing: http://zulko.github.io/moviepy/
* OpenCV, Scipy, PIL, or Pillow for .resize()
* numpy for calculations: http://www.numpy.org/
* mido for MIDI file operations: http://mido.readthedocs.org/

pip install moviepy numpy mido

usage: pitch.py [-h] [-s SPEED] [-fo FADEOUT] [-r] [-m MAXSTACK]
                input midi output
example: python pitch.py dog.mp4 151186.mid megalovania.mp4

speedx, stretch, pitchshift from zulko (black magic if you ask me):
https://zulko.github.io/blog/2014/03/29/soundstretching-and-pitch-shifting-in-python/
"""

def speedx(snd_array, factor):
    """ Speeds up / slows down a sound, by some factor. """
    indices = np.round(np.arange(0, len(snd_array), factor))
    indices = indices[indices < len(snd_array)].astype(int)
    return snd_array[indices]

def stretch(snd_array, factor, window_size, h):
    """ Stretches/shortens a sound, by some factor. """
    phase = np.zeros(window_size)
    hanning_window = np.hanning(window_size)
    result = np.zeros(len(snd_array) / factor + window_size)

    for i in np.arange(0, len(snd_array) - (window_size + h), h*factor):
        # Two potentially overlapping subarrays
        a1 = snd_array[i: i + window_size]
        a2 = snd_array[i + h: i + window_size + h]

        # The spectra of these arrays
        s1 = np.fft.fft(hanning_window * a1)
        s2 = np.fft.fft(hanning_window * a2)

        # Rephase all frequencies
        phase = (phase + np.angle(s2/s1)) % 2*np.pi

        a2_rephased = np.fft.ifft(np.abs(s2)*np.exp(1j*phase))
        i2 = int(i/factor)
        result[i2: i2 + window_size] += hanning_window*a2_rephased.real

    # normalize (16bit)
    result = ((2**(16-4)) * result/result.max())

    return result.astype('int16')

def pitchshift(snd_array, n, window_size=2**13, h=2**11):
    """ Changes the pitch of a sound by ``n`` semitones. """
    factor = 2**(1.0 * n / 12.0)
    stretched = stretch(snd_array, 1.0/factor, window_size, h)
    return speedx(stretched[window_size:], factor)

def splitshift(sound, n):
    """
    Split stereo channels and pitchshift each of them.
    Then combine them and return an AudioArrayClip of the values.
    pitchshift() returns int16, not float, so divide by 32768 (max val of int16).
    """
    sound1 = pitchshift(sound[:,0], n)
    sound2 = pitchshift(sound[:,1], n)
    combined = np.column_stack([sound1, sound2]).astype(float)/32768
    return AudioArrayClip(combined, fps=44100)

def poop(source, destination, midi_file, stretch, fadeout, rebuild, max_stack):
    """
    Create multiple pitchshifted versions of source video and arrange them to
    the pattern of the midi_file, also arrange the video if multiple notes play
    at the same time.
    """

    print "Reading input files"
    video = VideoFileClip(source, audio=False)
    """
    Non-main tracks are 30% the size of the main and have a white border and a
    margin around them.
    """
    smaller = video.resize(0.3)\
        .margin(mar=2, color=3*[255])\
        .margin(mar=8, opacity=0)
    audio = AudioFileClip(source, fps=44100)
    mid = MidiFile(midi_file)
    ignoredtracks = ["Percussion", "Bass"]

    print "Analysing MIDI file"
    notes = []   # the number of messages in each track
    lowest = 127 # will contain the lowest note
    highest = 0  # will contain the highest note
    for i, track in enumerate(mid.tracks):
        notes.append(0)
        #if track.name in ignoredtracks: continue
        for message in track:
            if message.type == "note_on":
                lowest = min(lowest, message.note)
                highest = max(highest, message.note)
                notes[-1] += 1
    """
    The main track is the one featured in the center. It is probably the one
    with the most notes. Also record the lowest, highest, and average note to
    generate the appropriate pitches.
    """
    maintrack = max(enumerate(notes), key=lambda x: x[1])[0]
    midpitch = int((lowest+highest)/2)
    print "Main track is probably", str(maintrack)+":", mid.tracks[maintrack].name
    mid.tracks.insert(0, mid.tracks.pop(maintrack)) # move main track to front
    notes.insert(0, notes.pop(maintrack)) # move main note count to front
    print sum(notes), "notes ranging from", lowest, "to", highest, "centering around", midpitch

    print "Transposing audio"
    sound = audio.to_soundarray(fps=44100) # source, original audio
    tones = range(lowest-midpitch, highest-midpitch) # the range of pitches we need
    pitches = [] # this will contain the final AudioFileClips
    if not os.path.exists("pitches/"):
        print "Creating folder for audio files"
        os.makedirs("pitches/")
    for n in tones:
        """
        Pitches only need to be generated if they do not already exist or if
        we force the creation of new ones. Save them in order in pitches.
        """
        name = "pitches/"+source+"_"+str(n)+".mp3"
        if not os.path.isfile(name) or rebuild:
            print "Transposing pitch", n
            splitshift(sound, n).write_audiofile(name)
        pitches.append(AudioFileClip(name, fps=44100))

    print "Adding video clips"
    clips = [video.set_duration(1)] # to set the video size
    positions = [("left", "bottom"), ("right", "bottom"), ("left", "top"),
        ("right", "top"), ("center", "bottom"), ("center", "top"),
        ("left", "center"), ("right", "center")] # non-main tracks
    """
    curpos is the current corner position on the screen and changes with each track.
    cache is used to make a unique file name whenever a new temporary file is created.
    endtime will be used at the end to set the end TextClip. It is the latest time any clip ends.
    """
    curpos = -2
    cache = endtime = 0
    for i, track in enumerate(mid.tracks):
        #if track.name in ignoredtracks: continue
        print("Processing {} notes: {}".format(notes[i], track.name))
        t = 1.0 # not 0 because we added one second of original video for size
        opennotes = [] # will contain all notes that are still playing
        curpos += 1
        for message in track:
            if not isinstance(message, MetaMessage):
                message.time *= stretch
                t += message.time
                if message.type == "note_on":
                    """
                    Add a video clip with the appropriate starting time and
                    pitch. Also add an entry to opennotes (we don't know when
                    the note ends yet).
                    """
                    part = video
                    mainvid = i is 0# and len(opennotes) is 0
                    if not mainvid: part = smaller
                    part = part\
                        .set_audio(pitches[min(len(pitches)-1, max(0, message.note-lowest))])\
                        .set_start(t/1000)
                    opennotes.append((message.note, len(clips), t))
                    """
                    If this isn't the main track, the video will be smaller and
                    placed at the edge. We'll get a position for each track.
                    If there is more than one video playing in this track, it
                    will be placed slighly closer to the center.
                    """
                    if not mainvid:
                        stackheight = 6
                        part = part.set_position(positions[curpos % len(positions)])
                    clips.append(part)
                elif message.type == "note_off":
                    reference = message.note
                    index = 0
                    """
                    Find the note that ended in opennotes using the note.
                    Get the index and start time, remove it from opennotes.
                    """
                    for note in reversed(opennotes):
                        n, j, d = note
                        if n == reference:
                            index = j
                            opennotes.remove(note)
                            break
                    """
                    Get the clip for the open note, set its time to the
                    difference between time now and start time. Have it fade out
                    and update the endtime if needed.
                    """
                    clips[index] = clips[index].set_duration((t-d)/1000+fadeout)
                    clips[index] = clips[index].crossfadeout(fadeout)
                    endtime = max(endtime, t/1000+fadeout)
                if len(clips) == max_stack:
                    """
                    To save some memory, the clips in memory are emptied
                    whenever they reach a certain size. All clips that are closed
                    are merged into one file on disk.
                    """
                    upuntil = len(clips) # the first open note
                    if len(opennotes) > 0: _, upuntil, _ = opennotes[0]
                    stillopen = clips[upuntil:]
                    print "Stack reached", len(clips), "clips, merging", upuntil
                    """
                    Save a temporary file to disk with all clips we can safely
                    discard from clips.
                    """
                    newcache = destination+".temporary"+str(cache)+".mp4"
                    CompositeVideoClip(clips[:upuntil]).write_videofile(newcache)
                    cache += 1
                    """
                    Shift all opennotes' indices down by the number of clips
                    merged and saved to disk. Set clips to be the new, merged
                    clip and any leftover clips.
                    """
                    for i, note in enumerate(opennotes):
                        n, j, d = note
                        opennotes[i] = (n, j-upuntil+1, d)
                    clips = [VideoFileClip(newcache)]+stillopen

    end = TextClip("pitch.py", font="Arial", color="white", fontsize=70)\
        .set_pos("center")\
        .set_duration(1)\
        .set_start(endtime)
    clips.append(end) # add an ending frame

    """
    Combine all leftover clips, write them to the final file and remove
    temporary files created before.
    """
    print "Combining", len(clips), "clips"
    final = CompositeVideoClip(clips).set_start(1)
    final.write_videofile(destination)
    clips = []
    if cache == 1:
        print "Removing one temporary file"
    elif cache > 1:
        print "Removing", cache, "temporary files"
    for i in range(0, cache):
        os.remove(destination+".temporary"+str(i)+".mp4")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YouTube Poop from video and MIDI files!")
    parser.add_argument("input", help="input video file")
    parser.add_argument("midi", help="MIDI file")
    parser.add_argument("output", help="output video file")
    parser.add_argument("-s", "--speed", type=float, help="speed factor", default=1.5)
    parser.add_argument("-fo", "--fadeout", type=float, help="fade out time in seconds", default=0.2)
    parser.add_argument("-r", "--rebuild", help="force pitch rebuild", action="store_true")
    parser.add_argument("-m", "--maxstack", type=int, help="maximum number of clips in memory", default=1000)
    args = parser.parse_args()

    poop(args.input, args.output, args.midi, args.speed, args.fadeout, args.rebuild, args.maxstack)
