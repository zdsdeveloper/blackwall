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
    (1176, 0.34, 0.0),      # 24.500 Hz  the floor, felt more than heard
    (1181, 0.26, 2.4),      # 24.604 Hz  five cycles off, a 5s beat under it
    (1776, 0.50, 0.0),      # 37.000 Hz  the mass
    (1780, 0.44, 1.1),      # 37.083 Hz  four cycles off, a 12s swell
    (1783, 0.20, 3.0),      # 37.146 Hz  a third voice, so the beat is not
                            #            a clean pulse but something turning
    (2664, 0.15, 0.4),      # 55.500 Hz  a fifth above
    (2670, 0.11, 1.6),      # 55.625 Hz  beating again
    (3552, 0.10, 2.2),      # 74.000 Hz  the octave
    (3557, 0.07, 0.8),      # 74.104 Hz
    (5328, 0.030, 1.7),     # 111.00 Hz  upper body, quiet
]

# Faint, and a long way off.
#
# These were sitting at 2.2-4.2kHz and loud enough to read as a signal coming
# from the wall itself, which is the wrong idea entirely -- it made the thing
# sound like equipment rather than like something enormous and aware. They are
# lower now, a quarter of the level, and shaped by a fourth-power envelope so
# each one is absent most of the time and only ever surfaces briefly. What is
# wanted is the sense of something happening on the far side of a very thick
# wall, not a tone on this side of it.
SHIMMER = [
    (38_400, 0.0035, 5, 0.0),    # 800 Hz
    (52_800, 0.0028, 3, 1.9),    # 1100 Hz
    (69_120, 0.0022, 7, 3.4),    # 1440 Hz
    (86_400, 0.0016, 4, 0.6),    # 1800 Hz
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
            buf[i] += amp * (env ** 4) * math.sin(step * i)

    # --- the breath ---------------------------------------------------------
    # One cycle every twenty-four seconds, over the whole mass. This is most of
    # what separates something alive from a held chord: the wall swells and
    # subsides, slowly enough that you feel it before you notice it.
    breath_step = two_pi_over_n * 2          # two cycles per 48s loop
    for i in range(N):
        buf[i] *= 0.78 + 0.22 * (0.5 - 0.5 * math.cos(breath_step * i))

    # --- the swell ----------------------------------------------------------
    # Six over the loop, so it divides exactly. Deep, slow, and felt rather
    # than heard: the thing on the other side moving.
    swell_every = N // 6
    for k in range(6):
        start = k * swell_every
        length = int(RATE * 5.5)
        f = two_pi_over_n * 912             # 19 Hz
        for j in range(length):
            i = (start + j) % N             # wraps, so the last one loops in
            u = j / length
            env = math.sin(math.pi * u) ** 2
            buf[i] += 0.42 * env * math.sin(f * i)

    # --- the bed ------------------------------------------------------------
    # Brown-ish noise: not periodic, so the tail is crossfaded into the head
    # below. Very quiet; it is there to stop the drone sounding synthetic.
    edge = int(RATE * 1.5)
    level = 0.0
    for i in range(N):
        level += rnd.uniform(-1, 1) * 0.02
        level = max(-1.0, min(1.0, level * 0.995))
        # Raised-cosine in and out, so the bed is silent exactly at the join.
        if i < edge:
            w = 0.5 - 0.5 * math.cos(math.pi * i / edge)
        elif i >= N - edge:
            w = 0.5 - 0.5 * math.cos(math.pi * (N - 1 - i) / edge)
        else:
            w = 1.0
        buf[i] += level * 0.09 * w

    # --- close the loop -----------------------------------------------------
    #
    # Everything above is exactly periodic and already meets itself. The noise
    # is the only part that cannot be, so it is faded to silence at both ends
    # of the loop instead: nothing discontinuous is left at the join, and the
    # bed dipping briefly once every forty-eight seconds is inaudible under a
    # drone this heavy.
    #
    # It used to be a crossfade, and that was wrong. Blending the tail toward
    # `buf[j]` walks it to the sample two seconds into the loop, not to the
    # sample at zero -- so the join never closed. It was survivable while the
    # low end was light and became a clear click the moment it was not:
    # measured at a step of 6251 across the join against a largest ordinary
    # step of 1618.

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
