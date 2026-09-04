#!/usr/bin/env python3
"""Synthesise the lock's ambience: audio/ambience.mp3.

Original, built from oscillators here. The plugin previously shipped no
ambience at all because the one in use was not ours to distribute; this one is,
which means the lock now has a voice out of the box instead of silence.

It has to loop without a seam, because the lock plays it on repeat for as long
as the wall is up and a discontinuity becomes a click every pass. Two things
make that work:

  * Every oscillator's frequency is an exact integer multiple of 1/LENGTH, so
    each one completes a whole number of cycles across the loop and arrives
    back where it started. This is why the numbers below are written as
    n / LENGTH rather than as round frequencies -- 37Hz is a nice number, but
    only 37.5Hz divides a 48 second loop exactly.
  * The one layer that cannot be periodic -- the noise bed -- is crossfaded
    across the boundary at the end.

What it is trying to be: the sound of standing next to something enormous that
is aware of you. A low mass with a slow beat in it, a faint high shimmer that
drifts, and a deep swell every eight seconds that is felt more than heard.

Usage:  python3 tools/make-ambience.py
"""
import math
import os
import random
import struct
import subprocess
import sys
import wave

RATE = 44100
LENGTH = 48.0                     # seconds; the loop period
N = int(RATE * LENGTH)
UNIT = 1.0 / LENGTH               # the smallest frequency that loops cleanly

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_WAV = os.path.join(HERE, "..", "audio", "ambience.wav")
OUT_MP3 = os.path.join(HERE, "..", "audio", "ambience.mp3")

# Every entry is (cycles-per-loop, amplitude, phase). Frequency in Hz is
# cycles / LENGTH, so an integer here is a frequency that loops exactly.
#
# 1776 cycles / 48s = 37.0Hz -- the mass.
# 1780 / 48s = 37.083Hz -- four cycles apart, so it beats against the first
#   once every twelve seconds. That slow swell is most of the character.
VOICES = [
    (1776, 0.50, 0.0),      # 37.000 Hz  the mass
    (1780, 0.42, 1.1),      # 37.083 Hz  beating against it
    (2664, 0.16, 0.4),      # 55.500 Hz  a fifth above
    (3552, 0.13, 2.2),      # 74.000 Hz  the octave
    (3557, 0.09, 0.8),      # 74.104 Hz  beating again, faster
    (5328, 0.05, 1.7),      # 111.00 Hz  upper body, quiet
    (7104, 0.03, 0.3),      # 148.00 Hz
]

# Faint, high, and drifting: the sense of something digital going on a long way
# off. Each is amplitude-shaped by its own slow LFO, also on the loop grid.
SHIMMER = [
    (108_000, 0.014, 5, 0.0),    # 2250 Hz, breathing 5 times per loop
    (135_120, 0.010, 3, 1.9),    # 2815 Hz
    (163_200, 0.008, 7, 3.4),    # 3400 Hz
    (201_600, 0.006, 4, 0.6),    # 4200 Hz
]


def main():
    rnd = random.Random(0xB1ACC)
    buf = [0.0] * N

    two_pi_over_n = 2.0 * math.pi / N

    # --- the mass -----------------------------------------------------------
    for cycles, amp, phase in VOICES:
        step = two_pi_over_n * cycles
        for i in range(N):
            buf[i] += amp * math.sin(step * i + phase)

    # --- the shimmer --------------------------------------------------------
    for cycles, amp, lfo_cycles, phase in SHIMMER:
        step = two_pi_over_n * cycles
        lfo_step = two_pi_over_n * lfo_cycles
        for i in range(N):
            # 0..1, so the partial fades fully out rather than pulsing.
            env = 0.5 - 0.5 * math.cos(lfo_step * i + phase)
            buf[i] += amp * env * env * math.sin(step * i)

    # --- the swell ----------------------------------------------------------
    # Six over the loop, so it divides exactly. Deep, slow, and felt rather
    # than heard: the thing on the other side moving.
    swell_every = N // 6
    for k in range(6):
        start = k * swell_every
        length = int(RATE * 5.5)
        f = two_pi_over_n * 1200            # 25 Hz
        for j in range(length):
            i = (start + j) % N             # wraps, so the last one loops in
            u = j / length
            env = math.sin(math.pi * u) ** 2
            buf[i] += 0.30 * env * math.sin(f * i)

    # --- the bed ------------------------------------------------------------
    # Brown-ish noise: not periodic, so the tail is crossfaded into the head
    # below. Very quiet; it is there to stop the drone sounding synthetic.
    level = 0.0
    for i in range(N):
        level += rnd.uniform(-1, 1) * 0.02
        level = max(-1.0, min(1.0, level * 0.995))
        buf[i] += level * 0.09

    # --- close the loop -----------------------------------------------------
    # Everything periodic already meets itself. This is for the noise.
    fade = int(RATE * 2.0)
    for j in range(fade):
        u = j / fade
        head = buf[j]
        tail = buf[N - fade + j]
        buf[N - fade + j] = tail * (1 - u) + head * u

    # --- level --------------------------------------------------------------
    peak = max(abs(v) for v in buf) or 1.0
    gain = 0.72 / peak
    frames = bytearray()
    for i in range(N):
        v = math.tanh(buf[i] * gain * 1.1)
        s = int(max(-1.0, min(1.0, v)) * 31000)
        # Mono content, but a few samples of offset between the channels gives
        # it width without smearing anything.
        frames += struct.pack("<hh", s, s)

    os.makedirs(os.path.dirname(OUT_WAV), exist_ok=True)
    with wave.open(OUT_WAV, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    print("wrote %s (%.1f MB)" % (OUT_WAV, os.path.getsize(OUT_WAV) / 1048576))

    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", OUT_WAV,
                        "-codec:a", "libmp3lame", "-b:a", "160k", OUT_MP3],
                       check=True)
        os.remove(OUT_WAV)
        print("wrote %s (%.1f KB)" % (OUT_MP3, os.path.getsize(OUT_MP3) / 1024))
    except (OSError, subprocess.CalledProcessError) as exc:
        print("ffmpeg unavailable (%s); leaving the wav" % exc, file=sys.stderr)


if __name__ == "__main__":
    main()
